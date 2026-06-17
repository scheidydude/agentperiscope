# HANDOFF — ccview (2026-06-17)

## 1. Mission

`ccview` is a local live viewer for Claude Code subagent activity. It tails CC session transcripts, listens to lifecycle hooks, and renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP live view) is complete and committed. Phase 2 (history persistence + search) is next.

---

## 2. Current State

### Committed and working (2 commits on `main`)

- `cd32df6` — Phase 1 MVP: watcher, parser, in-memory store, FastAPI server, React SPA, CLI, hooks install/uninstall, 18 tests
- `10f6cbd` — Hook port fix: server writes `~/.claude/ccview.port` on start, deletes on exit; `ccview hook` reads it instead of using hardcoded 7821

**Verified working:**
- `uv run ccview` launches, binds `127.0.0.1` only, opens browser, correctly shows Active/History sessions
- `ccview install-hooks` / `uninstall-hooks` idempotent
- `ccview hook` auto-discovers server port from `~/.claude/ccview.port`; silent no-op if server is down
- 18/18 tests pass
- Boot scan correctly categorizes: Active = sessions with `last_activity_ts` <1h + running agents; History = everything else

### Not started

Phase 2: persist sessions to SQLite so history survives restarts and is searchable. User confirmed this is the next priority. Exact scope TBD (see Open Questions).

### Next action

Ask the user which Phase 2 feature to tackle first (browse history vs. search vs. expand-transcript UX) — the user was asked this at the end of the session and had not yet replied. Then start `src/ccview/store.py` (SQLite persistence layer).

---

## 3. Decisions Made (and Why)

**Decision:** Port discovery via `~/.claude/ccview.port` file
- **Rejected:** fixed default port (7821 was hardcoded in hook subcommand); env var
- **Reason:** Server auto-selects a free port; installed hook command has no way to know it. Port file is the simplest cross-platform IPC.
- **Reversibility:** Easy. `config.py` + `cli.py` + `hooks.py`.

**Decision:** `async_launched` CC status → `"running"`, not `"done"`
- **Reason:** `async_launched` means the Agent tool dispatched the subagent in the background and the parent moved on. The subagent is still executing. Completion is detected by reading the subagent's own JSONL tail (`stop_reason == "end_turn"`) or via file-age fallback (unchanged >5 min → done).
- **Reversibility:** Easy — `model.py:apply_line`.

**Decision:** Stale session detection uses JSONL line timestamps, not file mtime
- **Reason:** CC writes metadata lines to old session files on startup, refreshing mtime. Sessions days old appeared in Active with mtime-based detection.
- **Reversibility:** Easy — `watcher.py:_reconcile_stale_sessions`.

**Decision:** Boot scan processes subagent files before parent files
- **Reason:** Parent JSONL has `toolUseResult` entries referencing subagent IDs. If parent is read first, the subagent doesn't exist in the store yet and the completion event is silently dropped.
- **Reversibility:** Easy — ordering in `_boot_scan`.

**Decision:** Filter displayed sessions by `cwd && last_activity_ts`
- **Reason:** CC creates hundreds of metadata-only JSONL files (mode, last-prompt, etc.) that parse as sessions with no real content. `last_activity_ts` is only set when a real AssistantLine/UserLine is processed.
- **Reversibility:** Easy — `App.tsx`.

**Decision:** `ensure_session` updates `cwd` post-creation when a real cwd arrives
- **Reason:** Session files start with metadata lines (no cwd). Without this update the session stays hidden behind the cwd filter permanently.
- **Reversibility:** Easy — `model.py:Store.ensure_session`.

---

## 4. Architecture & Key Files

### Python (`src/ccview/`)

| File | Purpose |
|---|---|
| `config.py` | Resolves Claude config dir: `--claude-dir` → `CLAUDE_CONFIG_DIR` → `~/.claude`. Pathlib only. |
| `transcripts.py` | Typed line models + `Tailer` (byte-offset per file, buffers partials, resets on compaction). |
| `model.py` | `Store`: in-memory `Session`/`Agent`/`Event`. `apply_line` ingests parsed lines. Delta broadcast via subscriber callbacks. |
| `watcher.py` | Boot scan (subagents before parents) + watchfiles live watch. `_reconcile_stale_sessions` + `_reconcile_one_subagent` handle completion detection. |
| `hooks.py` | `handle_hook` (stdin→POST, exits fast). `install_hooks`/`uninstall_hooks` (idempotent settings.json merge). `_resolve_port` reads `ccview.port`. |
| `server.py` | FastAPI on `127.0.0.1`. `/events`, `/ws`, `/` (SPA). |
| `cli.py` | Typer entry points. On start: writes `~/.claude/ccview.port`. On stop (finally + signal): deletes it. |

