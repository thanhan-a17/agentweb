---
name: agentweb-use
description: >-
  AgentWeb CLI usage for AI agents — zero-API-key web access. Covers the 4
  commands (search, fetch, research, deep-research), mandatory steer flags, clean invocation patterns,
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

## ⚠️ Mandatory: Always Steer Your Queries

**Raw queries without steer flags produce SEO spam.** Every agentweb call MUST include at least one steer flag. The difference between a raw query and a steered one is the difference between content farm junk and real answers.

| If you omit steer flags | Results you get |
|---|---|
| `search` without `--prefer`/`--exclude`/`--context` | Generic SEO spam, content farms, off-topic junk |
| `research` without `--context` | Keyword-biased evidence that misses the point |
| `deep-research` without `--context` | Vague branch decomposition, no focus signal, poor BM25 ranking |

**Default behavior:** `--prefer [sources]`, `--exclude [sources]`, and `--context` are NOT optional. They are the primary interface. Without them, the engine has zero signal about what you want.

## Install

```bash
# Quickest — one-curl (auto-installs uv + agentweb + skill)
curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash
```

**Extras:** `[browser]` = Camoufox + Playwright for JS pages, `[crawl]` = trafilatura for link extraction, `[youtube]` = yt-dlp + youtube_transcript_api for YouTube transcripts.

**Upgrade:** re-run the curl command or `uv tool upgrade agentweb`.

## Decision Tree — Flags Are Not Optional

```
Need web content?
├─ "Get me links and snippets"          → search   (MUST add --prefer/--exclude/--context)
├─ "I have a URL, I need its text"       → fetch    (--browser for JS SPAs, --cookies for auth)
├─ "Answer this with citations"          → research (MUST add --context to focus evidence)
├─ "Deep dive / compare / explore"       → deep-research (MUST add --context to steer branches)
└─ "YouTube video / transcript"          → search (YouTube provider is built-in)
```

## Golden Rules (Read First)

1. **ALWAYS use steer flags** — `--context` on every command, `--prefer`/`--exclude` on every `search`. Raw queries get SEO junk.
2. **ALWAYS** `--format json -o /tmp/file.json`. Without `-o`, JSON to stdout is empty on success.
3. **NEVER** `curl | python3` to scrape — `fetch` has layered fallbacks and better extraction.
4. **Check `ok` and `quality_score`** — `ok=true` with quality_score < 3 is boilerplate or bot-blocked.
5. **Prefetch the output dir exists** — `-o /tmp/x.json` works; `-o /tmp/newdir/x.json` crashes.
6. **Budget time** — search (<5s), fetch (<15s), research (20-50s), deep-research (30-180s).
7. **fetch + read beats research synthesis** — evidence extraction is keyword-biased; for precision, fetch the source URLs yourself.
8. **Multi-angle search** — one query angle is never enough. Run 2-3 parallel searches with different phrasings.
9. **Local language for local results** — English queries on Vietnamese topics return Western SEO junk.
10. **Bot-blocked pages** — retry fetch with `--browser`. If still blocked, switch sources.

## The 4 Commands

### `search` — Web Search (1-5s)

**Required flags:** `--prefer`, `--exclude`, `--context`. Without them you get garbage.

```bash
agentweb search "query" \
  --prefer duckduckgo jina \
  --exclude reddit youtube \
  --context "relevant background to improve ranking" \
  --format json -o /tmp/agentweb-results.json
```

Fires 12 providers in parallel (arXiv, DDG, general web, GitHub, HN, Jina, Nominatim, Reddit, StackExchange, Twitter, Wikipedia, YouTube). Short-circuits when ≥2 providers return ≥8 results. BM25 + FlashRank ranking.

**All flags:** `--prefer` (bias providers), `--exclude` (skip providers), `--context` (ranking intent), `--max-results` (default 8, range syntax `8-12`), `--timeout` (default 30s).

### `fetch` — Page Content (0.3-15s) — CURL REPLACEMENT

```bash
agentweb fetch <url> \
  [--browser] [--max-chars 10000] \
  [--cookies cookies.txt] [--header 'Authorization: Bearer ***'] \
  [--no-jina] \
  --format json -o /tmp/page.json
```

Layered extraction: direct HTTP → specialized extractors (Wikipedia REST API, YouTube transcript, arXiv abstract, Reddit JSON API) → Jina Reader → optional Camoufox browser. Content authenticity scoring across all phases.

**All flags:** `--browser` (Camoufox fallback for JS sites), `--max-chars` (default 12000), `--cookies` (Netscape cookies.txt for auth), `--header` (repeatable, for custom headers), `--no-jina` (skip Jina fallback), `--timeout` (default 30s).

### `research` — Question + Cited Answer (20-50s)

