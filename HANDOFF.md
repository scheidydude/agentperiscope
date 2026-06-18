# HANDOFF — agentperiscope (2026-06-17)

## 1. Mission

`agentperiscope` is a local live observability viewer for AI agent activity. It tails session transcripts, listens to lifecycle hooks, and renders a per-agent lane view in the browser at `127.0.0.1`. Phase 1 (MVP) and Phase 2 (history + search + expand + modal + stale-session fix + collapsible sections) are complete. **Phase 3** extends the project from a Claude Code-only viewer into a multi-provider live observability viewer supporting Claude Code, Codex CLI, and OpenCode.

---

## 2. Current State

### Committed on `main` (10 commits, all Phase 1–2)

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

**Verified working (Phase 1–2):**
- `uv run agentperiscope` launches, opens browser
- Active / History sections collapsible with counts; Active always shown
- Sessions that ended while agentperiscope was down appear in History on next boot
- SQLite history survives restart
- Search bar filters live
- AgentCard ▼/▲ expand + **⤢ pop out** modal
- 18/18 tests pass (`uv run pytest tests/ -q`)

### Phase 3 — Not yet started

See sections 3–6 for full scope.

---

## 3. Phase 3 Scope

### Goal

Extend from a Claude Code-only viewer into a **multi-provider live observability viewer**. The UI should not care which provider produced an event. Claude Code behavior must not regress.

### Deliverables

1. Provider abstraction (`providers/base.py` interface)
2. Claude Code provider refactor (wraps existing `watcher.py` + `transcripts.py`)
3. Codex CLI provider (new)
4. OpenCode provider (new)
5. Normalized internal event model (see section 4)
6. Provider config (YAML or dict in `config.py`)
7. Updated UI: provider label, filter by provider, group by provider/session/agent
8. Tests: provider interface unit tests, per-provider parser tests with fixtures, Claude Code regression tests, malformed-file tests
9. README updates: supported providers, how to enable each, config examples, how to add a provider

---

## 4. Normalized Event Model

All providers emit events that conform to this shape. No provider-specific fields leak into the UI.

```python
@dataclass
class NormalizedEvent:
    provider: str          # "claude-code" | "codex-cli" | "opencode"
    session_id: str
    agent_id: str
    agent_name: str | None
    timestamp: str         # ISO 8601
    event_type: str        # see below
    status: str | None     # "running" | "done" | "error" | None
    message: str | None    # human-readable content snippet
    tool_name: str | None  # tool or command name if applicable
    raw: dict              # original parsed source event, for debugging
```

**Event types:**
- `session_started`
- `session_ended`
- `agent_started`
- `agent_updated`
- `agent_message`
- `tool_call_started`
- `tool_call_output`
- `tool_call_finished`
- `agent_finished`
- `error`

---

## 5. Architecture Changes

### New files (Python)

| File | Purpose |
|---|---|
| `src/agentperiscope/providers/__init__.py` | Package |
| `src/agentperiscope/providers/base.py` | `Provider` ABC: `name`, `is_enabled()`, `start(store)`, `stop()` |
| `src/agentperiscope/providers/claude_code.py` | Wraps existing `Watcher`; emits `NormalizedEvent` |
| `src/agentperiscope/providers/codex_cli.py` | Tails `~/.codex/sessions/` → `NormalizedEvent` |
| `src/agentperiscope/providers/opencode.py` | Tails `~/.local/share/opencode/sessions/` → `NormalizedEvent` |
| `src/agentperiscope/normalized.py` | `NormalizedEvent` dataclass + `event_type` constants |

### Modified files (Python)

| File | Change |
|---|---|
| `config.py` | Add `providers` dict; resolve per-provider dirs; defaults overrideable |
| `model.py` | `Event` / `Agent` / `Session` accept `provider` field; store supports multi-provider |
| `cli.py` | Load all enabled providers; start/stop them together |
| `watcher.py` | Internals unchanged; `claude_code.py` wraps it |
| `db.py` | Schema migration: add `provider` column to sessions/agents/events tables |

### Config shape (in `config.py` or `~/.config/agentperiscope/config.yaml`)

```yaml
providers:
  claude-code:
    enabled: true
    transcript_dir: "~/.claude/projects"
    hooks_dir: "~/.claude"

  codex-cli:
    enabled: false
    transcript_dir: "~/.codex/sessions"
    log_dir: "~/.codex/logs"

  opencode:
    enabled: false
    transcript_dir: "~/.local/share/opencode/sessions"
    log_dir: "~/.local/share/opencode/logs"
```

