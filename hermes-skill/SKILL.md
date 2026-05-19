---
name: agentweb-use
description: >-
  AgentWeb CLI usage for AI agents — zero-API-key web access. Covers the 4
  commands (search, fetch, research, deep-research), clean invocation patterns,
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
**Version:** v0.3.0 | **Python:** ≥3.11

## Install

```bash
# Quickest — one-curl (auto-installs uv + agentweb)
curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash

# Or via uv (with extras)
uv tool install 'agentweb[browser,crawl,youtube] @ git+https://github.com/thanhan-a17/agentweb.git'

# Or pip
pip install 'agentweb[browser,crawl,youtube] @ git+https://github.com/thanhan-a17/agentweb.git'
```

**Extras:** `[browser]` = Camoufox + Playwright for JS pages, `[crawl]` = trafilatura for link extraction, `[youtube]` = yt-dlp + youtube_transcript_api for YouTube transcripts.

**Upgrade:** `curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash` (re-runs the script) or `uv tool upgrade agentweb`.

## Decision Tree

```
Need web content?
├─ "Get me links and snippets"          → search
├─ "I have a URL, I need its text"       → fetch    (NEVER curl)
├─ "Answer this with citations"          → research
├─ "Deep dive / compare / explore"       → deep-research
└─ "YouTube video / transcript"          → search (YouTube provider is built-in)
```

Use **AgentWeb for text extraction at scale**. Browser tools only for JS SPAs, visual interaction, CAPTCHAs. AgentWeb first; escalate to browser only when blocked.

## The 4 Commands

### `search` — Web Search (3-5s)

```bash
agentweb search "query" --format json -o /tmp/agentweb-<topic>.json
```

Parallel DDG + Jina + HN. YouTube search built-in (uses `site:youtube.com` + Jina fallback, zero API keys). Faster than built-in web_search tool. Returns ranked results with title, URL, snippet, source.

### `fetch` — Page Content (0.3-15s) — CURL REPLACEMENT

```bash
agentweb fetch <url> [--browser] [--max-chars 10000] --format json -o /tmp/agentweb-fetch.json
```

Layered extraction: direct HTTP → Jina Reader → optional Camoufox browser. Auto-detects CAPTCHAs, Cloudflare, bot blocks. Returns structured JSON with `text`, `ok`, `quality_score`, `tactics`, `metadata`. Use `--browser` for JS-heavy sites. **Never curl + python3 — fetch is always better, faster, cleaner.**

### `research` — Question + Cited Answer (30-50s)

```bash
agentweb research "question" --format json -o /tmp/agentweb-research.json
```

Search → parallel fetch top results → keyword evidence extraction → answer pack. Sources with `quality_score < 3.0` are auto-filtered. Best for "What is X?" / "How does Y work?".

### `deep-research` — Multi-Branch Deep Dive (60-180s+)

```bash
agentweb deep-research "complex query" --format json -o /tmp/agentweb-deep.json
```

Query decomposition → parallel branch dispatch → BM25 ranking → evidence extraction → contradiction detection. For **comparison queries** (`A vs B`), auto-generates 5 specialized branches (entity1, entity2, direct comparison, pros/cons, alternatives). Zero LLM. Best for broad topics, comparisons, conflicting claims.

## Golden Rules

1. **ALWAYS** `--format json -o /tmp/file.json`. Without `-o`, JSON to stdout is empty on success.
2. **NEVER** `curl | python3` to scrape — `fetch` has layered fallbacks and better extraction.
3. **Check `ok` and `quality_score`** — `ok=true` with quality_score < 3 is boilerplate or bot-blocked.
4. **Prefetch the output dir exists** — `-o /tmp/x.json` works; `-o /tmp/newdir/x.json` crashes.
5. **Budget time** — search (<5s), fetch (<15s), research (30-50s), deep-research (60-180s+).
6. **fetch + read beats research synthesis** — evidence extraction is keyword-biased; for precision, fetch the source URLs yourself.
7. **Multi-angle search** — one query angle is never enough. Run 2-3 parallel searches with different phrasings.
8. **Local language for local results** — English queries on Vietnamese topics return Western SEO junk.
9. **Bot-blocked pages** — retry fetch with `--browser`. If still blocked, switch sources.

## v0.3.0 Changes

- **YouTube search** built-in — no API key, uses DDG `site:` operator + Jina fallback
- **Bot-block detection** — CAPTCHA, Cloudflare, Jina errors detected automatically; bad results get `ok=false`
- **Quality gates** — sources < 3.0 are filtered from research/deep-research output
- **Comparison deep-research** — `A vs B` queries get 5 specialized branches
- **Reddit relevance filtering** — pump subreddits blocked, score floor + term overlap required
- **Stress test suite** — `stress_test.py` in repo
- **One-curl install script** — `curl -fsSL .../install.sh | bash`

## Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| `curl <url> \| python3 -c ...` | `agentweb fetch <url> --format json -o /tmp/x.json` |
| `web_search` tool | `agentweb search` (faster, no API key) |
| Trust research evidence blindly | Fetch source URLs directly for precision data |
| Deep-research for quick questions | Use search or research (<50s) |
| Sequential fetch loops | Parallel fetches (ThreadPoolExecutor) |
| One English query for non-English topic | Include at least one local-language query |
| `pip install agentweb` (PyPI) | `pip install git+https://github.com/thanhan-a17/agentweb.git` |

## Reference Files

- `references/agentweb-v0.2.0-test-sweep-findings.md` — Known bugs, reproduction recipes.
- `references/multi-source-research-tips.md` — Multi-angle research, content truncation, source credibility.
- `references/llm-benchmark-research-session.md` — Benchmark research methodology.
- `references/vn-coffee-market-research-pattern.md` — Local-language query bias example.
- `references/agentweb-vs-others-comparison.md` — AgentWeb vs other tools comparison.
