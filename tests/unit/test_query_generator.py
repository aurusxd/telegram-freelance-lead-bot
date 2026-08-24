import pytest

from app.discovery.query_generator import QueryGenerator
from app.llm.deepseek_client import LlmRequestError
from app.llm.queries import MAX_QUERIES, GeneratedQueries, build_queries_prompt, try_parse_queries

VALID = '{"queries": ["заказы боты", "нужен парсер", "фриланс python"]}'


class ScriptedLlm:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = responses
        self.calls = 0
        self.prompts: list[str] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        self.prompts.append(user_prompt)
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


async def test_valid_response_yields_queries() -> None:
    llm = ScriptedLlm([VALID])

    queries = await QueryGenerator(llm).generate("портфолио", limit=5)

    assert queries == ["заказы боты", "нужен парсер", "фриланс python"]
    assert llm.calls == 1


async def test_limit_caps_the_returned_queries() -> None:
    queries = await QueryGenerator(ScriptedLlm([VALID])).generate("портфолио", limit=2)

    assert len(queries) == 2


async def test_unparsable_response_is_retried_once() -> None:
    llm = ScriptedLlm(["не json", VALID])

    queries = await QueryGenerator(llm).generate("портфолио", limit=5)

    assert len(queries) == 3
    assert llm.calls == 2


async def test_two_failures_degrade_to_no_queries() -> None:
    llm = ScriptedLlm(["мусор"])

    assert await QueryGenerator(llm).generate("портфолио", limit=5) == []
    assert llm.calls == 2


async def test_request_error_degrades_without_crash() -> None:
    llm = ScriptedLlm([LlmRequestError("ReadTimeout")])

    assert await QueryGenerator(llm).generate("портфолио", limit=5) == []


async def test_prompt_carries_portfolio_summary() -> None:
    llm = ScriptedLlm([VALID])

    await QueryGenerator(llm).generate("Репозитории владельца: бот, парсер", limit=5)

    assert "Репозитории владельца: бот, парсер" in llm.prompts[0]


def test_duplicates_and_blanks_are_normalized() -> None:
    parsed = try_parse_queries('{"queries": ["Заказы", " заказы ", "", "парсер", "боты"]}')

    assert parsed is not None
    assert parsed.queries == ["Заказы", "парсер", "боты"]


def test_too_few_distinct_queries_are_rejected() -> None:
    assert try_parse_queries('{"queries": ["один", "один", "два"]}') is None


def test_overlong_list_is_capped_by_contract() -> None:
    payload = ", ".join(f'"запрос {index}"' for index in range(20))
    parsed = try_parse_queries(f'{{"queries": [{payload}]}}')

    assert parsed is not None
    assert len(parsed.queries) == MAX_QUERIES


@pytest.mark.parametrize("raw", ["", "текст", "{}", '{"queries": "строка"}', "[1,2,3]"])
def test_malformed_payloads_return_none(raw: str) -> None:
    assert try_parse_queries(raw) is None


def test_queries_model_rejects_short_list_directly() -> None:
    with pytest.raises(ValueError, match="at least"):
        GeneratedQueries(queries=["мало", "запросов"])


def test_prompt_clamps_requested_amount() -> None:
    assert "3 поисковых запросов" in build_queries_prompt("портфолио", 1)
    assert "10 поисковых запросов" in build_queries_prompt("портфолио", 99)
