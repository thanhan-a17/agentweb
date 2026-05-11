# AgentWeb

Standalone web access CLI for AI agents: search, fetch, extract, and source-pack.

## Quick start

```bash
python -m pip install -e '.[dev]'
agentweb --version
agentweb fetch https://example.com --format markdown
agentweb search "Ada Lovelace biography" --max-results 5
agentweb research "sparse autoencoders interpretability" --format json
agentweb services --format markdown
agentweb search "clinical trial metformin aging" --service pubmed --service openalex
agentweb fetch https://example.com/protected --camoufox --format markdown
```

See `docs/agentweb.md` for usage notes.

Additional docs:

- `docs/requirements.md` — concrete product definitions and target capabilities.
- `docs/architecture.md` — components, service boundaries, data flows, and runtime responsibilities.
- `docs/api.md` — SDK endpoint contracts, request/response schemas, status codes, and examples.
- `docs/extensions.md` — examples for adding domains, agent roles, and tools/services.
