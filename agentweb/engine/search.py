"""AgentWeb search orchestration.

search_providers() replaces core.search_web() as the primary entry point
for executing searches across all registered providers.
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

from agentweb.core import SearchResult, _canonical_url
from agentweb.engine.providers import PROVIDER_REGISTRY
from agentweb.engine.rank import rank_results


def search_providers(
    query: str,
    *,
    max_results: int = 8,
    timeout: int = 20,
    prefer: list[str] | None = None,
    exclude: list[str] | None = None,
    context: Any = None,
) -> list[SearchResult]:
    """Fire ALL registered providers in parallel with short-circuit and diversity ranking.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.
        timeout: Overall timeout per provider (clamped by each provider's max_timeout_s).
        prefer: List of provider names to prefer (run first / weight higher).
        exclude: List of provider names to exclude.
        context: Optional context object (ignored, reserved for future use).

    Returns:
        Deduplicated list of SearchResult items interleaved by source.
    """
    prefer = prefer or []
    exclude = exclude or []
    exclude_lower = {e.lower() for e in exclude}

    providers = [
        p for p in PROVIDER_REGISTRY.values()
        if p.name.lower() not in exclude_lower
    ]

    # Sort so preferred providers run first
    providers.sort(key=lambda p: (0 if p.name in prefer else 1, p.avg_latency_s))

    all_items: list[SearchResult] = []
    seen: set[str] = set()
    providers_completed = 0
    saw_timeout = False

    # Short-circuit thresholds
    _MIN_PROVIDERS = 2
    _MIN_RESULTS = 8

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futs: dict[concurrent.futures.Future, Any] = {}
        for p in providers:
            effective_timeout = int(min(timeout, p.max_timeout_s))
            futs[pool.submit(p.search, query, max_results, effective_timeout)] = p

        for fut in concurrent.futures.as_completed(futs):
            providers_completed += 1
            try:
                for item in fut.result():
                    key = _canonical_url(item.url)
                    if key and key not in seen:
                        seen.add(key)
                        all_items.append(item)
            except Exception as exc:
                exc_name = type(exc).__name__.lower()
                if "timeout" in exc_name or "timed out" in str(exc).lower():
                    saw_timeout = True
                continue

            if providers_completed >= _MIN_PROVIDERS and len(all_items) >= _MIN_RESULTS:
                for f in futs:
                    f.cancel()
                break

    if not all_items:
        from agentweb.errors import NoResults, Timeout
        if saw_timeout:
            raise Timeout(
                f"All search providers timed out for query: {query[:80]}",
                timeout=timeout,
            )
        raise NoResults(
            f"No search results found for query: {query[:80]}",
            query=query,
        )

    # Convert SearchResult → dict for rank_results
    result_dicts = [{
        "title": r.title,
        "url": r.url,
        "snippet": r.snippet,
        "source": r.source,
        "text": "",  # no full text at search stage
    } for r in all_items]

    # Apply two-pass semantic ranking (context augments the ranking query)
    ranked = rank_results(
        query,
        result_dicts,
        prefer=prefer,
        context=context,
        top_n=max_results,
    )

    # Convert back to SearchResult, preserving rank order
    final = []
    for rd in ranked:
        final.append(SearchResult(
            title=rd.get("title", ""),
            url=rd.get("url", ""),
            snippet=rd.get("snippet", ""),
            source=rd.get("source", ""),
        ))
    return final
