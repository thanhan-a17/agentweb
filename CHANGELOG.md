# Changelog

All notable changes to AgentWeb.

## [0.2.0] — 2026-05-15

### Added
- **Content Authenticity scoring** — replaces static domain blocklists with runtime content quality assessment. Multi-factor scoring (HTTP status, content length, blocked signals, paywalls, text ratio, sentence count, line diversity). Auto-escalation: HTTP → Jina Reader → stealth browser.
- **Deep Research pipeline** — multi-branch, zero-LLM research engine. Query decomposition, parallel sub-agents, BM25 ranking, evidence extraction, contradiction detection, structured report output. Supports refinement loops and streaming.
- **Sector-based search routing** — queries are classified into sectors (tech, food, travel, health, academic, etc.) and routed to the best providers per sector.
- **Stealth browser subsystem** — three preset levels (off/standard/aggressive): navigator spoofing, canvas noise, WebGL spoofing, timing jitter, referrer spoofing.
- **Auth profiles** — persistent browser sessions with cookie reuse via Camoufox.
- **SDK facade** (`AgentWeb` class) — programmatic access with OpenAI-compatible tool schemas for agent integration.
- **Safety guards** — InputGuard input validation, secret redaction.

### Changed
- **No more domain config** — `config.py` deleted. Content authenticity scoring replaces static stealth domain lists.
- **CLI improvements** — range syntax (`8-12`) for numeric options, stderr confirmation on `-o`, `--version` flag.
- **Provider improvements** — Reddit JSON API, GitHub API, Hacker News Algolia, StackExchange, ArXiv abstract extraction, YouTube transcript, Wikipedia REST API.
- **Multi-query expansion** — each deep-research branch generates 3 query variants and searches all 3.
- **Reference chasing** — follows outbound arXiv/DOI/Wikipedia/GitHub/PDF links from fetched content.
- **Inter-branch URL cache** — eliminates redundant fetches across parallel deep-research sub-agents.
- **Source diversity scoring** — classifies sources into 10 types, boosts underrepresented, penalizes overrepresented.

### Fixed
- **SSRF protection** — `_safe_url()` now blocks private, link-local, and cloud metadata IP addresses (loopback allowed for dev/testing).
- **Security audit** — 14 issues fixed (path traversal, XML bombs, secret leakage, exception sanitization, dead code removal, .gitignore hygiene, InputGuard wiring, forward references).
- **Deep research quality** — 4 rounds of fixes (executive summary, entity extraction, evidence scoring, contradiction detection, coverage scoring, DDG fallback, quality score calibration, niche query decomposition).
- **Bot-blocking after fallbacks** — content authenticity re-checked after all fetch tactics exhausted.
- **Junk source filtering** — cookie consent, Disqus, tracking scripts, and navigation breadcrumbs filtered from output.
- **Exception sanitization** — all warning/stderr output uses `{type(exc).__name__}`, never `{exc}`.

### Removed
- `api.py`, `storage.py`, `ingest.py` — unreferenced dead code (~500 lines). Never wired into CLI or SDK.
- `classify_output_claims()` — unreferenced dead code.
- `SafetyPolicy` and `SafetyDecision` — unreferenced dead code.
- `_default_ua_runner()` — unreferenced dead code.
- Duplicate `_now()` definitions — consolidated into `core.py`.

## [0.1.7] — 2026-04

- Initial public release with search, fetch, and basic research capabilities.
