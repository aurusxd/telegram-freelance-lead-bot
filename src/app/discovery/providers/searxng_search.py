from app.db.models import DiscoveryProvider
from app.discovery.candidate import DiscoveredSourceCandidate

SEED_CANDIDATES = (
    DiscoveredSourceCandidate(
        provider=DiscoveryProvider.searxng,
        username="python_jobs_seed",
        tg_chat_id=None,
        title="Python Jobs (seed)",
        link="https://t.me/python_jobs_seed",
        raw_snippet="Вакансии и заказы для python-разработчиков",
    ),
    DiscoveredSourceCandidate(
        provider=DiscoveryProvider.searxng,
        username="freelance_it_seed",
        tg_chat_id=None,
        title="Freelance IT (seed)",
        link="https://t.me/freelance_it_seed",
        raw_snippet="Заказы на разработку ботов и парсеров",
    ),
)


class FakeSearxngProvider:
    async def search(self, query: str) -> list[DiscoveredSourceCandidate]:
        del query
        return list(SEED_CANDIDATES)
