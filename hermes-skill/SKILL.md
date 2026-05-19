---
name: agentweb-use
description: >-
  AgentWeb CLI usage for AI agents — zero-API-key web access. Covers the 4
  commands (search, fetch, research, deep-research), steer flags, clean invocation patterns,
  and critical pitfalls so an agent reliably feeds web data into its reasoning.
category: software-development
triggers:
  - agentweb
  - web search
  - fetch url
  - web research
  - deep research
  - need current info
  - online research
  - browse the web
  - web access
  - search the web
---

# AgentWeb Usage

**Zero-API-key, no-LLM** web access CLI. Turns one shell command into a grounded, cited source pack.

**Repo:** `github.com/thanhan-a17/agentweb`
**Version:** v0.4.0 | **Python:** ≥3.11

## Install

```bash
# Quickest — one-curl (auto-installs uv + agentweb + skill)
curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash
```

**Extras:** `[browser]` = Camoufox + Playwright for JS pages, `[crawl]` = trafilatura for link extraction, `[youtube]` = yt-dlp + youtube_transcript_api for YouTube transcripts.

**Upgrade:** re-run the curl command or `uv tool upgrade agentweb`.

## Decision Tree

```
Need web content?
├─ "Get me links and snippets"          → search   [+ --prefer/--exclude to steer]
├─ "I have a URL, I need its text"       → fetch    [+ --browser for JS SPAs]
├─ "Answer this with citations"          → research [+ --context to focus evidence]
├─ "Deep dive / compare / explore"       → deep-research [+ --context to steer branches]
└─ "YouTube video / transcript"          → search (YouTube provider is built-in)
```

Use **AgentWeb for text extraction at scale**. Browser tools only for JS SPAs, visual interaction, CAPTCHAs. AgentWeb first; escalate to browser only when blocked.

## The 4 Commands

### `search` — Web Search (1-5s)

```bash
agentweb search "query" \
  --prefer duckduckgo jina \
  --exclude reddit youtube \
  --context "relevant background to improve ranking" \
  --format json -o /tmp/agentweb-results.json
```

Fires 12 providers in parallel (arXiv, DDG, general web, GitHub, HN, Jina, Nominatim, Reddit, StackExchange, Twitter, Wikipedia, YouTube). Short-circuits when ≥2 providers return ≥8 results. BM25 + FlashRank ranking.

**All flags:** `--prefer`, `--exclude`, `--context`, `--max-results` (default 8, range syntax `8-12`), `--timeout` (default 30s).

### `fetch` — Page Content (0.3-15s) — CURL REPLACEMENT

```bash
agentweb fetch <url> \
  [--browser] [--max-chars 10000] \
  [--cookies cookies.txt] [--header 'Authorization: Bearer ***'] \
  [--no-jina] \
  --format json -o /tmp/page.json
```

Layered extraction: direct HTTP → specialized extractors (Wikipedia REST API, YouTube transcript, arXiv abstract, Reddit JSON API) → Jina Reader → optional Camoufox browser. Content authenticity scoring across all phases.

**All flags:** `--browser` (Camoufox fallback), `--max-chars` (default 12000), `--cookies` (Netscape cookies.txt), `--header` (repeatable), `--no-jina` (skip Jina), `--timeout` (default 30s).

### `research` — Question + Cited Answer (20-50s)

```bash
agentweb research "question" \
  --context "what specifically I'm looking for" \
  --format json -o /tmp/research.json
```

Search → parallel fetch top results → keyword evidence extraction → answer pack. Sources with `quality_score < 3.0` auto-filtered. Best for "What is X?" / "How does Y work?".

**All flags:** `--context` (steer evidence focus), `--max-results` (default 6), `--max-chars` (default 6000), `--timeout` (default 30s).

### `deep-research` — Multi-Branch Deep Dive (30-180s)

```bash
agentweb deep-research "complex query" \
  --context "specific focus to narrow the search" \
  --refinement-loops 1 \
  --format json -o /tmp/deep.json
```

