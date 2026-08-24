import asyncio
from collections.abc import Iterable, Sequence

from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope, utcnow
from app.db.models import DiscoveryStatus
from app.discovery.candidate import DiscoveredSourceCandidate
from app.discovery.providers.base import SourceProvider
from app.discovery.query_generator import QueryGenerator
from app.llm.relevance import RelevanceChecker
from app.portfolio.service import PortfolioSummarySource
from app.repositories.discovered_chats import DiscoveredChatRepository
from app.repositories.monitored_chats import MonitoredChatRepository
from app.repositories.search_queries import SearchQueryRepository
from app.telethon_client.client import ResolvedChat, TelegramChatResolver
from app.telethon_client.history import ChatHistoryReader

EMPTY_HISTORY_REASON = "история чата пуста, оценка не проводилась"


class DiscoveryRunResult(BaseModel):
    queries: int = 0
    candidates: int = 0
    approved: int = 0
    rejected: int = 0
    unresolved: int = 0


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


def build_chat_context(messages: list[str]) -> str:
    return "\n".join(messages).strip()


def resolve_handle(candidate: DiscoveredSourceCandidate) -> str:
    return f"@{candidate.username}" if candidate.username else candidate.link


class DiscoveryPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        providers: Sequence[SourceProvider],
        query_generator: QueryGenerator,
        resolver: TelegramChatResolver,
        history: ChatHistoryReader,
        relevance_checker: RelevanceChecker,
        portfolio: PortfolioSummarySource,
        *,
        queries_per_run: int,
        messages_per_chat: int,
    ) -> None:
        self._session_factory = session_factory
        self._providers = providers
        self._query_generator = query_generator
        self._resolver = resolver
        self._history = history
        self._relevance_checker = relevance_checker
        self._portfolio = portfolio
        self._queries_per_run = queries_per_run
        self._messages_per_chat = messages_per_chat

    async def run_once(self) -> DiscoveryRunResult:
        portfolio_summary = self._portfolio.build_summary()
        queries = await self._prepare_queries(portfolio_summary)
        if not queries:
            logger.warning("discovery run skipped: no search queries generated")
            return DiscoveryRunResult()

        candidates = await self._collect_candidates(queries)
        fresh_candidates = await self._drop_known_candidates(candidates)
        result = DiscoveryRunResult(queries=len(queries), candidates=len(fresh_candidates))

        for candidate in fresh_candidates:
            await self._evaluate_candidate(candidate, portfolio_summary, result)

        logger.info(
            "discovery run finished: queries={} candidates={} approved={} rejected={}",
            result.queries,
            result.candidates,
            result.approved,
            result.rejected,
        )
        return result

    async def _prepare_queries(self, portfolio_summary: str) -> list[str]:
        queries = await self._query_generator.generate(portfolio_summary, self._queries_per_run)
        async with session_scope(self._session_factory) as session:
            repository = SearchQueryRepository(session)
            for query in queries:
                await repository.add_if_absent(query)
        return queries

    async def _collect_candidates(self, queries: list[str]) -> list[DiscoveredSourceCandidate]:
        collected: list[DiscoveredSourceCandidate] = []
        for query in queries:
            batches = await asyncio.gather(
                *(provider.search(query) for provider in self._providers),
                return_exceptions=True,
            )
            collected.extend(self._flatten_batches(batches))
            await self._mark_query_run(query)
        return deduplicate_candidates(collected)

    def _flatten_batches(
        self, batches: Sequence[list[DiscoveredSourceCandidate] | BaseException]
    ) -> list[DiscoveredSourceCandidate]:
        flattened: list[DiscoveredSourceCandidate] = []
        for batch in batches:
            if isinstance(batch, BaseException):
                logger.warning("provider failed: {}", type(batch).__name__)
                continue
            flattened.extend(batch)
        return flattened

    async def _mark_query_run(self, query: str) -> None:
        async with session_scope(self._session_factory) as session:
            await SearchQueryRepository(session).mark_run(query, utcnow())

    async def _drop_known_candidates(
        self, candidates: list[DiscoveredSourceCandidate]
    ) -> list[DiscoveredSourceCandidate]:
        async with session_scope(self._session_factory) as session:
            known = await DiscoveredChatRepository(session).existing_keys()
            known |= await MonitoredChatRepository(session).existing_keys()
        return [candidate for candidate in candidates if candidate.dedupe_key() not in known]

    async def _evaluate_candidate(
        self,
        candidate: DiscoveredSourceCandidate,
        portfolio_summary: str,
        result: DiscoveryRunResult,
    ) -> None:
        resolved = await self._resolver.resolve(resolve_handle(candidate))
        if resolved is None:
            result.unresolved += 1
            return

        context = build_chat_context(
            await self._history.read_last_messages(resolved, self._messages_per_chat)
        )
        if not context:
            await self._persist(candidate, resolved, DiscoveryStatus.rejected, EMPTY_HISTORY_REASON)
            result.rejected += 1
            return

        verdict = await self._relevance_checker.evaluate_chat(context, portfolio_summary)
        status = DiscoveryStatus.approved if verdict.is_relevant else DiscoveryStatus.rejected
        await self._persist(candidate, resolved, status, verdict.reason)
        if verdict.is_relevant:
            result.approved += 1
        else:
            result.rejected += 1

    async def _persist(
        self,
        candidate: DiscoveredSourceCandidate,
        resolved: ResolvedChat,
        status: DiscoveryStatus,
        relevance_reason: str,
    ) -> None:
        async with session_scope(self._session_factory) as session:
            stored = await DiscoveredChatRepository(session).upsert_evaluated(
                tg_chat_id=resolved.tg_chat_id,
                username=resolved.username or candidate.username,
                title=resolved.title or candidate.title,
                link=candidate.link,
                provider=candidate.provider,
                status=status,
                relevance_reason=relevance_reason,
                evaluated_at=utcnow(),
            )
        if stored is None:
            logger.warning("candidate {} conflicts with a stored chat", candidate.dedupe_key())
