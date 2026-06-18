"""In-memory session/agent/event state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agentperiscope.transcripts import (
    AnyLine,
    AssistantLine,
    ContentBlock,
    RawRef,
    SystemLine,
    UserLine,
)


@dataclass
class TokenCounts:
    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0

    def add_usage(self, u: "agentperiscope.transcripts.UsageBlock") -> None:  # type: ignore[name-defined]
        self.input += u.input_tokens
        self.output += u.output_tokens
        self.cache_creation += u.cache_creation_input_tokens
        self.cache_read += u.cache_read_input_tokens

    def total(self) -> int:
        return self.input + self.output


@dataclass
class Event:
    id: str
    agent_id: str
    ts: str
    kind: str  # text | tool_use | tool_result | thinking | usage | system
    tool_name: str | None = None
    summary: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw_ref: RawRef | None = None


@dataclass
class Agent:
    id: str  # agentId hex or session_id for root
    session_id: str
    parent_agent_id: str | None
    agent_type: str | None
    description: str | None
    status: str = "running"  # running | done | error
    started_at: str = ""
    ended_at: str | None = None
    current_tool: str | None = None
    last_text: str | None = None
    tokens: TokenCounts = field(default_factory=TokenCounts)
    events: list[Event] = field(default_factory=list)
    child_ids: list[str] = field(default_factory=list)
    transcript_path: Path | None = None
    provider: str = "claude-code"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "parent_agent_id": self.parent_agent_id,
            "agent_type": self.agent_type,
            "description": self.description,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "current_tool": self.current_tool,
            "last_text": self.last_text,
            "tokens": {
                "input": self.tokens.input,
                "output": self.tokens.output,
                "cache_creation": self.tokens.cache_creation,
                "cache_read": self.tokens.cache_read,
                "total": self.tokens.total(),
            },
            "child_ids": self.child_ids,
            "provider": self.provider,
        }

    def to_full_dict(self) -> dict:
        d = self.to_dict()
        d["events"] = [_event_dict(e) for e in self.events]
        return d


@dataclass
class Session:
    id: str
    cwd: str
    project_slug: str
    model: str | None = None
    started_at: str = ""
    status: str = "running"  # running | done
    root_agent_id: str = ""
    agents: dict[str, Agent] = field(default_factory=dict)
    last_activity_ts: str = ""  # ISO timestamp of last real assistant/user line
    provider: str = "claude-code"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "project_slug": self.project_slug,
            "model": self.model,
            "started_at": self.started_at,
            "status": self.status,
            "root_agent_id": self.root_agent_id,
            "last_activity_ts": self.last_activity_ts,
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "provider": self.provider,
        }

    def to_full_dict(self) -> dict:
        d = self.to_dict()
        d["agents"] = {k: v.to_full_dict() for k, v in self.agents.items()}
        return d


# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------

class Store:
    """Thread-safe(ish) in-memory state. Call apply_line to ingest parsed lines."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._subscribers: list[Callable[[dict], None]] = []

    # ------------------------------------------------------------------
    # Subscribers (WebSocket hub calls these)
    # ------------------------------------------------------------------

    def subscribe(self, cb: Callable[[dict], None]) -> None:
        self._subscribers.append(cb)

    def unsubscribe(self, cb: Callable[[dict], None]) -> None:
        self._subscribers.remove(cb)

    def _emit(self, delta: dict) -> None:
        for cb in list(self._subscribers):
            try:
                cb(delta)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {"sessions": {k: v.to_dict() for k, v in self._sessions.items()}}

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def ensure_session(self, session_id: str, cwd: str, project_slug: str, provider: str = "claude-code") -> Session:
        if session_id not in self._sessions:
            agent = Agent(
                id=session_id,
                session_id=session_id,
                parent_agent_id=None,
                agent_type="root",
                description=None,
                started_at=str(time.time()),
                provider=provider,
            )
            session = Session(
                id=session_id,
                cwd=cwd,
                project_slug=project_slug,
                root_agent_id=session_id,
                agents={session_id: agent},
                provider=provider,
            )
            self._sessions[session_id] = session
            self._emit({"type": "session_start", "session": session.to_dict()})
        else:
            # Update cwd/slug once we learn them (first lines may be metadata-only)
            sess = self._sessions[session_id]
            if cwd and not sess.cwd:
                sess.cwd = cwd
                sess.project_slug = project_slug
        return self._sessions[session_id]

    def ensure_agent(
        self,
        session_id: str,
        agent_id: str,
        parent_agent_id: str | None,
        agent_type: str | None,
        description: str | None,
        transcript_path: Path | None,
        started_at: str,
        provider: str = "claude-code",
    ) -> Agent:
        session = self._sessions.get(session_id)
        if session is None:
            return Agent(id=agent_id, session_id=session_id, parent_agent_id=None,
                         agent_type=agent_type, description=description, provider=provider)

        if agent_id not in session.agents:
            agent = Agent(
                id=agent_id,
                session_id=session_id,
                parent_agent_id=parent_agent_id,
                agent_type=agent_type,
                description=description,
                transcript_path=transcript_path,
                started_at=started_at,
                provider=provider,
            )
            session.agents[agent_id] = agent
            if parent_agent_id and parent_agent_id in session.agents:
                parent = session.agents[parent_agent_id]
                if agent_id not in parent.child_ids:
                    parent.child_ids.append(agent_id)
            self._emit({"type": "agent_start", "session_id": session_id, "agent": agent.to_dict()})
        return session.agents[agent_id]

    def apply_line(
        self,
        line: AnyLine,
        raw_ref: RawRef,
        session_id: str,
        project_slug: str,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        agent_type: str | None = None,
        agent_description: str | None = None,
    ) -> None:
        if not isinstance(line, (AssistantLine, UserLine, SystemLine)):
            return  # metadata-only lines don't create sessions

        cwd = ""
        ts = ""
        if isinstance(line, (AssistantLine, UserLine)):
            cwd = line.cwd
            ts = line.timestamp

        session = self.ensure_session(session_id, cwd, project_slug)

        # Track last activity timestamp for staleness detection
        if ts and ts > session.last_activity_ts:
            session.last_activity_ts = ts

        # Which agent does this line belong to?
        effective_agent_id = agent_id or session_id

        if agent_id and agent_id != session_id:
            agent = self.ensure_agent(
                session_id=session_id,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id or session_id,
                agent_type=agent_type,
                description=agent_description,
                transcript_path=raw_ref.path,
                started_at=ts,
            )
        else:
            agent = session.agents.get(session_id)
            if agent is None:
                return

        delta: dict | None = None

        if isinstance(line, AssistantLine):
            if session.model is None and line.model:
                session.model = line.model

            # Update agent state from content blocks
            for block in line.content:
                if block.type == "text" and block.text:
                    snippet = block.text[:200]
                    agent.last_text = snippet
                    event = Event(
                        id=f"{line.uuid}:text",
                        agent_id=effective_agent_id,
                        ts=ts,
                        kind="text",
                        summary=snippet,
                        raw_ref=raw_ref,
                    )
                    agent.events.append(event)
                    delta = {"type": "event", "session_id": session_id,
                             "agent_id": effective_agent_id, "event": _event_dict(event)}

                elif block.type == "thinking" and block.thinking:
                    event = Event(
                        id=f"{line.uuid}:thinking",
                        agent_id=effective_agent_id,
                        ts=ts,
                        kind="thinking",
                        summary=block.thinking[:100],
                        raw_ref=raw_ref,
                    )
                    agent.events.append(event)

                elif block.type == "tool_use" and block.tool_name:
                    agent.current_tool = block.tool_name
                    event = Event(
                        id=f"{line.uuid}:{block.tool_use_id}",
                        agent_id=effective_agent_id,
                        ts=ts,
                        kind="tool_use",
                        tool_name=block.tool_name,
                        summary=_tool_summary(block),
                        raw_ref=raw_ref,
                    )
                    agent.events.append(event)
                    delta = {"type": "event", "session_id": session_id,
                             "agent_id": effective_agent_id, "event": _event_dict(event)}

            if line.usage:
                agent.tokens.add_usage(line.usage)
                delta = {"type": "agent_update", "session_id": session_id,
                         "agent": agent.to_dict()}

        elif isinstance(line, UserLine):
            # Tool result — clear current_tool for root-level tool completions
            if line.tool_use_result is not None:
                # Check if a subagent completed
                tr = line.tool_use_result
                if isinstance(tr, dict) and "agentId" in tr:
                    completed_agent_id = tr["agentId"]
                    if completed_agent_id in session.agents:
                        sub = session.agents[completed_agent_id]
                        raw_status = tr.get("status", "done")
                        # async_launched = dispatched background agent, still running
                        # completed/done = finished
                        if raw_status in ("completed", "done"):
                            sub.status = "done"
                            sub.current_tool = None
                        elif raw_status == "async_launched":
                            sub.status = "running"
                        else:
                            sub.status = raw_status
                        sub.ended_at = ts
                        delta = {"type": "agent_update", "session_id": session_id,
                                 "agent": sub.to_dict()}
                else:
                    if agent.current_tool:
                        agent.current_tool = None
                        delta = {"type": "agent_update", "session_id": session_id,
                                 "agent": agent.to_dict()}

        elif isinstance(line, SystemLine):
            if line.subtype == "stop_hook_summary":
                agent.current_tool = None
                if effective_agent_id == session_id:
                    session.status = "done"
                    agent.status = "done"
                    delta = {"type": "session_update", "session": session.to_dict()}

        if delta:
            self._emit(delta)


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


def _tool_summary(block: ContentBlock) -> str:
    if not block.tool_input:
        return block.tool_name or ""
    # Pick a short representative key from the input
    inp = block.tool_input
    for key in ("command", "description", "file_path", "path", "query", "prompt"):
        if key in inp:
            val = str(inp[key])
            return f"{block.tool_name}: {val[:80]}"
    return block.tool_name or ""
