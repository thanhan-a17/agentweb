"""Twitter/X search provider."""

from dataclasses import dataclass

from agentweb.core import SearchResult, _search_twitter_site
from agentweb.engine.providers import SearchProvider


@dataclass
class TwitterSearchProvider(SearchProvider):
    name: str = "twitter"
    avg_latency_s: float = 3.0
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        return _search_twitter_site(query, max_results, timeout)
