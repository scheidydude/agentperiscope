"""Claude Code provider — wraps the existing Watcher."""

from __future__ import annotations

from pathlib import Path

from agentperiscope.model import Store
from agentperiscope.providers.base import Provider
from agentperiscope.watcher import Watcher


class ClaudeCodeProvider(Provider):
    name = "claude-code"

    def __init__(self, projects_dir: Path, store: Store, poll: bool = False) -> None:
        self._watcher = Watcher(projects_dir=projects_dir, store=store, poll=poll)

    async def run(self) -> None:
        await self._watcher.run()
