from typing import Protocol

from app.portfolio.github_client import SEED_REPOS, GithubRepo


class PortfolioSummarySource(Protocol):
    def build_summary(self) -> str: ...


def format_repo_line(repo: GithubRepo) -> str:
    topics = ", ".join(repo.topics) if repo.topics else "без топиков"
    description = repo.description or "без описания"
    return f"- {repo.name} ({repo.language or 'язык не указан'}): {description}; топики: {topics}"


def build_summary_from_repos(repos: list[GithubRepo]) -> str:
    if not repos:
        return "Портфолио пустое, оценивай по общему профилю python-разработчика."
    lines = [format_repo_line(repo) for repo in repos]
    return "Репозитории владельца:\n" + "\n".join(lines)


class SeedPortfolioSummary:
    def build_summary(self) -> str:
        return build_summary_from_repos(list(SEED_REPOS))
