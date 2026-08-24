from hypothesis import given
from hypothesis import strategies as st

from app.db.models import DiscoveryProvider
from app.discovery.candidate import DiscoveredSourceCandidate
from app.discovery.pipeline import deduplicate_candidates


def make_candidate(
    username: str | None = None,
    tg_chat_id: int | None = None,
    link: str = "https://t.me/some_chat",
) -> DiscoveredSourceCandidate:
    return DiscoveredSourceCandidate(
        provider=DiscoveryProvider.searxng,
        username=username,
        tg_chat_id=tg_chat_id,
        title=None,
        link=link,
        raw_snippet=None,
    )


@given(st.text())
def test_dedupe_key_is_deterministic_on_any_input(raw: str) -> None:
    candidate = make_candidate(link=raw)
    assert candidate.dedupe_key() == candidate.dedupe_key()


telegram_usernames = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"),
    min_size=5,
    max_size=32,
)


@given(telegram_usernames)
def test_dedupe_key_is_case_insensitive_for_username(username: str) -> None:
    assert make_candidate(username=username).dedupe_key() == (
        make_candidate(username=username.upper()).dedupe_key()
    )


def test_username_wins_over_chat_id_and_link() -> None:
    candidate = make_candidate(username="@Some_Chat", tg_chat_id=-1001)
    assert candidate.dedupe_key() == "some_chat"


def test_chat_id_used_when_username_absent() -> None:
    assert make_candidate(tg_chat_id=-1001).dedupe_key() == "-1001"


def test_link_normalized_when_username_and_chat_id_absent() -> None:
    assert make_candidate(link="HTTPS://T.ME/Some_Chat/").dedupe_key() == "t.me/some_chat"


def test_same_chat_from_two_providers_collapses_into_one() -> None:
    telethon_candidate = DiscoveredSourceCandidate(
        provider=DiscoveryProvider.telethon_search,
        username="Python_Jobs",
        tg_chat_id=-1001,
        title="Python Jobs",
        link="https://t.me/Python_Jobs",
        raw_snippet=None,
    )
    searxng_candidate = make_candidate(username="python_jobs", link="https://t.me/python_jobs")

    unique = deduplicate_candidates([telethon_candidate, searxng_candidate])

    assert len(unique) == 1
    assert unique[0].provider is DiscoveryProvider.telethon_search
