"""General search provider — aggregates DuckDuckGo, HN, Reddit, and StackExchange."""

from dataclasses import dataclass

from agentweb.core import (
    SearchResult,
    _search_duckduckgo,
    _search_hn_algolia,
    _search_reddit_api,
    _search_stackexchange_api,
)
from agentweb.engine.providers import SearchProvider


@dataclass
class GeneralSearchProvider(SearchProvider):
    name: str = "general"
    avg_latency_s: float = 0.5
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()

        for fn in (
            _search_duckduckgo,
            _search_hn_algolia,
            _search_reddit_api,
            _search_stackexchange_api,
        ):
            try:
                for item in fn(query, max_results, timeout):
                    if item.url not in seen:
                        seen.add(item.url)
                        results.append(item)
            except Exception:
                continue
            if len(results) >= max_results:
                break

        return results[:max_results]
