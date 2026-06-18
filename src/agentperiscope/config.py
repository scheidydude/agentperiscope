import os
from pathlib import Path


def claude_dir(override: str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env)
    return Path.home() / ".claude"


def projects_dir(override: str | None = None) -> Path:
    return claude_dir(override) / "projects"


def db_path(override: str | None = None) -> Path:
    return claude_dir(override) / "agentperiscope.db"


def default_provider_configs(claude_dir_override: str | None = None) -> dict:
    return {
        "claude-code": {
            "enabled": True,
            "transcript_dir": str(projects_dir(claude_dir_override)),
        },
        "codex-cli": {
            "enabled": True,
            "session_dir": str(Path.home() / ".codex" / "sessions"),
            "session_index": str(Path.home() / ".codex" / "session_index.jsonl"),
        },
        "opencode": {
            "enabled": True,
            "db_path": str(Path.home() / ".local" / "share" / "opencode" / "opencode.db"),
        },
    }
