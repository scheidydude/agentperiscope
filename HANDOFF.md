# HANDOFF — ccview (2026-06-17)

## 1. Mission

`ccview` is a local live viewer for Claude Code subagent activity. It tails CC session transcripts, listens to lifecycle hooks, and renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP) and Phase 2 (history + search + expand + modal + stale-session fix + collapsible sections) are complete. Phase 3 scope is TBD — ask the user.

---

## 2. Current State

### Committed and working (9 commits on `main`)

- `cd32df6` — Phase 1 MVP: watcher, parser, in-memory store, FastAPI server, React SPA, CLI, hooks, 18 tests
- `10f6cbd` — Hook port fix: `~/.claude/ccview.port` auto-discovery
- `90d48a2` — Phase 2a: SQLite persistence — `~/.claude/ccview.db`, survives restarts
- `d479042` — Phase 2b: client-side search bar (cwd, project_slug, description, last_text)
- `e2522f0` — Phase 2c: AgentCard expand + token breakdown (in/out/cache_read/cache_creation)
- `eff184c` — fix: root session completion detected via JSONL tail on boot (`end_turn` check)
- `683f1db` — chore: untrack `__pycache__`, archive HANDOFFs
- `bb6a12b` — feat: collapsible Active/History sections with item counts; Active always shown
- `59f1c6c` — feat: pop-out modal for agent event details

**Verified working:**
- `uv run ccview` launches, opens browser
- Active (always shown, defaults open) / History (defaults closed) sections collapsible with counts
- Sessions that ended while ccview was down correctly appear in History on next boot
- SQLite history survives restart
- Search bar filters live
- AgentCard ▼/▲ expands inline event list (scrollable, max 48 rows)
- **⤢ pop out** opens full modal: scrollable event list, full text (no truncation), metadata, timestamps, event count
- Modal closes on ✕ or backdrop click; events fetched once and reused
- 18/18 tests pass (`uv run pytest tests/ -q`)
- `__pycache__` untracked from git

### Not started

No Phase 3 scope defined. Ask user before building anything.

### Next action

Ask user what Phase 3 should be.

---

## 3. Decisions Made (and Why)

**Decision:** Pop-out modal uses `createPortal` to `document.body`
- **Reason:** Avoids z-index/overflow clipping from ancestor elements (the AgentCard has `overflow` and border context). Portal renders at body level, always above everything.
- **Reversibility:** Easy.

**Decision:** Events fetched once per AgentCard, reused for both inline and modal views
- **Reason:** No need to refetch when toggling modal. State lives in AgentCard; fetch is triggered on first expand or first modal open (whichever comes first).
- **Reversibility:** Easy.

**Decision:** Collapsible sections via local `useState` in `Section` component (not URL/global state)
- **Reason:** Ephemeral UI preference, not worth persisting. Simple and self-contained.
- **Reversibility:** Easy — could add localStorage persistence later.

**Decision:** Active section always rendered even at 0 items; History only rendered when non-empty
- **Reason:** Active is the primary view. Seeing "No active sessions" is informative. History with 0 items after filtering adds no value.
- **Reversibility:** Easy — `App.tsx`.

**Decision:** Detect root session completion via JSONL tail read on boot
- **Reason:** Sessions that ended while ccview was down would stay "running" for up to an hour. Reads last AssistantLine; if `stop_reason == "end_turn"` → immediately done. 1-hour fallback retained for mid-turn kills.
- **Reversibility:** Easy — `watcher.py:_reconcile_one_root`.

**Decision:** SQLite at `~/.claude/ccview.db`, DB subscriber on Store delta stream
- **Reason:** State files under `claude_dir`. DB is a side-effect layer; Store stays pure in-memory.
- **Reversibility:** Easy.

**Decision:** `db.load_into(store)` before `store.subscribe(db.on_delta)`
- **Reason:** Prevents history load from re-emitting WS deltas. Order in `cli.py` is load-bearing.
- **Reversibility:** Easy but must not reorder.

**Decision:** `session_start` delta upserts all agents including root
- **Reason:** Root agent is created inside `ensure_session` and only appears in `session_start` — never as a separate `agent_start`. Without this it never reaches the DB.
- **Reversibility:** Easy — `db.on_delta`.

**Decision:** `/api/sessions/{id}` registered before `app.mount("/", StaticFiles(...))` in `server.py`
- **Reason:** FastAPI matches routes in registration order. StaticFiles at `/` would catch `/api/*` otherwise.
- **Reversibility:** Load-bearing ordering — do not move the mount above API routes.

---

## 4. Architecture & Key Files

### Python (`src/ccview/`)

