# AgentWeb changelog

## 0.1.0 advanced mechanics branch

### Added

- Subject-aware search service registry with broad no-key providers including DuckDuckGo, Wikipedia, Wikidata, OpenAlex, Crossref, arXiv, PubMed, GitHub, and Hacker News.
- Typed mechanics contracts for agents, execution policies, tool specs, tool permissions, input schemas, and output schemas.
- Planning/orchestration layer that decomposes goals into task steps, assigns agents by role, enforces step budgets, supports plan revision, emits collaboration messages, reflects on outputs, and resolves conflicts.
- Multi-agent collaboration protocol with delegate, critique, aggregate, result, and escalation message types.
- SQLite persistence for agent definitions, runtime state, task state, tool call records, conversation history, service configuration, memory entries, memory configuration, schema migrations, and audit logs.
- Scoped memory layer with user/workspace/project/agent/task isolation, enable/disable/clear controls, lexical retrieval, citations, and prompt-injection filtering.
- Safety/input controls for text limits, upload limits, supported file types, high-risk subject policy, secret redaction, and claim classification.
- File ingestion for TXT, Markdown, HTML, CSV, JSON, DOCX, and simple PDF text fragments.
- SDK-style API facade for health, services, agents, tasks, search, fetch, and research.
- Documentation for requirements, architecture, API, extensions, quickstart, deployment, and known limitations.
- Tests covering mechanics, storage, API, orchestration, memory, safety, ingestion, and existing web search/fetch behavior.

### Migration notes

- SQLite schema version is now `2`.
- Existing databases should call `AgentWebStore(path).initialize()` on startup; it creates new tables idempotently and records the latest schema version.

### Known limitations

- The API is an executable Python facade, not a bundled HTTP daemon.
- Model provider abstraction is represented in agent configuration but no LLM runtime adapter is bundled yet.
- Background workers, distributed tracing exporters, and quota dashboards are not bundled production services yet.
- PDF parsing is intentionally lightweight; complex PDFs should use a dedicated parser adapter.
