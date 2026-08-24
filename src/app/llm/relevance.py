import json

from loguru import logger
from pydantic import BaseModel, ValidationError, field_validator

from app.llm.deepseek_client import LlmClient

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


def parse_verdict(raw_response: str) -> RelevanceVerdict:
    try:
        return RelevanceVerdict.model_validate_json(raw_response)
    except ValidationError:
        return parse_verdict_from_embedded_json(raw_response)


def parse_verdict_from_embedded_json(raw_response: str) -> RelevanceVerdict:
    start = raw_response.find("{")
    end = raw_response.rfind("}")
    if start == -1 or end <= start:
        logger.warning("llm response has no json object, treating message as irrelevant")
        return IRRELEVANT_ON_PARSE_FAILURE
    try:
        return RelevanceVerdict.model_validate(json.loads(raw_response[start : end + 1]))
    except (json.JSONDecodeError, ValidationError):
        logger.warning("llm response is not a valid verdict, treating message as irrelevant")
        return IRRELEVANT_ON_PARSE_FAILURE


class RelevanceChecker:
    def __init__(self, client: LlmClient) -> None:
        self._client = client

    async def evaluate_message(self, message_text: str, portfolio_summary: str) -> RelevanceVerdict:
        raw_response = await self._client.complete_json(
            system_prompt=MESSAGE_SYSTEM_PROMPT,
            user_prompt=build_message_prompt(message_text, portfolio_summary),
        )
        return parse_verdict(raw_response)

    async def evaluate_chat(self, chat_context: str, portfolio_summary: str) -> RelevanceVerdict:
        raw_response = await self._client.complete_json(
            system_prompt=CHAT_SYSTEM_PROMPT,
            user_prompt=build_chat_prompt(chat_context, portfolio_summary),
        )
        return parse_verdict(raw_response)
