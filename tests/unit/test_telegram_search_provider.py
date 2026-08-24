from typing import Any

import pytest
from telethon.errors import RPCError
from telethon.tl.types import Channel, Chat, User

from app.db.models import DiscoveryProvider
from app.discovery.providers.telegram_search import (
    TelethonGlobalSearchProvider,
    build_chat_link,
)
from app.telethon_client.client import ResolvedChat
from app.telethon_client.search import (
    TelethonGlobalSearch,
    collect_public_chats,
    is_public_source_chat,
)


def make_channel(
    *,
    channel_id: int = 1234,
    username: str | None = "python_jobs",
    megagroup: bool = True,
    broadcast: bool = False,
    title: str = "Python Jobs",
) -> Channel:
    return Channel(
        id=channel_id,
        title=title,
        photo=None,
        date=None,
        access_hash=999,
        username=username,
        megagroup=megagroup,
        broadcast=broadcast,
    )


class SearchResponse:
    def __init__(self, chats: Any) -> None:
        self.chats = chats


class FakeTelethonClient:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeGlobalSearch:
    def __init__(self, chats: list[ResolvedChat]) -> None:
        self._chats = chats
        self.queries: list[tuple[str, int]] = []

    async def search_chats(self, query: str, limit: int) -> list[ResolvedChat]:
        self.queries.append((query, limit))
        return list(self._chats)


def test_public_megagroup_and_broadcast_pass_the_filter() -> None:
    assert is_public_source_chat(make_channel()) is True
    assert is_public_source_chat(make_channel(megagroup=False, broadcast=True)) is True


@pytest.mark.parametrize(
    "chat",
    [
        make_channel(username=None),
        make_channel(megagroup=False, broadcast=False),
        Chat(id=1, title="Приватная группа", photo=None, participants_count=3, date=None, version=1),
        User(id=1, first_name="Человек"),
        "мусор",
    ],
)
def test_private_and_foreign_entities_are_filtered_out(chat: Any) -> None:
    assert is_public_source_chat(chat) is False


def test_collect_public_chats_tolerates_non_list_payload() -> None:
    assert collect_public_chats(None) == []
    assert collect_public_chats("мусор") == []


async def test_search_maps_response_chats_into_resolved_chats() -> None:
    client = FakeTelethonClient(SearchResponse([make_channel(), make_channel(username=None)]))

    chats = await TelethonGlobalSearch(client).search_chats("заказ бот", limit=25)

    assert len(chats) == 1
    assert chats[0].username == "python_jobs"
    assert chats[0].title == "Python Jobs"
    assert chats[0].tg_chat_id == -1000000001234
    assert client.requests[0].q == "заказ бот"
    assert client.requests[0].limit == 25


async def test_rpc_error_degrades_to_empty_result() -> None:
    client = FakeTelethonClient(RPCError("request", "FLOOD_WAIT"))

    assert await TelethonGlobalSearch(client).search_chats("заказ бот", limit=10) == []


async def test_response_without_chats_field_is_safe() -> None:
    client = FakeTelethonClient(object())

    assert await TelethonGlobalSearch(client).search_chats("заказ бот", limit=10) == []


async def test_provider_maps_chats_into_candidates() -> None:
    search = FakeGlobalSearch(
        [ResolvedChat(tg_chat_id=-1001, access_hash=7, title="Python Jobs", username="python_jobs")]
    )

    candidates = await TelethonGlobalSearchProvider(search, limit=30).search("заказ бот")

    assert search.queries == [("заказ бот", 30)]
    assert len(candidates) == 1
    assert candidates[0].provider is DiscoveryProvider.telethon_search
    assert candidates[0].username == "python_jobs"
    assert candidates[0].tg_chat_id == -1001
    assert candidates[0].link == "https://t.me/python_jobs"
    assert candidates[0].dedupe_key() == "python_jobs"


def test_link_falls_back_to_internal_form_without_username() -> None:
    assert build_chat_link(None, -1001234) == "https://t.me/c/1001234"
