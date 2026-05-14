# AgentWeb

**Web access for AI agents. Zero API keys. Zero LLM calls. Zero config.**

Search, fetch, research, and deep-research the web — without a single API key or LLM token. Classical NLP only (BM25, TF-IDF, regex). Predictable, auditable, free.

## Installation

```bash
pip install git+https://github.com/thanhan-a17/agentweb.git
```

```bash
# or with uv
uv tool install git+https://github.com/thanhan-a17/agentweb.git

# with browser/crawl extras for JS-heavy sites with anti-detection
uv tool install 'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git'
```

```bash
# from source
git clone https://github.com/thanhan-a17/agentweb
cd agentweb
uv tool install '.[browser,crawl]'
```

To upgrade:
```bash
pip install --upgrade git+https://github.com/thanhan-a17/agentweb.git
```

## Quick Start

```bash
agentweb search "latest GPT-4o pricing" --format json
agentweb fetch https://example.com --format markdown
agentweb research "best local LLM serving stack 2026" --format json
agentweb deep-research "transformer inference optimization" -o report.md
```

## Commands

| Command | What it does |
|---|---|
| `search` | Parallel search across 10+ providers — DuckDuckGo, HN, arXiv, Wikipedia, Reddit, GitHub, Stack Exchange, OpenStreetMap, Twitter/X, Jina. Sector-aware routing. |
| `fetch` | Full page extraction with layered fallback: specialized extractors → HTTP → Jina Reader → Camoufox stealth browser. Auto-escalates on blocked content. |
| `research` | Search + parallel fetch top sources → evidence pack with coverage score, knowledge gaps, answer sources, followup suggestions. |
| `deep-research` | Multi-branch: query decomposition → parallel search/fetch → BM25 ranking → contradiction detection → structured report. No LLM. |

### CLI Flags

| Flag | Applies to | Description |
|---|---|---|
| `--max-results` | search, research, deep-research | Result count (supports ranges e.g. `8-12`) |
| `--max-chars` | fetch, research, deep-research | Max chars per source (supports ranges) |
| `--format` | all | `json` or `markdown` |
| `--output` / `-o` | all | Write to file (confirms via stderr) |
| `--cookies` | fetch | Cookie string or Netscape cookies.txt path |
| `--header` | fetch | Extra request header (e.g. `Authorization: Bearer ***`) |
| `--no-jina` | fetch | Disable Jina Reader fallback |
| `--browser` | fetch | Try agent-browser snapshot fallback |
| `--refinement-loops` | deep-research | Iterative query refinement passes |

### Python SDK

```python
from agentweb import AgentWeb

aw = AgentWeb()

# Search
result = aw.search("latest ML papers")
for item in result["results"]:
    print(item["title"], item["url"], item["source"])

# Fetch with auto-escalation
page = aw.fetch("https://example.com", use_browser=True)
print(page["title"], page["quality_score"], page["source"])

# Research → evidence pack
pack = aw.research("transformer attention mechanisms")
print(pack["coverage_score"], pack["knowledge_gaps"])
for source in pack["sources"]:
    print(source["url"], source["quality_score"])

# Deep research → structured report
report = aw.deep_research("LoRA fine-tuning best practices 2026")
print(report["report_markdown"][:2000])

# Streaming support
for phase in aw.deep_research_stream("quantization methods LLM"):
    print(f"Phase: {phase['phase']}")
```

```python
# OpenAI-compatible tool schemas for agent integration
tools = AgentWeb.openai_tools()
# Returns function-calling JSON schemas for search, fetch, research, deep_research
```

## Why

**Made for agents, not humans.** Every command outputs structured JSON with quality scores, provenance, and tactics metadata — no HTML to parse, no ads to filter.

- **Zero API keys.** DuckDuckGo, HN Algolia, arXiv, Wikipedia, Reddit, GitHub, Stack Exchange, OpenStreetMap, Jina Reader — all free, zero-config.
- **Zero LLM calls.** Classical NLP only (BM25, TF-IDF, regex, keyword scoring). Predictable, auditable, free. No model bills, no rate limits from AI providers.
- **Layered fallback.** Specialized extractors → Direct HTTP → Jina Reader → Camoufox stealth browser. Auto-escalates based on content quality score — no domain lists to maintain.
- **Sector-aware routing.** Automatically classifies queries (tech, health, academic, food, travel, shopping, entertainment, news) and routes to the most relevant search providers.
- **Content authenticity scoring.** Real-time assessment of response quality (0.0–1.0) detecting CAPTCHAs, Cloudflare blocks, paywalls, and boilerplate — replaces hardcoded domain allow/block lists.

## Architecture

```
CLI · search · fetch · research · deep-research
  └─ SDK (AgentWeb class)
       └─ Core Engine
            ├─ Specialized extractors (Wikipedia, YouTube, arXiv, Reddit)
            ├─ HTTP fetch with content authenticity scoring
            ├─ Jina Reader fallback
            └─ Browser fallback (Camoufox stealth + auth profiles)
  └─ Providers (10+ free, sector-routed)
       ├─ DuckDuckGo · HN Algolia · Jina + Bing
       ├─ arXiv API · Wikipedia API · Reddit JSON
       ├─ GitHub API · Stack Exchange API · OpenStreetMap Nominatim
       └─ Twitter/X via DuckDuckGo + Jina
  └─ deep-research pipeline (zero LLM)
       ├─ Safety → Decompose → Route → Parallel Sub-agents
       ├─ BM25 Rank → Evidence Extraction → Contradiction Detection
       └─ Structured Report + Optional Refinement
```

## Design

- **Zero external API deps** — no keys, no subscriptions, no LLM bills
- **Content-first** — quality scoring replaces domain lists, auto-escalation based on what the server actually returns
- **Layered extraction** — every fetch path escalates through 3+ tactics automatically
- **Agent-native output** — JSON with quality scores, provenance, coverage metrics, knowledge gaps
- **Classical NLP only** — predictable, auditable, free. No model calls anywhere in the pipeline
- **Anti-detection** — 3 stealth levels (off/standard/aggressive), 15+ browser countermeasures, canvas noise, WebGL spoofing, timing jitter

### Advanced Features

- **Auth profiles** — persistent Camoufox browser sessions with cookie extraction. Login once, reuse cookies across fetches. `agentweb.auth_profile` module.
- **File ingestion** — ingest PDF, DOCX, HTML, CSV, JSON, TXT, MD into structured documents. `FileIngestor` class.
- **Safety guards** — input validation, domain safety policy (medical/legal/financial/security), secret redaction (API keys, tokens), output claim classification.
- **Stealth browser** — Three preset levels (off/standard/aggressive). Canvas noise, WebGL spoofing, navigator property spoofing, plugin arrays, Chrome runtime objects, permission query spoofing, referrer spoofing, timing API jitter, CDP global cleanup.
- **Storage** — SQLite persistence for tasks, tool calls, and audit logs via `AgentWebStore`.

## License

MIT — see [LICENSE](LICENSE). Built by [Nous Research](https://nousresearch.com).
