# HANDOFF — ccview (2026-06-17)

## 1. Mission

`ccview` is a local live viewer for Claude Code subagent activity. It tails CC session transcripts, listens to lifecycle hooks, and renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP) and Phase 2 (history + search + expand + stale-session fix) are complete. Phase 3 scope is TBD — ask the user.

---

## 2. Current State

### Committed and working (6 commits on `main`)

- `cd32df6` — Phase 1 MVP: watcher, parser, in-memory store, FastAPI server, React SPA, CLI, hooks, 18 tests
- `10f6cbd` — Hook port fix: `~/.claude/ccview.port` auto-discovery
- `90d48a2` — Phase 2a: SQLite persistence — `~/.claude/ccview.db`, survives restarts
- `d479042` — Phase 2b: client-side search bar (cwd, project_slug, description, last_text)
- `e2522f0` — Phase 2c: AgentCard expand (fetch `/api/sessions/{id}`); token breakdown in/out/cache
- `eff184c` — fix: root session completion detected via JSONL tail on boot (`end_turn` check)

**Verified working:**
- `uv run ccview` launches, opens browser, shows Active/History
- Sessions that ended while ccview was down now correctly appear in History on next boot (end_turn tail read)
- History survives restart via SQLite
- Search filters live, no backend round-trip
- AgentCard ▼/▲ expand fetches event log on demand
- `18/18` tests pass (`uv run pytest tests/ -q`)
- `__pycache__` untracked from git (`.gitignore` already had the pattern; committed `git rm --cached`)

### Not started

No Phase 3 scope defined. Ask user before building anything.

### Next action

Ask user what Phase 3 should be.

---

## 3. Decisions Made (and Why)

**Decision:** Detect root session completion via JSONL tail read on boot
- **Alternatives:** Lower staleness threshold (too aggressive for long-running sessions); periodic background reconcile task
- **Reason:** Mirrors the existing `_reconcile_one_subagent` approach. Reads last AssistantLine from tail; if `stop_reason == "end_turn"` → immediately done. 1-hour fallback retained for sessions killed mid-turn.
- **Reversibility:** Easy — `watcher.py:_reconcile_one_root`.

**Decision:** SQLite at `~/.claude/ccview.db`, follows `--claude-dir`
- **Reason:** All ccview state files live under `claude_dir`. Consistent with port file.
- **Reversibility:** Easy — `config.py:db_path`.

**Decision:** DB subscriber pattern — `Store.subscribe(db.on_delta)`
- **Reason:** Store stays pure in-memory; DB is a side-effect layer. Same delta stream as WebSocket hub.
- **Reversibility:** Easy.

**Decision:** `db.load_into(store)` populates `store._sessions` directly (bypasses `ensure_session`)
- **Reason:** `ensure_session` emits `session_start` WS events. Loading history shouldn't broadcast. Direct dict population avoids spurious emissions.
- **Reversibility:** Easy.

**Decision:** `session_start` delta also upserts all agents in `delta["session"]["agents"]`
- **Reason:** Root agent is created inside `ensure_session` and only emitted inside `session_start` — never as a separate `agent_start`. Without this, root agents are never persisted to DB.
- **Reversibility:** Easy — `db.on_delta`.

**Decision:** Expand fetches `/api/sessions/{id}` on demand — events not in WS snapshot
- **Reason:** Long sessions can have hundreds of events. Fetch-on-expand avoids bloating the initial snapshot.
- **Reversibility:** Easy.

**Decision:** `/api/sessions/{id}` registered before `app.mount("/", StaticFiles(...))` in `server.py`
- **Reason:** FastAPI/Starlette checks routes in registration order. StaticFiles at `/` would catch `/api/*` otherwise.
- **Reversibility:** Easy, but load-bearing ordering.

**Decision:** Client-side search (no backend endpoint)
- **Reason:** All sessions including history are in the WS snapshot. Browser filtering is instant.
- **Reversibility:** Easy to add server-side if DB grows too large.

---

## 4. Architecture & Key Files

### Python (`src/ccview/`)

| File | Purpose |
|---|---|
| `config.py` | Resolves Claude config dir. `db_path()` added this project. |
| `db.py` | `DB` class: SQLite schema, `load_into`, `on_delta`, `_upsert_session`, `_upsert_agent`. |
| `model.py` | `Store` + `Session`/`Agent`/`Event`. `Agent.to_full_dict()` and `Session.to_full_dict()` include events list (REST only). |
| `server.py` | FastAPI. `GET /api/sessions/{session_id}` returns `to_full_dict()`. Must stay before `app.mount("/", ...)`. |
| `cli.py` | Creates `DB`, calls `db.load_into(store)` then `store.subscribe(db.on_delta)` before watcher starts. `db.close()` in finally. |
| `watcher.py` | Boot scan + live watch. `_reconcile_one_root` (new) reads JSONL tail for end_turn. `_reconcile_one_subagent` unchanged. |
| `transcripts.py` | Unchanged. Typed line models + `Tailer`. |
| `hooks.py` | Unchanged. Hook ingest + install/uninstall. |

