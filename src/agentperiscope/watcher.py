"""File watcher: monitors Claude Code transcript trees for changes."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from watchfiles import awatch, Change

from agentperiscope.model import Store
from agentperiscope.transcripts import Tailer, AssistantLine, UserLine, parse_line

log = logging.getLogger(__name__)


def _project_slug(path: Path, projects_dir: Path) -> str:
    """Return the opaque <encoded-cwd> slug from a path inside projects_dir."""
    try:
        rel = path.relative_to(projects_dir)
        return rel.parts[0]
    except (ValueError, IndexError):
        return str(path.parent.name)


def _session_id_from_path(path: Path) -> str | None:
    """Extract session UUID from a JSONL path (any depth)."""
    name = path.name
    if name.endswith(".jsonl"):
        return name[:-6]
    return None


def _agent_id_from_path(path: Path) -> str | None:
    """Extract agentId from a subagent JSONL path like agent-<id>.jsonl."""
    name = path.name
    if name.startswith("agent-") and name.endswith(".jsonl"):
        return name[len("agent-"):-len(".jsonl")]
    return None


def _is_subagent_jsonl(path: Path) -> bool:
    return path.parent.name == "subagents" and path.name.startswith("agent-")


def _parent_session_id(subagent_path: Path) -> str | None:
    """For a subagent JSONL, return the parent session UUID."""
    # subagent_path = .../projects/<slug>/<session-id>/subagents/agent-<id>.jsonl
    try:
        return subagent_path.parent.parent.name
    except (AttributeError, IndexError):
        return None


def _load_meta(subagent_path: Path) -> tuple[str | None, str | None]:
    """Return (agentType, description) from sibling .meta.json if present."""
    import json
    meta_path = subagent_path.with_suffix("").with_suffix(".meta.json")
    # agent-<id>.jsonl → agent-<id>.meta.json
    stem = subagent_path.stem  # agent-<id>
    meta_path = subagent_path.parent / f"{stem}.meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data.get("agentType"), data.get("description")
    except (OSError, ValueError):
        return None, None


def _read_tail_lines(path: Path, nbytes: int = 8192) -> list[bytes]:
    """Read the last nbytes of path, return complete lines."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - nbytes))
            raw = fh.read()
        return [l for l in raw.split(b"\n") if l.strip()]
    except OSError:
        return []


def _reconcile_subagent_completion(
    store: "Store",  # type: ignore[name-defined]
    session_id: str,
    agent_id: str,
    pairs: list,
) -> None:
    """Mark subagent done if the latest batch of lines shows end_turn."""
    session = store.get_session(session_id)
    if not session:
        return
    agent = session.agents.get(agent_id)
    if not agent or agent.status == "done":
        return
    for line, _ in reversed(pairs):
        if isinstance(line, AssistantLine):
            if line.stop_reason == "end_turn":
                agent.status = "done"
                agent.current_tool = None
            break


