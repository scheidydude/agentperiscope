# agentperiscope

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Local live observability viewer for AI agent activity. Tails session transcripts from Claude Code, Codex, and OpenCode, then renders a live per-agent view in the browser.

## Install

```sh
uv tool install .
```

Requires Python 3.12+. No Node required at runtime — the built React SPA is bundled in the wheel.

## Run

```sh
agentperiscope
```

Opens `http://127.0.0.1:<auto-port>` in your browser. Binds loopback only.

### Options

```
--claude-dir PATH   Override Claude config dir (default: CLAUDE_CONFIG_DIR or ~/.claude)
--port INT          Fixed port instead of auto-select
--poll              Force polling file watcher (fallback for restrictive environments)
--no-open           Don't auto-open browser
--no-codex          Disable Codex CLI provider
--no-opencode       Disable OpenCode provider
```

### Find the URL

```sh
agentperiscope port    # prints http://127.0.0.1:XXXXX
agentperiscope open    # prints URL and opens browser
```

The raw port is also in `~/.claude/agentperiscope.port`.

### Stop

Press **Ctrl+C** in the terminal, or from anywhere:

```sh
curl -X POST http://127.0.0.1:$(cat ~/.claude/agentperiscope.port)/api/stop
```

## Run as a service (macOS)

For daily use, install as a macOS LaunchAgent — starts on login, restarts on crash:

```sh
agentperiscope install-service
```

Logs go to `~/Library/Logs/agentperiscope/`. Manage without uninstalling:

```sh
launchctl stop com.agentperiscope    # stop
launchctl start com.agentperiscope   # start
agentperiscope service-status        # show launchctl status + URL
agentperiscope open                  # open browser to running instance
```

Remove the service:

```sh
agentperiscope uninstall-service
```

## Wire up hooks (recommended)

Hooks give agentperiscope instant notification when Claude Code agents start/stop:

```sh
agentperiscope install-hooks            # global: ~/.claude/settings.json
agentperiscope install-hooks --project  # project: ./.claude/settings.json
agentperiscope uninstall-hooks
```

## Supported providers

| Provider | Source | Default |
|---|---|---|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | enabled |
| **Codex** (OpenAI Codex Desktop) | `~/.codex/sessions/**/*.jsonl` | enabled if dir exists |
| **OpenCode** | `~/.local/share/opencode/opencode.db` | enabled if db exists |

Providers are auto-detected. If the source directory or database does not exist the provider is skipped silently on startup.

Override paths via `--claude-dir` (Claude Code) or disable providers with `--no-codex` / `--no-opencode`.

### Adding a provider

1. Implement `Provider` ABC from `agentperiscope.providers.base`
2. Call `store.ensure_session(..., provider="your-name")` when creating sessions
3. Register in `cli.py` alongside the existing providers
4. Add fixtures and parser tests under `tests/fixtures/your-name/`

## Features

### Live agent view

Sessions appear as cards grouped by **Active** and **History**. Each card shows:

- Provider badge (Claude Code / Codex / OpenCode)
- Status dot (pulsing blue = running, green = done, red = error)
- Agent type and description
- Current tool in use
- Last text output
- Token breakdown: input / output / cache reads / cache writes

### Provider filter

Toggle providers in the header to show/hide sessions by source.

### Search

Type in the search bar to filter by working directory, project name, agent description, or last text. No server round-trip.

### Expand and pop out

Click **▼** on any agent card to expand an inline event log. Click **⤢ pop out** for a full scrollable modal with all events and metadata.

### History

Completed sessions persist in `~/.claude/agentperiscope.db` and reload on startup. Sessions that ended while agentperiscope was down appear in History, not Active.

## Architecture

```
~/.claude/projects/<slug>/<session-id>.jsonl         ← Claude Code: tailed by watcher
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl         ← Codex: tailed by provider
~/.local/share/opencode/opencode.db                  ← OpenCode: polled every 3s
~/.claude/agentperiscope.db                          ← SQLite history
~/.claude/agentperiscope.port                        ← port file for hook subcommand
FastAPI 127.0.0.1:<port>  /ws → browser WebSocket    ← live push
GET /api/sessions/{id}                               ← full session with events
POST /api/stop                                       ← programmatic shutdown
```

## Known limitations

- Codex sessions have no explicit end-of-session event; sessions are marked done after 30 minutes of inactivity.
- OpenCode sessions ended by user cancellation (`MessageAbortedError`) are detected and marked done.
- Event history (expand/pop-out) is only available for sessions active during the current run; restarted sessions show no events until new activity arrives.
- The Codex provider watches the OpenAI Codex Desktop app (`~/.codex`), not a separate `codex` CLI.

## Development

### Iterating on changes

```sh
# Run directly from the repo (no install needed):
uv run agentperiscope

# After any Python change, just re-run — uv picks up changes automatically.

# After frontend changes, rebuild the SPA first:
cd frontend && npm run build
uv run agentperiscope
```

### Reinstall after changes

```sh
uv tool install . --reinstall
```

If running as a service, reinstall then bounce it:

```sh
uv tool install . --reinstall
launchctl stop com.agentperiscope && launchctl start com.agentperiscope
```

Or one-liner:

```sh
uv tool install . --reinstall && launchctl kickstart -k gui/$(id -u)/com.agentperiscope
```

### Frontend dev with HMR

```sh
# Terminal 1 — backend on a fixed port:
uv run agentperiscope --port 7821 --no-open

# Terminal 2 — Vite dev server:
cd frontend && npm run dev
```

### Tests

```sh
uv run pytest tests/ -q
```

## WSL note

Claude Code on native Windows writes to `%USERPROFILE%\.claude`; inside WSL it writes to the Linux `~/.claude`. Use `--claude-dir` to point at the right one:

```sh
agentperiscope --claude-dir /mnt/c/Users/YourName/.claude
```
