import json
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram.types import Chat, Message, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import Base, create_engine, create_session_factory
from app.db.models import Lead
from app.telethon_client.client import ResolvedChat
from tests.unit.fixtures.relevance_messages import RelevanceCase


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


class FakeOwnerNotifier:
    def __init__(self, *, delivered: bool = True) -> None:
        self.sent: list[tuple[int, str]] = []
        self._delivered = delivered

    async def notify_lead(self, lead: Lead, chat_title: str) -> bool:
        self.sent.append((lead.id, chat_title))
        return self._delivered


class FakeVerdictLlm:
    def __init__(self, cases: Sequence[RelevanceCase]) -> None:
        self._cases = cases
        self.prompts: list[str] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        self.prompts.append(user_prompt)
        case = self._match_case(user_prompt)
        return json.dumps(
            {
                "is_relevant": case.expected_relevant,
                "reason": f"кейс: {case.description}",
                "confidence": 0.9 if case.expected_relevant else 0.1,
            },
            ensure_ascii=False,
        )

    def _match_case(self, user_prompt: str) -> RelevanceCase:
        for case in self._cases:
            probe = case.text.strip()[:60]
            if probe and probe in user_prompt:
                return case
        raise AssertionError("llm called with a prompt that matches no fixture case")


class BrokenJsonLlm:
    def __init__(self, response: str = "модель прислала не json") -> None:
        self._response = response
        self.calls = 0

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        self.calls += 1
        return self._response


class StubPortfolioSummary:
    def build_summary(self) -> str:
        return "Портфолио: python, telegram-боты, парсеры"


def make_group_message(
    text: str,
    *,
    chat_id: int = -1001,
    message_id: int = 1,
    user_id: int = 555,
    username: str | None = "customer",
    first_name: str = "Заказчик",
    chat_type: str = "supergroup",
) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type=chat_type, title="Мониторимый чат"),
        from_user=User(id=user_id, is_bot=False, first_name=first_name, username=username),
        text=text or None,
    )
