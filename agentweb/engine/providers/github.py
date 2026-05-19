"""GitHub search provider."""

from dataclasses import dataclass

from agentweb.core import SearchResult, _search_github_api
from agentweb.engine.providers import SearchProvider


@dataclass
class GitHubSearchProvider(SearchProvider):
    name: str = "github"
    avg_latency_s: float = 0.2
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        return _search_github_api(query, max_results, timeout)
