from dataclasses import dataclass

from app.db.models import DiscoveryProvider


@dataclass(frozen=True)
class DiscoveredSourceCandidate:
    provider: DiscoveryProvider
    username: str | None
    tg_chat_id: int | None
    title: str | None
    link: str
    raw_snippet: str | None

    def dedupe_key(self) -> str:
        if self.username:
            return self.username.removeprefix("@").strip().lower()
        if self.tg_chat_id is not None:
            return str(self.tg_chat_id)
        return normalize_link(self.link)


def normalize_link(link: str) -> str:
    stripped = link.strip().lower()
    for prefix in ("https://", "http://", "tg://", "www."):
        stripped = stripped.removeprefix(prefix)
    stripped = stripped.removeprefix("www.")
    return stripped.rstrip("/")
