from loguru import logger

from app.llm.deepseek_client import LlmClient, LlmRequestError
from app.llm.queries import (
    QUERIES_SYSTEM_PROMPT,
    build_queries_prompt,
    try_parse_queries,
)
from app.llm.relevance import MAX_LLM_ATTEMPTS


class QueryGenerator:
    def __init__(self, client: LlmClient) -> None:
        self._client = client

    async def generate(self, portfolio_summary: str, limit: int) -> list[str]:
        for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
            queries = await self._try_single_attempt(portfolio_summary, limit)
            if queries is not None:
                return queries[:limit]
            logger.warning("query generation attempt {} of {} failed", attempt, MAX_LLM_ATTEMPTS)
        return []

    async def _try_single_attempt(self, portfolio_summary: str, limit: int) -> list[str] | None:
        try:
            raw_response = await self._client.complete_json(
                system_prompt=QUERIES_SYSTEM_PROMPT,
                user_prompt=build_queries_prompt(portfolio_summary, limit),
            )
        except LlmRequestError:
            return None
        parsed = try_parse_queries(raw_response)
        return parsed.queries if parsed is not None else None
