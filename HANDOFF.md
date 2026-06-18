# HANDOFF — agentperiscope (2026-06-17)

## 1. Mission

`agentperiscope` is a local live observability viewer for AI agent activity. It tails session transcripts and listens to lifecycle hooks across multiple providers (Claude Code, Codex, OpenCode), then renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP), Phase 2 (history + search + expand + modal), and Phase 3 (multi-provider) are complete and working. Open-sourced under MIT.

---

## 2. Current State

### Committed on `main` (16 commits)

- `cd32df6` — Phase 1 MVP: watcher, parser, in-memory store, FastAPI server, React SPA, CLI, hooks, 18 tests
- `10f6cbd` — Hook port fix: `~/.claude/agentperiscope.port` auto-discovery
- `90d48a2` — Phase 2a: SQLite persistence — `~/.claude/agentperiscope.db`, survives restarts
- `d479042` — Phase 2b: client-side search bar
- `e2522f0` — Phase 2c: AgentCard expand + token breakdown
- `eff184c` — fix: root session completion via JSONL tail on boot
- `683f1db` — chore: untrack `__pycache__`, archive HANDOFFs
- `bb6a12b` — feat: collapsible Active/History sections with item counts
- `59f1c6c` — feat: pop-out modal for agent event details
- `2bac495` — refactor: rename project ccview → agentperiscope
- `805d0b3` — chore: MIT license, README/HANDOFF update
- `0b7a210` — feat: Phase 3 — multi-provider (Codex CLI + OpenCode)
- `209d722` — fix: OpenCode marks aborted/stale sessions done
- `bde889b` — fix: proper Ctrl+C; stop API; macOS service commands
- `29a2491` — fix: remove duplicate force-include in hatchling build
- `9656dae` — feat: `port` and `open` subcommands; URL in service-status

**Repo**: `git@github.com:scheidydude/agentperiscope.git`

**Verified working:**
- `uv run agentperiscope` launches, opens browser
- All three providers start and report status on startup
- Claude Code: tails `~/.claude/projects/**/*.jsonl` via watchfiles
- Codex: tails `~/.codex/sessions/**/*.jsonl` via watchfiles
- OpenCode: polls `~/.local/share/opencode/opencode.db` every 3s
- Provider filter chips in UI header work
- ProviderBadge appears on each session card
- Active / History sections collapsible with counts
- Sessions that ended while agentperiscope was down appear in History
- SQLite history (`~/.claude/agentperiscope.db`) survives restart
- OpenCode aborted sessions (`MessageAbortedError`) marked done on load
- OpenCode stale sessions (last activity > 30 min, no clean finish) marked done
- Ctrl+C works cleanly (cancels all provider tasks)
- `POST /api/stop` shuts down server programmatically
- `agentperiscope port` / `agentperiscope open` print/open the URL
- `agentperiscope install-service` / `uninstall-service` manage macOS LaunchAgent
- `uv tool install . --reinstall` works (duplicate force-include bug fixed)
- 42/42 tests pass (`uv run pytest tests/ -q`)

---

## 3. Architecture & Key Files

### Python (`src/agentperiscope/`)

| File | Purpose |
|---|---|
| `config.py` | `claude_dir()`, `db_path()`, `default_provider_configs()` |
| `model.py` | `Store`, `Session`, `Agent`, `Event`. All have `provider` field. |
| `db.py` | SQLite schema + `_migrate()` (adds `provider` col). `load_into` → `subscribe`. |
| `server.py` | FastAPI. `POST /api/stop` uses `app.state.shutdown`. API routes before SPA mount. |
| `cli.py` | DB init → `load_into` → `subscribe` → start all providers. Signal handler cancels all tasks. |
| `watcher.py` | Boot scan + live watch for Claude Code. Untouched since Phase 1. |
| `transcripts.py` | Typed CC JSONL line models + `Tailer`. Untouched since Phase 1. |
| `hooks.py` | Hook ingest + install/uninstall. Marker: `"agentperiscope"`. |
| `service.py` | macOS LaunchAgent plist install/uninstall/status. |
| `providers/base.py` | `Provider` ABC: `name`, `async run()` |
| `providers/claude_code.py` | Wraps `Watcher`. `name = "claude-code"`. |
| `providers/codex_cli.py` | Tails Codex JSONL. `name = "codex-cli"`. |
| `providers/opencode.py` | Polls OpenCode SQLite. `name = "opencode"`. |

