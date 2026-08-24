import json

from loguru import logger
from pydantic import BaseModel, ValidationError, field_validator

from app.llm.deepseek_client import LlmClient, LlmRequestError

MAX_LLM_ATTEMPTS = 2
MAX_REASON_LENGTH = 200
MAX_MESSAGE_CONTEXT_CHARS = 4000

MESSAGE_SYSTEM_PROMPT = (
    "Ты помощник фриланс-разработчика. По тексту сообщения из телеграм-чата определи, "
    "ищет ли автор исполнителя на разработку, подходящую под портфолио владельца. "
    "Релевантно только прямое или явно подразумеваемое предложение работы или заказа. "
    "Обсуждение технологий, вопросы новичков, оффтоп и резюме других исполнителей — нерелевантно. "
    "Ответь строго JSON-объектом с полями is_relevant (bool), reason (строка до 200 символов "
    "по-русски), confidence (число от 0 до 1)."
)

CHAT_SYSTEM_PROMPT = (
    "Ты помощник фриланс-разработчика. По последним сообщениям телеграм-чата определи, "
    "публикуются ли в нём заказы на разработку, подходящие под портфолио владельца. "
    "Ответь строго JSON-объектом с полями is_relevant (bool), reason (строка до 200 символов "
    "по-русски), confidence (число от 0 до 1)."
)


class RelevanceVerdict(BaseModel):
    is_relevant: bool
    reason: str
    confidence: float

    @field_validator("reason")
    @classmethod
    def truncate_reason(cls, value: str) -> str:
        return value.strip()[:MAX_REASON_LENGTH]

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return min(max(value, 0.0), 1.0)


IRRELEVANT_ON_PARSE_FAILURE = RelevanceVerdict(
    is_relevant=False,
    reason="ответ модели не разобран, сообщение пропущено",
    confidence=0.0,
)


def truncate_context(text: str) -> str:
    return text[:MAX_MESSAGE_CONTEXT_CHARS]


def build_message_prompt(message_text: str, portfolio_summary: str) -> str:
    return (
        f"Портфолио владельца:\n{portfolio_summary}\n\n"
        f"Сообщение из чата:\n{truncate_context(message_text)}"
    )


def build_chat_prompt(chat_context: str, portfolio_summary: str) -> str:
    return (
        f"Портфолио владельца:\n{portfolio_summary}\n\n"
        f"Последние сообщения чата:\n{truncate_context(chat_context)}"
    )


def try_parse_verdict(raw_response: str) -> RelevanceVerdict | None:
    try:
        return RelevanceVerdict.model_validate_json(raw_response)
    except ValidationError:
        return try_parse_embedded_verdict(raw_response)


def try_parse_embedded_verdict(raw_response: str) -> RelevanceVerdict | None:
    start = raw_response.find("{")
    end = raw_response.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return RelevanceVerdict.model_validate(json.loads(raw_response[start : end + 1]))
    except (json.JSONDecodeError, ValidationError):
        return None


class RelevanceChecker:
    def __init__(self, client: LlmClient) -> None:
        self._client = client

    async def evaluate_message(self, message_text: str, portfolio_summary: str) -> RelevanceVerdict:
        return await self._evaluate(
            MESSAGE_SYSTEM_PROMPT,
            build_message_prompt(message_text, portfolio_summary),
        )

    async def evaluate_chat(self, chat_context: str, portfolio_summary: str) -> RelevanceVerdict:
        return await self._evaluate(
            CHAT_SYSTEM_PROMPT,
            build_chat_prompt(chat_context, portfolio_summary),
        )

    async def _evaluate(self, system_prompt: str, user_prompt: str) -> RelevanceVerdict:
        for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
            verdict = await self._try_single_attempt(system_prompt, user_prompt)
            if verdict is not None:
                return verdict
            logger.warning("llm attempt {} of {} produced no verdict", attempt, MAX_LLM_ATTEMPTS)
        return IRRELEVANT_ON_PARSE_FAILURE

    async def _try_single_attempt(
        self, system_prompt: str, user_prompt: str
    ) -> RelevanceVerdict | None:
        try:
            raw_response = await self._client.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except LlmRequestError:
            return None
        return try_parse_verdict(raw_response)
