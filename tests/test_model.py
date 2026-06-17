"""Tests for in-memory state store."""

import json
from pathlib import Path

import pytest

from agentperiscope.model import Store
from agentperiscope.transcripts import parse_line, RawRef


def _ref(path: str = "/tmp/fake.jsonl", offset: int = 0) -> RawRef:
    return RawRef(Path(path), offset, 0)


def _line(obj: dict):
    return parse_line(json.dumps(obj).encode())


def test_ensure_session_creates_root_agent():
    store = Store()
    sess = store.ensure_session("s1", "/tmp", "slug")
    assert "s1" in store.snapshot()["sessions"]
    assert "s1" in sess.agents


def test_ensure_session_idempotent():
    store = Store()
    s1 = store.ensure_session("s1", "/tmp", "slug")
    s2 = store.ensure_session("s1", "/other", "slug")
    assert s1 is s2


def test_ensure_agent_links_parent():
    store = Store()
    store.ensure_session("sess1", "/tmp", "slug")
    agent = store.ensure_agent(
        session_id="sess1",
        agent_id="child1",
        parent_agent_id="sess1",
        agent_type="Explore",
        description="test",
        transcript_path=None,
        started_at="2026-01-01",
    )
    sess = store.snapshot()["sessions"]["sess1"]
    assert "child1" in sess["agents"]
    assert "child1" in sess["agents"]["sess1"]["child_ids"]


def test_apply_assistant_line_updates_tokens():
    store = Store()
    store.ensure_session("s1", "/tmp", "slug")

    raw = {
        "type": "assistant",
        "uuid": "u1",
        "parentUuid": None,
        "sessionId": "s1",
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": "/tmp",
        "isSidechain": False,
        "message": {
            "model": "claude-haiku",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    }
    line = _line(raw)
    store.apply_line(line, _ref(), session_id="s1", project_slug="slug")

    sess = store.snapshot()["sessions"]["s1"]
    agent = sess["agents"]["s1"]
    assert agent["tokens"]["input"] == 10
    assert agent["tokens"]["output"] == 5
    assert agent["last_text"] == "hi"


def test_apply_tool_use_sets_current_tool():
    store = Store()
    store.ensure_session("s1", "/tmp", "slug")

    raw = {
        "type": "assistant",
        "uuid": "u1",
        "parentUuid": None,
        "sessionId": "s1",
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": "/tmp",
        "isSidechain": False,
        "message": {
            "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x"}}],
        },
    }
    line = _line(raw)
    store.apply_line(line, _ref(), session_id="s1", project_slug="slug")

    sess = store.snapshot()["sessions"]["s1"]
    assert sess["agents"]["s1"]["current_tool"] == "Read"


def test_subagent_completion_updates_status():
    store = Store()
    store.ensure_session("parent", "/tmp", "slug")
    store.ensure_agent(
        session_id="parent",
        agent_id="child1",
        parent_agent_id="parent",
        agent_type="Explore",
        description=None,
        transcript_path=None,
        started_at="2026-01-01",
    )

    raw = {
        "type": "user",
        "uuid": "u2",
        "parentUuid": "u1",
        "sessionId": "parent",
        "timestamp": "2026-01-01T00:00:02Z",
        "cwd": "/tmp",
        "isSidechain": False,
        "message": {"role": "user", "content": []},
        "toolUseResult": {
            "status": "completed",
            "agentId": "child1",
            "agentType": "Explore",
        },
    }
    line = _line(raw)
    store.apply_line(line, _ref(), session_id="parent", project_slug="slug")

    sess = store.snapshot()["sessions"]["parent"]
    assert sess["agents"]["child1"]["status"] == "done"


def test_delta_broadcast():
    deltas = []
    store = Store()
    store.subscribe(deltas.append)
    store.ensure_session("s1", "/tmp", "slug")
    assert any(d["type"] == "session_start" for d in deltas)
