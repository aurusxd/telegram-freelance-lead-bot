from typing import Protocol

from app.discovery.candidate import DiscoveredSourceCandidate


class SourceProvider(Protocol):
    async def search(self, query: str) -> list[DiscoveredSourceCandidate]: ...
