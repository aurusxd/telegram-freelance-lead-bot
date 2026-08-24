import re
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from app.db.models import DiscoveryProvider
from app.discovery.candidate import DiscoveredSourceCandidate

REQUEST_TIMEOUT_SECONDS = 20.0
SEARCH_PATH = "/search"
MAX_RESULTS_PER_QUERY = 30
TELEGRAM_HOSTS = frozenset({"t.me", "www.t.me", "telegram.me", "www.telegram.me"})
PRIVATE_PATH_PREFIXES = ("joinchat", "+", "c", "s", "share", "addstickers", "proxy", "socks")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")


def parse_tme_username(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https", ""):
        return None
    if parsed.netloc.lower() not in TELEGRAM_HOSTS:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return None
    candidate = segments[0]
    if candidate.lower() in PRIVATE_PATH_PREFIXES or candidate.startswith("+"):
        return None
    return candidate.lower() if USERNAME_PATTERN.match(candidate) else None


def build_search_query(query: str) -> str:
    return f"site:t.me {query}"


def to_candidate(result: dict[str, Any]) -> DiscoveredSourceCandidate | None:
    url = result.get("url")
    if not isinstance(url, str):
        return None
    username = parse_tme_username(url)
    if username is None:
        return None
    title = result.get("title")
    snippet = result.get("content")
    return DiscoveredSourceCandidate(
        provider=DiscoveryProvider.searxng,
        username=username,
        tg_chat_id=None,
        title=title if isinstance(title, str) else None,
        link=f"https://t.me/{username}",
        raw_snippet=snippet if isinstance(snippet, str) else None,
    )


class SearxngProvider:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_results: int = MAX_RESULTS_PER_QUERY,
    ) -> None:
        self._base_url = base_url
        self._transport = transport
        self._max_results = max_results

    async def search(self, query: str) -> list[DiscoveredSourceCandidate]:
        results = await self._fetch_results(query)
        candidates = (to_candidate(result) for result in results[: self._max_results])
        return [candidate for candidate in candidates if candidate is not None]

    async def _fetch_results(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            try:
                response = await client.get(
                    SEARCH_PATH,
                    params={"q": build_search_query(query), "format": "json"},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("searxng request failed: {}", type(error).__name__)
                return []
        return extract_results(payload)


def extract_results(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, dict)]


SEED_CANDIDATES = (
    DiscoveredSourceCandidate(
        provider=DiscoveryProvider.searxng,
        username="python_jobs_seed",
        tg_chat_id=None,
        title="Python Jobs (seed)",
        link="https://t.me/python_jobs_seed",
        raw_snippet="Вакансии и заказы для python-разработчиков",
    ),
    DiscoveredSourceCandidate(
        provider=DiscoveryProvider.searxng,
        username="freelance_it_seed",
        tg_chat_id=None,
        title="Freelance IT (seed)",
        link="https://t.me/freelance_it_seed",
        raw_snippet="Заказы на разработку ботов и парсеров",
    ),
)


class FakeSearxngProvider:
    async def search(self, query: str) -> list[DiscoveredSourceCandidate]:
        del query
        return list(SEED_CANDIDATES)
