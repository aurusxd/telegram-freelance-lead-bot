from app.db.models import DiscoveryProvider
from app.discovery.candidate import DiscoveredSourceCandidate
from app.telethon_client.client import ResolvedChat
from app.telethon_client.search import DEFAULT_SEARCH_LIMIT, GlobalChatSearch


def build_chat_link(username: str | None, tg_chat_id: int) -> str:
    if username:
        return f"https://t.me/{username.removeprefix('@')}"
    return f"https://t.me/c/{abs(tg_chat_id)}"


def to_candidate(chat: ResolvedChat) -> DiscoveredSourceCandidate:
    return DiscoveredSourceCandidate(
        provider=DiscoveryProvider.telethon_search,
        username=chat.username,
        tg_chat_id=chat.tg_chat_id,
        title=chat.title,
        link=build_chat_link(chat.username, chat.tg_chat_id),
        raw_snippet=None,
    )


class TelethonGlobalSearchProvider:
    def __init__(self, search: GlobalChatSearch, limit: int = DEFAULT_SEARCH_LIMIT) -> None:
        self._search = search
        self._limit = limit

    async def search(self, query: str) -> list[DiscoveredSourceCandidate]:
        chats = await self._search.search_chats(query, self._limit)
        return [to_candidate(chat) for chat in chats]
