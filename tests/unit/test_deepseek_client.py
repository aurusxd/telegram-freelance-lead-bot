import json
from typing import Any

import httpx
import pytest

from app.llm.deepseek_client import (
    COMPLETIONS_PATH,
    DeepSeekClient,
    LlmRequestError,
    build_payload,
)

API_KEY = "test-key"
MODEL = "deepseek-chat"
VERDICT_JSON = '{"is_relevant": true, "reason": "заказ на бота", "confidence": 0.8}'


def completion_response(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def build_client(handler: Any) -> DeepSeekClient:
    return DeepSeekClient(
        API_KEY, MODEL, base_url="https://api.deepseek.test", transport=httpx.MockTransport(handler)
    )


async def test_sends_json_object_request_and_returns_content() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion_response(VERDICT_JSON))

    content = await build_client(handler).complete_json(
        system_prompt="системный промпт", user_prompt="сообщение из чата"
    )

    assert content == VERDICT_JSON
    assert captured["path"] == COMPLETIONS_PATH
    assert captured["auth"] == f"Bearer {API_KEY}"
    assert captured["body"]["model"] == MODEL
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0] == {
        "role": "system",
        "content": "системный промпт",
    }
    assert captured["body"]["messages"][1] == {"role": "user", "content": "сообщение из чата"}


async def test_http_error_raises_llm_request_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, json={"error": "server"})

    with pytest.raises(LlmRequestError):
        await build_client(handler).complete_json(system_prompt="s", user_prompt="u")


async def test_timeout_raises_llm_request_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(LlmRequestError):
        await build_client(handler).complete_json(system_prompt="s", user_prompt="u")


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": ["мусор"]},
        {"unexpected": "shape"},
        ["не объект"],
    ],
)
async def test_malformed_response_raises_llm_request_error(payload: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=payload)

    with pytest.raises(LlmRequestError):
        await build_client(handler).complete_json(system_prompt="s", user_prompt="u")


def test_payload_never_carries_the_api_key() -> None:
    payload = build_payload(MODEL, "system", "user")

    assert API_KEY not in json.dumps(payload)
