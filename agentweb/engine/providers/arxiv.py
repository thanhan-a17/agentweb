"""arXiv search provider."""

from dataclasses import dataclass

from agentweb.core import SearchResult, _search_arxiv_api
from agentweb.engine.providers import SearchProvider


@dataclass
class ArxivSearchProvider(SearchProvider):
    name: str = "arxiv"
    avg_latency_s: float = 5.0
    max_timeout_s: float = 3.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        return _search_arxiv_api(query, max_results, timeout)
