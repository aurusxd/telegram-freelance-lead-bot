import json
from typing import Any, Protocol

import httpx
from loguru import logger

REQUEST_TIMEOUT_SECONDS = 60.0
COMPLETIONS_PATH = "/chat/completions"
RESPONSE_TEMPERATURE = 0.2


class LlmRequestError(Exception):
    pass


class LlmClient(Protocol):
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str: ...


def build_payload(model: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": RESPONSE_TEMPERATURE,
        "stream": False,
    }


def extract_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise LlmRequestError("deepseek response is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmRequestError("deepseek response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LlmRequestError("deepseek response has empty content")
    return content


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.deepseek.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._transport = transport

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            return await self._request_completion(client, system_prompt, user_prompt)

    async def _request_completion(
        self,
        client: httpx.AsyncClient,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        try:
            response = await client.post(
                COMPLETIONS_PATH,
                json=build_payload(self._model, system_prompt, user_prompt),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("deepseek request failed: {}", type(error).__name__)
            raise LlmRequestError(type(error).__name__) from error
        return extract_content(payload)


class FakeDeepSeekClient:
    def __init__(self, *, is_relevant: bool = False) -> None:
        self._is_relevant = is_relevant

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return json.dumps(
            {
                "is_relevant": self._is_relevant,
                "reason": "фейковый клиент, реальная оценка не выполнялась",
                "confidence": 0.5,
            },
            ensure_ascii=False,
        )
