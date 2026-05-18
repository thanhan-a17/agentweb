# Changelog

All notable changes to AgentWeb.

## [0.3.0] — 2026-05-18

### Added
- **YouTube search provider** — searches YouTube via DuckDuckGo `site:` operator + Jina Reader fallback. No API key needed. Added to tech, food, travel, health, academic, entertainment, and general sector routes.
- **Bot-block detection** — runtime scanning for CAPTCHA walls, Cloudflare challenges, Jina error wrappers, and "blocked by network security" messages. Results with bot content are marked `ok=false` and excluded from analysis.
- **Quality filtering in `research()`** — sources below `quality_score >= 3.0` are filtered out before building answer packs. Coverage metrics now reflect only quality-passed sources. New `coverage` block exposes `requested/fetched/quality_passed` counts.
- **Reddit relevance filtering** — blocks known pump subreddits (IBRX, Livimmune, DRTS_Stock), requires minimum score > 1, enforces 15% query-term overlap for relevance. Applied to both JSON API and Jina-based Reddit results.
- **Comparison query decomposition in deep-research** — `"A vs B"` queries now get 5 specialized branches (entity1, entity2, direct comparison, pros/cons, alternatives) with entity extraction and context isolation.
- **Source URL propagation through evidence pipeline** — entity, stat, date, and table claims now carry `source_url` for full traceability back to the originating page.
- **Quality gate in deep-research `rank_sources()`** — drops results with `quality_score < 3.0` before ranking, adds `quality_filtered:N` warning to metadata.
- **Claim-type diversity in executive summary** — max 2 claims of the same type, max 5 total. Prevents summary from being dominated by a single angle.
- **Source diversity metric** in deep-research metadata — `unique_domains / total_fetched` ratio.
- **Capping controls** — `max_sources=30` and `max_findings=30` (previously hardcoded at 15/20). Exposed in metadata for auditability.
- **Stress test suite** (`stress_test.py`) — automated quality validation for search, research, and deep-research with pass/fail metrics.

### Changed
- **DuckDuckGo HTML parser** — multiple fallback selectors for result blocks, title/link extraction, and snippet parsing. Snippet fallback uses title when no snippet found.
- **Twitter search** — Jina Reader is now the primary fallback (was direct fetch).
- **Stricter quality scoring** — bot-block penalty increased to -3.0 (from -2.0), non-ok results get -3.0 instead of 0, pages under 200 chars get -2.0. `to_dict()` now includes `text_len` field.
- **Evidence extraction** — max claims increased from 20 to 30, returns `candidates_count` for pipeline transparency. Structured facts (table rows, key-value pairs) now merged without a hard cap — `build_report()` handles the final limiting.
- **Executive summary** — expanded from 3 to 5 sentences with claim-type diversity enforcement.

### Fixed
- **Source URL handling in evidence** — table/key-value facts now carry the correct `source_url` and `source_title` instead of empty strings. Source diversity key deduplication uses robust `split("?")[0]` stripping.
- **DDG result block parsing** — fallback to any result-class div when primary selector fails (DDG markup changes frequently).

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
