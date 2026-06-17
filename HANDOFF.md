# HANDOFF — ccview (2026-06-17)

## 1. Mission

`ccview` is a local live viewer for Claude Code subagent activity. It tails CC session transcripts and listens to lifecycle hooks, rendering a per-agent lane view in the browser at `127.0.0.1`. The goal: see agents fan out, watch tool calls in real time, step away from the terminal. Phase 1 (MVP) is functionally complete and debugged. Phase 2 (history/search persistence) has not started.

---

## 2. Current State

### Working and verified
- **Boot scan + watcher**: `Watcher` reads all existing JSONL files on start, then watches for live changes via `watchfiles`. Finds sessions, subagents, and correctly tracks which are running vs done.
- **Parser** (`transcripts.py`): Typed models for `AssistantLine`, `UserLine`, `SystemLine`, `UnknownLine`. Byte-offset `Tailer` per file. Tolerates unknown line types without crashing.
- **In-memory store** (`model.py`): `Session/Agent/Event` state. Delta broadcasting to WebSocket subscribers.
- **Server** (`server.py`): FastAPI on `127.0.0.1` only (verified via `lsof`). `POST /events` for hook ingest, `/ws` WebSocket hub, SPA served at `/`.
- **CLI** (`cli.py`): `ccview`, `ccview hook`, `ccview install-hooks`, `ccview uninstall-hooks` all working.
- **React SPA** (`frontend/`): Agent lane UI (dark theme, Tailwind). Active vs History sections. Blue pulsing dot = running, green = done. Built into `src/ccview/web/`.
- **Packaging**: `uv sync` installs cleanly. `uv run ccview` works. `pyproject.toml` bundles `src/ccview/web/` into the wheel.
- **18/18 tests passing.**

### Status bugs fixed this session (do not revert)
- `async_launched` CC status → `"running"` (not `"done"`) — these are background-dispatched agents still doing work
- Agent completion detected from subagent's own JSONL tail (`stop_reason == "end_turn"`) via `_reconcile_one_subagent`; fallback: file unchanged >5 min → done regardless of stop_reason
- Ghost sessions (metadata-only JSONL, no real lines) filtered: `App.tsx` requires `cwd && last_activity_ts`
- Stale "running" root agents: uses JSONL line timestamps (not file mtime, which CC refreshes on startup) — any root with `last_activity_ts` older than 1h is marked done
- Boot scan ordering: subagent files processed before parent files so subagents exist in store when parent's `toolUseResult` references them

### Known remaining issues / next actions
1. **`ccview hook` port is hardcoded to 7821** — if server auto-picked a different port, hooks won't reach it. Fix: server should write its chosen port to a known location (e.g., `~/.claude/ccview.port`) that `ccview hook` reads.
2. **No `git init`** — repo has no git history. Should be initialized if the user wants version control.
3. **Phase 2 not started** — no persistence of historical sessions, no search, no SQLite.
4. **`install-hooks` hook event list** — currently installs `SubagentStart`, `SubagentStop`, `Stop`, `PreToolUse`, `PostToolUse`. Worth confirming which are actually useful for the live view vs noise.

**Exact next action**: Fix the hook port problem (item 1 above) — it's the only thing preventing `ccview install-hooks` from working end-to-end in a real session.

---

## 3. Decisions Made (and Why)

**Decision:** `async_launched` CC status → `"running"`, not `"done"`
- **Rejected:** mapping to `"done"` (done earlier in the session, caused 20 agents to show as done while still running)
- **Reason:** `async_launched` means the parent dispatched the subagent asynchronously and moved on; the subagent is still executing. Completion is detected by reading the subagent's own transcript tail.
- **Reversibility:** Easy to change in `model.py:apply_line`.

**Decision:** Completion detection uses two signals: (a) `stop_reason == "end_turn"` in the subagent's JSONL tail, (b) file mtime >5 min as fallback for `tool_use`/`None`/missing AssistantLine cases
- **Rejected:** trusting only `toolUseResult` from the parent (parent only gets `async_launched`, no completion signal for async agents)
- **Reason:** Async agents never write a completion entry back to the parent. Only the subagent's own file tells you when it stopped.
- **Reversibility:** Easy. Logic is isolated in `_reconcile_one_subagent` in `watcher.py`.

**Decision:** Stale session detection uses JSONL line timestamps, not file mtime
- **Rejected:** file mtime (was the original implementation)
- **Reason:** CC writes metadata lines (`last-prompt`, `mode`, `ai-title`, etc.) to session files on startup, making mtime recent even for week-old sessions. This caused dozens of dead sessions to appear in Active.
- **Reversibility:** Easy. Logic is in `_reconcile_stale_sessions`.

**Decision:** Filter displayed sessions by `cwd && last_activity_ts` (not just `cwd`)
- **Rejected:** filter by `cwd` alone
- **Reason:** Some sessions get `cwd` set from metadata-only JSONL lines but never have real assistant/user content. `last_activity_ts` is only set when a real `AssistantLine` or `UserLine` is parsed.
- **Reversibility:** Easy. In `App.tsx`.

