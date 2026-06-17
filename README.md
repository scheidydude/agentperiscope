# ccview

Local live viewer for Claude Code subagent activity. Tails session transcripts and listens to lifecycle hooks, then renders a live per-agent view in the browser.

## Install

```sh
uv tool install .
# or for ephemeral use:
uvx --from . ccview
```

Requires Python 3.12+. No Node required at runtime — the built React SPA is bundled in the wheel.

## Run

```sh
ccview
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

Hooks give ccview instant notification when agents start/stop rather than waiting for the next file-change event:

```sh
ccview install-hooks          # global: ~/.claude/settings.json
ccview install-hooks --project  # project: ./.claude/settings.json
```

To remove:

```sh
ccview uninstall-hooks
```

The install writes `ccview hook` as the hook command. That subcommand reads the hook JSON from stdin and POSTs it to the local server, then exits immediately — it never blocks Claude Code.

## Architecture

```
~/.claude/projects/<slug>/<session-id>.jsonl          ← tailed by watcher
~/.claude/projects/<slug>/<session-id>/subagents/     ← subagent transcripts
settings.json hooks → ccview hook → POST /events      ← instant lifecycle events
FastAPI 127.0.0.1:<port>  /ws → browser WebSocket     ← live push
```

## WSL note

Claude Code on native Windows writes to `%USERPROFILE%\.claude`; Claude Code inside WSL writes to the Linux `~/.claude`. These are separate installs. Use `--claude-dir` to point ccview at whichever one you're running:

```sh
# From inside WSL, watching the Windows-side transcripts:
ccview --claude-dir /mnt/c/Users/YourName/.claude
```

## Cross-platform test checklist

Run these on each OS (macOS verified; Windows/Linux manual):

- [ ] `ccview` resolves config dir correctly (`--claude-dir` override works)
- [ ] Browser opens automatically; `--no-open` suppresses it
- [ ] Server binds `127.0.0.1` (verify with `netstat -an | grep <port>`)
- [ ] `ccview install-hooks` writes correct settings.json; hooks fire in next session
- [ ] `ccview hook` exits fast (<50ms) even when server is down
- [ ] `--poll` mode works in environments without inotify/FSEvents

## Development

```sh
# Python
uv sync
uv run pytest

# Frontend
cd frontend
npm install
npm run build   # → src/ccview/web/
# or for dev with HMR (start ccview on port 7821 first):
npm run dev
```
