from typing import Any

import httpx

from app.portfolio.github_client import GithubApiClient, build_auth_headers

USERNAME = "aurusxd"
TOKEN = "test-token"


def repo_payload(name: str, *, fork: bool = False, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "description": f"описание {name}",
        "topics": ["python", "telegram"],
        "language": "Python",
        "html_url": f"https://github.com/{USERNAME}/{name}",
        "fork": fork,
    }
    payload.update(overrides)
    return payload


def build_client(handler: Any) -> GithubApiClient:
    return GithubApiClient(
        USERNAME, TOKEN, base_url="https://api.github.test", transport=httpx.MockTransport(handler)
    )


async def test_maps_repos_into_contract_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/users/{USERNAME}/repos"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json=[repo_payload("lead-bot")])

    repos = await build_client(handler).list_repos()

    assert len(repos) == 1
    assert repos[0].name == "lead-bot"
    assert repos[0].topics == ["python", "telegram"]
    assert repos[0].language == "Python"
    assert repos[0].html_url == f"https://github.com/{USERNAME}/lead-bot"


async def test_skips_forks_and_malformed_entries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[
                repo_payload("own-repo"),
                repo_payload("forked-repo", fork=True),
                {"description": "без имени и ссылки"},
                "мусорная строка",
            ],
        )

    repos = await build_client(handler).list_repos()

    assert [repo.name for repo in repos] == ["own-repo"]


async def test_tolerates_null_description_and_topics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200, json=[repo_payload("bare", description=None, topics=None, language=None)]
        )

    repos = await build_client(handler).list_repos()

    assert repos[0].description is None
    assert repos[0].topics == []
    assert repos[0].language is None


async def test_follows_pagination_until_short_page() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 1:
            return httpx.Response(200, json=[repo_payload(f"repo-{index}") for index in range(100)])
        return httpx.Response(200, json=[repo_payload("last-repo")])

    repos = await build_client(handler).list_repos()

    assert pages == [1, 2]
    assert len(repos) == 101


async def test_http_error_degrades_to_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(401, json={"message": "Bad credentials"})

    assert await build_client(handler).list_repos() == []


async def test_timeout_degrades_to_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    assert await build_client(handler).list_repos() == []


async def test_missing_username_skips_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise AssertionError("request must not be sent without username")

    client = GithubApiClient("", TOKEN, transport=httpx.MockTransport(handler))

    assert await client.list_repos() == []


def test_auth_header_omitted_without_token() -> None:
    assert "Authorization" not in build_auth_headers("")
    assert build_auth_headers(TOKEN)["Authorization"] == f"Bearer {TOKEN}"
