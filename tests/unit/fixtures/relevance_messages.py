from dataclasses import dataclass
from enum import Enum


class RelevanceCaseKind(str, Enum):
    clearly_relevant = "clearly_relevant"
    clearly_irrelevant = "clearly_irrelevant"
    borderline = "borderline"
    garbage = "garbage"


@dataclass(frozen=True)
class RelevanceCase:
    text: str
    expected_relevant: bool
    kind: RelevanceCaseKind
    description: str


LONG_ORDER_TEXT = (
    "Ищу python-разработчика на телеграм-бота с оплатой по этапам. "
    + "Далее подробное описание проекта. " * 300
)

MESSAGE_CASES: tuple[RelevanceCase, ...] = (
    RelevanceCase(
        text="Ищу разработчика для Telegram-бота на Python, бюджет 50 000, детали в личке",
        expected_relevant=True,
        kind=RelevanceCaseKind.clearly_relevant,
        description="прямой заказ на бота, стек совпадает с портфолио",
    ),
    RelevanceCase(
        text="Нужен парсер данных с маркетплейса, есть бюджет, готов обсудить сроки",
        expected_relevant=True,
        kind=RelevanceCaseKind.clearly_relevant,
        description="прямой заказ на парсер, стек совпадает с портфолио",
    ),
    RelevanceCase(
        text="Требуется доработать бота на aiogram, оплата почасовая, работы на месяц",
        expected_relevant=True,
        kind=RelevanceCaseKind.clearly_relevant,
        description="заказ на доработку существующего проекта",
    ),
    RelevanceCase(
        text="Кто идёт на созвон в 15:00?",
        expected_relevant=False,
        kind=RelevanceCaseKind.clearly_irrelevant,
        description="организационный шум чата",
    ),
    RelevanceCase(
        text="мемчик про питон топ, ржу второй день",
        expected_relevant=False,
        kind=RelevanceCaseKind.clearly_irrelevant,
        description="оффтоп с упоминанием технологии",
    ),
    RelevanceCase(
        text="Всем привет, я новичок, с чего начать учить питон?",
        expected_relevant=False,
        kind=RelevanceCaseKind.clearly_irrelevant,
        description="вопрос новичка, не заказ",
    ),
    RelevanceCase(
        text="Я python-разработчик, ищу проекты, вот моё резюме и портфолио",
        expected_relevant=False,
        kind=RelevanceCaseKind.clearly_irrelevant,
        description="резюме другого исполнителя, спрос не на разработчика",
    ),
    RelevanceCase(
        text="У меня есть скрипт на Python, который парсит цены, работает нормально",
        expected_relevant=False,
        kind=RelevanceCaseKind.borderline,
        description="упоминание разработки без запроса исполнителя",
    ),
    RelevanceCase(
        text="Ищем 1С-программиста на постоянный проект, оплата белая",
        expected_relevant=False,
        kind=RelevanceCaseKind.borderline,
        description="настоящий заказ, но стек вне портфолио",
    ),
    RelevanceCase(
        text="Нужен человек автоматизировать рутину с отчётами, стек обсудим, бюджет есть",
        expected_relevant=True,
        kind=RelevanceCaseKind.borderline,
        description="заказ без явного стека, задача попадает в профиль",
    ),
    RelevanceCase(
        text="",
        expected_relevant=False,
        kind=RelevanceCaseKind.garbage,
        description="пустой текст сообщения",
    ),
    RelevanceCase(
        text="   ",
        expected_relevant=False,
        kind=RelevanceCaseKind.garbage,
        description="только пробелы",
    ),
    RelevanceCase(
        text="🔥🔥🔥",
        expected_relevant=False,
        kind=RelevanceCaseKind.garbage,
        description="только эмодзи",
    ),
    RelevanceCase(
        text=LONG_ORDER_TEXT,
        expected_relevant=True,
        kind=RelevanceCaseKind.garbage,
        description="релевантный заказ в тексте длиннее границы обрезки контекста",
    ),
)

CHAT_CASES: tuple[RelevanceCase, ...] = (
    RelevanceCase(
        text=(
            "Ищу разработчика на телеграм-бота\n"
            "Нужен парсер маркетплейса, бюджет есть\n"
            "Требуется автоматизация отчётов"
        ),
        expected_relevant=True,
        kind=RelevanceCaseKind.clearly_relevant,
        description="чат с потоком заказов по профилю",
    ),
    RelevanceCase(
        text="Доброе утро\nкто на созвон\nмемы\nкупил новую клавиатуру",
        expected_relevant=False,
        kind=RelevanceCaseKind.clearly_irrelevant,
        description="чат бытового общения без заказов",
    ),
    RelevanceCase(
        text="Ищем сварщика вахтой\nтребуется водитель категории С",
        expected_relevant=False,
        kind=RelevanceCaseKind.borderline,
        description="чат вакансий вне ИТ",
    ),
    RelevanceCase(
        text="",
        expected_relevant=False,
        kind=RelevanceCaseKind.garbage,
        description="пустая история чата",
    ),
)


def message_cases_without_empty_text() -> tuple[RelevanceCase, ...]:
    return tuple(case for case in MESSAGE_CASES if case.text.strip())


def empty_text_message_cases() -> tuple[RelevanceCase, ...]:
    return tuple(case for case in MESSAGE_CASES if not case.text.strip())