class Watcher:
    def __init__(self, projects_dir: Path, store: Store, poll: bool = False) -> None:
        self._projects_dir = projects_dir
        self._store = store
        self._poll = poll
        # path → Tailer
        self._tailers: dict[Path, Tailer] = {}
        # path → (agent_id, parent_session_id, agent_type, description)
        self._subagent_meta: dict[Path, tuple[str, str, str | None, str | None]] = {}
        # active project slugs → watch root paths
        self._active: set[Path] = set()

    # ------------------------------------------------------------------
    # Boot scan — pick up files already on disk before hooks fire
    # ------------------------------------------------------------------

    def _boot_scan(self) -> None:
        """Discover all existing JSONL files and create tailers.

        Process subagent files before parent files so that when the parent's
        toolUseResult is parsed, the subagent already exists in session.agents.
        """
        if not self._projects_dir.exists():
            return
        all_jsonl = list(self._projects_dir.rglob("*.jsonl"))
        # subagents first (deeper paths), then root session files
        subagent_files = [p for p in all_jsonl if _is_subagent_jsonl(p)]
        parent_files = [p for p in all_jsonl if not _is_subagent_jsonl(p)]
        for jsonl in subagent_files + parent_files:
            self._register_path(jsonl)

        self._reconcile_stale_sessions()

    def _reconcile_stale_sessions(self) -> None:
        """After boot scan: mark stale roots done and reconcile async subagents."""
        now = datetime.now(timezone.utc)
        now_ts = time.time()

        # --- root agents ---
        for path, tailer in self._tailers.items():
            if _is_subagent_jsonl(path):
                continue
            session_id = _session_id_from_path(path)
            if not session_id:
                continue
            session = self._store.get_session(session_id)
            if not session:
                continue
            root = session.agents.get(session_id)
            if root and root.status == "running":
                self._reconcile_one_root(path, root, session, now, now_ts)

        # --- async subagents (async_launched → running, may now be done) ---
        for path, meta in self._subagent_meta.items():
            agent_id, parent_session, _, _ = meta
            session = self._store.get_session(parent_session)
            if not session:
                continue
            agent = session.agents.get(agent_id)
            if not agent or agent.status == "done":
                continue
            self._reconcile_one_subagent(path, agent, now_ts)

    def _reconcile_one_root(
        self, path: Path, root: "Agent", session: "Session", now: datetime, now_ts: float  # type: ignore[name-defined]
    ) -> None:
        """Read tail of root JSONL; mark done on end_turn or 1h staleness fallback."""
        try:
            file_is_old = now_ts - path.stat().st_mtime > 3600  # >1h unchanged
        except OSError:
            file_is_old = False

        tail = _read_tail_lines(path)
        for line_bytes in reversed(tail):
            parsed = parse_line(line_bytes)
            if isinstance(parsed, AssistantLine):
                if parsed.stop_reason == "end_turn":
                    root.status = "done"
                    root.current_tool = None
                    session.status = "done"
                elif file_is_old:
                    # mid-tool-use stop + old file = died spawning subagents
                    root.status = "done"
                    root.current_tool = None
                    session.status = "done"
                # else: mid-turn stop — fall through to time-based check
                break
        else:
            # No AssistantLine at all — metadata-only or empty session
            if not session.last_activity_ts or file_is_old:
                root.status = "done"
                session.status = "done"
                return

        if root.status == "running" and session.last_activity_ts:
            try:
                last_ts = datetime.fromisoformat(
                    session.last_activity_ts.replace("Z", "+00:00")
                )
                if (now - last_ts).total_seconds() > 3600:
                    root.status = "done"
                    session.status = "done"
            except (ValueError, TypeError):
                pass

    def _reconcile_one_subagent(self, path: Path, agent: "Agent", now_ts: float) -> None:  # type: ignore[name-defined]
        """Read tail of subagent JSONL to determine if it finished."""
        try:
            file_is_old = now_ts - path.stat().st_mtime > 300  # >5 min unchanged
        except OSError:
            return

        tail = _read_tail_lines(path)
        for line_bytes in reversed(tail):
            parsed = parse_line(line_bytes)
            if isinstance(parsed, AssistantLine):
                if parsed.stop_reason == "end_turn":
                    # Clean completion
                    agent.status = "done"
                    agent.current_tool = None
                elif file_is_old:
                    # tool_use/None + old file = died mid-call or mid-stream
                    agent.status = "done"
                    agent.current_tool = None
                break
        else:
            # No AssistantLine found — mark done if file is old
            if file_is_old:
                agent.status = "done"
                agent.current_tool = None

    def _register_path(self, path: Path) -> None:
        if path in self._tailers:
            return
        tailer = Tailer(path)
        # Read all existing content immediately on boot
        pairs = tailer.read_new()
        self._tailers[path] = tailer

        slug = _project_slug(path, self._projects_dir)

        if _is_subagent_jsonl(path):
            agent_id = _agent_id_from_path(path)
            parent_session = _parent_session_id(path)
            if agent_id and parent_session:
                agent_type, description = _load_meta(path)
                self._subagent_meta[path] = (agent_id, parent_session, agent_type, description)
                for line, ref in pairs:
                    cwd = line.cwd if isinstance(line, (AssistantLine, UserLine)) else ""
                    self._store.ensure_session(parent_session, cwd, slug)
                    self._store.apply_line(
                        line, ref,
                        session_id=parent_session,
                        project_slug=slug,
                        agent_id=agent_id,
                        parent_agent_id=parent_session,
                        agent_type=agent_type,
                        agent_description=description,
                    )
                # Mark done if subagent's own transcript ended cleanly
                _reconcile_subagent_completion(self._store, parent_session, agent_id, pairs)
        else:
            session_id = _session_id_from_path(path)
            if session_id:
                for line, ref in pairs:
                    cwd = line.cwd if isinstance(line, (AssistantLine, UserLine)) else ""
                    self._store.ensure_session(session_id, cwd, slug)
                    self._store.apply_line(line, ref, session_id=session_id, project_slug=slug)

    # ------------------------------------------------------------------
    # Incremental update
    # ------------------------------------------------------------------

    def _process_change(self, change_type: Change, path: Path) -> None:
        if path.suffix != ".jsonl":
            return
        if path.name.endswith(".meta.json"):
            return

        if path not in self._tailers:
            self._register_path(path)
            return

        tailer = self._tailers[path]
        pairs = tailer.read_new()
        slug = _project_slug(path, self._projects_dir)

        if _is_subagent_jsonl(path):
            meta = self._subagent_meta.get(path)
            if meta is None:
                agent_id = _agent_id_from_path(path)
                parent_session = _parent_session_id(path)
                if agent_id and parent_session:
                    agent_type, description = _load_meta(path)
                    meta = (agent_id, parent_session, agent_type, description)
                    self._subagent_meta[path] = meta
            if meta:
                agent_id, parent_session, agent_type, description = meta
                for line, ref in pairs:
                    cwd = line.cwd if isinstance(line, (AssistantLine, UserLine)) else ""
                    self._store.ensure_session(parent_session, cwd, slug)
                    self._store.apply_line(
                        line, ref,
                        session_id=parent_session,
                        project_slug=slug,
                        agent_id=agent_id,
                        parent_agent_id=parent_session,
                        agent_type=agent_type,
                        agent_description=description,
                    )
                _reconcile_subagent_completion(self._store, parent_session, agent_id, pairs)
                # File-tail check in case end_turn wasn't in this batch
                session = self._store.get_session(parent_session)
                if session:
                    agent_obj = session.agents.get(agent_id)
                    if agent_obj and agent_obj.status == "running":
                        self._reconcile_one_subagent(path, agent_obj, time.time())
        else:
            session_id = _session_id_from_path(path)
            if session_id:
                for line, ref in pairs:
                    cwd = line.cwd if isinstance(line, (AssistantLine, UserLine)) else ""
                    self._store.ensure_session(session_id, cwd, slug)
                    self._store.apply_line(line, ref, session_id=session_id, project_slug=slug)

    # ------------------------------------------------------------------
    # Async run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._boot_scan()
        log.info("watcher: boot scan done, %d tailers", len(self._tailers))

        kwargs: dict = {"force_polling": self._poll}
        async for changes in awatch(self._projects_dir, **kwargs):
            for change_type, raw_path in changes:
                path = Path(raw_path)
                try:
                    self._process_change(change_type, path)
                except Exception as exc:
                    log.warning("watcher error on %s: %s", path, exc)
