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
