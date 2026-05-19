"""AgentWeb Hermes plugin — auto-discovered web search provider.

Register the :class:`AgentWebProvider` so Hermes can route ``web_search``
and ``web_extract`` tool calls through the AgentWeb CLI.

No API key needed — AgentWeb is free and uses public web sources.
"""

from __future__ import annotations

from .provider import AgentWebProvider


def register(ctx) -> None:
    """Register the AgentWeb provider with the Hermes plugin context."""
    ctx.register_web_search_provider(AgentWebProvider())
