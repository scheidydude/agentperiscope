"""Tests for provider abstraction, Codex CLI parser, and OpenCode parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentperiscope.model import Store
from agentperiscope.providers.base import Provider
from agentperiscope.providers.codex_cli import CodexCliProvider, _session_id_from_path
from agentperiscope.providers.opencode import OpenCodeProvider

FIXTURES = Path(__file__).parent / "fixtures"
CODEX_FIXTURES = FIXTURES / "codex-cli"
OC_FIXTURES = FIXTURES / "opencode"


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------


def test_provider_is_abstract():
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


def test_provider_name_attribute():
    from agentperiscope.providers.claude_code import ClaudeCodeProvider
    from agentperiscope.providers.codex_cli import CodexCliProvider
    from agentperiscope.providers.opencode import OpenCodeProvider

    assert ClaudeCodeProvider.name == "claude-code"
    assert CodexCliProvider.name == "codex-cli"
    assert OpenCodeProvider.name == "opencode"


# ---------------------------------------------------------------------------
# Codex CLI: path parsing
# ---------------------------------------------------------------------------


def test_session_id_from_codex_path():
    path = Path("rollout-2026-06-13T14-40-37-019ec2ed-fe84-7130-81c8-2a5f5a505c22.jsonl")
    assert _session_id_from_path(path) == "019ec2ed-fe84-7130-81c8-2a5f5a505c22"


def test_session_id_from_non_rollout():
    assert _session_id_from_path(Path("something.jsonl")) is None


def test_session_id_from_fixture():
    fixture = next(CODEX_FIXTURES.glob("rollout-*.jsonl"))
    sid = _session_id_from_path(fixture)
    assert sid == "019e0000-0000-7000-8000-000000000001"


# ---------------------------------------------------------------------------
# Codex CLI: event parsing
# ---------------------------------------------------------------------------


def _make_codex_provider(fixture_dir: Path) -> tuple[CodexCliProvider, Store]:
    store = Store()
    index = fixture_dir / "session_index.jsonl"
    provider = CodexCliProvider(
        session_dir=fixture_dir,
        store=store,
        session_index=index if index.exists() else None,
    )
    return provider, store


def test_codex_boot_scan_creates_session():
    provider, store = _make_codex_provider(CODEX_FIXTURES)
    provider._load_session_index()
    provider._boot_scan()

    sessions = store.snapshot()["sessions"]
    assert len(sessions) == 1

    sid = "019e0000-0000-7000-8000-000000000001"
    assert sid in sessions
    session = sessions[sid]
    assert session["provider"] == "codex-cli"
    assert session["cwd"] == "/home/user/project"


def test_codex_session_index_sets_project_slug():
    provider, store = _make_codex_provider(CODEX_FIXTURES)
    provider._load_session_index()
    provider._boot_scan()

    sid = "019e0000-0000-7000-8000-000000000001"
    session = store.snapshot()["sessions"][sid]
    assert session["project_slug"] == "Write hello world"


def test_codex_agent_message_creates_text_event():
    provider, store = _make_codex_provider(CODEX_FIXTURES)
    provider._load_session_index()
    provider._boot_scan()

    sid = "019e0000-0000-7000-8000-000000000001"
    session_obj = store.get_session(sid)
    assert session_obj is not None
    agent = session_obj.agents[sid]

    text_events = [e for e in agent.events if e.kind == "text"]
    assert len(text_events) >= 1
    assert "hello world" in (text_events[-1].summary or "").lower()


def test_codex_function_call_creates_tool_event():
    provider, store = _make_codex_provider(CODEX_FIXTURES)
    provider._load_session_index()
    provider._boot_scan()

    sid = "019e0000-0000-7000-8000-000000000001"
    session_obj = store.get_session(sid)
    agent = session_obj.agents[sid]

    tool_events = [e for e in agent.events if e.kind == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_name == "exec_command"


def test_codex_function_call_output_clears_tool():
    provider, store = _make_codex_provider(CODEX_FIXTURES)
    provider._load_session_index()
    provider._boot_scan()

    sid = "019e0000-0000-7000-8000-000000000001"
    session_obj = store.get_session(sid)
    agent = session_obj.agents[sid]
    # After function_call_output, current_tool should be cleared
    assert agent.current_tool is None


def test_codex_malformed_line_skipped():
    provider, store = _make_codex_provider(CODEX_FIXTURES)
    provider._load_session_index()
    # Inject a bad line
    sid = "019e0000-0000-7000-8000-000000000001"
    provider._ingest({"type": "unknown_event", "payload": None}, sid, Path("fake.jsonl"))
    # Should not crash — session may or may not exist yet
    # Just verify no exception was raised


def test_codex_empty_file_handled(tmp_path: Path):
    empty = tmp_path / "rollout-2026-06-01T00-00-00-019e0000-0000-7000-8000-000000000002.jsonl"
    empty.write_bytes(b"")
    provider, store = _make_codex_provider(tmp_path)
    provider._boot_scan()
    sessions = store.snapshot()["sessions"]
    # Empty file creates no session (no session_meta)
    assert len(sessions) == 0


def test_codex_truncated_json_line_skipped(tmp_path: Path):
    path = tmp_path / "rollout-2026-06-01T00-00-00-019e0000-0000-7000-8000-000000000003.jsonl"
    path.write_bytes(
        b'{"timestamp":"2026-06-01T10:00:00.000Z","type":"session_meta","payload":{"id":"019e0000-0000-7000-8000-000000000003","cwd":"/tmp"}}\n'
        b'{"timestamp":"2026-06-01T10:00:01.000Z","type":"event_msg","payload":{"type":"agent_message","message":'  # truncated
    )
    provider, store = _make_codex_provider(tmp_path)
    provider._boot_scan()
    # Partial line is silently dropped; session is still created
    sessions = store.snapshot()["sessions"]
    assert "019e0000-0000-7000-8000-000000000003" in sessions


# ---------------------------------------------------------------------------
# OpenCode: event parsing
# ---------------------------------------------------------------------------


def _make_oc_provider() -> tuple[OpenCodeProvider, Store]:
    store = Store()
    db = OC_FIXTURES / "opencode_fixture.db"
    provider = OpenCodeProvider(db_path=db, store=store)
    return provider, store


def test_opencode_poll_creates_session():
    provider, store = _make_oc_provider()
    provider._poll_once()

    sessions = store.snapshot()["sessions"]
    assert "ses_test001" in sessions
    session = sessions["ses_test001"]
    assert session["provider"] == "opencode"
    assert session["cwd"] == "/home/user/project"


def test_opencode_session_title_as_project_slug():
    provider, store = _make_oc_provider()
    provider._poll_once()

    session = store.snapshot()["sessions"]["ses_test001"]
    assert session["project_slug"] == "Test session"


def test_opencode_text_part_creates_event():
    provider, store = _make_oc_provider()
    provider._poll_once()

    session_obj = store.get_session("ses_test001")
    assert session_obj is not None
    agent = session_obj.agents["ses_test001"]

    text_events = [e for e in agent.events if e.kind == "text"]
    assert len(text_events) == 1
    assert "Hello" in (text_events[0].summary or "")


def test_opencode_tool_part_creates_tool_event():
    provider, store = _make_oc_provider()
    provider._poll_once()

    session_obj = store.get_session("ses_test001")
    agent = session_obj.agents["ses_test001"]

    tool_events = [e for e in agent.events if e.kind == "tool_result"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_name == "read"


def test_opencode_finish_stop_marks_session_done():
    provider, store = _make_oc_provider()
    provider._poll_once()

    session = store.snapshot()["sessions"]["ses_test001"]
    assert session["status"] == "done"


def test_opencode_idempotent_poll():
    provider, store = _make_oc_provider()
    provider._poll_once()
    provider._poll_once()

    session_obj = store.get_session("ses_test001")
    agent = session_obj.agents["ses_test001"]
    # Events should not be duplicated on second poll
    text_events = [e for e in agent.events if e.kind == "text"]
    assert len(text_events) == 1


def test_opencode_missing_db_does_not_crash(tmp_path: Path):
    store = Store()
    provider = OpenCodeProvider(db_path=tmp_path / "nonexistent.db", store=store)
    provider._poll_once()
    assert store.snapshot()["sessions"] == {}


# ---------------------------------------------------------------------------
# Claude Code regression: provider field preserved
# ---------------------------------------------------------------------------


def test_claude_code_provider_field_default():
    store = Store()
    session = store.ensure_session("s1", "/tmp", "slug")
    assert session.provider == "claude-code"
    assert store.snapshot()["sessions"]["s1"]["provider"] == "claude-code"


def test_provider_field_in_agent_dict():
    store = Store()
    store.ensure_session("s1", "/tmp", "slug")
    agent = store.ensure_agent(
        session_id="s1",
        agent_id="child1",
        parent_agent_id="s1",
        agent_type="Explore",
        description=None,
        transcript_path=None,
        started_at="2026-01-01",
    )
    assert agent.provider == "claude-code"
    assert agent.to_dict()["provider"] == "claude-code"


def test_custom_provider_field():
    store = Store()
    session = store.ensure_session("s2", "/tmp", "slug", provider="codex-cli")
    assert session.provider == "codex-cli"
    assert store.snapshot()["sessions"]["s2"]["provider"] == "codex-cli"
