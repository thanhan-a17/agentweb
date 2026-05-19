"""DuckDuckGo search provider."""

from dataclasses import dataclass

from agentweb.core import SearchResult, _search_duckduckgo
from agentweb.engine.providers import SearchProvider


@dataclass
class DuckDuckGoSearchProvider(SearchProvider):
    name: str = "duckduckgo"
    avg_latency_s: float = 0.4
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        return _search_duckduckgo(query, max_results, timeout)
