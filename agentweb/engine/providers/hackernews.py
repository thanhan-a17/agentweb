"""Hacker News search provider."""

from dataclasses import dataclass

from agentweb.core import SearchResult, _search_hn_algolia
from agentweb.engine.providers import SearchProvider


@dataclass
class HackerNewsSearchProvider(SearchProvider):
    name: str = "hackernews"
    avg_latency_s: float = 0.3
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        return _search_hn_algolia(query, max_results, timeout)
