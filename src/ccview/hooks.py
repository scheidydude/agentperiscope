"""Hook handler and settings.json installer."""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_HOOK_EVENTS = ["SubagentStart", "SubagentStop", "Stop", "PreToolUse", "PostToolUse"]


def _resolve_port(port: int | None, claude_dir: Path | None = None) -> int | None:
    """Return port from explicit arg, port file, or None if server not running."""
    if port:
        return port
    from ccview import config as cfg
    port_file = cfg.claude_dir(str(claude_dir) if claude_dir else None) / "ccview.port"
    try:
        return int(port_file.read_text().strip())
    except (OSError, ValueError):
        return None


def handle_hook(port: int | None = None) -> None:
    """Read hook JSON from stdin, POST to local server. Exit fast."""
    try:
        payload = sys.stdin.buffer.read()
    except Exception:
        sys.exit(0)

    resolved = _resolve_port(port)
    if not resolved:
        sys.exit(0)  # server not running — fail silently

    try:
        url = f"http://127.0.0.1:{resolved}/events"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # never block Claude Code
    sys.exit(0)


def _hook_command(ccview_path: str) -> str:
    """Generate OS-appropriate hook command string."""
    import platform
    system = platform.system()
    if system == "Windows":
        return f'"{ccview_path}" hook'
    return f'"{ccview_path}" hook'


def _find_ccview_bin() -> str:
    """Return the path to the installed ccview binary."""
    import shutil
    found = shutil.which("ccview")
    return found or "ccview"


def _load_settings(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


_CCVIEW_MARKER = "ccview"


def install_hooks(settings_path: Path, ccview_bin: str | None = None) -> None:
    """Idempotently merge ccview hooks into settings_path."""
    bin_path = ccview_bin or _find_ccview_bin()
    cmd = _hook_command(bin_path)

    data = _load_settings(settings_path)
    hooks: dict = data.setdefault("hooks", {})

    changed = False
    for event in _HOOK_EVENTS:
        handlers: list = hooks.setdefault(event, [])
        already = any(
            any(
                isinstance(h, dict) and _CCVIEW_MARKER in h.get("command", "")
                for h in entry.get("hooks", [])
            )
            for entry in handlers
            if isinstance(entry, dict)
        )
        if not already:
            handlers.append({
                "hooks": [{"type": "command", "command": cmd}]
            })
            changed = True

    if changed:
        _save_settings(settings_path, data)
        print(f"hooks installed → {settings_path}")
    else:
        print(f"hooks already present in {settings_path}")


def uninstall_hooks(settings_path: Path) -> None:
    """Remove all ccview hook entries from settings_path."""
    if not settings_path.exists():
        return
    data = _load_settings(settings_path)
    hooks: dict = data.get("hooks", {})

    changed = False
    for event in list(hooks.keys()):
        handlers = hooks[event]
        new_handlers = []
        for entry in handlers:
            if not isinstance(entry, dict):
                new_handlers.append(entry)
                continue
            inner = entry.get("hooks", [])
            cleaned = [
                h for h in inner
                if not (isinstance(h, dict) and _CCVIEW_MARKER in h.get("command", ""))
            ]
            if cleaned:
                new_handlers.append({**entry, "hooks": cleaned})
            elif len(inner) != len(cleaned):
                changed = True
            else:
                new_handlers.append(entry)

        if len(new_handlers) != len(handlers):
            changed = True
        hooks[event] = new_handlers
        # prune empty event keys
        if not hooks[event]:
            del hooks[event]
            changed = True

    if changed:
        _save_settings(settings_path, data)
        print(f"hooks removed from {settings_path}")
    else:
        print(f"no ccview hooks found in {settings_path}")