**Decision:** Boot scan processes subagent files before parent files
- **Rejected:** natural rglob order (parents first)
- **Reason:** Parent JSONL contains `toolUseResult` entries that reference subagent IDs. If parent is processed first, the subagent doesn't exist in the store yet when the completion is recorded, so the completion is silently dropped.
- **Reversibility:** Easy. Ordering is in `_boot_scan`.

**Decision:** `ensure_session` updates `cwd` when called with a non-empty cwd on an already-existing session
- **Rejected:** idempotent (never update after creation)
- **Reason:** Metadata-only lines are processed first and create the session with `cwd=""`. The first real AssistantLine/UserLine then provides the real cwd. Without this update, the session is invisible to the `cwd` filter forever.
- **Reversibility:** Easy. In `Store.ensure_session`.

**Decision:** `async_launched` agents are reconciled in `_reconcile_stale_sessions` (post-boot-scan), not during `_register_path`
- **Rejected:** reconcile during `_register_path`
- **Reason:** During boot scan, subagent files are processed before parent files. At the time `_register_path` runs for a subagent, `store.get_session(parent_session)` returns `None` (session not created yet), so early reconciliation silently no-ops.
- **Reversibility:** Easy. `_reconcile_stale_sessions` is called at end of `_boot_scan`.

**Decision:** No `SubagentStart`/`SubagentStop` hook handling in the store yet — hooks just call `ensure_session` and emit a raw delta
- **Reason:** The watcher's file tail is the source of truth for content. Hooks provide a "something changed" signal, not a parsed data source. The `/events` endpoint just ensures the session is known and broadcasts the hook payload raw.
- **Reversibility:** Easy to enhance; hooks could fast-path agent creation.

---

## 4. Architecture & Key Files

### Python backend (`src/ccview/`)

| File | What it does |
|---|---|
| `config.py` | Resolves Claude config dir: `--claude-dir` → `CLAUDE_CONFIG_DIR` → `~/.claude`. All pathlib, no shell assumptions. |
| `transcripts.py` | Typed line models (`AssistantLine`, `UserLine`, `SystemLine`, `UnknownLine`). `Tailer` class: per-file byte offset, reads new bytes on each call, buffers partial lines, resets on compaction. |
| `model.py` | `Store`: in-memory `Session`/`Agent`/`Event` state. `apply_line` ingests parsed lines and updates agent state (tokens, current_tool, last_text, status). Delta broadcasting via subscriber callbacks. Critical: `ensure_session` updates cwd on existing sessions. |
| `watcher.py` | `Watcher`: boot scan + watchfiles live watch. `_boot_scan` processes subagent files before parent files. `_reconcile_stale_sessions` marks old roots done and reconciles async subagents. `_reconcile_one_subagent` reads file tail to detect completion. |
| `hooks.py` | `handle_hook`: reads stdin JSON, POSTs to server, exits fast. `install_hooks`/`uninstall_hooks`: idempotent merge into `settings.json`. |
| `server.py` | FastAPI on `127.0.0.1`. `/events` (hook ingest), `/ws` (WebSocket hub), `/` (SPA). `find_free_port()` auto-selects port. |
| `cli.py` | Typer CLI. `ccview` (main), `ccview hook`, `ccview install-hooks`, `ccview uninstall-hooks`. |

### React frontend (`frontend/src/`)

| File | What it does |
|---|---|
| `types.ts` | TypeScript interfaces: `SessionState`, `AgentState`, `TokenCounts`, `WsMessage` union. |
| `useStore.ts` | WebSocket connection + state reducer. `applyMessage` handles snapshot/session_start/agent_update etc. Auto-reconnects. |
| `App.tsx` | Root component. Filters sessions by `cwd && last_activity_ts`, sorts by `last_activity_ts` descending, splits into Active/History sections. |
| `SessionView.tsx` | One card per session. Grid of AgentCards. |
| `AgentCard.tsx` | Per-agent card: status dot, agent_type, description, last_text, current_tool badge, token count. |

### Tests & fixtures (`tests/`)
- `test_transcripts.py` — parser + Tailer unit tests
- `test_model.py` — Store state machine tests
- `fixtures/` — sanitized real JSONL samples (parent session, subagent, meta, hook payload)

### Schema reference
- `docs/transcript-schema.md` — observed CC JSONL schema on CC v2.1.153/macOS. Ground truth for parser decisions.

### Do not touch casually
- `src/ccview/web/` — generated by `npm run build` in `frontend/`. Committed so wheel packaging works. Re-run `scripts/build_frontend.sh` to regenerate.
- Boot scan ordering in `_boot_scan` (subagents before parents) — reverting this silently breaks completion tracking.

---

## 5. Gotchas & Hard-Won Knowledge

- **CC writes metadata lines to old session files on startup** (`last-prompt`, `mode`, `ai-title`). File mtime is useless for staleness detection. Use the `last_activity_ts` (ISO timestamp from the last real AssistantLine/UserLine).

- **`async_launched` is not a completion status.** It means the Agent tool dispatched the subagent asynchronously and the parent moved on. The subagent is still running. Only the subagent's own JSONL tail reveals when it finishes.

