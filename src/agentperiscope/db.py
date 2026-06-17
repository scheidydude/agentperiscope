"""SQLite persistence for agentperiscope sessions."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentperiscope.model import Store

_DDL = """\
CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT PRIMARY KEY,
    cwd              TEXT    NOT NULL DEFAULT '',
    project_slug     TEXT    NOT NULL DEFAULT '',
    model            TEXT,
    started_at       TEXT    NOT NULL DEFAULT '',
    status           TEXT    NOT NULL DEFAULT 'running',
    root_agent_id    TEXT    NOT NULL DEFAULT '',
    last_activity_ts TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agents (
    id                    TEXT    NOT NULL,
    session_id            TEXT    NOT NULL,
    parent_agent_id       TEXT,
    agent_type            TEXT,
    description           TEXT,
    status                TEXT    NOT NULL DEFAULT 'running',
    started_at            TEXT    NOT NULL DEFAULT '',
    ended_at              TEXT,
    last_text             TEXT,
    tokens_input          INTEGER NOT NULL DEFAULT 0,
    tokens_output         INTEGER NOT NULL DEFAULT 0,
    tokens_cache_creation INTEGER NOT NULL DEFAULT 0,
    tokens_cache_read     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (id, session_id)
);
"""


class DB:
    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_DDL)
        self._conn.commit()

    def load_into(self, store: "Store") -> None:
        from agentperiscope.model import Agent, Session, TokenCounts

        for row in self._conn.execute("SELECT * FROM sessions").fetchall():
            session = Session(
                id=row["id"],
                cwd=row["cwd"],
                project_slug=row["project_slug"],
                model=row["model"],
                started_at=row["started_at"],
                status=row["status"],
                root_agent_id=row["root_agent_id"],
                last_activity_ts=row["last_activity_ts"],
            )
            store._sessions[row["id"]] = session

        for row in self._conn.execute("SELECT * FROM agents").fetchall():
            session = store._sessions.get(row["session_id"])
            if not session:
                continue
            agent = Agent(
                id=row["id"],
                session_id=row["session_id"],
                parent_agent_id=row["parent_agent_id"],
                agent_type=row["agent_type"],
                description=row["description"],
                status=row["status"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                last_text=row["last_text"],
                tokens=TokenCounts(
                    input=row["tokens_input"],
                    output=row["tokens_output"],
                    cache_creation=row["tokens_cache_creation"],
                    cache_read=row["tokens_cache_read"],
                ),
            )
            session.agents[row["id"]] = agent

        # Rebuild child_ids after all agents are loaded
        for session in store._sessions.values():
            for agent in session.agents.values():
                if agent.parent_agent_id and agent.parent_agent_id in session.agents:
                    parent = session.agents[agent.parent_agent_id]
                    if agent.id not in parent.child_ids:
                        parent.child_ids.append(agent.id)

    def on_delta(self, delta: dict) -> None:
        t = delta["type"]
        if t in ("session_start", "session_update"):
            self._upsert_session(delta["session"])
            for agent_d in delta["session"]["agents"].values():
                self._upsert_agent(agent_d)
        elif t in ("agent_start", "agent_update"):
            self._upsert_agent(delta["agent"])

    def _upsert_session(self, s: dict) -> None:
        self._conn.execute(
            """INSERT INTO sessions
                   (id, cwd, project_slug, model, started_at, status, root_agent_id, last_activity_ts)
               VALUES (:id, :cwd, :project_slug, :model, :started_at, :status, :root_agent_id, :last_activity_ts)
               ON CONFLICT(id) DO UPDATE SET
                   cwd=excluded.cwd,
                   project_slug=excluded.project_slug,
                   model=excluded.model,
                   started_at=excluded.started_at,
                   status=excluded.status,
                   root_agent_id=excluded.root_agent_id,
                   last_activity_ts=excluded.last_activity_ts""",
            s,
        )
        self._conn.commit()

    def _upsert_agent(self, a: dict) -> None:
        self._conn.execute(
            """INSERT INTO agents
                   (id, session_id, parent_agent_id, agent_type, description,
                    status, started_at, ended_at, last_text,
                    tokens_input, tokens_output, tokens_cache_creation, tokens_cache_read)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id, session_id) DO UPDATE SET
                   parent_agent_id=excluded.parent_agent_id,
                   agent_type=excluded.agent_type,
                   description=excluded.description,
                   status=excluded.status,
                   ended_at=excluded.ended_at,
                   last_text=excluded.last_text,
                   tokens_input=excluded.tokens_input,
                   tokens_output=excluded.tokens_output,
                   tokens_cache_creation=excluded.tokens_cache_creation,
                   tokens_cache_read=excluded.tokens_cache_read""",
            (
                a["id"], a["session_id"], a["parent_agent_id"], a["agent_type"],
                a["description"], a["status"], a["started_at"], a["ended_at"],
                a["last_text"],
                a["tokens"]["input"], a["tokens"]["output"],
                a["tokens"]["cache_creation"], a["tokens"]["cache_read"],
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
