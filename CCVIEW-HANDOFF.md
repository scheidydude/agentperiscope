# CCVIEW-HANDOFF-001 — Build Brief for Claude Code

**Audience:** Claude Code CLI (agentic build).
**Companion doc:** `CCVIEW-SCOPE-001.md` — that is the authoritative source for *what* and *why*. This doc is *how*: constraints, structure, tasks, and acceptance criteria. Read the scope doc first; if anything here conflicts with it, the scope doc wins on intent and this doc wins on implementation detail.

**Project:** `ccview` — a local, cross-platform live viewer for Claude Code subagent activity. It tails Claude Code's session transcripts and listens to lifecycle hooks, then renders a live per-agent view in the browser on `127.0.0.1`.

---

## 0. How to use this document

Work top to bottom. The build is gated into **checkpoints**; at each `🛑 CHECKPOINT`, stop, run the stated verification, and report results before continuing. Do not skip Phase 0 — it de-risks every assumption below.

Suggested kickoff (the human will paste something like this):
> "Read CCVIEW-SCOPE-001.md and CCVIEW-HANDOFF-001.md. Execute Phase 0, then stop at the checkpoint and show me what you found."

---

## 1. Hard constraints (non-negotiable)

- **Local only.** No remote hosts, no reverse proxy, no auth server. The server **binds `127.0.0.1` exclusively — never `0.0.0.0`.**
- **Cross-platform: macOS, Windows, Linux (incl. WSL).** Use `pathlib`, `watchfiles`, and `webbrowser`; make **no shell, path-separator, or `curl`-exists assumptions.**
- **Packaging via `uv`.** `uv tool install ccview` must put a working `ccview` on PATH on all three OSes. Python **3.12**. No Node required at runtime — the built React SPA is bundled into the wheel and served by FastAPI.
- **Not Docker.** Do not introduce a container for the runtime. It watches host files directly.
- **Viewer-only MVP.** No pause/approve/control features. No recomputing token cost (defer to the existing `tokenscape` tool).
- **Don't persist raw transcript content.** Store references (`file + offset`), lazy-load detail on demand. Transcripts may contain secrets.

---

## 2. Stack (pinned)

| Layer | Choice |
|---|---|
| Language / runtime | Python 3.12 |
| Packaging / env | `uv`, `hatchling` build backend, console entry point `ccview` |
| CLI | `typer` (argparse acceptable if you want zero extra dep) |
| Server | `fastapi` + `uvicorn`; native Starlette WebSocket (no extra dep) |
| File watching | `watchfiles` |
| Store (Phase 2 only) | `sqlite3` (stdlib) |
| Frontend | React + Vite + TypeScript + Tailwind |

Keep the dependency list short. Justify any addition beyond the table.

---

## 3. Target repo structure

```
ccview/
├── pyproject.toml            # uv/hatchling; entry: ccview = "ccview.cli:app"
├── README.md
├── CCVIEW-SCOPE-001.md
├── CCVIEW-HANDOFF-001.md
├── docs/
│   └── transcript-schema.md  # YOU write this in Phase 0 from real files
├── src/ccview/
│   ├── __main__.py
│   ├── cli.py                # ccview | ccview hook | ccview install-hooks/uninstall-hooks
│   ├── config.py             # config-dir resolution
│   ├── transcripts.py        # line-variant models + offset tailer
│   ├── watcher.py            # watchfiles, lazy per-project watches
│   ├── model.py              # Session/Agent/Event + in-memory state
│   ├── hooks.py              # hook stdin handler + settings.json install/uninstall
│   ├── server.py             # FastAPI: /events, /ws, serves SPA at /
│   └── web/                  # built SPA (generated; bundled into wheel)
├── frontend/                 # React + Vite source → builds into src/ccview/web/
├── tests/
│   ├── fixtures/             # sanitized sample transcripts
│   └── test_*.py
└── scripts/build_frontend.*  # cross-platform build helper
```

---

## 4. Phase 0 — Discovery & de-risking (do this first, on THIS machine)

**You can read the real data.** Do not code the parser against the schema notes in the scope doc as if they were gospel — they are secondhand. Verify against actual files here.

Tasks:
1. Resolve the config dir: `CLAUDE_CONFIG_DIR` → else `~/.claude`. List `<config>/projects/`.
2. Find a recent session that spawned subagents. Inspect the JSONL: enumerate the distinct line `type`s, the content-block shapes (`text`, `tool_use`, `tool_result`, thinking, usage), and the `parentUuid` chaining.
3. **Determine the actual subagent layout** — child files under `<session-id>/subagents/`? sibling session files linked by `parentUuid`? Both? Document exactly what this CC version does.
4. Inspect a real hook payload: temporarily register a `SubagentStart`/`Stop` + `Stop` hook that appends its stdin JSON to a log file, run a quick session, and capture the real field set (`session_id`, `transcript_path`, `cwd`, `hook_event_name`, matcher behavior). Confirm hooks fire on this OS.
5. Write `docs/transcript-schema.md` capturing what you actually observed, and copy a **sanitized** sample (redact any secrets/paths/PII) into `tests/fixtures/`.

