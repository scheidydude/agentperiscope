"""Tests for JSONL parser."""

import json
from pathlib import Path

import pytest

from ccview.transcripts import (
    AssistantLine,
    SystemLine,
    UnknownLine,
    UserLine,
    Tailer,
    parse_line,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _encode(obj: dict) -> bytes:
    return json.dumps(obj).encode()


def test_parse_assistant_line():
    raw = _encode({
        "type": "assistant",
        "uuid": "abc",
        "parentUuid": None,
        "sessionId": "s1",
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": "/tmp",
        "isSidechain": False,
        "message": {
            "model": "claude-haiku-4-5",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    })
    line = parse_line(raw)
    assert isinstance(line, AssistantLine)
    assert line.model == "claude-haiku-4-5"
    assert len(line.content) == 2
    assert line.content[0].type == "text"
    assert line.content[0].text == "hello"
    assert line.content[1].tool_name == "Bash"
    assert line.usage is not None
    assert line.usage.input_tokens == 10


def test_parse_user_line_with_agent_result():
    raw = _encode({
        "type": "user",
        "uuid": "u1",
        "parentUuid": "a1",
        "sessionId": "s1",
        "timestamp": "2026-01-01T00:00:01Z",
        "cwd": "/tmp",
        "isSidechain": False,
        "message": {"role": "user", "content": []},
        "toolUseResult": {
            "status": "completed",
            "agentId": "deadbeef",
            "agentType": "Explore",
            "totalTokens": 100,
        },
    })
    line = parse_line(raw)
    assert isinstance(line, UserLine)
    assert line.tool_use_result is not None
    assert line.tool_use_result["agentId"] == "deadbeef"


def test_parse_system_line():
    raw = _encode({
        "type": "system",
        "uuid": "sys1",
        "parentUuid": "a1",
        "sessionId": "s1",
        "timestamp": "2026-01-01T00:00:02Z",
        "cwd": "/tmp",
        "isSidechain": False,
        "subtype": "stop_hook_summary",
        "stopReason": "end_turn",
    })
    line = parse_line(raw)
    assert isinstance(line, SystemLine)
    assert line.subtype == "stop_hook_summary"
    assert line.stop_reason == "end_turn"


def test_unknown_type_does_not_crash():
    raw = _encode({"type": "totally-unknown-future-type", "data": [1, 2, 3]})
    line = parse_line(raw)
    assert isinstance(line, UnknownLine)
    assert line.type == "totally-unknown-future-type"


def test_malformed_json_returns_none():
    line = parse_line(b"{not valid json")
    assert line is None


def test_blank_line_returns_none():
    assert parse_line(b"") is None
    assert parse_line(b"   \r\n") is None


def test_partial_assistant_line_tolerant():
    """Missing fields should not crash — use defaults."""
    raw = _encode({"type": "assistant", "sessionId": "s1"})
    line = parse_line(raw)
    assert isinstance(line, AssistantLine)
    assert line.content == []


def test_tailer_reads_new_lines(tmp_path):
    f = tmp_path / "test.jsonl"
    line1 = json.dumps({"type": "mode", "sessionId": "s1"}) + "\n"
    f.write_text(line1)

    tailer = Tailer(f)
    results = tailer.read_new()
    assert len(results) == 1

    # Append another line
    line2 = json.dumps({"type": "mode", "sessionId": "s1"}) + "\n"
    with f.open("a") as fh:
        fh.write(line2)

    results2 = tailer.read_new()
    assert len(results2) == 1

    # No new data
    assert tailer.read_new() == []


def test_tailer_handles_compaction(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text(json.dumps({"type": "mode", "sessionId": "s1"}) + "\n")
    tailer = Tailer(f)
    tailer.read_new()
    assert tailer.offset > 0

    # Simulate compaction: overwrite with shorter content
    f.write_text(json.dumps({"type": "mode", "sessionId": "s2"}) + "\n")
    # Truncate so size < offset
    with f.open("rb+") as fh:
        fh.truncate(1)

    # Should reset and not crash; no newline in 1 byte so offset stays 0
    results = tailer.read_new()
    assert tailer.offset == 0  # reset happened; partial byte buffered, no complete line


def test_fixture_parent_session_parses():
    fixture = FIXTURES / "parent-session-sample.jsonl"
    tailer = Tailer(fixture)
    results = tailer.read_new()
    assert len(results) > 0
    types = {r[0].__class__.__name__ for r in results}
    assert len(types) > 1  # multiple line types


def test_fixture_subagent_session_parses():
    fixture = FIXTURES / "subagent-session-sample.jsonl"
    tailer = Tailer(fixture)
    results = tailer.read_new()
    assert len(results) > 0
    for line, _ in results:
        assert isinstance(line, (AssistantLine, UserLine, UnknownLine))