### React frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `types.ts` | `EventState`, `AgentState`, `SessionState` — all have `provider: string`. |
| `AgentCard.tsx` | Expand + inline events + pop-out modal. |
| `SessionView.tsx` | Session header with `ProviderBadge`. |
| `ProviderBadge.tsx` | Colored chip: orange=Claude Code, green=Codex, sky=OpenCode. |
| `ProviderFilter.tsx` | Toggle buttons in header; filters `sorted` by provider. |
| `App.tsx` | `Section` (collapsible); search + provider filter; `matchesQuery`. |
| `useStore.ts` | WS connect + reconnect + state reducer. Untouched since Phase 1. |

### Tests & fixtures
- `tests/test_transcripts.py` — 11 tests (Phase 1)
- `tests/test_model.py` — 7 tests (Phase 1–2)
- `tests/test_providers.py` — 24 tests (Phase 3)
- `tests/fixtures/codex-cli/` — sample JSONL + session_index.jsonl
- `tests/fixtures/opencode/` — SQLite fixture DB (includes aborted session)

### Built output
- `src/agentperiscope/web/` — committed. Rebuild: `cd frontend && npm run build`.

---

## 4. Provider Details

### Claude Code (`providers/claude_code.py`)
- Wraps `Watcher` unchanged. Default `provider="claude-code"` on all `ensure_session` calls.
- Boot scan: subagent files before parent files (load-bearing ordering).
- Session completion: `end_turn` from JSONL tail; 1-hour staleness fallback.

### Codex CLI (`providers/codex_cli.py`)
- Sessions at `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl`
- Session index at `~/.codex/session_index.jsonl` → thread names
- Session ID = last 36 chars of filename stem
- Top-level event types used: `session_meta`, `event_msg` (user_message/agent_message), `response_item` (function_call/custom_tool_call/function_call_output)
- No explicit session-end event. Staleness: 30 min without activity → done.
- This provider watches **OpenAI Codex Desktop** (`~/.codex`), not a separate CLI.

### OpenCode (`providers/opencode.py`)
- SQLite at `~/.local/share/opencode/opencode.db`, polled every 3s
- `session` table: id, directory (cwd), title (project_slug), model (JSON), time_updated
- `message` table: role, finish, tokens, error
- `part` table: type=text|tool|reasoning|step-finish — tool parts have `state.status`
- Session completion signals:
  - `finish: "stop"` on last assistant message → done
  - `error` field on assistant message (e.g. `MessageAbortedError`) → done
  - Last activity > 30 min and still running → done (staleness fallback)
- Poll skips sessions where `time_updated == last_seen` (idempotent)
- Message IDs tracked in `_msg_seen` to prevent duplicate event ingestion

### Provider stamping
All providers call `ensure_session(..., provider="<name>")`. Default is `"claude-code"` so `Watcher` (untouched) stamps correctly without code changes. The `provider` field flows through `Session.to_dict()` → WS snapshot → TypeScript `SessionState.provider`.

---

## 5. Shutdown Architecture

Signal handler in `cli.py`:
```python
def _shutdown():
    server.should_exit = True          # tells uvicorn to drain
    for task in asyncio.all_tasks():   # cancels awatch + asyncio.sleep loops
        if task is not current_task:
            task.cancel()
    port_file.unlink(missing_ok=True)

asyncio.gather(..., return_exceptions=True)  # catches CancelledError from providers
```

`POST /api/stop` triggers the same `_shutdown` via `app.state.shutdown`.

Without cancelling all tasks, Ctrl+C set `server.should_exit` but provider tasks blocked `gather` indefinitely.

---

## 6. Decisions Made (All Phases)

**Provider stamping at `ensure_session` call site, not a translation layer**
- Reason: simplest; Watcher unchanged; default `"claude-code"` means no arg needed in watcher.py.

**OpenCode: poll SQLite, don't tail**
- Reason: SQLite can't be tailed like JSONL. WAL mode means reads are safe during writes.

**Codex: staleness = 30 min (not 1h like Claude Code)**
- Reason: Codex sessions are user-initiated chat threads — shorter idle window is appropriate.

**OpenCode aborted sessions: `error` field → terminal**
- Reason: `MessageAbortedError` means user cancelled. No `finish` field is emitted. Treating `error` as terminal prevents ghost "active" sessions.

**macOS service via LaunchAgent, not launchd system daemon**
- Reason: User-level agent in `~/Library/LaunchAgents/` runs as the user, has access to `~/.claude`, no sudo needed.

**`POST /api/stop` uses `app.state.shutdown`**
- Reason: clean separation; server.py doesn't import cli.py; cli.py injects the callback via `fastapi_app.state.shutdown` after building the app.

