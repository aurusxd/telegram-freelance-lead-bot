import enum
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class DiscoveryProvider(str, enum.Enum):
    telethon_search = "telethon_search"
    searxng = "searxng"


class DiscoveryStatus(str, enum.Enum):
    pending = "pending"
    fetched = "fetched"
    evaluated = "evaluated"
    approved = "approved"
    rejected = "rejected"


class MonitoredChatOrigin(str, enum.Enum):
    sources_file = "sources_file"
    command = "command"


class MonitoredChat(Base):
    __tablename__ = "monitored_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int] = mapped_column(unique=True, index=True)
    title: Mapped[str]
    username: Mapped[str | None]
    invite_link: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True)
    origin: Mapped[MonitoredChatOrigin]
    added_at: Mapped[datetime] = mapped_column(default=utcnow)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitored_chat_id: Mapped[int] = mapped_column(ForeignKey("monitored_chats.id"), index=True)
    tg_message_id: Mapped[int]
    tg_user_id: Mapped[int] = mapped_column(index=True)
    tg_username: Mapped[str | None]
    tg_first_name: Mapped[str | None]
    message_text: Mapped[str]
    relevance_reason: Mapped[str]
    found_at: Mapped[datetime] = mapped_column(default=utcnow)
    notified_at: Mapped[datetime | None]

    __table_args__ = (UniqueConstraint("monitored_chat_id", "tg_message_id"),)


class DiscoveredChat(Base):
    __tablename__ = "discovered_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int | None] = mapped_column(unique=True)
    username: Mapped[str | None] = mapped_column(unique=True)
    title: Mapped[str | None]
    link: Mapped[str]
    provider: Mapped[DiscoveryProvider]
    status: Mapped[DiscoveryStatus] = mapped_column(default=DiscoveryStatus.pending)
    relevance_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    evaluated_at: Mapped[datetime | None]


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_text: Mapped[str] = mapped_column(unique=True)
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_run_at: Mapped[datetime | None]


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    topics: Mapped[str | None]
    language: Mapped[str | None]
    html_url: Mapped[str]
    synced_at: Mapped[datetime] = mapped_column(default=utcnow)
