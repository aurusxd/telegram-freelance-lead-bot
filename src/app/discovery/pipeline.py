import asyncio
from collections.abc import Iterable, Sequence

from loguru import logger

from app.discovery.candidate import DiscoveredSourceCandidate
from app.discovery.providers.base import SourceProvider

SEED_DISCOVERY_QUERY = "ищу разработчика telegram бот python"


def deduplicate_candidates(
    candidates: Iterable[DiscoveredSourceCandidate],
) -> list[DiscoveredSourceCandidate]:
    seen: set[str] = set()
    unique: list[DiscoveredSourceCandidate] = []
    for candidate in candidates:
        key = candidate.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


class DiscoveryPipeline:
    def __init__(self, providers: Sequence[SourceProvider]) -> None:
        self._providers = providers

    async def collect_candidates(self, query: str) -> list[DiscoveredSourceCandidate]:
        batches = await asyncio.gather(*(provider.search(query) for provider in self._providers))
        return deduplicate_candidates(candidate for batch in batches for candidate in batch)

    async def run_once(self, query: str = SEED_DISCOVERY_QUERY) -> int:
        candidates = await self.collect_candidates(query)
        logger.info("discovery run collected {} unique candidates", len(candidates))
        return len(candidates)
