import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import PortfolioItem


def serialize_topics(topics: list[str]) -> str | None:
    return json.dumps(topics, ensure_ascii=False) if topics else None


def deserialize_topics(raw_topics: str | None) -> list[str]:
    if not raw_topics:
        return []
    parsed = json.loads(raw_topics)
    return [str(topic) for topic in parsed] if isinstance(parsed, list) else []


class PortfolioItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        repo_name: str,
        description: str | None,
        topics: list[str],
        language: str | None,
        html_url: str,
    ) -> PortfolioItem:
        serialized_topics = serialize_topics(topics)
        synced_at = utcnow()
        statement = (
            insert(PortfolioItem)
            .values(
                repo_name=repo_name,
                description=description,
                topics=serialized_topics,
                language=language,
                html_url=html_url,
                synced_at=synced_at,
            )
            .on_conflict_do_update(
                index_elements=[PortfolioItem.repo_name],
                set_={
                    "description": description,
                    "topics": serialized_topics,
                    "language": language,
                    "html_url": html_url,
                    "synced_at": synced_at,
                },
            )
            .returning(PortfolioItem)
        )
        result = await self._session.execute(statement)
        return result.scalar_one()

    async def list_all(self) -> Sequence[PortfolioItem]:
        statement = select(PortfolioItem).order_by(PortfolioItem.repo_name)
        result = await self._session.execute(statement)
        return result.scalars().all()
