"""Codex CLI provider — tails ~/.codex/sessions/**/*.jsonl."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from watchfiles import awatch

from agentperiscope.model import Event, Store
from agentperiscope.providers.base import Provider

log = logging.getLogger(__name__)

PROVIDER = "codex-cli"
STALE_SECONDS = 1800  # 30 minutes


def _session_id_from_path(path: Path) -> str | None:
    """Extract session UUID from rollout-<timestamp>-<uuid>.jsonl filename."""
    stem = path.stem  # rollout-2026-06-13T14-40-37-019ec2ed-fe84-7130-81c8-2a5f5a505c22
    if not stem.startswith("rollout-"):
        return None
    # UUID is the last 36 characters of the stem
    if len(stem) >= 36:
        return stem[-36:]
    return None


def _ms_or_iso_to_iso(ts: str | int | float | None) -> str:
    """Normalise timestamp to ISO 8601 string."""
    if ts is None:
        return ""
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
        except (OSError, OverflowError):
            return ""
    return str(ts)


class _RawTailer:
    """Byte-offset tailer that returns raw parsed JSON objects."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0

    def read_new(self) -> list[dict]:
        try:
            size = self._path.stat().st_size
        except OSError:
            return []

        if size < self._offset:
            self._offset = 0

        if size == self._offset:
            return []

        try:
            with self._path.open("rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read(size - self._offset)
            self._offset = size
        except OSError:
            return []

        results = []
        for raw in chunk.split(b"\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                results.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return results


class CodexCliProvider(Provider):
    name = PROVIDER

    def __init__(
        self,
        session_dir: Path,
        store: Store,
        session_index: Path | None = None,
    ) -> None:
        self._session_dir = session_dir
        self._store = store
        self._session_index = session_index
        self._tailers: dict[Path, _RawTailer] = {}
        # session_id → thread_name (display name)
        self._thread_names: dict[str, str] = {}

    def _load_session_index(self) -> None:
        if not self._session_index or not self._session_index.exists():
            return
        try:
            for raw in self._session_index.read_bytes().split(b"\n"):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    sid = obj.get("id")
                    name = obj.get("thread_name")
                    if sid and name:
                        self._thread_names[sid] = name
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass

    def _boot_scan(self) -> None:
        if not self._session_dir.exists():
            return
        for path in sorted(self._session_dir.rglob("rollout-*.jsonl")):
            self._register_path(path)

    def _register_path(self, path: Path) -> None:
        if path in self._tailers:
            return
        session_id = _session_id_from_path(path)
        if not session_id:
            return
        tailer = _RawTailer(path)
        events = tailer.read_new()
        self._tailers[path] = tailer
        for obj in events:
            self._ingest(obj, session_id, path)

    def _ingest(self, obj: dict, session_id: str, path: Path) -> None:
        ts = obj.get("timestamp", "")
        t = obj.get("type", "")
        payload = obj.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if t == "session_meta":
            cwd = payload.get("cwd", "")
            thread_name = self._thread_names.get(session_id, session_id[:8])
            session = self._store.ensure_session(session_id, cwd, thread_name, provider=PROVIDER)
            if ts:
                if ts > session.last_activity_ts:
                    session.last_activity_ts = ts
            return

        session = self._store.get_session(session_id)
        if session is None:
            # Session not yet created (event arrived before session_meta on resume)
            cwd = ""
            thread_name = self._thread_names.get(session_id, session_id[:8])
            session = self._store.ensure_session(session_id, cwd, thread_name, provider=PROVIDER)

        agent = session.agents.get(session_id)
        if agent is None:
            return

        if ts and ts > session.last_activity_ts:
            session.last_activity_ts = ts

        if t == "event_msg":
            pt = payload.get("type", "")
            if pt == "agent_message":
                msg = payload.get("message", "")
                if msg:
                    snippet = str(msg)[:200]
                    agent.last_text = snippet
                    event = Event(
                        id=f"codex:{session_id}:{ts}:text",
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
            elif pt == "user_message":
                # User input — no event created, just marks activity
                pass

        elif t == "response_item":
            pt = payload.get("type", "")
            if pt in ("function_call", "custom_tool_call"):
                tool_name = payload.get("name") or payload.get("tool") or "unknown"
                call_id = payload.get("call_id", "")
                agent.current_tool = tool_name
                event = Event(
                    id=f"codex:{session_id}:{ts}:{call_id}:tool",
                    agent_id=session_id,
                    ts=ts,
                    kind="tool_use",
                    tool_name=tool_name,
                    summary=_codex_tool_summary(payload),
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
            elif "call_id" in payload and "output" in payload:
                # function_call_output — clear tool
                if agent.current_tool:
                    agent.current_tool = None
                    self._store._emit({
                        "type": "agent_update",
                        "session_id": session_id,
                        "agent": agent.to_dict(),
                    })

    def _reconcile_stale(self) -> None:
        now = time.time()
        for path, tailer in self._tailers.items():
            session_id = _session_id_from_path(path)
            if not session_id:
                continue
            session = self._store.get_session(session_id)
            if not session or session.status == "done":
                continue
            agent = session.agents.get(session_id)
            if not agent or agent.status != "running":
                continue
            # Mark done if last activity > STALE_SECONDS ago
            if session.last_activity_ts:
                try:
                    last = datetime.fromisoformat(
                        session.last_activity_ts.replace("Z", "+00:00")
                    )
                    age = (datetime.now(timezone.utc) - last).total_seconds()
                    if age > STALE_SECONDS:
                        agent.status = "done"
                        session.status = "done"
                except (ValueError, TypeError):
                    pass

    async def run(self) -> None:
        self._load_session_index()
        self._boot_scan()
        self._reconcile_stale()
        log.info("codex-cli provider: boot scan done, %d sessions", len(self._tailers))

        if not self._session_dir.exists():
            log.warning("codex-cli session_dir not found: %s", self._session_dir)
            return

        async for changes in awatch(self._session_dir):
            for _change_type, raw_path in changes:
                path = Path(raw_path)
                if path.suffix != ".jsonl":
                    continue
                if path not in self._tailers:
                    self._register_path(path)
                    continue
                session_id = _session_id_from_path(path)
                if not session_id:
                    continue
                tailer = self._tailers[path]
                for obj in tailer.read_new():
                    try:
                        self._ingest(obj, session_id, path)
                    except Exception as exc:
                        log.warning("codex-cli parse error %s: %s", path, exc)


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


def _codex_tool_summary(payload: dict) -> str:
    name = payload.get("name", "")
    args = payload.get("arguments") or payload.get("input") or ""
    if isinstance(args, str) and len(args) > 80:
        args = args[:80]
    elif isinstance(args, dict):
        for key in ("cmd", "command", "file_path", "path", "query"):
            if key in args:
                args = f"{key}={str(args[key])[:60]}"
                break
        else:
            args = ""
    return f"{name}: {args}" if args else name
