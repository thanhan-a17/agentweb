"""AgentWeb search provider — Hermes plugin form.

Wraps the ``agentweb`` CLI as a Hermes :class:`WebSearchProvider`.
AgentWeb is a free, no-API-key web search tool that fires 12+ sources
in parallel (DDG, arXiv, Wikipedia, GitHub, Reddit, HN, YouTube, etc.)
and ranks results with BM25 + FlashRank.

Two capabilities: search and extract (via ``agentweb fetch``).
No crawl support.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


def _run_agentweb(*args: str, timeout: int = 30) -> Optional[str]:
    """Run ``agentweb`` with *args* and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["agentweb", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.debug("agentweb stderr: %s", result.stderr[:500])
            return None
        return result.stdout
    except FileNotFoundError:
        logger.debug("agentweb CLI not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("agentweb timed out after %ss", timeout)
        return None
    except Exception as exc:
        logger.debug("agentweb error: %s", exc)
        return None


class AgentWebProvider(WebSearchProvider):
    """Hermes web provider that delegates to the AgentWeb CLI.

    Search requests are shaped as ``agentweb search <query> --max-results <limit> --format json``.
    Extract requests as ``agentweb fetch <url> --format json``.

    Requires the ``agentweb`` CLI to be installed and on ``$PATH``.
    """

    # ── Identity ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "agentweb"

    @property
    def display_name(self) -> str:
        return "AgentWeb"

    # ── Availability ──────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True when the ``agentweb`` CLI is installed and accessible.

        Runs ``agentweb --version`` — no network I/O.
        """
        try:
            result = subprocess.run(
                ["agentweb", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── Capabilities ──────────────────────────────────────────────────

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def supports_crawl(self) -> bool:
        return False

    # ── Search ────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute a multi-provider search via AgentWeb.

        Returns the standard Hermes search-result shape::

            {"success": bool, "data": {"web": [{title, url, description, position}, ...]}}
        """
        safe_limit = max(1, min(int(limit), 100))

        stdout = _run_agentweb(
            "search", query,
            "--max-results", str(safe_limit),
            "--format", "json",
        )
        if stdout is None:
            return {
                "success": False,
                "error": "AgentWeb search failed. Is `agentweb` installed and on $PATH?",
            }

        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError as exc:
            logger.warning("agentweb returned invalid JSON: %s", exc)
            return {"success": False, "error": f"AgentWeb returned invalid JSON: {exc}"}

        results = raw.get("results", [])
        web = []
        for i, item in enumerate(results):
            web.append({
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "description": str(item.get("snippet", "")),
                "position": i + 1,
            })

        return {"success": True, "data": {"web": web}}

    # ── Extract ───────────────────────────────────────────────────────

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Fetch content from one or more URLs via AgentWeb.

        Returns the standard Hermes extract-result shape::

            [
                {"url": str, "title": str, "content": str,
                 "raw_content": str, "metadata": dict},
                ...
            ]
        """
        results: List[Dict[str, Any]] = []
        for url in urls:
            stdout = _run_agentweb("fetch", url, "--format", "json", timeout=60)
            if stdout is None:
                results.append({
                    "url": url,
                    "error": "AgentWeb fetch failed. Is `agentweb` installed and on $PATH?",
                })
                continue

            try:
                raw = json.loads(stdout)
            except json.JSONDecodeError as exc:
                results.append({
                    "url": url,
                    "error": f"AgentWeb returned invalid JSON: {exc}",
                })
                continue

            if not raw.get("ok", False):
                results.append({
                    "url": url,
                    "title": raw.get("title", ""),
                    "error": f"Fetch failed (HTTP {raw.get('status_code', '?')})",
                })
                continue

            content = raw.get("text") or ""
            results.append({
                "url": raw.get("final_url", url),
                "title": raw.get("title", ""),
                "content": content[:100_000],  # cap for Hermes' tool output limit
                "raw_content": content,
                "metadata": {
                    "status_code": raw.get("status_code"),
                    "source": raw.get("source"),
                    "text_len": raw.get("text_len", len(content)),
                    "quality_score": raw.get("quality_score"),
                    **raw.get("metadata", {}),
                },
            })

        return results

    # ── Setup schema ──────────────────────────────────────────────────

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "AgentWeb",
            "badge": "free · no key",
            "tag": "Free multi-provider web search — no API key needed. Uses DDG, arXiv, "
                   "Wikipedia, GitHub, Reddit, HN, YouTube, and more. Requires agentweb CLI.",
            "env_vars": [],
        }
