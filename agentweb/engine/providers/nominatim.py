"""Nominatim (OpenStreetMap) search provider."""

from dataclasses import dataclass

from agentweb.core import SearchResult, _search_nominatim
from agentweb.engine.providers import SearchProvider


@dataclass
class NominatimSearchProvider(SearchProvider):
    name: str = "nominatim"
    avg_latency_s: float = 0.3
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        return _search_nominatim(query, max_results, timeout)