**DB migration via `ALTER TABLE ... ADD COLUMN ... DEFAULT`**
- Reason: safe and idempotent (wrapped in try/except OperationalError); existing rows get `"claude-code"` default.

*(All Phase 1–2 decisions still apply — see git log for context.)*

---

## 7. Gotchas & Hard-Won Knowledge

### Phase 1–2 (preserved)
- **CC refreshes mtime on old session files at startup.** Never use mtime for staleness.
- **`async_launched` ≠ done.** Background-dispatch signal only.
- **`stop_reason="tool_use"` is mid-turn.** `end_turn` = complete.
- **Root agent only in `session_start`, never `agent_start`.** `ensure_session` creates it inline.
- **`load_into` must precede `store.subscribe(db.on_delta)`.** Order is load-bearing.
- **`to_full_dict()` is REST-only.** Never call in WS deltas.
- **StaticFiles mount at `/` must be last in `build_app`.**
- **Ghost sessions from metadata-only JSONLs.** Guard: `s.cwd && s.last_activity_ts` in App.tsx.
- **Boot scan ordering is load-bearing.** Subagent files before parent files.
- **`createPortal` required for modal.** Overflow clipping on ancestors.
- **`check_same_thread=False` on sqlite3.**

### Phase 3 (new)
- **OpenCode `finish: null` ≠ running.** Null means the message has an `error` field (aborted). Treat `error` as terminal or you get ghost active sessions.
- **OpenCode `session` table has `agent` column in production but not all schema versions.** Don't SELECT it — it's unused by the provider.
- **Codex session ID is last 36 chars of filename stem**, not a split on `-`. Stems vary in length; slicing `[-36:]` is reliable.
- **Provider tasks block `asyncio.gather` after uvicorn exits.** Must cancel all tasks in signal handler, not just set `server.should_exit`.
- **hatchling `force-include` + `packages` both including `web/` causes duplicate path build error.** Only use `packages`; `force-include` is not needed.
- **Provider dirs that don't exist → skip, don't crash.** Always guard with `Path.exists()` before starting a provider.

---

## 8. Do Not Touch

- `src/agentperiscope/web/` — generated. Edit `frontend/src/`, then rebuild.
- Boot scan ordering in `watcher.py:_boot_scan` — load-bearing.
- `async_launched` → `"running"` in `model.py:apply_line` — hard-won.
- `ensure_session` cwd update block — removing breaks metadata-only-start sessions.
- `_reconcile_stale_sessions` position — must run after all files processed.
- Route registration order in `server.py:build_app` — API routes before `app.mount("/", ...)`.
- `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py`.
- `asyncio.gather(..., return_exceptions=True)` — needed so `CancelledError` from providers doesn't surface as failure.

---

## 9. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** `uv sync` → `uv run agentperiscope`. Tests: `uv run pytest tests/ -q`. sqlite3 is stdlib.
- **Frontend:** React + Vite + TypeScript + Tailwind. `cd frontend && npm run build` → `src/agentperiscope/web/`. Built output committed in wheel.
- **Reinstall:** `uv tool install . --reinstall`. With service: add `launchctl kickstart -k gui/$(id -u)/com.agentperiscope`.
- **No raw content persisted.** `last_text` = 200-char snippet.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Never crash on parse.
- **No comments unless WHY is non-obvious.**
- **Commits:** conventional (`feat:`, `fix:`, `chore:`), imperative subject.

---

## 10. Open Questions

1. **No event persistence.** Pop-out modal shows nothing for sessions from prior runs. Still open from Phase 2.
2. **No tests for DB, search, expand, modal.** Phase 2 features untested at unit level.
3. **OpenCode subagents.** OpenCode has agent/subagent concepts (`parent_id` on session table). Not yet wired up — all activity maps to root agent only.
4. **Codex multi-turn token counts.** Token data is in `event_msg` with `rate_limits` payload — not yet parsed into `agent.tokens`.

---

## 11. Resume Command

> "Read HANDOFF.md. Phase 1, 2, and 3 complete. Three providers: Claude Code (watchfiles JSONL), Codex (watchfiles JSONL, `~/.codex`), OpenCode (SQLite poll, `~/.local/share/opencode`). Do not touch `watcher.py`, `transcripts.py`, boot scan ordering, or route registration order without reading sections 7 and 8. Run `uv run pytest tests/ -q` after any Python change. Run `cd frontend && npm run build` after any frontend change, then `uv tool install . --reinstall` to package."
