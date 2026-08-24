import json
from typing import Protocol


class LlmClient(Protocol):
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str: ...


class FakeDeepSeekClient:
    def __init__(self, *, is_relevant: bool = True) -> None:
        self._is_relevant = is_relevant

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return json.dumps(
            {
                "is_relevant": self._is_relevant,
                "reason": "фейковый клиент стадии 1, реальная оценка не выполнялась",
                "confidence": 0.5,
            },
            ensure_ascii=False,
        )
