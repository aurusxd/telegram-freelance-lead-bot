import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import Base, create_engine, create_session_factory
from app.telethon_client.client import ResolvedChat


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


class FakeChatResolver:
    def __init__(
        self,
        resolved: dict[str, ResolvedChat] | None = None,
        *,
        healthy: bool = True,
    ) -> None:
        self.resolved = resolved or {}
        self.calls: list[str] = []
        self._healthy = healthy

    async def resolve(self, handle: str) -> ResolvedChat | None:
        self.calls.append(handle)
        return self.resolved.get(handle)

    async def health_check(self) -> bool:
        return self._healthy


def make_resolved_chat(
    handle: str,
    tg_chat_id: int,
    title: str = "Chat title",
) -> ResolvedChat:
    return ResolvedChat(
        tg_chat_id=tg_chat_id,
        access_hash=1234567890,
        title=title,
        username=handle.removeprefix("@"),
    )


def write_sources_file(path: Path, entries: object) -> Path:
    sources_path = path / "sources.json"
    sources_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return sources_path
