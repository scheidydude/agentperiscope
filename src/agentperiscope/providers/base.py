"""Provider ABC for agent runtime integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Provider(ABC):
    name: str

    @abstractmethod
    async def run(self) -> None:
        """Start watching/polling until cancelled."""
        ...
