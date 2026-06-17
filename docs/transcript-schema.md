# Transcript Schema — Observed on macOS, CC v2.1.153

All data observed directly from `~/.claude` on 2026-06-16. Schema details verified against live files.

---

## Config Directory

Resolution order:
1. `CLAUDE_CONFIG_DIR` env var (not set by default)
2. `~/.claude`

Projects: `<config>/projects/<encoded-cwd>/`

The `<encoded-cwd>` slug is OS-dependent and opaque — unix paths become `-Users-name-project`. Never parse it; read `cwd` from inside JSONL lines instead.

---

## File Layout

```
~/.claude/projects/<encoded-cwd>/
├── <session-id>.jsonl                         # parent session transcript
└── <session-id>/
    ├── subagents/
    │   ├── agent-<agentId>.jsonl              # subagent transcript
    │   └── agent-<agentId>.meta.json          # subagent metadata
    └── tool-results/
        └── <toolUseId>.txt                    # large tool result files
```

**Layout confirmed**: subagents directory is at `<session-id>/subagents/` alongside the parent JSONL. This is the definitive pattern — not sibling session files, not `parentUuid` chaining to other root-level JSONLs.

---

## Subagent Identification

- `agentId` = hex string like `a27817f43a815e3f3`
- File: `agent-<agentId>.jsonl`
- Every line in the subagent JSONL carries `"agentId": "<agentId>"`
- Meta file: `agent-<agentId>.meta.json` — fields: `agentType` (string), `description` (string)

---

## JSONL Line Types

All lines share a base set of fields:
- `type` — discriminant (see below)
- `uuid` — line UUID
- `parentUuid` — chaining within the conversation (null for first)
- `sessionId` — parent session UUID (same for both parent and subagent files)
- `isSidechain` — bool; `true` for subagent lines
- `timestamp` — ISO 8601
- `cwd` — working directory
- `entrypoint` — e.g. `"cli"`
- `gitBranch` — current branch or null
- `userType` — e.g. `"external"`
- `version` — CC version string

### `assistant`

Assistant turn. Key-unique field: `message` (object).

Parent-session additional fields: `requestId`

Subagent-only additional fields: `agentId`, `attributionAgent`

`message` shape:
```json
{
  "model": "claude-haiku-4-5-20251001",
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [ /* content blocks */ ],
  "stop_reason": "tool_use" | "end_turn" | null,
  "stop_sequence": null,
  "usage": {
    "input_tokens": 3,
    "cache_creation_input_tokens": 10251,
    "cache_read_input_tokens": 0,
    "output_tokens": 117,
    "cache_creation": {
      "ephemeral_5m_input_tokens": 10251,
      "ephemeral_1h_input_tokens": 0
    },
    "service_tier": "standard",
    "inference_geo": "not_available"
  }
}
```

Content block types observed:
- `text` — `{"type": "text", "text": "..."}`
- `thinking` — `{"type": "thinking", "thinking": "..."}`
- `tool_use` — `{"type": "tool_use", "id": "toolu_...", "name": "ToolName", "input": {...}}`
- `tool_result` — `{"type": "tool_result", "tool_use_id": "toolu_...", "content": [...]}`

### `user`

User turn or tool result. Key-unique field: `message` (user prompt) or `toolUseResult`.

Additional fields that may be present:
- `toolUseResult` — result of a tool use; shape varies by tool:
  - For `Agent` tool: `{"status": "completed", "prompt": "...", "agentId": "...", "agentType": "...", "content": "...", "totalDurationMs": N, "totalTokens": N, "totalToolUseCount": N, "usage": {...}, "toolStats": {...}}`
  - For `Bash`: `{"stdout": "...", "stderr": "...", "interrupted": false, "isImage": false, "noOutputExpected": false}`
  - For file tools: `{"type": "text", "file": {"filePath": "...", "content": "..."}}`
- `sourceToolAssistantUUID` — UUID of assistant turn that triggered this tool result
- `promptId` — for user-typed messages
- `permissionMode` — e.g. `"acceptEdits"`

**Subagent linking via `toolUseResult`**: When the `Agent` tool completes, the parent's `user` line has `toolUseResult.agentId` matching the subagent's `agentId`. This is how a finished subagent connects back to the parent turn.

### `system`

System metadata. Has `subtype` field.

Subtypes observed:
- `stop_hook_summary` — fields: `stopReason`, `hasOutput`, `hookCount`, `hookErrors`, `hookInfos`, `preventedContinuation`, `toolUseID`
- `turn_duration` — fields: `durationMs`, `messageCount`, `isMeta`
- `away_summary` — fields: `content`

### `attachment`

Metadata injected into the transcript. Has `attachment` field (object).

Attachment types observed:
- `hook_success` — `{hookName, toolUseID, hookEvent, content, stdout, stderr, exitCode, command, durationMs}`
- `async_hook_response` — `{processId, hookName, hookEvent, response, stdout, stderr, exitCode}`
- `deferred_tools_delta` — `{addedNames, addedLines, removedNames, readdedNames, pendingMcpServers}`
- `agent_listing_delta` — `{addedTypes, addedLines, removedTypes, isInitial, showConcurrencyNote}`
- `skill_listing` — `{content, skillCount, isInitial, names}`
- `task_reminder` — `{content, itemCount}`

### Metadata-only types (no `uuid` / `parentUuid`)

These lines carry session-level state and are NOT conversation turns:

| type | key fields |
|---|---|
| `last-prompt` | `lastPrompt`, `leafUuid`, `sessionId` |
| `mode` | `mode`, `sessionId` |
| `permission-mode` | `permissionMode`, `sessionId` |
| `ai-title` | `aiTitle`, `sessionId` |
| `file-history-snapshot` | `isSnapshotUpdate`, `messageId`, `snapshot` |

---

## Subagent File Differences vs Parent

| Field | Parent | Subagent |
|---|---|---|
| `agentId` | absent | present (hex ID) |
| `attributionAgent` | absent | present on `assistant` lines |
| `isSidechain` | `false` | `true` |
| line types | all types | `assistant` + `user` only |
| `sessionId` | session UUID | same session UUID |

The `sessionId` in subagent lines is the **parent** session UUID, not a separate one. The subagent is identified by `agentId`, not a separate `sessionId`.

---

## Hook Payloads

Observed field set for `PreToolUse` (confirmed firing on macOS):

```json
{
  "session_id": "...",
  "transcript_path": "/Users/.../.claude/projects/.../SESSION.jsonl",
  "cwd": "/Users/.../project",
  "permission_mode": "acceptEdits",
  "effort": {"level": "medium"},
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {"command": "...", "description": "..."},
  "tool_use_id": "toolu_..."
}
```

Expected fields for `SubagentStart` / `SubagentStop` (not yet captured; likely include `subagent_id` / `agentId`).

Hook commands must read stdin, process fast, and exit 0. Use `ccview hook` subcommand as the command — all logic stays in one Python binary; only the installed path differs per OS.

---

## Parser Notes

- Open files in binary mode, decode UTF-8 with `errors='replace'`, strip `\r\n`
- Track per-file byte offset; on MODIFY event, seek to offset, read new bytes, split on `\n`, buffer trailing partial
- If file size < stored offset: file was compacted — reset offset to 0 and re-read
- Unknown `type` values must **not** crash — log and skip, preserving raw bytes
- Unknown fields within known types must be tolerated (forward-compatible)
