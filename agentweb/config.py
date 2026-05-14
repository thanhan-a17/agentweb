"""Configuration system for AgentWeb.

Previously this module maintained a hardcoded domain list for stealth fetch
tactics (GSMArena, Medium, Reddit, etc.). That approach was removed in favor
of domain-agnostic content authenticity scoring — see authenticity.py.

The tool now works out of the box with zero configuration. No domain lists,
no per-site tuning, no config files needed. The fetch pipeline auto-escalates
based on content quality: HTTP -> Jina Reader -> Browser fallback.

If you're looking for a config file to add custom settings, one doesn't exist
anymore. The tool just works.
"""