**Required flag:** `--context`. Without it, evidence extraction has no focus signal.

```bash
agentweb research "question" \
  --context "what specifically I'm looking for" \
  --format json -o /tmp/research.json
```

Search → parallel fetch top results → keyword evidence extraction → answer pack. Sources with `quality_score < 3.0` auto-filtered. Best for "What is X?" / "How does Y work?".

**All flags:** `--context` (steer evidence focus — **required**), `--max-results` (default 6), `--max-chars` (default 6000), `--timeout` (default 30s).

### `deep-research` — Multi-Branch Deep Dive (30-180s)

**Required flag:** `--context`. Without it, branch decomposition has no direction and BM25 ranking has no signal.

```bash
agentweb deep-research "complex query" \
  --context "specific focus to narrow the search" \
  --refinement-loops 1 \
  --format json -o /tmp/deep.json
```

Query decomposition → parallel branch dispatch → BM25 ranking (via engine/rank.py) → FlashRank reranking → evidence extraction → contradiction detection. Zero LLM. For **comparison queries** (`A vs B`), auto-generates 5 specialized branches.

**All flags:** `--context` (primary steer — **required**), `--refinement-loops` (default 1), `--max-results` (default 8, range syntax `8-12`), `--max-chars` (default 6000), `--timeout` (default 30s).

## Steer Flags Reference

| Flag | search | research | deep-research | Effect |
|---|---|---|---|---|
| `--context "..."` | ✅ Required | ✅ Required | ✅ Required | Tells the engine what you're really after. Include domain knowledge, what to prioritize, what to skip. |
| `--prefer [source...]` | ✅ Required | ❌ | ❌ | Bias toward specific providers. `--prefer github jina` when looking for code. |
| `--exclude [source...]` | ✅ Required | ❌ | ❌ | Block noisy sources. `--exclude reddit youtube` cuts SEO spam by >50%. |

**Why context is required:**
- `search` without context → BM25 ranks against the raw query, which favors generic keyword matches
- `research` without context → evidence extraction picks the most keyword-dense sentences, not the most relevant ones
- `deep-research` without context → branch decomposition is vague, BM25 ranking across branches has no signal, and contradiction detection compares irrelevant claims

A good context tells the engine: who you are, what you're researching, what kind of answer you want, and what to ignore.

```bash
# ❌ Bad — raw query, gets SEO junk
agentweb deep-research "Hermes Agent use cases" -f json -o /tmp/x.json

# ✅ Good — context steers toward real content
agentweb deep-research "Hermes Agent use cases" \
  --context "Researching concrete real-world applications of Hermes Agent by Nous Research. Want specific user stories, setup patterns, and workflows — not general AI agent articles. Skip overviews, skip comparisons with other agents." \
  -f json -o /tmp/x.json
```

## SDK Usage

```python
from agentweb import AgentWeb

aw = AgentWeb()

# Search with steer flags (required)
result = aw.search("quantum computing",
    prefer=["arxiv", "github"],
    exclude=["reddit", "youtube"],
    context="focus on 2026 breakthroughs in error correction"
)

# Fetch a URL
page = aw.fetch("https://example.com", max_chars=5000)

# Research with context (required)
pack = aw.research("latest AI benchmarks",
    context="focus on 2026 results, production deployments only"
)

# Deep research with streaming (context required)
for chunk in aw.deep_research_stream("Python vs Rust for data pipelines"):
    if chunk["phase"] == "complete":
        report = chunk["report"]

# OpenAI function-calling schemas
tools = AgentWeb.openai_tools()
```

## Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| `agentweb search "query" -f json` (no steer flags) | `agentweb search "query" --prefer github --exclude reddit --context "..." -f json ...` |
| `curl <url> \| python3 -c ...` | `agentweb fetch <url> --format json -o /tmp/x.json` |
| `web_search` tool | `agentweb search` (faster, no API key) |
| Trust research evidence blindly | Fetch source URLs directly for precision data |
| Deep-research for quick questions | Use search or research (<50s) |
| Sequential fetch loops | Parallel fetches (ThreadPoolExecutor) |
| One English query for non-English topic | Include at least one local-language query |
| `pip install agentweb` (PyPI) | `curl -fsSL .../install.sh \| bash` or `uv tool install agentweb` |

## Reference Files

- `references/agentweb-v0.2.0-test-sweep-findings.md` — Known bugs, reproduction recipes.
- `references/multi-source-research-tips.md` — Multi-angle research, content truncation, source credibility.
- `references/llm-benchmark-research-session.md` — Benchmark research methodology.
- `references/vn-coffee-market-research-pattern.md` — Local-language query bias example.
- `references/agentweb-vs-others-comparison.md` — AgentWeb vs others comparison.
