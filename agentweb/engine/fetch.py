"""AgentWeb fetch orchestration.

fetch_url() delegates to the core fetch implementation while serving as the
new engine entry point, preserving backward compatibility.
"""

from __future__ import annotations

from typing import Any

from agentweb.core import FetchResult, fetch_url as _core_fetch_url


def fetch_url(
    url: str,
    *,
    timeout: int = 20,
    cookies: str | None = None,
    headers: dict[str, str] | None = None,
    max_chars: int = 12000,
    use_jina: bool = True,
    use_browser: bool = False,
) -> FetchResult:
    """Fetch and extract content from a URL.

    Delegates directly to agentweb.core.fetch_url to preserve existing
    behaviour, error handling, and tactic sequencing.
    """
    return _core_fetch_url(
        url,
        timeout=timeout,
        cookies=cookies,
        headers=headers,
        max_chars=max_chars,
        use_jina=use_jina,
        use_browser=use_browser,
    )
