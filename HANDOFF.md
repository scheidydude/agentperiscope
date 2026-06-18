# HANDOFF — agentperiscope (2026-06-17)

## 1. Mission

`agentperiscope` is a local live viewer for Claude Code subagent activity. It tails CC session transcripts, listens to lifecycle hooks, and renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP) and Phase 2 (history + search + expand + modal + stale-session fix + collapsible sections) are complete. Open-sourced under MIT. Phase 3 scope is TBD — ask the user.

---

## 2. Current State

### Committed on `main` (10 commits)

- `cd32df6` — Phase 1 MVP: watcher, parser, in-memory store, FastAPI server, React SPA, CLI, hooks, 18 tests
- `10f6cbd` — Hook port fix: `~/.claude/agentperiscope.port` auto-discovery
- `90d48a2` — Phase 2a: SQLite persistence — `~/.claude/agentperiscope.db`, survives restarts
- `d479042` — Phase 2b: client-side search bar (cwd, project_slug, description, last_text)
- `e2522f0` — Phase 2c: AgentCard expand + token breakdown (in/out/cache_read/cache_creation)
- `eff184c` — fix: root session completion detected via JSONL tail on boot (`end_turn` check)
- `683f1db` — chore: untrack `__pycache__`, archive HANDOFFs
- `bb6a12b` — feat: collapsible Active/History sections with item counts; Active always shown
- `59f1c6c` — feat: pop-out modal for agent event details
- `2bac495` — refactor: rename project ccview → agentperiscope (package, CLI, state files, imports)

**Repo**: `git@github.com:scheidydude/agentperiscope.git`

**Verified working:**
- `uv run agentperiscope` launches, opens browser
- Active / History sections collapsible with counts; Active always shown
- Sessions that ended while agentperiscope was down appear in History on next boot
- SQLite history survives restart
- Search bar filters live
- AgentCard ▼/▲ expand + **⤢ pop out** modal
- 18/18 tests pass (`uv run pytest tests/ -q`)

### Not started

No Phase 3 scope defined. Ask user before building anything.

### Next action

Ask user what Phase 3 should be.

---

## 3. Decisions Made (and Why)

**Decision:** MIT license
- **Reason:** Standard permissive OSS license. Copyright 2026 David Scheiderman.
- **Reversibility:** Easy to change before first public release.

**Decision:** Pop-out modal uses `createPortal` to `document.body`
- **Reason:** Avoids z-index/overflow clipping from AgentCard ancestor elements.
- **Reversibility:** Easy.

**Decision:** Events fetched once per AgentCard, reused for inline and modal
- **Reason:** No refetch needed when toggling modal. Fetch on first expand or first modal open.
- **Reversibility:** Easy.

**Decision:** Collapsible sections via local `useState` in `Section` component
- **Reason:** Ephemeral UI preference, not worth persisting. Simple and self-contained.
- **Reversibility:** Easy — could add localStorage later.

**Decision:** Active always shown (even at 0); History only when non-empty
- **Reason:** Active is the primary view — "No active sessions" is informative.
- **Reversibility:** Easy — `App.tsx`.

**Decision:** Root session completion via JSONL tail read on boot
- **Reason:** Sessions that ended while agentperiscope was down stayed "running" for an hour. Reads last AssistantLine; `end_turn` → done immediately. 1-hour fallback for mid-turn kills.
- **Reversibility:** Easy — `watcher.py:_reconcile_one_root`.

**Decision:** SQLite at `~/.claude/agentperiscope.db`, DB subscriber on Store delta stream
- **Reason:** State files under `claude_dir`. Store stays pure in-memory; DB is a side-effect layer.
- **Reversibility:** Easy.

**Decision:** `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py`
- **Reason:** Prevents history load from re-emitting WS deltas to clients.
- **Reversibility:** Easy but ordering is load-bearing — do not reorder.

**Decision:** `session_start` delta upserts all agents including root
- **Reason:** Root agent only appears in `session_start`, never as a separate `agent_start`. Without this it never reaches the DB.
- **Reversibility:** Easy — `db.on_delta`.

**Decision:** `/api/sessions/{id}` registered before `app.mount("/", StaticFiles(...))` in `server.py`
- **Reason:** FastAPI matches routes in registration order. StaticFiles at `/` catches `/api/*` otherwise.
- **Reversibility:** Load-bearing ordering — do not move the mount above API routes.

**Decision:** Client-side search (no backend endpoint)
- **Reason:** All sessions including history are in the WS snapshot. Browser filtering is instant.
- **Reversibility:** Easy to add server-side if DB grows too large.

---

## 4. Architecture & Key Files

### Python (`src/agentperiscope/`)

