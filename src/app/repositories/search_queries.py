from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SearchQuery


class SearchQueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_if_absent(self, query_text: str) -> bool:
        statement = (
            insert(SearchQuery)
            .values(query_text=query_text)
            .on_conflict_do_nothing(index_elements=[SearchQuery.query_text])
            .returning(SearchQuery.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def mark_run(self, query_text: str, ran_at: datetime) -> None:
        statement = (
            update(SearchQuery)
            .where(SearchQuery.query_text == query_text)
            .values(last_run_at=ran_at)
        )
        await self._session.execute(statement)

    async def last_run_at(self) -> datetime | None:
        result = await self._session.execute(select(func.max(SearchQuery.last_run_at)))
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[SearchQuery]:
        statement = select(SearchQuery).order_by(SearchQuery.generated_at)
        result = await self._session.execute(statement)
        return result.scalars().all()
