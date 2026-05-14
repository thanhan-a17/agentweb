"""AgentWeb SDK class — high-level wrappers for agent-native use.

Convenience methods that wrap core.py and deep_research.py functions,
return structured dicts with a ``meta`` envelope, and use errors.py for
structured error wrapping.
"""

from __future__ import annotations

import email.utils
import time
from typing import Any, Iterator

import requests

from agentweb import __version__
from agentweb.core import (
    FetchResult,
    SearchResult,
    compute_novelty_scores,
    fetch_url,
    research as _research,
    search_by_provider,
    search_web,
)
from agentweb.deep_research import _deep_research_stream
from agentweb.errors import AgentWebError, NoResults, ValidationError, map_exception


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _build_meta(
    *,
    tool: str,
    results: list[dict[str, Any]] | None = None,
    max_results: int = 0,
) -> dict[str, Any]:
    """Build a meta envelope attached to every SDK result dict.

    Parameters
    ----------
    tool : str
        The SDK tool name (e.g. "search", "fetch", "research", "deep_research").
    results : list[dict] | None
        List of per-item result dicts (used to compute coverage/diversity).
    max_results : int
        The requested max_results for this operation (used to gauge coverage).

    The meta includes ``coverage``, ``knowledge_gaps``, and
    ``source_diversity`` alongside the standard identity fields.
    """
    meta: dict[str, Any] = {
        "api_version": "v1",
        "agent": "AgentWeb",
        "sdk_version": __version__,
        "tool": tool,
        "timestamp": _now(),
        "provenance": "sdk",
    }

    if results is not None:
        total = len(results)
        meta["coverage"] = {
            "returned": total,
            "requested": max_results,
            "pct": round(total / max_results * 100, 1) if max_results else 0.0,
        }
        # Source diversity: count unique source/provider values across results
        sources: set[str] = set()
        for r in results:
            src = r.get("source", "") or r.get("provider", "")
            if src:
                sources.add(src)
        meta["source_diversity"] = len(sources)
        # Knowledge gaps: if we got far fewer results than requested, flag it
        if max_results and total < max_results:
            meta["knowledge_gaps"] = f"returned {total} of {max_results} requested results"
        else:
            meta["knowledge_gaps"] = "none_detected"
    else:
        # Single-result operations (e.g. fetch)
        meta["coverage"] = {"returned": 1, "requested": 1, "pct": 100.0}
        meta["source_diversity"] = 1
        meta["knowledge_gaps"] = "none_detected"

    return meta


def _maybe_wrap(exc: Exception, tool: str = "unknown") -> Exception:
    """Recast common exceptions into AgentWeb error types.

    Checks both exception type (via map_exception) and message text
    for maximum coverage across different request library versions.
    """
    # First check if it's already an AgentWebError.
    if isinstance(exc, AgentWebError):
        return exc

    # Use map_exception for type-based matching (requests exceptions, etc.)
    mapped = map_exception(exc)
    if not isinstance(mapped, AgentWebError) or type(mapped) is AgentWebError:
        # map_exception returns AgentWebError (the base) only as a fallback.
        # Fall through to the message-based checks below for better accuracy.
        pass
    elif isinstance(mapped, (NoResults, ValidationError)):
        # map_exception got a clean match — use it.
        return mapped
    else:
        # For RateLimited, BotBlocked, Timeout, prefer the mapped result
        # (its type-based detection is more reliable than message scanning).
        return mapped

    # Message-based fallback (for exceptions where type detection is ambiguous).
    msg = str(exc)
    msg_lower = msg.lower()
    if "rate" in msg_lower or "429" in msg:
        from agentweb.errors import RateLimited
        return RateLimited(msg)
    if "timeout" in msg_lower or "timed out" in msg_lower or isinstance(exc, requests.exceptions.Timeout):
        from agentweb.errors import Timeout
        return Timeout(msg, timeout=0)
    if "block" in msg_lower or "denied" in msg_lower or "403" in msg:
        from agentweb.errors import BotBlocked
        return BotBlocked(msg)
    if "no result" in msg_lower or "empty" in msg_lower:
        return NoResults(msg, query="")
    if "invalid" in msg_lower or "unsupported" in msg_lower:
        return ValidationError(msg)
    # Type-based checks for request library exceptions (not caught above)
    if isinstance(exc, requests.exceptions.ConnectionError):
        from agentweb.errors import BotBlocked
        return BotBlocked(f"Connection failed: {msg}")
    if isinstance(exc, requests.exceptions.RequestException):
        return AgentWebError(msg, code=tool)
    return AgentWebError(msg, code=tool)


