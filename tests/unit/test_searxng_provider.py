from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.db.models import DiscoveryProvider
from app.discovery.providers.searxng_search import (
    SearxngProvider,
    build_search_query,
    extract_results,
    parse_tme_username,
)

BASE_URL = "http://searxng.test:8080"


def build_provider(handler: Any, **kwargs: Any) -> SearxngProvider:
    return SearxngProvider(BASE_URL, transport=httpx.MockTransport(handler), **kwargs)


def result(url: str, title: str = "Заголовок", content: str = "Сниппет") -> dict[str, Any]:
    return {"url": url, "title": title, "content": content}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://t.me/python_jobs", "python_jobs"),
        ("http://t.me/Python_Jobs", "python_jobs"),
        ("https://telegram.me/python_jobs", "python_jobs"),
        ("https://www.t.me/python_jobs/", "python_jobs"),
        ("https://t.me/python_jobs/12345", "python_jobs"),
        ("https://t.me/python_jobs?single", "python_jobs"),
    ],
)
def test_public_chat_urls_yield_username(url: str, expected: str) -> None:
    assert parse_tme_username(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://t.me/joinchat/AAAAAE",
        "https://t.me/+abcdefgh",
        "https://t.me/c/1234567890/1",
        "https://t.me/s/python_jobs",
        "https://example.com/python_jobs",
        "https://tme.com/python_jobs",
        "https://t.me/",
        "https://t.me/ab",
        "https://t.me/1channel",
        "ftp://t.me/python_jobs",
        "не ссылка вовсе",
        "",
    ],
)
def test_private_and_foreign_urls_yield_nothing(url: str) -> None:
    assert parse_tme_username(url) is None


@given(st.text())
def test_parser_never_raises_on_arbitrary_input(raw: str) -> None:
    parse_tme_username(raw)


@given(st.text())
def test_parser_is_deterministic(raw: str) -> None:
    assert parse_tme_username(raw) == parse_tme_username(raw)


@given(
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"),
        min_size=5,
        max_size=31,
    ).filter(lambda value: value[0].isalpha())
)
def test_username_parsing_is_case_insensitive(username: str) -> None:
    assert parse_tme_username(f"https://t.me/{username}") == username.lower()


def test_query_targets_telegram_domain() -> None:
    assert build_search_query("заказ бота") == "site:t.me заказ бота"


async def test_search_maps_results_into_candidates() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["q"] = request.url.params["q"]
        captured["format"] = request.url.params["format"]
        return httpx.Response(200, json={"results": [result("https://t.me/python_jobs")]})

    candidates = await build_provider(handler).search("заказ бота")

    assert captured["path"] == "/search"
    assert captured["q"] == "site:t.me заказ бота"
    assert captured["format"] == "json"
    assert len(candidates) == 1
    assert candidates[0].provider is DiscoveryProvider.searxng
    assert candidates[0].username == "python_jobs"
    assert candidates[0].tg_chat_id is None
    assert candidates[0].link == "https://t.me/python_jobs"
    assert candidates[0].raw_snippet == "Сниппет"


async def test_non_telegram_results_are_dropped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "results": [
                    result("https://example.com/vacancy"),
                    result("https://t.me/joinchat/SECRET"),
                    result("https://t.me/real_chat"),
                    {"title": "без url"},
                    "мусор",
                ]
            },
        )

    candidates = await build_provider(handler).search("заказ бота")

    assert [candidate.username for candidate in candidates] == ["real_chat"]


async def test_results_are_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"results": [result(f"https://t.me/chat_number_{index}") for index in range(50)]},
        )

    candidates = await build_provider(handler, max_results=5).search("заказ бота")

    assert len(candidates) == 5


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_http_error_degrades_to_empty_list(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json={"error": "boom"})

    assert await build_provider(handler).search("заказ бота") == []


async def test_timeout_degrades_to_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    assert await build_provider(handler).search("заказ бота") == []


@pytest.mark.parametrize("payload", [{"results": "мусор"}, {"other": []}, ["список"], 42])
def test_malformed_payloads_yield_no_results(payload: Any) -> None:
    assert extract_results(payload) == []
