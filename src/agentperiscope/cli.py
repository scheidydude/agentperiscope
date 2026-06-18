"""agentperiscope CLI entry point."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import webbrowser
from pathlib import Path
from typing import Annotated, Optional

import typer
import uvicorn

from agentperiscope import config as cfg

app = typer.Typer(help="Local live viewer for Claude Code subagent activity.")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Main: start watcher + server
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    claude_dir: Annotated[Optional[str], typer.Option("--claude-dir", help="Path to Claude config dir")] = None,
    port: Annotated[int, typer.Option("--port", help="Server port (0 = auto)")] = 0,
    poll: Annotated[bool, typer.Option("--poll", help="Force polling file watcher (slower but universal)")] = False,
    no_open: Annotated[bool, typer.Option("--no-open", help="Don't open browser")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    no_codex: Annotated[bool, typer.Option("--no-codex", help="Disable Codex CLI provider")] = False,
    no_opencode: Annotated[bool, typer.Option("--no-opencode", help="Disable OpenCode provider")] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    _setup_logging(verbose)

    from agentperiscope.db import DB
    from agentperiscope.model import Store
    from agentperiscope.server import build_app, find_free_port
    from agentperiscope.providers.claude_code import ClaudeCodeProvider
    from agentperiscope.providers.codex_cli import CodexCliProvider
    from agentperiscope.providers.opencode import OpenCodeProvider

    projects = cfg.projects_dir(claude_dir)
    if not projects.exists():
        typer.echo(f"projects dir not found: {projects}", err=True)
        raise typer.Exit(1)

    actual_port = port if port else find_free_port()
    db = DB(cfg.db_path(claude_dir))
    store = Store()
    db.load_into(store)
    store.subscribe(db.on_delta)

    provider_cfgs = cfg.default_provider_configs(claude_dir)

    providers = [ClaudeCodeProvider(projects_dir=projects, store=store, poll=poll)]
    typer.echo(f"agentperiscope listening on http://127.0.0.1:{actual_port}")
    typer.echo(f"provider claude-code: watching {projects}")

    if not no_codex:
        codex_cfg = provider_cfgs["codex-cli"]
        codex_dir = Path(codex_cfg["session_dir"])
        codex_index = Path(codex_cfg["session_index"])
        if codex_dir.exists():
            providers.append(CodexCliProvider(
                session_dir=codex_dir,
                store=store,
                session_index=codex_index if codex_index.exists() else None,
            ))
            typer.echo(f"provider codex-cli: watching {codex_dir}")
        else:
            typer.echo(f"provider codex-cli: skipped (dir not found: {codex_dir})")

    if not no_opencode:
        oc_cfg = provider_cfgs["opencode"]
        oc_db = Path(oc_cfg["db_path"])
        if oc_db.exists():
            providers.append(OpenCodeProvider(db_path=oc_db, store=store))
            typer.echo(f"provider opencode: watching {oc_db}")
        else:
            typer.echo(f"provider opencode: skipped (db not found: {oc_db})")

    fastapi_app = build_app(store)
    url = f"http://127.0.0.1:{actual_port}"
    port_file = cfg.claude_dir(claude_dir) / "agentperiscope.port"

    async def _run() -> None:
        uv_config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=actual_port,
            log_level="warning",
        )
        server = uvicorn.Server(uv_config)

        if not no_open:
            asyncio.get_event_loop().call_later(0.5, lambda: webbrowser.open(url))

        def _cleanup() -> None:
            server.should_exit = True
            try:
                port_file.unlink(missing_ok=True)
            except OSError:
                pass

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _cleanup)

        try:
            port_file.write_text(str(actual_port))
            await asyncio.gather(
                server.serve(),
                *[p.run() for p in providers],
            )
        finally:
            _cleanup()
            db.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# hook subcommand
# ---------------------------------------------------------------------------

@app.command("hook")
def hook_cmd(
    port: Annotated[Optional[int], typer.Option("--port", help="agentperiscope server port (auto-detected if omitted)")] = None,
) -> None:
    """Read hook JSON from stdin and POST to the local agentperiscope server."""
    from agentperiscope.hooks import handle_hook
    handle_hook(port)


# ---------------------------------------------------------------------------
# install-hooks / uninstall-hooks
# ---------------------------------------------------------------------------

@app.command("install-hooks")
def install_hooks_cmd(
    global_: Annotated[bool, typer.Option("--global", "-g", help="Install in global ~/.claude/settings.json")] = False,
    project: Annotated[bool, typer.Option("--project", "-p", help="Install in ./.claude/settings.json")] = False,
    claude_dir: Annotated[Optional[str], typer.Option("--claude-dir")] = None,
    bin_override: Annotated[Optional[str], typer.Option("--bin", help="Path to agentperiscope binary")] = None,
) -> None:
    """Add agentperiscope hooks to Claude Code settings.json (idempotent)."""
    from agentperiscope.hooks import install_hooks

    paths = _resolve_settings_paths(global_, project, claude_dir)
    for p in paths:
        install_hooks(p, bin_override)


@app.command("uninstall-hooks")
def uninstall_hooks_cmd(
    global_: Annotated[bool, typer.Option("--global", "-g")] = False,
    project: Annotated[bool, typer.Option("--project", "-p")] = False,
    claude_dir: Annotated[Optional[str], typer.Option("--claude-dir")] = None,
) -> None:
    """Remove agentperiscope hooks from Claude Code settings.json."""
    from agentperiscope.hooks import uninstall_hooks

    paths = _resolve_settings_paths(global_, project, claude_dir)
    for p in paths:
        uninstall_hooks(p)


def _resolve_settings_paths(global_: bool, project: bool, claude_dir_override: str | None) -> list[Path]:
    """Return list of settings.json paths to operate on."""
    paths = []
    if not global_ and not project:
        # default: global
        global_ = True
    if global_:
        paths.append(cfg.claude_dir(claude_dir_override) / "settings.json")
    if project:
        paths.append(Path(".claude") / "settings.json")
    return paths
