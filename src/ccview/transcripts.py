"""JSONL transcript parser and byte-offset tailer.

Schema: docs/transcript-schema.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed line models
# ---------------------------------------------------------------------------

@dataclass
class UsageBlock:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UsageBlock":
        return cls(
            input_tokens=d.get("input_tokens", 0),
            output_tokens=d.get("output_tokens", 0),
            cache_creation_input_tokens=d.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=d.get("cache_read_input_tokens", 0),
        )


@dataclass
class ContentBlock:
    type: str  # text | thinking | tool_use | tool_result
    text: str | None = None
    thinking: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ContentBlock":
        return cls(
            type=d.get("type", "unknown"),
            text=d.get("text"),
            thinking=d.get("thinking"),
            tool_use_id=d.get("id") or d.get("tool_use_id"),
            tool_name=d.get("name"),
            tool_input=d.get("input"),
        )


@dataclass
class AssistantLine:
    uuid: str
    parent_uuid: str | None
    session_id: str
    timestamp: str
    cwd: str
    is_sidechain: bool
    model: str | None
    content: list[ContentBlock]
    usage: UsageBlock | None
    stop_reason: str | None
    agent_id: str | None  # subagent only
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class UserLine:
    uuid: str
    parent_uuid: str | None
    session_id: str
    timestamp: str
    cwd: str
    is_sidechain: bool
    content: list[ContentBlock]
    tool_use_result: dict[str, Any] | None
    agent_id: str | None  # subagent only
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class SystemLine:
    uuid: str | None
    parent_uuid: str | None
    session_id: str
    timestamp: str
    subtype: str
    duration_ms: int | None
    stop_reason: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class UnknownLine:
    type: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


AnyLine = AssistantLine | UserLine | SystemLine | UnknownLine


def _parse_content(raw_content: Any) -> list[ContentBlock]:
    if not isinstance(raw_content, list):
        return []
    blocks = []
    for item in raw_content:
        if isinstance(item, dict):
            try:
                blocks.append(ContentBlock.from_dict(item))
            except Exception:
                pass
    return blocks


def parse_line(raw: bytes) -> AnyLine | None:
    """Parse one JSONL line. Returns None for blank/unparseable lines."""
    text = raw.decode("utf-8", errors="replace").strip().rstrip("\r")
    if not text:
        return None
    try:
        obj: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        log.debug("json parse error: %s", text[:120])
        return None

    kind = obj.get("type", "")

    try:
        if kind == "assistant":
            msg = obj.get("message") or {}
            usage_raw = msg.get("usage")
            return AssistantLine(
                uuid=obj.get("uuid", ""),
                parent_uuid=obj.get("parentUuid"),
                session_id=obj.get("sessionId", ""),
                timestamp=obj.get("timestamp", ""),
                cwd=obj.get("cwd", ""),
                is_sidechain=bool(obj.get("isSidechain")),
                model=msg.get("model"),
                content=_parse_content(msg.get("content")),
                usage=UsageBlock.from_dict(usage_raw) if isinstance(usage_raw, dict) else None,
                stop_reason=msg.get("stop_reason"),
                agent_id=obj.get("agentId"),
                raw=obj,
            )

        if kind == "user":
            msg = obj.get("message") or {}
            return UserLine(
                uuid=obj.get("uuid", ""),
                parent_uuid=obj.get("parentUuid"),
                session_id=obj.get("sessionId", ""),
                timestamp=obj.get("timestamp", ""),
                cwd=obj.get("cwd", ""),
                is_sidechain=bool(obj.get("isSidechain")),
                content=_parse_content(msg.get("content") if isinstance(msg, dict) else []),
                tool_use_result=obj.get("toolUseResult"),
                agent_id=obj.get("agentId"),
                raw=obj,
            )

        if kind == "system":
            return SystemLine(
                uuid=obj.get("uuid"),
                parent_uuid=obj.get("parentUuid"),
                session_id=obj.get("sessionId", ""),
                timestamp=obj.get("timestamp", ""),
                subtype=obj.get("subtype", ""),
                duration_ms=obj.get("durationMs"),
                stop_reason=obj.get("stopReason"),
                raw=obj,
            )

    except Exception as exc:
        log.warning("parse_line failed for type=%r: %s", kind, exc)

    return UnknownLine(type=kind or "<no-type>", raw=obj if isinstance(obj, dict) else {})


# ---------------------------------------------------------------------------
# Byte-offset tailer
# ---------------------------------------------------------------------------

@dataclass
class RawRef:
    path: Path
    offset: int
    length: int


class Tailer:
    """Tracks a byte offset into one JSONL file; yields new complete lines on each read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._offset: int = 0
        self._buf: bytes = b""

    @property
    def offset(self) -> int:
        return self._offset

    def read_new(self) -> list[tuple[AnyLine, RawRef]]:
        """Read new bytes since last call. Returns (parsed_line, raw_ref) pairs."""
        try:
            size = self.path.stat().st_size
        except OSError:
            return []

        if size < self._offset:
            # file was compacted/rotated — reset
            log.debug("tailer reset (shrink) %s", self.path)
            self._offset = 0
            self._buf = b""

        if size == self._offset:
            return []

        results: list[tuple[AnyLine, RawRef]] = []
        try:
            with self.path.open("rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read(size - self._offset)
        except OSError as exc:
            log.warning("tailer read error %s: %s", self.path, exc)
            return []

        self._buf += chunk
        while b"\n" in self._buf:
            line_bytes, self._buf = self._buf.split(b"\n", 1)
            raw_ref = RawRef(
                path=self.path,
                offset=self._offset,
                length=len(line_bytes) + 1,
            )
            self._offset += len(line_bytes) + 1
            parsed = parse_line(line_bytes)
            if parsed is not None:
                results.append((parsed, raw_ref))

        return results
