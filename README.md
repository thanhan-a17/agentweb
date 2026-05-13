# AgentWeb

**Web access for AI agents. One command. No API keys. No LLM dependency.**

AgentWeb is a CLI that gives any AI agent search, fetch, research, and multi-branch deep research — without a single API subscription or LLM call. Every command outputs clean JSON or markdown designed for programmatic consumption.

```bash
uv tool install agentweb

agentweb search "latest GPT-4o pricing" --format json
agentweb fetch https://example.com --format markdown
agentweb research "best local LLM serving stack 2026" --format json
agentweb deep-research "transformer inference optimization" --format markdown -o report.md
```

---

## Why AgentWeb?

**No API keys.** No SerpAPI, no Brave, no Bing, no OpenAI. It uses DuckDuckGo HTML, Hacker News Algolia, and Jina Reader — all free, all zero-config.

**No LLM calls.** Every piece of reasoning inside AgentWeb is classical NLP: regex, BM25, term-overlap scoring. No hallucination, no latency, no cost per call.

**Designed for agents.** The output JSON has exactly what an agent needs — structured results, extracted text, metadata, quality scores, tactics used, and warnings. No HTML to parse, no ad text to filter.

**Resilient by default.** If a site blocks direct HTTP, it falls through to Jina Reader. If you install the optional browser extras, it escalates to headless Camoufox with anti-detection stealth.

---

## Commands

| Command | What it does | When to use it |
|---|---|---|
| `search` | Parallel search across DDG + Jina + HN Algolia | You need links and snippets for a query |
| `fetch` | Full page text extraction with layered fallbacks | You have a URL and need its content |
| `research` | Search + fetch + evidence extraction pipeline | You need an answer with cited sources |
| `deep-research` | Multi-branch: decompose, parallel fetch, BM25 rank, extract evidence, find contradictions | You have a complex or comparison query |

### `search`

```bash
agentweb search "your query" --max-results 8 --timeout 20 --format json -o results.json
```

Runs DuckDuckGo, Jina Search, and Hacker News in parallel. Returns deduplicated results with title, URL, snippet, and source attribution. ~3-5s.

### `fetch`

```bash
agentweb fetch <url> --timeout 20 --max-chars 12000 --format json
```

Layered extraction: direct HTTP → Jina Reader → (optional) Camoufox browser. Auto-detects bot-blocked pages and escalates. Extracts title, text, metadata, links. Returns quality score (0–10) and warnings. ~2-15s.

### `research`

```bash
agentweb research "your question" --max-results 6 --format json
```

End-to-end: search → parallel fetch top results → keyword-based evidence extraction. Returns a complete answer pack with sourced evidence snippets. ~30-50s.

### `deep-research`

```bash
agentweb deep-research "complex query" --max-results 8 --refinement-loops 1 --format markdown -o report.md
```

Full 8-phase pipeline: query decomposition → multi-provider routing → parallel sub-agent dispatch → BM25 ranking → evidence extraction → contradiction detection → refinement loop → report generation. Zero LLM. ~40-90s.

---

## Installation

### Quick install (recommended)

```bash
pip install agentweb
```

Or with uv:

```bash
uv tool install agentweb
```

### With browser/crawl extras

```bash
uv tool install 'agentweb[browser,crawl]'
# or
pip install 'agentweb[browser,crawl]'
```

The `browser` extra adds Camoufox + Playwright for JS-heavy sites with anti-detection stealth. The `crawl` extra adds trafilatura for content-aware link extraction.

### From source

```bash
git clone https://github.com/thanhan-a17/agentweb
cd agentweb
uv tool install '.[browser,crawl]'
```

---

## Agent Usage Pattern

The output JSON is designed for agent-side consumption. Here's how to compose commands in a Python workflow:

```python
import subprocess, json

# Step 1: Search
subprocess.run(["agentweb", "search", "GPT-4o pricing 2026", "--format", "json", "-o", "/tmp/search.json"])
results = json.load(open("/tmp/search.json"))["results"]
best_url = results[0]["url"]

# Step 2: Fetch the best result
subprocess.run(["agentweb", "fetch", best_url, "--format", "json", "-o", "/tmp/fetch.json"])
page = json.load(open("/tmp/fetch.json"))
content = page["text"]  # Clean extracted text, ready for your LLM
```

### For AI agent use (Hermes, Claude Code, etc.)

```bash
# Quick fact-finding chain
agentweb research "Claude Code vs Cursor pricing features 2026" --max-results 8 --format json

# Deep comparison
agentweb deep-research "best local LLM serving stack 2026 comparison" --format markdown

# Fetch with authenticated cookies
agentweb fetch https://app.example.com/dashboard --cookies ~/.cookies/example.txt
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  CLI (argparse) — search · fetch · research     │
│                  deep-research                   │
├─────────────────────────────────────────────────┤
│  Core Engine — search(), fetch_url(), research() │
├─────────────────────────────────────────────────┤
│  Fallback Layers — Direct HTTP → Jina → Browser  │
├─────────────────────────────────────────────────┤
│  Extras — Stealth (anti-detection), Safety       │
└─────────────────────────────────────────────────┘
```

The package also includes infrastructure for multi-agent workflows (`mechanics.py`, `orchestration.py`, `memory.py`, `storage.py`) and browser auth profiles (`auth_profile.py`) — these are available for programmatic use but not exposed through the CLI.

---

## Design Principles

- **Zero external API dependencies** — no keys, no subscriptions, no LLM endpoints
- **Layered fallback** — every extraction path has an escalation strategy
- **Agent-first output** — JSON with quality scores, warnings, and tactics metadata
- **Classical NLP only** — regex, BM25, phrase matching. Predictable, auditable, free
- **Anti-detection by default** — realistic headers, redirect handling, optional stealth JS

---

## License

MIT — see [LICENSE](LICENSE). Built by [Nous Research](https://nousresearch.com).