### React frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `types.ts` | `SessionState`, `AgentState`, `TokenCounts`, `WsMessage` union |
| `useStore.ts` | WebSocket + reconnect + state reducer |
| `App.tsx` | Filter/sort sessions; Active vs History split |
| `SessionView.tsx` | Session card + agent grid |
| `AgentCard.tsx` | Per-agent: status dot, tool badge, last_text, tokens |

### Built output
- `src/ccview/web/` — built SPA, committed, bundled into wheel. Rebuild: `cd frontend && npm run build`.

### Tests
- `tests/test_transcripts.py`, `tests/test_model.py` — 18 tests, all pass
- `tests/fixtures/` — sanitized real JSONL samples

### Schema reference
- `docs/transcript-schema.md` — observed CC JSONL schema on v2.1.153/macOS. Ground truth for parser.

---

## 5. Gotchas & Hard-Won Knowledge

- **CC refreshes mtime on old session files at startup.** Never use file mtime for staleness. Use `last_activity_ts` (ISO timestamp from last real AssistantLine/UserLine in the JSONL).

- **`async_launched` ≠ done.** It's a background-dispatch signal. Parent got the ack and moved on. Subagent is still running. Only the subagent's own tail (or file age) tells you when it finishes.

- **`stop_reason="tool_use"` is mid-turn, not end-of-turn.** Two AssistantLines per turn: one with `stop_reason=null` (streaming start), one with actual stop_reason. `end_turn` = complete. `tool_use` = waiting for tool result. File age >5 min is the fallback for any non-`end_turn` case.

- **Subagent JSONL differs from parent JSONL.** Only `assistant` and `user` types. Adds `agentId` and `attributionAgent`. `sessionId` = parent session UUID (not a subagent-specific ID).

- **Boot scan order is load-bearing.** Subagents must be registered before parents, or completion events in parent `toolUseResult` silently drop (subagent not in `session.agents` yet).

- **`_reconcile_one_subagent` must run after boot scan, not during `_register_path`.** At `_register_path` time for subagent files, `store.get_session(parent_session)` returns None — session not created yet.

- **Hundreds of ghost sessions from metadata-only JSONLs.** CC writes `mode`, `last-prompt`, `ai-title`, `permission-mode` etc. to every session file. These parse as sessions with no real content. Guard: only show `cwd && last_activity_ts`.

- **`ensure_session` must update cwd after creation.** Session files start metadata-only, so the session is first created with `cwd=""`. First real line brings the actual cwd. Without the post-creation update, session is invisible forever.

---

## 6. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** Dev: `uv sync` → `uv run ccview`. Tests: `uv run pytest tests/`.
- **Frontend**: React + Vite + TypeScript + Tailwind. Build: `cd frontend && npm run build` → `src/ccview/web/`. Built output is committed and bundled in the wheel (no Node at runtime).
- **No raw content persisted.** Store `RawRef` (file + offset), not payloads. Secrets stay in JSONL on disk.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Unknown fields ignored. Parser never crashes.
- **No comments unless the WHY is non-obvious.**
- **Commits**: conventional (`feat:`, `fix:`), imperative subject, body explains why not what.

---

## 7. Open Questions

1. **Phase 2 scope — which first?**
   - (a) Browse history: past sessions visible after restarts (SQLite index over JSONL tree)
   - (b) Search: filter/full-text across session history
   - (c) UI polish first: click-to-expand full transcript, token breakdown per turn
   The user was asked but hadn't answered at handoff time. **Ask before building.**

2. **SQLite location**: `~/.claude/ccview.db`? Or alongside `ccview.port`? Should follow `--claude-dir`.

3. **History retention policy**: index everything ever, or configurable window (e.g., last 30 days)? Relevant to DB size on heavy users.

4. **Hook event subset**: currently installs `SubagentStart`, `SubagentStop`, `Stop`, `PreToolUse`, `PostToolUse`. `PreToolUse` fires on every tool call — useful for live updates but noisy in DB. Worth filtering at ingest?

---

## 8. Do Not Touch

- `src/ccview/web/` — generated. Edit `frontend/src/`, then `cd frontend && npm run build`.
- Boot scan ordering in `_boot_scan` (`subagent_files + parent_files`) — reverting silently breaks completion tracking.
- `async_launched` → `"running"` mapping in `model.py:apply_line` — this was wrong (mapped to `"done"`) and cost real debugging time.
- `ensure_session` cwd update block — removing it makes metadata-only-start sessions permanently invisible.
- `_reconcile_stale_sessions` position — must run after all files are processed, not during `_register_path`.

---

## 9. Resume Command

> "Read HANDOFF.md. Ask the user which Phase 2 feature to start with (browse history / search / UI polish) before writing any code. Once confirmed, create `src/ccview/store.py` as the SQLite persistence layer. Do not change watcher.py completion logic or model.py status mapping without reading section 5. Run `uv run pytest tests/ -q` after any Python changes."