### React frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `types.ts` | `EventState` added. `AgentState.events?: EventState[]` added. |
| `AgentCard.tsx` | Expand toggle; fetches `/api/sessions/{id}` on first open; token breakdown per token type. |
| `SessionView.tsx` | Passes `sessionId` to `AgentCard`. |
| `App.tsx` | Search state + `matchesQuery` filter + `<input>` in header. |
| `useStore.ts` | Unchanged. |

### Built output
- `src/ccview/web/` — committed, rebuilt each session. `cd frontend && npm run build`.

### Tests
- `tests/test_transcripts.py`, `tests/test_model.py` — 18 tests, all pass.
- No tests for DB, search, or expand (integration-level).

---

## 5. Gotchas & Hard-Won Knowledge

- **CC refreshes mtime on old session files at startup.** Never use file mtime for staleness. Use `last_activity_ts` (content-derived) or `stop_reason` from the JSONL tail.

- **`async_launched` ≠ done.** Background-dispatch signal. Subagent is still running. Only the subagent's own tail (or age) tells you when it finishes.

- **`stop_reason="tool_use"` is mid-turn, not end-of-turn.** `end_turn` = complete. `tool_use` = waiting for tool result.

- **Root agent is only emitted in `session_start`, never as `agent_start`.** `ensure_session` creates the root Agent inline. DB persistence must handle it in the `session_start` branch of `on_delta`.

- **`load_into` must run before `store.subscribe(db.on_delta)`.** Order in `cli.py`: `DB()` → `Store()` → `load_into` → `subscribe` → `Watcher`. Do not reorder.

- **`check_same_thread=False` on sqlite3.** Single-threaded asyncio event loop, so no real threading issue, but SQLite's default check raises without this flag.

- **`to_full_dict()` is REST-only.** Don't call it in `snapshot()` or WS deltas — events lists are large.

- **StaticFiles mount at `/` must be last in `build_app`.** Any `@app.get(...)` registered after it is unreachable.

- **Hundreds of ghost sessions from metadata-only JSONLs.** Guard: `s.cwd && s.last_activity_ts` in `App.tsx`. Not persisted to SQLite (store only emits after real lines).

- **Boot scan ordering is load-bearing.** Subagent files before parent files in `_boot_scan`. Reverting silently drops completion events.

---

## 6. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** `uv sync` → `uv run ccview`. Tests: `uv run pytest tests/ -q`. sqlite3 is stdlib — no new deps added.
- **Frontend:** React + Vite + TypeScript + Tailwind. `cd frontend && npm run build` → `src/ccview/web/`. Built output committed and bundled in the wheel.
- **No raw content persisted.** `last_text` is 200-char snippet, `summary` is truncated. Full transcript stays in JSONL on disk.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Never crash on parse.
- **No comments unless WHY is non-obvious.**
- **Commits:** conventional (`feat:`, `fix:`), imperative subject, body explains why not what.

---

## 7. Open Questions

1. **Phase 3 scope — what's next?** Options:
   - (a) DB retention policy: everything vs. configurable window (e.g. last 30 days)
   - (b) Event persistence to SQLite: currently lost on restart; expand panel shows nothing for historical sessions
   - (c) Token cost estimates: model → $/1k token, show session cost
   - (d) macOS notification on session complete
   - (e) Server-side pagination if DB grows large
   - **Ask user before building.**

2. **No event persistence to SQLite yet.** Expand panel is empty for sessions from a prior ccview run. Worth persisting events (tool_use + text summaries) to DB?

3. **Tests for Phase 2 features.** DB, search, expand have no unit tests. Worth adding `tests/test_db.py`?

---

## 8. Do Not Touch

- `src/ccview/web/` — generated. Edit `frontend/src/`, then rebuild.
- Boot scan ordering in `watcher.py:_boot_scan` (`subagent_files + parent_files`) — load-bearing for completion tracking.
- `async_launched` → `"running"` mapping in `model.py:apply_line` — correct, hard-won.
- `ensure_session` cwd update block — removing makes metadata-only-start sessions permanently invisible.
- `_reconcile_stale_sessions` position — must run after all files processed, not during `_register_path`.
- Route registration order in `server.py:build_app` — API routes before `app.mount("/", ...)`.
- `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py` — order is load-bearing.

---

## 9. Resume Command

> "Read HANDOFF.md. Phase 1 and Phase 2 are complete (history/search/expand/stale-session fix). Ask the user what Phase 3 should be before writing any code. Do not touch watcher.py completion logic, model.py status mapping, or route ordering in server.py without reading sections 5 and 8. Run `uv run pytest tests/ -q` after any Python changes."