Query decomposition → parallel branch dispatch → BM25 ranking (via engine/rank.py) → FlashRank reranking → evidence extraction → contradiction detection. Zero LLM. For **comparison queries** (`A vs B`), auto-generates 5 specialized branches.

**All flags:** `--context` (primary steer), `--refinement-loops` (default 1), `--max-results` (default 8, range syntax `8-12`), `--max-chars` (default 6000), `--timeout` (default 30s).

## Steer Flags — ALWAYS Use Them

Every command accepts steering that dramatically improves result quality. Raw queries get SEO junk; steered queries get answers.

| Flag | search | research | deep-research | Effect |
|---|---|---|---|---|
| `--context "..."` | ✅ | ✅ | ✅ | Tells the engine what you're really after. Include domain knowledge, what to prioritize, what to skip. |
| `--prefer [source...]` | ✅ | ❌ | ❌ | Bias toward specific providers. `--prefer github jina` when looking for code. |
| `--exclude [source...]` | ✅ | ❌ | ❌ | Block noisy sources. `--exclude reddit youtube` cuts SEO spam by >50%. |

**Context is the single most powerful flag.** Without it, agentweb has no signal about intent. A good context tells who you are, what you're researching, what kind of answer you want, and what to ignore.

## Golden Rules

1. **ALWAYS** `--format json -o /tmp/file.json`. Without `-o`, JSON to stdout is empty on success.
2. **NEVER** `curl | python3` to scrape — `fetch` has layered fallbacks and better extraction.
3. **Check `ok` and `quality_score`** — `ok=true` with quality_score < 3 is boilerplate or bot-blocked.
4. **Prefetch the output dir exists** — `-o /tmp/x.json` works; `-o /tmp/newdir/x.json` crashes.
5. **Budget time** — search (<5s), fetch (<15s), research (20-50s), deep-research (30-180s).
6. **fetch + read beats research synthesis** — evidence extraction is keyword-biased; for precision, fetch the source URLs yourself.
7. **Multi-angle search** — one query angle is never enough. Run 2-3 parallel searches with different phrasings.
8. **Local language for local results** — English queries on Vietnamese topics return Western SEO junk.
9. **Bot-blocked pages** — retry fetch with `--browser`. If still blocked, switch sources.
10. **Broad queries without context poison deep-research** — always pair with `--context`. Or better: `search` first → identify specific URLs → `fetch` each one.

## SDK Usage (for agents calling AgentWeb programmatically)

```python
from agentweb import AgentWeb

aw = AgentWeb()

# Search with steer flags
result = aw.search("quantum computing", prefer=["arxiv"], exclude=["reddit"])

# Fetch a URL
page = aw.fetch("https://example.com", max_chars=5000)

# Research with context
pack = aw.research("latest AI benchmarks", context="focus on 2026 results")

# Deep research with streaming
for chunk in aw.deep_research_stream("Python vs Rust"):
    if chunk["phase"] == "complete":
        report = chunk["report"]
```

## Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| `curl <url> \| python3 -c ...` | `agentweb fetch <url> --format json -o /tmp/x.json` |
| `web_search` tool | `agentweb search` (faster, no API key) |
| Build a Hermes web provider plugin for agentweb | Use agentweb directly via terminal — preserves all 4 modes |
| Trust research evidence blindly | Fetch source URLs directly for precision data |
| Deep-research for quick questions | Use search or research (<50s) |
| Sequential fetch loops | Parallel fetches (ThreadPoolExecutor) |
| One English query for non-English topic | Include at least one local-language query |
| Raw queries without steer flags | Use `--context`, `--prefer`, `--exclude` on every search |
| `pip install agentweb` (PyPI) | `curl -fsSL .../install.sh \| bash` or `uv tool install agentweb` |

## Reference Files

- `references/agentweb-v0.2.0-test-sweep-findings.md` — Known bugs, reproduction recipes.
- `references/multi-source-research-tips.md` — Multi-angle research, content truncation, source credibility.
- `references/llm-benchmark-research-session.md` — Benchmark research methodology.
- `references/vn-coffee-market-research-pattern.md` — Local-language query bias example.
- `references/agentweb-vs-others-comparison.md` — AgentWeb vs others comparison.