🛑 **CHECKPOINT 0** — Report: resolved config path, the subagent linking mechanism, the line-variant inventory, a real hook payload, and which OS you verified on. Wait for go-ahead.

---

## 5. Phase 1 — Local live web view (MVP)

### 5.1 `config.py`
- Resolve order: `--claude-dir` flag → `CLAUDE_CONFIG_DIR` → `Path.home()/".claude"`. Return the `projects` dir. All via `pathlib`; works on Windows/macOS/Linux unchanged.

### 5.2 `transcripts.py`
- Typed models for each line variant you found in Phase 0. **Be schema-drift tolerant:** unknown line types/fields must not crash — log and skip, preserving raw.
- `Tailer`: per-file byte offset; on read, seek → read new bytes → split on `\n` → parse complete lines → buffer trailing partial. Open binary, decode UTF-8 leniently, strip `\r`. If file shrinks below offset (compaction), reset to 0.
- Map a transcript file → `Session` or `Agent` (subagent) using the linking rule from Phase 0.

### 5.3 `watcher.py`
- `watchfiles` over the `projects` tree. To respect Linux inotify limits, **lazily add watches only for active project subtrees** (a project becomes active on `SessionStart`/`SubagentStart` via the hook, or on first observed mtime change). Provide a `--poll` fallback (`force_polling`).
- Handle CREATE (new subagent files mid-run) as well as MODIFY.

### 5.4 `model.py`
- In-memory `Session`/`Agent`/`Event` state per the scope doc's data model. `Event` carries a `raw_ref` (file + offset), not full payloads. Emit deltas to subscribers.

### 5.5 `hooks.py`
- `ccview hook`: read hook JSON from stdin, POST to `http://127.0.0.1:<port>/events`, exit 0 fast (never block Claude Code). Fail silently if the server is down.
- `install-hooks [--global|--project]`: idempotently merge the correct block into the right `settings.json` (`<config>/settings.json` or `./.claude/settings.json`). Generate the per-OS command string referencing the installed `ccview`. `uninstall-hooks` reverses it cleanly. **Never clobber unrelated user hook config** — merge, don't overwrite.
- Do not rely on `SubagentStop` for completion alone (it can miss on `max_turns`); reconcile against the tail (agent done when its file stops growing and the parent resumes).

### 5.6 `server.py`
- FastAPI bound to `127.0.0.1`, auto-select a free port. `POST /events` (hook ingest), `/ws` (WebSocket hub broadcasting live state + deltas), static SPA at `/`. On startup, `webbrowser.open(url)`.

### 5.7 `cli.py`
- `ccview` (no args): start watcher + server, open browser. `ccview hook`, `ccview install-hooks`, `ccview uninstall-hooks`. `--claude-dir`, `--port`, `--poll`, `--no-open` flags.

### 5.8 Frontend (`frontend/` → `src/ccview/web/`)
- "Agent lanes": one card/column per agent, showing status (running/done/error), current tool, latest text snippet, token counter. Click expands the full transcript (lazy-fetched via `raw_ref`). Live updates over the WebSocket. Tree view for parent→child relationships.
- Build output goes into `src/ccview/web/` and is included in the wheel (`pyproject` package-data).

🛑 **CHECKPOINT 1** — Demo: with `ccview` running and a real Claude Code session spawning subagents in another terminal, the browser shows each subagent appear live, its tools/text update, and completion register. Report.

---

## 6. Acceptance criteria (Definition of Done for MVP)

- `uv tool install .` then `ccview` launches, binds `127.0.0.1` (verified — not `0.0.0.0`), opens the browser.
- `ccview install-hooks` wires Claude Code correctly on the current OS; `uninstall-hooks` fully reverts.
- Running a real CC session with subagents shows them live in the UI within ~1s of spawn, with per-agent tool/text/token updates and accurate parent→child nesting.
- Parser tolerates unknown line types without crashing (test with a malformed fixture).
- No raw transcript content persisted; secrets are not written to any ccview store/log.
- `pytest` green; type-checked (`pyright`/`mypy`); `ruff` clean.
- README documents install, run, hook setup, and the `--claude-dir`/WSL note.

---

## 7. Cross-platform honesty

You can auto-verify only the OS you are running on. Make the other two correct **by construction** (pathlib, watchfiles, webbrowser, no shell/`curl` assumptions, generate per-OS hook commands). Produce a short **manual cross-platform test checklist** in the README for the human to run on the remaining OSes (config-dir resolution, hook firing, server bind, browser open). Call out the WSL-vs-native-Windows split-install caveat explicitly.

---

## 8. Out of scope (do not build in MVP)

- Reverse proxy / auth / multi-host / any non-loopback listener.
- Docker runtime.
- Control actions (pause/approve/interrupt).
- Cost/token analytics beyond a raw counter (that's `tokenscape`).
- Tauri desktop shell and TUI mode (future phases; design the backend so they could attach later, but don't build them now).

---

## 9. Report format at each checkpoint

Keep it short: what you verified, any surprises vs. the scope doc's assumptions, decisions you made and why, and what you'll do next. Surface anything that contradicts the schema notes so the human can adjust the plan.
