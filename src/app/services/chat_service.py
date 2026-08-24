import json
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.db.models import MonitoredChatOrigin
from app.repositories.monitored_chats import MonitoredChatRepository
from app.telethon_client.client import TelegramChatResolver


class SourcesFileError(Exception):
    pass


class SourcesFileEntry(BaseModel):
    handle: str = Field(min_length=2)
    title: str | None = None
    enabled: bool

    @field_validator("handle")
    @classmethod
    def handle_starts_with_at(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith("@"):
            raise ValueError("handle must start with @")
        if len(stripped) < 2:
            raise ValueError("handle must contain a username after @")
        return stripped


def load_sources_file(path: Path) -> list[SourcesFileEntry]:
    raw_text = read_sources_file_text(path)
    payload = parse_sources_file_json(path, raw_text)
    entries = validate_sources_file_entries(path, payload)
    reject_duplicate_handles(path, entries)
    return entries


def read_sources_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourcesFileError(f"cannot read sources file {path}: {error}") from error


def parse_sources_file_json(path: Path, raw_text: str) -> object:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise SourcesFileError(f"sources file {path} is not valid JSON: {error}") from error


def validate_sources_file_entries(path: Path, payload: object) -> list[SourcesFileEntry]:
    if not isinstance(payload, list):
        raise SourcesFileError(f"sources file {path} must contain a JSON array of objects")
    entries: list[SourcesFileEntry] = []
    for index, item in enumerate(payload):
        try:
            entries.append(SourcesFileEntry.model_validate(item))
        except ValidationError as error:
            raise SourcesFileError(f"sources file {path}, entry #{index}: {error}") from error
    return entries


def reject_duplicate_handles(path: Path, entries: list[SourcesFileEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        key = entry.handle.lower()
        if key in seen:
            raise SourcesFileError(f"sources file {path} contains duplicate handle {entry.handle}")
        seen.add(key)


class SourcesSyncResult(BaseModel):
    synced: int = 0
    deactivated: int = 0
    unresolved: list[str] = Field(default_factory=list)


class ChatServiceStatus(BaseModel):
    telethon_healthy: bool
    active_chats: int
    discovery_interval_minutes: int


class ChatService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        resolver: TelegramChatResolver,
        discovery_interval_minutes: int,
    ) -> None:
        self._session_factory = session_factory
        self._resolver = resolver
        self._discovery_interval_minutes = discovery_interval_minutes

    async def build_status(self) -> ChatServiceStatus:
        async with session_scope(self._session_factory) as session:
            active_chats = len(await MonitoredChatRepository(session).list_active())
        return ChatServiceStatus(
            telethon_healthy=await self._resolver.health_check(),
            active_chats=active_chats,
            discovery_interval_minutes=self._discovery_interval_minutes,
        )

    async def sync_from_sources_file(self, path: Path) -> SourcesSyncResult:
        entries = load_sources_file(path)
        result = SourcesSyncResult()
        async with session_scope(self._session_factory) as session:
            repository = MonitoredChatRepository(session)
            for entry in entries:
                if entry.enabled:
                    await self._sync_enabled_entry(repository, entry, result)
                else:
                    await self._sync_disabled_entry(repository, entry, result)
        logger.info(
            "sources sync finished: synced={} deactivated={} unresolved={}",
            result.synced,
            result.deactivated,
            len(result.unresolved),
        )
        return result

    async def _sync_enabled_entry(
        self,
        repository: MonitoredChatRepository,
        entry: SourcesFileEntry,
        result: SourcesSyncResult,
    ) -> None:
        resolved = await self._resolver.resolve(entry.handle)
        if resolved is None:
            result.unresolved.append(entry.handle)
            logger.warning("skipping unresolved source chat {}", entry.handle)
            return
        await repository.upsert(
            tg_chat_id=resolved.tg_chat_id,
            title=resolved.title,
            username=resolved.username or entry.handle,
            origin=MonitoredChatOrigin.sources_file,
        )
        result.synced += 1

    async def _sync_disabled_entry(
        self,
        repository: MonitoredChatRepository,
        entry: SourcesFileEntry,
        result: SourcesSyncResult,
    ) -> None:
        if await repository.deactivate_by_username(entry.handle):
            result.deactivated += 1
