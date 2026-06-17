# HANDOFF — ccview (2026-06-17)

## 1. Mission

`ccview` is a local live viewer for Claude Code subagent activity. It tails CC session transcripts, listens to lifecycle hooks, and renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP live view) and Phase 2 (history + search + expand) are complete. Phase 3 scope is TBD — ask the user.

---

## 2. Current State

### Committed and working (5 commits on `main`)

- `cd32df6` — Phase 1 MVP: watcher, parser, in-memory store, FastAPI server, React SPA, CLI, hooks install/uninstall, 18 tests
- `10f6cbd` — Hook port fix: `~/.claude/ccview.port` auto-discovery
- `90d48a2` — Phase 2a: SQLite persistence — sessions/agents survive restarts, written to `~/.claude/ccview.db`
- `d479042` — Phase 2b: client-side search bar in header (filters cwd, project_slug, agent description, last_text)
- `e2522f0` — Phase 2c: click-to-expand AgentCard (fetches `/api/sessions/{id}`, shows event log); token breakdown shows in/out/cache_read/cache_creation separately

**Verified working:**
- `uv run ccview` launches, opens browser, shows Active/History
- History survives server restart (SQLite populated before boot scan)
- Search bar filters live without backend round-trip
- AgentCard ▼/▲ toggle fetches full event list on demand
- `18/18` tests pass (`uv run pytest tests/ -q`)

### Not started

No Phase 3 scope defined. Ask user what's next before building anything.

### Next action

Ask user what Phase 3 should be. Candidates: pagination/retention policy for large DBs, hook event filtering (PreToolUse is noisy), diff/export view, token cost estimates, notification on session complete.

---

## 3. Decisions Made (and Why)

**Decision:** SQLite at `~/.claude/ccview.db`, follows `--claude-dir`
- **Alternatives:** alongside `ccview.port`; separate configurable path
- **Reason:** All ccview state files live under `claude_dir`; consistent with port file. `config.db_path()` mirrors `config.projects_dir()`.
- **Reversibility:** Easy — `config.py:db_path`.

**Decision:** DB subscriber pattern — `Store.subscribe(db.on_delta)`
- **Alternatives:** Write to DB inside `Store.apply_line`; write from `Watcher`
- **Reason:** Store stays pure in-memory; DB is a side-effect layer. Subscribes to same delta stream as WebSocket hub.
- **Reversibility:** Easy.

**Decision:** `db.load_into(store)` populates `store._sessions` directly (bypasses `ensure_session`)
- **Reason:** `ensure_session` emits `session_start` WS events. Loading history shouldn't broadcast to clients (no clients yet at boot anyway, but it's semantically wrong and wastes cycles). Direct dict population is cleaner.
- **Reversibility:** Easy.

**Decision:** `session_start` delta also upserts all agents in `delta["session"]["agents"]`
- **Reason:** Root agent is created inside `ensure_session` and is only ever emitted as part of `session_start` (never as a separate `agent_start`). Without this, root agents are never persisted to DB.
- **Reversibility:** Easy — `db.on_delta`.

**Decision:** Expand fetches `/api/sessions/{id}` on demand — events not in WS snapshot
- **Alternatives:** Include events in WS snapshot; stream events over WS
- **Reason:** Long sessions can have hundreds of events per agent. Sending all upfront bloats the initial snapshot significantly. Fetch-on-expand is the right tradeoff.
- **Reversibility:** Easy.

**Decision:** `/api/sessions/{id}` registered before `app.mount("/", StaticFiles(...))` in `server.py`
- **Reason:** FastAPI/Starlette checks routes in registration order. StaticFiles mounted at `/` would otherwise catch `/api/*` paths. API routes must be registered first.
- **Reversibility:** Easy, but load-bearing ordering — do not move the mount above the API routes.

**Decision:** Client-side search (no backend search endpoint)
- **Reason:** All sessions (including history loaded from SQLite) are in the WS snapshot on connect. Filtering in the browser is instant and needs zero backend work.
- **Reversibility:** Easy to add a server endpoint later if DB grows too large for full-snapshot delivery.

Previous Phase 1 decisions (port file, `async_launched` mapping, boot scan ordering, staleness detection) remain unchanged — see archived HANDOFF for details.

---

## 4. Architecture & Key Files

### Python (`src/ccview/`)

| File | Purpose |
|---|---|
| `config.py` | Resolves Claude config dir. **New:** `db_path()` helper. |
| `db.py` | **New this session.** `DB` class: SQLite schema, `load_into`, `on_delta`, `_upsert_session`, `_upsert_agent`. |
| `model.py` | `Store` + `Session`/`Agent`/`Event`. **New:** `Agent.to_full_dict()` and `Session.to_full_dict()` — include `events` list, used by REST endpoint only. |
| `server.py` | FastAPI. **New:** `GET /api/sessions/{session_id}` returns `session.to_full_dict()`. Must stay before `app.mount("/", ...)`. |
| `cli.py` | **Modified:** creates `DB`, calls `db.load_into(store)` and `store.subscribe(db.on_delta)` before watcher runs. `db.close()` in finally block. |
| `watcher.py` | Unchanged. Boot scan + watchfiles live watch. |
| `transcripts.py` | Unchanged. |
| `hooks.py` | Unchanged. |

