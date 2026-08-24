import pytest

from app.llm.deepseek_client import LlmRequestError
from app.llm.relevance import (
    IRRELEVANT_ON_PARSE_FAILURE,
    MAX_LLM_ATTEMPTS,
    RelevanceChecker,
    RelevanceVerdict,
    try_parse_verdict,
)

VALID_VERDICT = '{"is_relevant": true, "reason": "прямой заказ на бота", "confidence": 0.9}'
PORTFOLIO = "Портфолио: python, telegram-боты"


class ScriptedLlm:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


async def test_valid_response_needs_a_single_call() -> None:
    llm = ScriptedLlm([VALID_VERDICT])

    verdict = await RelevanceChecker(llm).evaluate_message("ищу разработчика", PORTFOLIO)

    assert verdict.is_relevant is True
    assert verdict.reason == "прямой заказ на бота"
    assert llm.calls == 1


async def test_unparsable_response_is_retried_once_and_then_succeeds() -> None:
    llm = ScriptedLlm(["модель заболталась", VALID_VERDICT])

    verdict = await RelevanceChecker(llm).evaluate_message("ищу разработчика", PORTFOLIO)

    assert verdict.is_relevant is True
    assert llm.calls == 2


async def test_request_error_is_retried_once_and_then_succeeds() -> None:
    llm = ScriptedLlm([LlmRequestError("ReadTimeout"), VALID_VERDICT])

    verdict = await RelevanceChecker(llm).evaluate_message("ищу разработчика", PORTFOLIO)

    assert verdict.is_relevant is True
    assert llm.calls == 2


async def test_two_failures_degrade_to_irrelevant_without_extra_calls() -> None:
    llm = ScriptedLlm(["мусор", "снова мусор", VALID_VERDICT])

    verdict = await RelevanceChecker(llm).evaluate_message("ищу разработчика", PORTFOLIO)

    assert verdict == IRRELEVANT_ON_PARSE_FAILURE
    assert verdict.is_relevant is False
    assert llm.calls == MAX_LLM_ATTEMPTS


async def test_persistent_request_error_does_not_crash_the_caller() -> None:
    llm = ScriptedLlm([LlmRequestError("ConnectError")])

    verdict = await RelevanceChecker(llm).evaluate_message("ищу разработчика", PORTFOLIO)

    assert verdict.is_relevant is False
    assert llm.calls == MAX_LLM_ATTEMPTS


def test_verdict_wrapped_in_prose_is_recovered() -> None:
    verdict = try_parse_verdict(f"Вот ответ:\n```json\n{VALID_VERDICT}\n```")

    assert verdict is not None
    assert verdict.is_relevant is True


@pytest.mark.parametrize(
    "raw",
    ["", "просто текст", "{}", '{"is_relevant": "да"}', "[1, 2, 3]"],
)
def test_unparsable_payloads_return_none(raw: str) -> None:
    assert try_parse_verdict(raw) is None


def test_reason_is_truncated_to_contract_length() -> None:
    verdict = RelevanceVerdict(is_relevant=True, reason="я" * 500, confidence=0.5)

    assert len(verdict.reason) == 200


@pytest.mark.parametrize(
    ("raw_confidence", "expected"),
    [(1.7, 1.0), (-0.4, 0.0), (0.42, 0.42)],
)
def test_confidence_is_clamped(raw_confidence: float, expected: float) -> None:
    verdict = RelevanceVerdict(is_relevant=True, reason="ок", confidence=raw_confidence)

    assert verdict.confidence == expected
