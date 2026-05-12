"""AgentWeb: high-quality web access CLI for agents."""

from __future__ import annotations

import sys
from typing import Any

__version__ = "0.1.0"

# ── Lazy-loading module ──────────────────────────────────────────────────
# Eagerly importing everything at top level slows down CLI startup for
# commands like --help, auth, validate that only need a subset of modules.
# Instead we lazy-import on first attribute access.
#
# This is the full set of public names exported by agentweb. The mapping
# tells __getattr__ which module to pull each name from.

_LAZY_IMPORTS: dict[str, str] = {
    "AgentWebAPI": "agentweb.api",
    "AgentWebStore": "agentweb.storage",
    "AgentDefinition": "agentweb.mechanics",
    "BrowserProfile": "agentweb.auth_profile",
    "ExecutionPolicy": "agentweb.mechanics",
    "FileIngestor": "agentweb.ingest",
    "IngestedDocument": "agentweb.ingest",
    "MemoryEntry": "agentweb.memory",
    "MemoryStore": "agentweb.memory",
    "Orchestrator": "agentweb.orchestration",
    "Plan": "agentweb.orchestration",
    "Scope": "agentweb.memory",
    "StealthConfig": "agentweb.stealth",
    "StealthLevel": "agentweb.stealth",
    "StealthMiddleware": "agentweb.stealth",
    "TaskStep": "agentweb.orchestration",
    "ToolRegistry": "agentweb.mechanics",
    "ToolSpec": "agentweb.mechanics",
    "browser_status": "agentweb.auth_profile",
    "close_browser": "agentweb.auth_profile",
    "delete_profile": "agentweb.auth_profile",
    "extract_cookies": "agentweb.auth_profile",
    "fetch_with_profile": "agentweb.auth_profile",
    "generate_stealth_js": "agentweb.stealth",
    "get_stealth_preset": "agentweb.stealth",
    "list_profiles": "agentweb.auth_profile",
    "open_browser": "agentweb.auth_profile",
}

__all__ = sorted(_LAZY_IMPORTS) + ["__version__"]


def __getattr__(name: str) -> Any:
    if name == "__version__":
        return __version__
    if name in _LAZY_IMPORTS:
        mod = __import__(_LAZY_IMPORTS[name], fromlist=[name])
        attr = getattr(mod, name)
        # Cache on the package dict so subsequent access is fast
        setattr(sys.modules[__name__], name, attr)
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
