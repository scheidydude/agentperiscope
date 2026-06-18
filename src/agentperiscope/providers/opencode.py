"""OpenCode provider — polls ~/.local/share/opencode/opencode.db."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agentperiscope.model import Event, Store
from agentperiscope.providers.base import Provider

log = logging.getLogger(__name__)

PROVIDER = "opencode"
POLL_INTERVAL = 3.0  # seconds


def _ms_to_iso(ms: int | float | None) -> str:
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError):
        return ""


def _safe_json(s: str | None) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


class OpenCodeProvider(Provider):
    name = PROVIDER

    def __init__(self, db_path: Path, store: Store) -> None:
        self._db_path = db_path
        self._store = store
        # session_id → last time_updated (ms) seen
        self._session_seen: dict[str, int] = {}
        # message_id → set of part types already ingested
        self._msg_seen: set[str] = set()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _poll_once(self) -> None:
        try:
            conn = self._connect()
            try:
                self._ingest_sessions(conn)
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            log.warning("opencode db error: %s", exc)
        except Exception as exc:
            log.warning("opencode poll error: %s", exc)

    def _ingest_sessions(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT id, project_id, directory, title, model, time_created, time_updated FROM session ORDER BY time_created ASC"
        ).fetchall()

        for row in rows:
            sid = row["id"]
            time_updated = row["time_updated"] or 0
            last_seen = self._session_seen.get(sid, 0)

            cwd = row["directory"] or ""
            title = row["title"] or sid[:8]
            model_json = row["model"]
            model_str = None
            if model_json:
                m = _safe_json(model_json)
                model_str = m.get("id") or m.get("name")

            is_new = sid not in self._session_seen
            self._session_seen[sid] = time_updated

            session = self._store.ensure_session(sid, cwd, title, provider=PROVIDER)
            if model_str and not session.model:
                session.model = model_str

            ts_created = _ms_to_iso(row["time_created"])
            ts_updated = _ms_to_iso(time_updated)

            agent = session.agents.get(sid)
            if agent:
                if not agent.started_at and ts_created:
                    agent.started_at = ts_created
                if ts_updated and ts_updated > session.last_activity_ts:
                    session.last_activity_ts = ts_updated

            if time_updated == last_seen and not is_new:
                continue

            self._ingest_messages(conn, sid)

    def _ingest_messages(self, conn: sqlite3.Connection, session_id: str) -> None:
        session = self._store.get_session(session_id)
        if session is None:
            return
        agent = session.agents.get(session_id)
        if agent is None:
            return

        rows = conn.execute(
            "SELECT id, time_created, time_updated, data FROM message WHERE session_id = ? ORDER BY time_created ASC",
            (session_id,),
        ).fetchall()

        last_finish = None
        for row in rows:
            data = _safe_json(row["data"])
            role = data.get("role", "")
            finish = data.get("finish")
            if finish:
                last_finish = finish

            msg_id = row["id"]
            if role == "assistant" and msg_id not in self._msg_seen:
                self._msg_seen.add(msg_id)
                ts = _ms_to_iso(row["time_created"])
                # Update token counts from message
                tok = data.get("tokens", {})
                if tok:
                    cache = tok.get("cache", {})
                    agent.tokens.input += tok.get("input", 0)
                    agent.tokens.output += tok.get("output", 0)
                    agent.tokens.cache_creation += cache.get("write", 0)
                    agent.tokens.cache_read += cache.get("read", 0)
                    self._store._emit({
                        "type": "agent_update",
                        "session_id": session_id,
                        "agent": agent.to_dict(),
                    })
                self._ingest_parts(conn, msg_id, session_id, ts)

        # Determine session completion
        if last_finish == "stop" and session.status == "running":
            session.status = "done"
            agent.status = "done"
            agent.current_tool = None
            self._store._emit({"type": "session_update", "session": session.to_dict()})

    def _ingest_parts(
        self,
        conn: sqlite3.Connection,
        message_id: str,
        session_id: str,
        msg_ts: str,
    ) -> None:
        session = self._store.get_session(session_id)
        if not session:
            return
        agent = session.agents.get(session_id)
        if not agent:
            return

        rows = conn.execute(
            "SELECT id, time_created, data FROM part WHERE message_id = ? ORDER BY time_created ASC",
            (message_id,),
        ).fetchall()

        for row in rows:
            data = _safe_json(row["data"])
            part_type = data.get("type", "")
            ts = _ms_to_iso(row["time_created"]) or msg_ts

            if part_type == "text":
                text = data.get("text", "")
                if not text:
                    continue
                snippet = text[:200]
                agent.last_text = snippet
                event = Event(
                    id=f"opencode:{row['id']}:text",
                    agent_id=session_id,
                    ts=ts,
                    kind="text",
                    summary=snippet,
                )
                agent.events.append(event)
                self._store._emit({
                    "type": "event",
                    "session_id": session_id,
                    "agent_id": session_id,
                    "event": _event_dict(event),
                })

            elif part_type == "tool":
                tool_name = data.get("tool", "unknown")
                state = data.get("state", {}) or {}
                status = state.get("status", "")
                call_id = data.get("callID", row["id"])

                if status in ("pending", "running", ""):
                    agent.current_tool = tool_name
                    inp = state.get("input", {})
                    summary = _opencode_tool_summary(tool_name, inp)
                    event = Event(
                        id=f"opencode:{row['id']}:tool_use",
                        agent_id=session_id,
                        ts=ts,
                        kind="tool_use",
                        tool_name=tool_name,
                        summary=summary,
                    )
                    agent.events.append(event)
                    self._store._emit({
                        "type": "event",
                        "session_id": session_id,
                        "agent_id": session_id,
                        "event": _event_dict(event),
                    })
                    self._store._emit({
                        "type": "agent_update",
                        "session_id": session_id,
                        "agent": agent.to_dict(),
                    })
                elif status == "completed":
                    if agent.current_tool == tool_name:
                        agent.current_tool = None
                    event = Event(
                        id=f"opencode:{row['id']}:tool_result",
                        agent_id=session_id,
                        ts=ts,
                        kind="tool_result",
                        tool_name=tool_name,
                        summary=_opencode_result_summary(state),
                    )
                    agent.events.append(event)
                    self._store._emit({
                        "type": "event",
                        "session_id": session_id,
                        "agent_id": session_id,
                        "event": _event_dict(event),
                    })
                    self._store._emit({
                        "type": "agent_update",
                        "session_id": session_id,
                        "agent": agent.to_dict(),
                    })

    async def run(self) -> None:
        if not self._db_path.exists():
            log.warning("opencode db not found: %s", self._db_path)
            return

        log.info("opencode provider: starting, db=%s", self._db_path)
        self._poll_once()  # boot scan

        while True:
            await asyncio.sleep(POLL_INTERVAL)
            self._poll_once()


def _event_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "agent_id": e.agent_id,
        "ts": e.ts,
        "kind": e.kind,
        "tool_name": e.tool_name,
        "summary": e.summary,
        "tokens_in": e.tokens_in,
        "tokens_out": e.tokens_out,
    }


def _opencode_tool_summary(tool_name: str, inp: dict | None) -> str:
    if not inp:
        return tool_name
    for key in ("filePath", "file_path", "path", "pattern", "query", "command"):
        if key in inp:
            return f"{tool_name}: {str(inp[key])[:80]}"
    return tool_name


def _opencode_result_summary(state: dict) -> str:
    output = state.get("output", "")
    if isinstance(output, str):
        return output[:200]
    if isinstance(output, dict):
        # e.g. {"count": 2, "truncated": false}
        return str(output)[:200]
    return ""
