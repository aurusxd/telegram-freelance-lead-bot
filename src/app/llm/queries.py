import json

from pydantic import BaseModel, ValidationError, field_validator

MIN_QUERIES = 3
MAX_QUERIES = 10

QUERIES_SYSTEM_PROMPT = (
    "Ты помощник фриланс-разработчика. По портфолио владельца составь поисковые запросы, "
    "по которым можно найти телеграм-чаты и каналы с заказами на разработку под этот профиль. "
    "Запросы короткие, на русском, без операторов поиска и без слова telegram. "
    'Ответь строго JSON-объектом вида {"queries": ["..."]}, от 3 до 10 непустых запросов '
    "без повторов."
)


class GeneratedQueries(BaseModel):
    queries: list[str]

    @field_validator("queries")
    @classmethod
    def normalize_queries(cls, value: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for query in value:
            normalized = query.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        if len(unique) < MIN_QUERIES:
            raise ValueError(f"expected at least {MIN_QUERIES} distinct queries")
        return unique[:MAX_QUERIES]


def build_queries_prompt(portfolio_summary: str, limit: int) -> str:
    return (
        f"Портфолио владельца:\n{portfolio_summary}\n\n"
        f"Нужно {min(max(limit, MIN_QUERIES), MAX_QUERIES)} поисковых запросов."
    )


def try_parse_queries(raw_response: str) -> GeneratedQueries | None:
    try:
        return GeneratedQueries.model_validate_json(raw_response)
    except ValidationError:
        return try_parse_embedded_queries(raw_response)


def try_parse_embedded_queries(raw_response: str) -> GeneratedQueries | None:
    start = raw_response.find("{")
    end = raw_response.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return GeneratedQueries.model_validate(json.loads(raw_response[start : end + 1]))
    except (json.JSONDecodeError, ValidationError):
        return None