| File | Purpose |
|---|---|
| `config.py` | Resolves Claude config dir. `db_path()` returns `~/.claude/ccview.db`. |
| `db.py` | `DB` class: SQLite schema, `load_into`, `on_delta`, upsert helpers. |
| `model.py` | `Store` + `Session`/`Agent`/`Event`. `to_full_dict()` on Agent/Session includes events (REST only). |
| `server.py` | FastAPI. `GET /api/sessions/{id}` registered before SPA mount. |
| `cli.py` | DB init → `load_into` → `subscribe` → Watcher. `db.close()` in finally. |
| `watcher.py` | Boot scan + live watch. `_reconcile_one_root` reads JSONL tail for `end_turn`. |
| `transcripts.py` | Unchanged. Typed line models + `Tailer`. |
| `hooks.py` | Unchanged. |

### React frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `types.ts` | `EventState` interface; `AgentState.events?: EventState[]`. |
| `AgentCard.tsx` | Expand toggle + inline event list + **⤢ pop out** button + `AgentModal` (portal). |
| `SessionView.tsx` | Passes `sessionId` to `AgentCard`. |
| `App.tsx` | `Section` component (collapsible, count); search input + `matchesQuery`. |
| `useStore.ts` | Unchanged. |

### Built output
- `src/ccview/web/` — committed. Rebuild: `cd frontend && npm run build`.

### Tests
- `tests/test_transcripts.py`, `tests/test_model.py` — 18 tests, all pass.
- No tests for DB, search, expand, or modal.

---

## 5. Gotchas & Hard-Won Knowledge

- **CC refreshes mtime on old session files at startup.** Never use file mtime for staleness. Use `last_activity_ts` (content timestamp) or `stop_reason` from the JSONL tail.

- **`async_launched` ≠ done.** Background-dispatch signal. Subagent still running. Only the subagent's own tail (or age >5 min) tells you when it finishes.

- **`stop_reason="tool_use"` is mid-turn.** `end_turn` = complete; `tool_use` = waiting for tool result.

- **Root agent only emitted in `session_start`, never as `agent_start`.** `ensure_session` creates it inline. DB must handle it in the `session_start` branch of `on_delta`.

- **`load_into` must precede `store.subscribe(db.on_delta)`.** Order: `DB()` → `Store()` → `load_into` → `subscribe` → `Watcher`. Do not reorder.

- **`check_same_thread=False` on sqlite3.** Single asyncio thread, so no real race; just satisfies SQLite's default thread check.

- **`to_full_dict()` is REST-only.** Never call in `snapshot()` or WS deltas — event lists are large.

- **StaticFiles mount at `/` must be last in `build_app`.** Any `@app.get(...)` after it is unreachable.

- **Hundreds of ghost sessions from metadata-only JSONLs.** Guard: `s.cwd && s.last_activity_ts` in `App.tsx`. Not persisted to SQLite.

- **Boot scan ordering is load-bearing.** Subagent files before parent files. Reverting silently drops completion events.

- **`createPortal` required for modal.** Without it, `overflow` on ancestor elements clips the fixed overlay.

---

## 6. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** `uv sync` → `uv run ccview`. Tests: `uv run pytest tests/ -q`. sqlite3 is stdlib.
- **Frontend:** React + Vite + TypeScript + Tailwind. `cd frontend && npm run build` → `src/ccview/web/`. Built output committed in the wheel.
- **No raw content persisted.** `last_text` = 200-char snippet; `summary` = truncated. Full transcript stays in JSONL.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Never crash on parse.
- **No comments unless WHY is non-obvious.**
- **Commits:** conventional (`feat:`, `fix:`, `chore:`), imperative subject, body explains why not what.

---

## 7. Open Questions

1. **Phase 3 scope — what's next?** Options:
   - (a) Event persistence to SQLite: expand modal currently empty for sessions from prior ccview run
   - (b) DB retention policy: everything vs. configurable window (last 30 days)
   - (c) Token cost estimates: model → $/1k token, session cost total
   - (d) macOS notification on session complete
   - (e) Server-side pagination if DB grows too large for full-snapshot delivery
   - **Ask user before building.**

2. **No event persistence yet.** Pop-out modal shows nothing for historical sessions (prior run). Worth adding `events` table to DB?

3. **No tests for Phase 2 features.** DB, search, expand, modal untested at unit level.

---

## 8. Do Not Touch

- `src/ccview/web/` — generated. Edit `frontend/src/`, then rebuild.
- Boot scan ordering in `watcher.py:_boot_scan` — load-bearing for completion tracking.
- `async_launched` → `"running"` in `model.py:apply_line` — correct, hard-won.
- `ensure_session` cwd update block — removing makes metadata-only-start sessions permanently invisible.
- `_reconcile_stale_sessions` position — must run after all files processed.
- Route registration order in `server.py:build_app` — API routes before `app.mount("/", ...)`.
- `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py`.

---

## 9. Resume Command

> "Read HANDOFF.md. Phase 1 and Phase 2 are complete. Ask the user what Phase 3 should be before writing any code. Do not touch watcher.py completion logic, model.py status mapping, or route ordering in server.py without reading sections 5 and 8. Run `uv run pytest tests/ -q` after any Python changes."
