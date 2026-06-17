# agentperiscope

Local live viewer for Claude Code subagent activity. Tails session transcripts and listens to lifecycle hooks, then renders a live per-agent view in the browser.

## Install

```sh
uv tool install .
# or for ephemeral use:
uvx --from . agentperiscope
```

Requires Python 3.12+. No Node required at runtime — the built React SPA is bundled in the wheel.

## Run

```sh
agentperiscope
```

Opens `http://127.0.0.1:<auto-port>` in your browser. Binds loopback only — never `0.0.0.0`.

### Options

```
--claude-dir PATH   Override Claude config dir (default: CLAUDE_CONFIG_DIR or ~/.claude)
--port INT          Fixed port instead of auto-select
--poll              Force polling file watcher (fallback for restrictive environments)
--no-open           Don't auto-open browser
```

## Wire up hooks (recommended)

Hooks give agentperiscope instant notification when agents start/stop rather than waiting for the next file-change event:

```sh
agentperiscope install-hooks            # global: ~/.claude/settings.json
agentperiscope install-hooks --project  # project: ./.claude/settings.json
```

To remove:

```sh
agentperiscope uninstall-hooks
```

The install writes `agentperiscope hook` as the hook command. That subcommand reads the hook JSON from stdin and POSTs it to the local server, then exits immediately — it never blocks Claude Code.

## Features

### Live agent view

Sessions appear as cards. Each card shows a grid of agent lanes — one per subagent plus the root agent. Each lane shows:

- Status dot (pulsing blue = running, green = done, red = error)
- Agent type and description
- Current tool in use
- Last text output
- Token breakdown: input / output / cache reads / cache writes

### Active and History

- **Active** — sessions with at least one running agent. Always shown, even when empty. Defaults open.
- **History** — completed sessions, loaded from SQLite on startup so they survive server restarts. Defaults closed.

Both sections are collapsible and show item counts. Sessions are sorted newest-first.

### Search

Type in the search bar to filter sessions across Active and History. Matches against working directory, project slug, agent descriptions, and last text output. No server round-trip — all sessions are in the browser on connect.

### Expand and pop out

Click **▼** on any agent card to expand an inline event log (text, tool calls, thinking blocks with timestamps). When expanded, click **⤢ pop out** to open a full modal with:

- Scrollable event list with full text (no truncation)
- Agent metadata: type, description, status, start/end times
- Token breakdown
- Event count

Click outside the modal or **✕** to close. Events are fetched once and reused for both views.

## Architecture

```
~/.claude/projects/<slug>/<session-id>.jsonl          ← tailed by watcher
~/.claude/projects/<slug>/<session-id>/subagents/     ← subagent transcripts
~/.claude/agentperiscope.db                                   ← SQLite history (sessions + agents)
~/.claude/agentperiscope.port                                 ← auto-detected port for hook subcommand
settings.json hooks → agentperiscope hook → POST /events      ← instant lifecycle events
FastAPI 127.0.0.1:<port>  /ws → browser WebSocket     ← live push
GET /api/sessions/{id}                                ← full session with events (on demand)
```

## WSL note

Claude Code on native Windows writes to `%USERPROFILE%\.claude`; Claude Code inside WSL writes to the Linux `~/.claude`. These are separate installs. Use `--claude-dir` to point agentperiscope at whichever one you're running:

```sh
# From inside WSL, watching the Windows-side transcripts:
agentperiscope --claude-dir /mnt/c/Users/YourName/.claude
```

## Cross-platform test checklist

Run these on each OS (macOS verified; Windows/Linux manual):

- [ ] `agentperiscope` resolves config dir correctly (`--claude-dir` override works)
- [ ] Browser opens automatically; `--no-open` suppresses it
- [ ] Server binds `127.0.0.1` (verify with `netstat -an | grep <port>`)
- [ ] `agentperiscope install-hooks` writes correct settings.json; hooks fire in next session
- [ ] `agentperiscope hook` exits fast (<50ms) even when server is down
- [ ] `--poll` mode works in environments without inotify/FSEvents
- [ ] History persists across server restarts (`~/.claude/agentperiscope.db`)
- [ ] Completed sessions from prior run appear in History, not Active

## Development

```sh
# Python
uv sync
uv run pytest

# Frontend
cd frontend
npm install
npm run build   # → src/agentperiscope/web/
# or for dev with HMR (start agentperiscope on a fixed port first):
uv run agentperiscope --port 7821 --no-open &
npm run dev
```
