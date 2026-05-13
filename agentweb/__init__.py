"""AgentWeb: high-quality web access CLI for agents."""

__all__ = [
    "__version__",
    "fetch_url",
    "search_web",
    "search_by_provider",
    "research",
    "FetchResult",
    "SearchResult",
    "format_markdown_fetch",
    "format_markdown_research",
]
__version__ = "0.1.7"

from .core import (
    FetchResult,
    SearchResult,
    fetch_url,
    format_markdown_fetch,
    format_markdown_research,
    research,
    search_by_provider,
    search_web,
)