All paths default to the above but are overrideable. If a configured dir does not exist, the provider logs a warning and skips gracefully (never crashes the server).

### New files (React frontend)

| File | Purpose |
|---|---|
| `frontend/src/ProviderBadge.tsx` | Colored chip: "Claude Code", "Codex CLI", "OpenCode" |
| `frontend/src/ProviderFilter.tsx` | Checkbox group; filters WS state client-side |

### Modified files (React frontend)

| File | Change |
|---|---|
| `types.ts` | Add `provider: string` to `AgentState` and `EventState` |
| `AgentCard.tsx` | Render `ProviderBadge` next to agent name |
| `App.tsx` | Add `ProviderFilter`; `matchesQuery` checks provider; grouping by provider |
| `useStore.ts` | No changes expected |

---

## 6. Provider Implementation Notes

### Claude Code (refactor, not rewrite)

- Extract a thin `claude_code.py` that instantiates `Watcher` and translates its `Store` deltas into `NormalizedEvent` before re-emitting.
- Alternatively, keep `Watcher` writing directly to `Store` and add a `provider="claude-code"` tag at the point of ingestion. Simpler option — prefer this.
- **Do not touch** `watcher.py` internals, `transcripts.py`, or the boot scan order.

### Codex CLI

- Investigate: `~/.codex/sessions/`, `~/.codex/logs/`. Codex CLI (OpenAI's open-source CLI tool) may write JSONL, plain text, or SQLite. Check the actual format before writing the parser.
- If JSONL: parse structured fields. If plain text: extract timestamps + tool names with regex.
- Be defensive: files may be actively written. Skip malformed lines; never crash.
- Assign `session_id` from the filename or a field in the log. If unavailable, use a hash of the file path.

### OpenCode

- Investigate: `~/.local/share/opencode/` on Linux; may differ on macOS (`~/Library/Application Support/opencode/` or `~/.local/share/opencode/`). Check both.
- OpenCode (sst/opencode) likely writes structured session data. Confirm format before writing the parser.
- Same defensive parsing rules as Codex CLI.
- Provider path should be overrideable for macOS vs Linux differences.

### Investigation step (do first, before writing parsers)

Run the following to find actual log locations:
```bash
# Codex CLI
find ~/.codex -type f 2>/dev/null | head -30
ls -la ~/.codex/ 2>/dev/null

# OpenCode
find ~/.local/share/opencode -type f 2>/dev/null | head -30
find ~/Library/Application\ Support/opencode -type f 2>/dev/null | head -30
```

If neither tool is installed locally, check their GitHub repos for the session/log format before writing any parser.

---

## 7. Testing Requirements

- **Provider interface:** Unit test `Provider` ABC — `start`, `stop`, `is_enabled` contracts.
- **Claude Code regression:** Existing 18 tests must still pass. Add at least 3 regression tests confirming Claude Code provider emits correct `NormalizedEvent` types.
- **Codex CLI parser:** Fixture-based tests with sample log snippets (real or synthesized). Test: valid JSONL, plain text fallback, partial/truncated file, empty file.
- **OpenCode parser:** Same fixture pattern as Codex CLI.
- **Malformed files:** Each provider parser must handle truncated lines, invalid JSON, and missing required fields without raising.
- **DB migration:** Test that existing DB (with no `provider` column) migrates cleanly on boot.

Fixture files go in `tests/fixtures/codex-cli/` and `tests/fixtures/opencode/`.

---

## 8. Preserved Rules (Do Not Touch)

Everything in Phase 1–2 "Do Not Touch" still applies:

- `src/agentperiscope/web/` — generated. Edit `frontend/src/`, then rebuild.
- Boot scan ordering in `watcher.py:_boot_scan` — load-bearing for completion tracking.
- `async_launched` → `"running"` in `model.py:apply_line` — correct, hard-won.
- `ensure_session` cwd update block — removing makes metadata-only-start sessions permanently invisible.
- `_reconcile_stale_sessions` position — must run after all files processed.
- Route registration order in `server.py:build_app` — API routes before `app.mount("/", ...)`.
- `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py`.

---

## 9. Decisions Made (All Phases)

**Decision:** MIT license
- **Reason:** Standard permissive OSS license.

**Decision:** Pop-out modal uses `createPortal` to `document.body`
- **Reason:** Avoids z-index/overflow clipping from AgentCard ancestors.

**Decision:** Events fetched once per AgentCard, reused for inline and modal
- **Reason:** No refetch needed when toggling modal.

**Decision:** Collapsible sections via local `useState` in `Section` component
- **Reason:** Ephemeral UI preference, not worth persisting.

**Decision:** Active always shown (even at 0); History only when non-empty
- **Reason:** Active is the primary view.

**Decision:** Root session completion via JSONL tail read on boot
- **Reason:** Sessions that ended while agentperiscope was down stayed "running". `end_turn` → done; 1-hour fallback for mid-turn kills.

**Decision:** SQLite at `~/.claude/agentperiscope.db`, DB subscriber on Store delta stream
- **Reason:** Store stays pure in-memory; DB is a side-effect layer.

**Decision:** `db.load_into(store)` before `store.subscribe(db.on_delta)` in `cli.py`
- **Reason:** Prevents history load from re-emitting WS deltas.

**Decision:** `session_start` delta upserts all agents including root
- **Reason:** Root agent only appears in `session_start`, never as `agent_start`.

**Decision:** `/api/sessions/{id}` registered before `app.mount("/", StaticFiles(...))`
- **Reason:** FastAPI matches routes in registration order.

**Decision (Phase 3):** Provider tag added at ingestion point, not in a translation layer
- **Reason:** Simpler than a full event translation pipeline. `Watcher` writes to `Store` with `provider="claude-code"` stamped at the call site in `cli.py`. New providers follow the same pattern.
- **Reversibility:** Easy to refactor to a translation layer later if needed.

**Decision (Phase 3):** Per-provider config defaults in `config.py`; overrideable via config file
- **Reason:** Safe defaults for common installs; power users can override paths.
- **Reversibility:** Easy.

---

## 10. Gotchas & Hard-Won Knowledge (All Phases)

- **CC refreshes mtime on old session files at startup.** Never use file mtime for staleness.
- **`async_launched` ≠ done.** Background-dispatch signal only.
- **`stop_reason="tool_use"` is mid-turn.** `end_turn` = complete.
- **Root agent only emitted in `session_start`, never as `agent_start`.** `ensure_session` creates it inline.
- **`load_into` must precede `store.subscribe(db.on_delta)`.**
- **`check_same_thread=False` on sqlite3.**
- **`to_full_dict()` is REST-only.** Never call in WS deltas.
- **StaticFiles mount at `/` must be last in `build_app`.**
- **Hundreds of ghost sessions from metadata-only JSONLs.** Guard: `s.cwd && s.last_activity_ts` in `App.tsx`.
- **Boot scan ordering is load-bearing.**
- **`createPortal` required for modal.**
- **Phase 3 (new):** Log directories for Codex CLI and OpenCode may not exist on all machines. Always guard with `Path.exists()` before setting up watchers. Never fail the server startup if a provider dir is missing.
- **Phase 3 (new):** Codex CLI and OpenCode log formats are not yet confirmed. Investigate before writing parsers. Do not assume JSONL.

---

## 11. Conventions In Play

- **Python 3.12, `uv` toolchain, hatchling.** `uv sync` → `uv run agentperiscope`. Tests: `uv run pytest tests/ -q`. sqlite3 is stdlib.
- **Frontend:** React + Vite + TypeScript + Tailwind. `cd frontend && npm run build` → `src/agentperiscope/web/`. Built output committed in the wheel.
- **No raw content persisted.** `last_text` = 200-char snippet. Full transcript stays in JSONL.
- **Schema drift tolerance.** Unknown line types → `UnknownLine`. Never crash on parse.
- **No comments unless WHY is non-obvious.**
- **Commits:** conventional (`feat:`, `fix:`, `chore:`), imperative subject, body explains why not what.

---

## 12. Open Questions

1. **Codex CLI log format** — JSONL, plain text, or SQLite? Must confirm before writing parser.
2. **OpenCode log format** — same question. Check `~/.local/share/opencode/` on Linux and `~/Library/Application Support/opencode/` on macOS.
3. **DB migration strategy** — add `provider` column with `ALTER TABLE` + default `"claude-code"` for existing rows, or recreate schema. Prefer ALTER + default.
4. **Provider filter UX** — checkbox group in header or sidebar? TBD.
5. **No event persistence yet.** Pop-out modal shows nothing for historical sessions (prior run). Still open from Phase 2.

---

## 13. Resume Command

> "Read HANDOFF.md. Phase 1 and 2 complete. Phase 3 is multi-provider support (Claude Code + Codex CLI + OpenCode). Start by investigating Codex CLI and OpenCode log formats (see section 6 investigation step) before writing any parsers. Then implement the provider abstraction (section 5), normalized event model (section 4), and new providers. Do not touch watcher.py internals, transcripts.py, or route ordering in server.py without reading sections 8 and 10. Run `uv run pytest tests/ -q` after any Python changes."