class AgentWeb:
    """High-level SDK for agent-native web access.

    Usage::

        aw = AgentWeb()
        results = aw.search("quantum computing breakthroughs")
        page = aw.fetch("https://example.com")
        pack = aw.research("latest AI benchmarks 2025")
        report = aw.deep_research("compare Python vs Rust performance")
    """

    def __init__(self) -> None:
        """Initialize the AgentWeb SDK."""
        pass

    # ── Search ──────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        max_results: int = 8,
        timeout: int = 20,
        already_knows: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search the web with resilient no-key providers.

        Returns a dict with ``results``, ``query``, and ``meta``.
        """
        try:
            results: list[SearchResult] = search_web(
                query,
                max_results=max_results,
                timeout=timeout,
            )
            result_dicts = [r.to_dict() for r in results]

            # ── TF-IDF novelty scoring against already_knows ──────────
            if already_knows:
                texts = [rd.get("snippet", "") or "" for rd in result_dicts]
                novel_scores = compute_novelty_scores(already_knows, texts)
                for rd, ns in zip(result_dicts, novel_scores):
                    rd["meta"]["novel_score"] = round(ns, 3)
                    if ns < 0.3:
                        rd["meta"]["suppression_reason"] = "already_known"
                # Re-rank by novelty (higher novelty first)
                result_dicts.sort(
                    key=lambda x: x.get("meta", {}).get("novel_score", 1.0),
                    reverse=True,
                )

            return {
                "query": query,
                "results": result_dicts,
                "meta": _build_meta(tool="search", results=result_dicts, max_results=max_results),
            }
        except Exception as exc:
            raise _maybe_wrap(exc, tool="search") from exc

    # ── Fetch ───────────────────────────────────────────────────────────

    def fetch(
        self,
        url: str,
        *,
        timeout: int = 20,
        max_chars: int = 12000,
        cookies: str | None = None,
        headers: dict[str, str] | None = None,
        use_jina: bool = True,
        use_browser: bool = False,
        already_knows: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a single URL with layered extraction tactics.

        Returns a dict with the fetch result fields plus ``meta``.
        """
        try:
            result: FetchResult = fetch_url(
                url,
                timeout=timeout,
                cookies=cookies,
                headers=headers,
                max_chars=max_chars,
                use_jina=use_jina,
                use_browser=use_browser,
            )
            data = result.to_dict(max_chars=max_chars)
            data["meta"] = _build_meta(tool="fetch", results=[data], max_results=1)

            # ── TF-IDF novelty scoring against already_knows ──────────
            if already_knows:
                ns = compute_novelty_scores(already_knows, [data.get("text", "")])[0]
                data["meta"]["novel_score"] = round(ns, 3)
                if ns < 0.3:
                    data["meta"]["suppression_reason"] = "already_known"

            return data
        except Exception as exc:
            raise _maybe_wrap(exc, tool="fetch") from exc

    # ── Research ────────────────────────────────────────────────────────

    def research(
        self,
        query: str,
        *,
        max_results: int = 6,
        timeout: int = 20,
        max_chars: int = 6000,
        refine: str = "",
        exclude_sources: list[str] | None = None,
        already_knows: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search + fetch top sources and emit an agent-ready evidence pack.

        Returns a dict with ``search_results``, ``sources``, ``answer_pack``,
        ``coverage_score``, ``knowledge_gaps``, ``suggested_followups``,
        and ``meta``.
        """
        try:
            pack = _research(
                query,
                max_results=max_results,
                timeout=timeout,
                max_chars=max_chars,
                refine=refine,
                exclude_sources=exclude_sources,
            )
            # Combine search_results + sources for meta computation
            all_results = (pack.get("search_results") or []) + (pack.get("sources") or [])

            # ── TF-IDF novelty scoring against already_knows ──────────
            if already_knows:
                for result_list_key in ("search_results", "sources"):
                    items = pack.get(result_list_key) or []
                    if items:
                        texts = [
                            (it.get("snippet") or it.get("text") or "")
                            for it in items
                        ]
                        novel_scores = compute_novelty_scores(already_knows, texts)
                        for it, ns in zip(items, novel_scores):
                            it.setdefault("meta", {})["novel_score"] = round(ns, 3)
                            if ns < 0.3:
                                it["meta"]["suppression_reason"] = "already_known"
                        # Re-rank by novelty (higher first)
                        items.sort(
                            key=lambda x: x.get("meta", {}).get("novel_score", 1.0),
                            reverse=True,
                        )

            pack["meta"] = _build_meta(tool="research", results=all_results, max_results=max_results)
            return pack
        except Exception as exc:
            raise _maybe_wrap(exc, tool="research") from exc

    # ── Deep Research ───────────────────────────────────────────────────

    def deep_research_stream(
        self,
        query: str,
        *,
        max_results: int = 8,
        timeout: int = 20,
        max_chars: int = 6000,
        refinement_loops: int = 0,
        refine: str | None = None,
        already_knows: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Streaming deep research pipeline.

        Yields phase dicts as the pipeline progresses so the calling agent
        can start consuming intermediate results before the full report
        is ready.

        Phases yielded:
        - ``{"phase": "decompose", "query": str, "branches": [...]}``
        - ``{"phase": "search", "branch": str, "results": [...]}``  — per sub-agent
        - ``{"phase": "fetch", "branch": str, "sources": [...]}``   — per sub-agent
        - ``{"phase": "rank", "sources": [...]}``
        - ``{"phase": "evidence", "claims": [...]}``
        - ``{"phase": "complete", "report": {...}}``

        Usage::

            for chunk in aw.deep_research_stream("Python vs Rust"):
                if chunk["phase"] == "complete":
                    print(chunk["report"]["report_markdown"])
        """
        try:
            yield from _deep_research_stream(
                query,
                max_results=max_results,
                timeout=timeout,
                max_chars=max_chars,
                refinement_loops=refinement_loops,
                refine=refine,
                already_knows=already_knows,
            )
        except Exception as exc:
            raise _maybe_wrap(exc, tool="deep_research") from exc

    def deep_research(
        self,
        query: str,
        *,
        max_results: int = 8,
        timeout: int = 20,
        max_chars: int = 6000,
        refinement_loops: int = 0,
        refine: str | None = None,
        already_knows: list[str] | None = None,
    ) -> dict[str, Any]:
        """Multi-branch deep research pipeline (zero LLM).

        Decomposes the query into sub-questions, fetches in parallel,
        BM25-ranks results, extracts evidence, detects contradictions,
        and builds a structured report.

        Parameters
        ----------
        query : str
            The research query.
        refine : str | None, optional
            Agent-steerable refinement string appended to the query
            (e.g., ``"pricing"`` or ``"technical specifications"``).

        Returns a dict with ``report_markdown``, ``report_json``,
        ``elapsed_seconds``, and ``meta``.
        """
        try:
            # Collect all chunks from the stream, keep the final report
            report: dict[str, Any] | None = None
            for chunk in _deep_research_stream(
                query,
                max_results=max_results,
                timeout=timeout,
                max_chars=max_chars,
                refinement_loops=refinement_loops,
                refine=refine,
                already_knows=already_knows,
            ):
                if chunk["phase"] == "complete":
                    report = chunk["report"]
                    break

            if report is None:
                raise AgentWebError("deep_research pipeline did not complete", code="deep_research")

            report["meta"] = _build_meta(tool="deep_research")
            return report
        except Exception as exc:
            raise _maybe_wrap(exc, tool="deep_research") from exc

    # ── OpenAI Tools ────────────────────────────────────────────────────

    @staticmethod
    def openai_tools() -> list[dict[str, Any]]:
        """Return a list of OpenAI function-calling JSON schemas.

        Each schema describes a method on this class so an LLM can call
        them via the OpenAI tools / function calling API.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web for a given query. Returns a list of search results with titles, URLs, and snippets.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query string.",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of search results to return (default: 8).",
                                "default": 8,
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds for each request (default: 20).",
                                "default": 20,
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch",
                    "description": "Fetch and extract the text content of a single URL. Uses layered tactics including direct HTTP, readability, Jina reader, and optional browser fallback.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to fetch.",
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Maximum characters to return (default: 12000).",
                                "default": 12000,
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds (default: 20).",
                                "default": 20,
                            },
                            "use_jina": {
                                "type": "boolean",
                                "description": "Enable Jina reader fallback for JavaScript-rendered pages (default: true).",
                                "default": True,
                            },
                            "use_browser": {
                                "type": "boolean",
                                "description": "Enable headless browser fallback via agent-browser if installed (default: false).",
                                "default": False,
                            },
                        },
                        "required": ["url"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "research",
                    "description": "Search the web for a query, then fetch the top results and compile an agent-ready evidence pack with key claims and source attribution.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The research query string.",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of search results to fetch sources from (default: 6).",
                                "default": 6,
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds for each request (default: 20).",
                                "default": 20,
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Maximum characters per fetched source (default: 6000).",
                                "default": 6000,
                            },
                            "refine": {
                                "type": "string",
                                "description": "Optional refinement text appended to the search query to narrow results (e.g. 'pricing', 'benchmarks').",
                                "default": "",
                            },
                            "exclude_sources": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of source names/patterns to exclude (e.g. 'vendor blogs', 'wikipedia').",
                                "default": [],
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "deep_research",
                    "description": "Run the deep research pipeline: decompose a complex query into sub-questions, search and fetch in parallel, BM25-rank results, extract evidence, detect contradictions, and produce a structured report. Zero LLM calls used internally.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The deep research query string.",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum results per sub-query branch (default: 8).",
                                "default": 8,
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds for each request (default: 20).",
                                "default": 20,
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Maximum characters per fetched source (default: 6000).",
                                "default": 6000,
                            },
                            "refinement_loops": {
                                "type": "integer",
                                "description": "Number of refinement loops for follow-up searches (default: 1).",
                                "default": 1,
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
        ]
