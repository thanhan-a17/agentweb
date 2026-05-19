"""AgentWeb: high-quality web access CLI for agents."""

__all__ = [
    "__version__",
    "AgentWeb",
    "ContentAuthenticity",
    "compute_novelty_scores",
    "fetch_url",
    "search_web",
    "search_by_provider",
    "research",
    "FetchResult",
    "SearchResult",
    "format_markdown_fetch",
    "format_markdown_research",
]
__version__ = "0.3.0"

from agentweb.authenticity import ContentAuthenticity
from agentweb.engine.rank import compute_novelty_scores
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
from .sdk import AgentWeb
