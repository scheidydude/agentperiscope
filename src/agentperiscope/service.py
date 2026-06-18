"""macOS LaunchAgent install / uninstall for agentperiscope."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.agentperiscope"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "agentperiscope"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{binary}</string>
        <string>--no-open</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/stderr.log</string>
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
"""


def _binary() -> str:
    binary = shutil.which("agentperiscope")
    if binary:
        return binary
    # Fallback: same Python environment
    return str(Path(sys.executable).parent / "agentperiscope")


def install(bin_override: str | None = None) -> None:
    binary = bin_override or _binary()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(
        _PLIST_TEMPLATE.format(label=LABEL, binary=binary, log_dir=LOG_DIR)
    )
    subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)], check=True)
    print(f"Service installed and started.")
    print(f"  plist:  {PLIST_PATH}")
    print(f"  logs:   {LOG_DIR}/stdout.log")
    print(f"  stop:   launchctl stop {LABEL}")
    print(f"  start:  launchctl start {LABEL}")
    print(f"  remove: agentperiscope uninstall-service")


def uninstall() -> None:
    if not PLIST_PATH.exists():
        print("No service installed.")
        return
    subprocess.run(["launchctl", "unload", "-w", str(PLIST_PATH)], check=False)
    PLIST_PATH.unlink(missing_ok=True)
    print(f"Service removed: {PLIST_PATH}")
    print(f"Logs remain at: {LOG_DIR}")


def status() -> None:
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Service '{LABEL}' is not loaded.")

    from pathlib import Path
    port_file = Path.home() / ".claude" / "agentperiscope.port"
    if port_file.exists():
        port = port_file.read_text().strip()
        print(f"Listening on: http://127.0.0.1:{port}")
    else:
        print("Port file not found — server may not be running.")
