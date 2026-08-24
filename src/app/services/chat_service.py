import enum
import json
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.db.models import DiscoveredChat, DiscoveryStatus, MonitoredChat, MonitoredChatOrigin
from app.repositories.discovered_chats import DiscoveredChatRepository
from app.repositories.monitored_chats import MonitoredChatRepository, normalize_username
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


class AddChatOutcome(str, enum.Enum):
    added = "added"
    reactivated = "reactivated"
    already_monitored = "already_monitored"
    unresolved = "unresolved"


class AddChatResult(BaseModel):
    outcome: AddChatOutcome
    handle: str
    title: str | None = None


class RemoveChatOutcome(str, enum.Enum):
    removed = "removed"
    not_found = "not_found"


class RemoveChatResult(BaseModel):
    outcome: RemoveChatOutcome
    handle: str
    title: str | None = None


class PromoteOutcome(str, enum.Enum):
    promoted = "promoted"
    not_found = "not_found"
    unresolved = "unresolved"


class PromoteResult(BaseModel):
    outcome: PromoteOutcome
    title: str | None = None


class ChatServiceStatus(BaseModel):
    telethon_healthy: bool
    active_chats: int
    discovery_interval_minutes: int


def normalize_handle(handle: str) -> str:
    return f"@{normalize_username(handle)}"


def discovered_key(chat: DiscoveredChat) -> str:
    if chat.username:
        return chat.username.lower()
    return str(chat.tg_chat_id)


def classify_add_outcome(existing: MonitoredChat | None) -> AddChatOutcome:
    if existing is None:
        return AddChatOutcome.added
    return AddChatOutcome.already_monitored if existing.is_active else AddChatOutcome.reactivated


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

    async def add_chat(self, handle: str) -> AddChatResult:
        normalized_handle = normalize_handle(handle)
        resolved = await self._resolver.resolve(normalized_handle)
        if resolved is None:
            return AddChatResult(outcome=AddChatOutcome.unresolved, handle=normalized_handle)
        async with session_scope(self._session_factory) as session:
            repository = MonitoredChatRepository(session)
            existing = await repository.get_by_tg_chat_id(resolved.tg_chat_id)
            outcome = classify_add_outcome(existing)
            await repository.upsert(
                tg_chat_id=resolved.tg_chat_id,
                title=resolved.title,
                username=resolved.username or normalized_handle,
                origin=existing.origin if existing else MonitoredChatOrigin.command,
            )
        return AddChatResult(
            outcome=outcome,
            handle=normalized_handle,
            title=resolved.title,
        )

    async def remove_chat(self, handle: str) -> RemoveChatResult:
        normalized_handle = normalize_handle(handle)
        async with session_scope(self._session_factory) as session:
            repository = MonitoredChatRepository(session)
            chat = await repository.get_by_username(normalized_handle)
            if chat is None or not chat.is_active:
                return RemoveChatResult(
                    outcome=RemoveChatOutcome.not_found,
                    handle=normalized_handle,
                    title=chat.title if chat else None,
                )
            await repository.deactivate_by_username(normalized_handle)
            return RemoveChatResult(
                outcome=RemoveChatOutcome.removed,
                handle=normalized_handle,
                title=chat.title,
            )

    async def list_chats(self) -> Sequence[MonitoredChat]:
        async with session_scope(self._session_factory) as session:
            return await MonitoredChatRepository(session).list_all()

    async def list_pending_discovered(self) -> list[DiscoveredChat]:
        async with session_scope(self._session_factory) as session:
            approved = await DiscoveredChatRepository(session).list_by_status(
                DiscoveryStatus.approved
            )
            monitored_keys = await MonitoredChatRepository(session).existing_keys()
        return [chat for chat in approved if discovered_key(chat) not in monitored_keys]

    async def promote_discovered(self, discovered_chat_id: int) -> PromoteResult:
        async with session_scope(self._session_factory) as session:
            discovered = await DiscoveredChatRepository(session).get(discovered_chat_id)
            if discovered is None or discovered.status is not DiscoveryStatus.approved:
                return PromoteResult(outcome=PromoteOutcome.not_found)
            identity = await self._resolve_discovered_identity(discovered)
            if identity is None:
                return PromoteResult(outcome=PromoteOutcome.unresolved, title=discovered.title)
            tg_chat_id, title, username = identity
            await MonitoredChatRepository(session).upsert(
                tg_chat_id=tg_chat_id,
                title=title,
                username=username,
                origin=MonitoredChatOrigin.command,
            )
        return PromoteResult(outcome=PromoteOutcome.promoted, title=title)

    async def _resolve_discovered_identity(
        self, discovered: DiscoveredChat
    ) -> tuple[int, str, str | None] | None:
        if discovered.tg_chat_id is not None:
            return (
                discovered.tg_chat_id,
                discovered.title or discovered.link,
                discovered.username,
            )
        if discovered.username is None:
            return None
        resolved = await self._resolver.resolve(normalize_handle(discovered.username))
        if resolved is None:
            return None
        return resolved.tg_chat_id, resolved.title, resolved.username or discovered.username

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