| File | Purpose |
|---|---|
| `config.py` | Resolves Claude config dir. `db_path()` → `~/.claude/agentperiscope.db`. |
| `db.py` | `DB`: SQLite schema, `load_into`, `on_delta`, upsert helpers. |
| `model.py` | `Store` + `Session`/`Agent`/`Event`. `to_full_dict()` includes events (REST only). |
| `server.py` | FastAPI. `GET /api/sessions/{id}` before SPA mount. |
| `cli.py` | DB init → `load_into` → `subscribe` → Watcher. `db.close()` in finally. |
| `watcher.py` | Boot scan + live watch. `_reconcile_one_root` reads JSONL tail for `end_turn`. |
| `transcripts.py` | Typed line models + `Tailer`. Unchanged since Phase 1. |
| `hooks.py` | Hook ingest + install/uninstall. Marker string: `"agentperiscope"`. |

### React frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `types.ts` | `EventState`; `AgentState.events?: EventState[]`. |
| `AgentCard.tsx` | Expand toggle + inline event list + **⤢ pop out** + `AgentModal` (portal). |
| `SessionView.tsx` | Passes `sessionId` to `AgentCard`. |
| `App.tsx` | `Section` (collapsible, count); search input + `matchesQuery`. |
| `useStore.ts` | WS connect + reconnect + state reducer. Unchanged since Phase 1. |

### Built output
- `src/agentperiscope/web/` — committed. Rebuild: `cd frontend && npm run build`.

### Tests
- `tests/test_transcripts.py`, `tests/test_model.py` — 18 tests, all pass.
- No tests for DB, search, expand, or modal.

---

## 5. Gotchas & Hard-Won Knowledge

- **CC refreshes mtime on old session files at startup.** Never use file mtime for staleness. Use `last_activity_ts` (content timestamp) or `stop_reason` from JSONL tail.

- **`async_launched` ≠ done.** Background-dispatch signal. Subagent still running. Only subagent's own tail (or age >5 min) tells you when it finishes.

- **`stop_reason="tool_use"` is mid-turn.** `end_turn` = complete; `tool_use` = waiting for tool result.

- **Root agent only emitted in `session_start`, never as `agent_start`.** `ensure_session` creates it inline. DB `on_delta` must handle it in the `session_start` branch.

- **`load_into` must precede `store.subscribe(db.on_delta)`.** Order: `DB()` → `Store()` → `load_into` → `subscribe` → `Watcher`. Do not reorder.

- **`check_same_thread=False` on sqlite3.** Single asyncio thread; just satisfies SQLite's default thread check.

- **`to_full_dict()` is REST-only.** Never call in `snapshot()` or WS deltas — event lists are large.

- **StaticFiles mount at `/` must be last in `build_app`.** Any `@app.get(...)` after it is unreachable.

- **Hundreds of ghost sessions from metadata-only JSONLs.** Guard: `s.cwd && s.last_activity_ts` in `App.tsx`.

- **Boot scan ordering is load-bearing.** Subagent files before parent files. Reverting silently drops completion events.

- **`createPortal` required for modal.** Without it, `overflow` on ancestor elements clips the fixed overlay.

---

## 6. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** `uv sync` → `uv run agentperiscope`. Tests: `uv run pytest tests/ -q`. sqlite3 is stdlib.
- **Frontend:** React + Vite + TypeScript + Tailwind. `cd frontend && npm run build` → `src/agentperiscope/web/`. Built output committed in the wheel.
- **No raw content persisted.** `last_text` = 200-char snippet; `summary` = truncated. Full transcript stays in JSONL.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Never crash on parse.
- **No comments unless WHY is non-obvious.**
- **Commits:** conventional (`feat:`, `fix:`, `chore:`), imperative subject, body explains why not what.

---

## 7. Open Questions

1. **Phase 3 scope — what's next?**
   - (a) Event persistence to SQLite: expand modal empty for sessions from prior run
   - (b) DB retention policy: everything vs. configurable window (e.g. last 30 days)
   - (c) Token cost estimates: model → $/1k token, session cost total
   - (d) macOS notification on session complete
   - (e) Server-side pagination if DB grows too large
   - **Ask user before building.**

2. **No event persistence yet.** Pop-out modal shows nothing for historical sessions (prior run).

3. **No tests for Phase 2.** DB, search, expand, modal untested at unit level.

---

## 8. Do Not Touch

- `src/agentperiscope/web/` — generated. Edit `frontend/src/`, then rebuild.
- Boot scan ordering in `watcher.py:_boot_scan` — load-bearing for completion tracking.
- `async_launched` → `"running"` in `model.py:apply_line` — correct, hard-won.
- `ensure_session` cwd update block — removing makes metadata-only-start sessions permanently invisible.
- `_reconcile_stale_sessions` position — must run after all files processed.
- Route registration order in `server.py:build_app` — API routes before `app.mount("/", ...)`.
- `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py`.

---

## 9. Resume Command

> "Read HANDOFF.md. Phase 1 and Phase 2 complete; project open-sourced as agentperiscope (MIT). Ask the user what Phase 3 should be before writing any code. Do not touch watcher.py completion logic, model.py status mapping, or route ordering in server.py without reading sections 5 and 8. Run `uv run pytest tests/ -q` after any Python changes."