### React frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `types.ts` | **Modified:** added `EventState` interface; added optional `events?: EventState[]` to `AgentState`. |
| `AgentCard.tsx` | **Rewritten:** click ▼/▲ header to expand. Expanded view fetches `/api/sessions/{id}`, shows `EventRow` list (ts, kind, summary). Token breakdown always shows in/out/cache_read/cache_creation. |
| `SessionView.tsx` | **Modified:** passes `sessionId={session.id}` to `AgentCard`. |
| `App.tsx` | **Modified:** `useState` search query, `matchesQuery` filter, search `<input>` in header. |
| `useStore.ts` | Unchanged. |

### Built output
- `src/ccview/web/` — committed, rebuilt each session. Rebuild: `cd frontend && npm run build`.

### Tests
- `tests/test_transcripts.py`, `tests/test_model.py` — 18 tests, all pass
- No new tests added for Phase 2 (DB, search, expand are integration-level; unit tests cover parser and store logic)

---

## 5. Gotchas & Hard-Won Knowledge

**Phase 1 hard-won knowledge still applies — read the archived HANDOFF if you touch watcher.py or model.py status logic.**

- **Root agent is only emitted in `session_start`, never as `agent_start`.** `ensure_session` creates the root Agent inline and emits `session_start` containing it. If you add DB persistence for agents, you must handle this in the `session_start` branch of `on_delta`, not only in `agent_start`/`agent_update`.

- **`load_into` must run before `store.subscribe(db.on_delta)`.** If subscribed first, the boot scan would re-emit deltas that double-write already-loaded sessions. Current order in `cli.py` is: `DB()` → `Store()` → `load_into` → `subscribe` → `Watcher` — do not reorder.

- **`check_same_thread=False` on sqlite3.** The DB is created in the main thread but `on_delta` is called from the asyncio event loop (single-threaded, so no real threading issue, but SQLite's default thread check would raise without this flag).

- **`to_full_dict()` on Agent/Session is REST-only.** Don't call it in `to_dict()` or `snapshot()` — events lists are large and would break the WS snapshot size budget.

- **StaticFiles mount at `/` must be last in `build_app`.** FastAPI matches routes in registration order. Any `@app.get(...)` registered after `app.mount("/", ...)` would be unreachable.

- **Hundreds of ghost sessions from metadata-only JSONLs** (unchanged from Phase 1): guard is `s.cwd && s.last_activity_ts` in `App.tsx`. These are not persisted to SQLite because `db.on_delta` is only triggered when the store emits, and the store only emits after `ensure_session` which only fires from real `AssistantLine`/`UserLine`.

---

## 6. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** Dev: `uv sync` → `uv run ccview`. Tests: `uv run pytest tests/ -q`. No new deps added in Phase 2 (sqlite3 is stdlib).
- **Frontend**: React + Vite + TypeScript + Tailwind. Build: `cd frontend && npm run build` → `src/ccview/web/`. Built output is committed and bundled in the wheel.
- **No raw content persisted.** `DB` stores `last_text` (already a 200-char snippet) and `summary` (already truncated). Full transcript text stays in JSONL on disk.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Unknown fields ignored. Never crash on parse.
- **No comments unless WHY is non-obvious.**
- **Commits**: conventional (`feat:`, `fix:`), imperative subject, body explains why not what.

---

## 7. Open Questions

1. **Phase 3 scope — what's next?** Options:
   - (a) DB retention policy: index everything vs. configurable window (last 30 days). Relevant now that DB is live.
   - (b) Hook event filtering: `PreToolUse` fires on every tool call — currently not persisted (events are in-memory only), but if we add event persistence it becomes noisy.
   - (c) Token cost estimates: map model name → $/1k token, show session cost
   - (d) Notification on session complete (macOS notification center?)
   - (e) Pagination if DB grows large (currently all sessions in WS snapshot)
   - **Ask user before building any of these.**

2. **No event persistence to SQLite yet.** Events (text/tool_use) are in-memory only and lost on restart. The expand panel shows nothing for historical sessions from a prior run. Is this acceptable or should events be persisted?

3. **Tests for Phase 2 features.** DB, search, expand are untested at unit level. Worth adding `tests/test_db.py`?

---

## 8. Do Not Touch

- `src/ccview/web/` — generated. Edit `frontend/src/`, then rebuild.
- Boot scan ordering in `watcher.py:_boot_scan` (`subagent_files + parent_files`) — reverting silently breaks completion tracking.
- `async_launched` → `"running"` mapping in `model.py:apply_line` — correct, hard-won, do not change.
- `ensure_session` cwd update block — removing makes metadata-only-start sessions permanently invisible.
- `_reconcile_stale_sessions` position — must run after all files processed, not during `_register_path`.
- Route registration order in `server.py:build_app` — API routes before `app.mount("/", ...)`.
- `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py` — order is load-bearing.

---

## 9. Resume Command

> "Read HANDOFF.md. Phase 1 and Phase 2 (history/search/expand) are complete and committed. Ask the user what Phase 3 should be before writing any code. Do not touch watcher.py completion logic, model.py status mapping, or route ordering in server.py without reading sections 5 and 8. Run `uv run pytest tests/ -q` after any Python changes."
