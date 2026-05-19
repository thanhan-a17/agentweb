"""Jina Reader search provider."""

from dataclasses import dataclass

from agentweb.core import (
    SearchResult,
    _search_jina_general,
    _search_via_jina_reader,
)
from agentweb.engine.providers import SearchProvider


@dataclass
class JinaSearchProvider(SearchProvider):
    name: str = "jina"
    avg_latency_s: float = 3.0
    max_timeout_s: float = 5.0
    weight: float = 1.0
    requires_auth: bool = False

    def search(self, query: str, max_results: int, timeout: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()

        for fn in (_search_via_jina_reader, _search_jina_general):
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