- **`stop_reason="tool_use"` is mid-turn, not end-of-turn.** CC emits TWO AssistantLine entries per turn: one with `stop_reason=null` (streaming start) and one with the actual stop_reason. The last line in a clean subagent file is `stop_reason="end_turn"`. If the last is `"tool_use"` or `null`, the agent either died mid-call or is still running — use file mtime to distinguish.

- **Subagent JSONL schema differs from parent JSONL.** Subagent files only have `assistant` and `user` types (no `system`). They add `agentId` and `attributionAgent` fields. The `sessionId` in subagent lines is the **parent** session UUID, not a subagent-specific ID.

- **Metadata-only JSONL files create ghost sessions.** Lines like `mode`, `last-prompt`, `permission-mode`, `attachment`, `file-history-snapshot` have `sessionId` but no `cwd` or `timestamp`. Without guarding, they create hundreds of empty sessions that appear in Active (root.status never set to done). Guard: only show sessions with both `cwd` and `last_activity_ts` set.

- **`ensure_session` must update cwd post-creation.** A fresh session file starts with metadata lines (no cwd). The first real line arrives later. If `ensure_session` is idempotent after creation, the session is permanently invisible to any cwd-based filter.

- **Boot scan order matters for completion tracking.** Parent JSONL has `toolUseResult` entries with `agentId`. If the parent JSONL is read before the subagent file, the subagent doesn't exist in `session.agents` when the `toolUseResult` is processed — the completion is silently dropped.

- **`_reconcile_one_subagent` is called in `_reconcile_stale_sessions`, not during `_register_path`.** During boot scan, `_register_path` is called for subagent files before the parent session exists in the store (`store.get_session(parent_session)` returns None). Reconciliation must happen after ALL files are processed.

- **Not a git repo yet.** `git status` gives `fatal: not a git repository`. Run `git init && git add . && git commit` before touching version-controlled workflows.

---

## 6. Conventions In Play

- **Python 3.12, uv toolchain, hatchling build.** Entry point: `ccview = "ccview.cli:app"`. Dev: `uv sync`, `uv run ccview`.
- **Frontend**: React + Vite + TypeScript + Tailwind. Dev server proxies `/ws` and `/events` to `127.0.0.1:7821`. Build: `cd frontend && npm run build` → outputs to `src/ccview/web/`. The built SPA is committed and bundled into the wheel.
- **No comments unless the WHY is non-obvious.** No docstrings on obvious methods.
- **Schema drift tolerance**: unknown line types → `UnknownLine`, unknown fields ignored. Parser must never crash on unexpected JSONL.
- **No raw content persisted.** Store `RawRef` (file + offset), not payloads. Secrets stay in the JSONL on disk, not in ccview's state.
- **Tests in `tests/`** use sanitized fixtures from `tests/fixtures/`. Run: `uv run pytest tests/`. No mocking of the file system in transcript tests — use `tmp_path`.

---

## 7. Open Questions

1. **Hook port discovery**: `ccview hook` has `--port 7821` hardcoded. How should the installed ccview binary know which port the server started on? Options: (a) write port to `~/.claude/ccview.port`, (b) fix port via `--port` flag in both server and hook install, (c) use a well-known default and document it. User input needed on preferred approach.

2. **Which hook events to install?** Currently: `SubagentStart`, `SubagentStop`, `Stop`, `PreToolUse`, `PostToolUse`. `PreToolUse` fires on every tool call — noisy but useful for seeing agent activity. Worth confirming with user whether all five are wanted or just lifecycle events.

3. **`ccview install-hooks` — global vs project default?** Currently defaults to global if neither `--global` nor `--project` is specified. Is that right?

4. **Phase 2 scope**: The scope doc mentions SQLite for history. Is this the next priority, or is there polish work on Phase 1 first (e.g., click-to-expand full transcript, token detail breakdown)?

5. **`git init`?** The repo has no git history. Should we initialize before next session?

---

## 8. Do Not Touch

- **`src/ccview/web/`** — generated output. Edit `frontend/src/` instead, then rebuild.
- **Boot scan ordering** (`subagent_files + parent_files` in `_boot_scan`) — reverting breaks completion tracking silently.
- **`async_launched` → `"running"` mapping** — not `"done"`. This was wrong once and cost real debugging time.
- **`ensure_session` cwd update logic** — the `if cwd and not sess.cwd: sess.cwd = cwd` block in `Store.ensure_session`. Remove it and sessions with initial metadata lines become permanently invisible.
- **`_reconcile_stale_sessions` call order** — must run after both subagent and parent files are processed. Moving it into `_register_path` breaks it.

---

## 9. Resume Command

> "Read HANDOFF.md. The immediate next task is fixing the hook port discovery problem: `ccview hook` has `--port 7821` hardcoded, but the server auto-selects a free port. Fix this so installed hooks find the running server — proposed approach is writing the chosen port to `~/.claude/ccview.port` on server start and reading it in `ccview hook`. Do not change the subagent status/completion logic in `watcher.py` without reading section 5 (Gotchas). Run `uv run pytest tests/ -q` after any Python changes. Confirm with user before starting Phase 2 (SQLite persistence)."
