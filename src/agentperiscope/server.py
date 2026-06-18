"""FastAPI server: /events (hook ingest), /ws (WebSocket hub), / (SPA)."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from agentperiscope.model import Store

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_app(store: Store) -> FastAPI:
    app = FastAPI(title="agentperiscope")
    clients: list[WebSocket] = []

    def _broadcast(delta: dict) -> None:
        msg = json.dumps(delta)
        dead = []
        for ws in list(clients):
            try:
                asyncio.get_event_loop().create_task(ws.send_text(msg))
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.remove(ws)

    store.subscribe(_broadcast)

    @app.post("/events")
    async def ingest_hook(request: Request) -> Response:
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return Response(status_code=400)
        event_name = payload.get("hook_event_name", "")
        session_id = payload.get("session_id", "")
        transcript_path = payload.get("transcript_path", "")
        log.debug("hook: %s session=%s", event_name, session_id)

        # Hooks are the fast signal — the watcher handles actual transcript tailing.
        # Here we just ensure the session exists and can be watched.
        if session_id and transcript_path:
            tp = Path(transcript_path)
            cwd = payload.get("cwd", "")
            slug = tp.parent.name if tp.parent else ""
            store.ensure_session(session_id, cwd, slug)

        store._emit({"type": "hook", "payload": payload})
        return Response(status_code=204)

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        clients.append(websocket)
        try:
            # Send full snapshot on connect
            await websocket.send_text(json.dumps({
                "type": "snapshot",
                "data": store.snapshot(),
            }))
            while True:
                # Keep alive — client may send pings
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in clients:
                clients.remove(websocket)

    @app.get("/api/sessions/{session_id}")
    async def get_session_full(session_id: str) -> Response:
        session = store.get_session(session_id)
        if session is None:
            return Response(status_code=404)
        return JSONResponse(session.to_full_dict())

    @app.post("/api/stop")
    async def stop_server(request: Request) -> Response:
        shutdown = getattr(request.app.state, "shutdown", None)
        if shutdown:
            asyncio.get_event_loop().call_soon(shutdown)
        return JSONResponse({"status": "stopping"})

    # Serve built SPA if present, else a minimal fallback
    if WEB_DIR.exists() and (WEB_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="spa")
    else:
        @app.get("/")
        async def fallback() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

    return app


_FALLBACK_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>agentperiscope</title>
  <style>
    body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 2rem; }
    h1 { color: #58a6ff; }
    #status { color: #3fb950; }
    #log { margin-top: 1rem; white-space: pre; font-size: 0.85rem; max-height: 80vh; overflow-y: auto; }
    .agent { border-left: 3px solid #58a6ff; padding-left: 1rem; margin: 0.5rem 0; }
    .done { border-color: #3fb950; }
    .error { border-color: #f85149; }
  </style>
</head>
<body>
  <h1>agentperiscope</h1>
  <div id="status">connecting…</div>
  <div id="sessions"></div>
  <script>
    const status = document.getElementById('status');
    const sessions = document.getElementById('sessions');
    let state = {};

    function render() {
      sessions.innerHTML = '';
      for (const [sid, session] of Object.entries(state)) {
        const div = document.createElement('div');
        div.innerHTML = '<h2>' + session.cwd + ' <small>(' + sid.slice(0,8) + ')</small></h2>';
        for (const [aid, agent] of Object.entries(session.agents || {})) {
          const cls = agent.status === 'done' ? 'done' : agent.status === 'error' ? 'error' : '';
          const tool = agent.current_tool ? ' [' + agent.current_tool + ']' : '';
          const tokens = agent.tokens ? agent.tokens.total + ' tokens' : '';
          div.innerHTML += '<div class="agent ' + cls + '">' +
            '<b>' + (agent.agent_type || 'root') + '</b>' + tool +
            (agent.description ? ' — ' + agent.description : '') +
            ' <span style="color:#8b949e">' + agent.status + ' ' + tokens + '</span>' +
            (agent.last_text ? '<br><small>' + agent.last_text.slice(0,120) + '</small>' : '') +
            '</div>';
        }
        sessions.appendChild(div);
      }
    }

    function connect() {
      const ws = new WebSocket('ws://' + location.host + '/ws');
      ws.onopen = () => { status.textContent = 'connected'; };
      ws.onclose = () => { status.textContent = 'disconnected — reconnecting…'; setTimeout(connect, 2000); };
      ws.onmessage = e => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'snapshot') {
          state = msg.data.sessions || {};
        } else if (msg.type === 'session_start' || msg.type === 'session_update') {
          state[msg.session ? msg.session.id : Object.keys(msg)[1]] = msg.session || msg;
        } else if (msg.type === 'agent_start' || msg.type === 'agent_update') {
          const sess = state[msg.session_id];
          if (sess) sess.agents[msg.agent.id] = msg.agent;
        }
        render();
      };
    }
    connect();
  </script>
</body>
</html>
"""
