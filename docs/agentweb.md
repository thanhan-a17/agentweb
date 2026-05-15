# AgentWeb — Usage Guide

AgentWeb is a CLI for AI agents that need web access. Four commands cover everything from a quick search to multi-branch deep research — no API keys, no LLM dependency.

## Installation

```bash
pip install agentweb
# or
uv tool install agentweb

# With browser/crawl extras for JS-heavy sites:
uv tool install 'agentweb[browser,crawl]'
```

## Commands

### search — Web search

```bash
agentweb search "your query" --max-results 8 --timeout 20 --format json -o results.json
```

Parallel search across DuckDuckGo HTML, Jina Reader, and Hacker News Algolia. Returns deduplicated results with title, URL, snippet, and source attribution. ~3–5s.

### fetch — Page text extraction

```bash
agentweb fetch <url> --timeout 20 --max-chars 12000 --format json
```

Layered extraction: direct HTTP → Jina Reader → (optional) Camoufox browser. Auto-detects bot-blocked pages and escalates tactics. Returns clean text, title, metadata, links, quality score, and warnings. ~2–15s.

Cookies support for authenticated pages:

```bash
agentweb fetch https://app.example.com/dashboard --cookies ~/.cookies/example.txt
```

### research — Question answering

```bash
agentweb research "your question" --max-results 6 --timeout 20 --format json
```

Search → parallel fetch top results → extract evidence snippets → generate answer pack. Returns an evidence array with source attribution. ~30–50s.

### deep-research — Multi-branch deep research

```bash
agentweb deep-research "complex query" --max-results 8 --refinement-loops 1 --format markdown -o report.md
```

8-phase pipeline: query decomposition → multi-provider routing → parallel sub-agent dispatch → BM25 ranking → evidence extraction → contradiction detection → refinement loop → report generation. Zero LLM. ~40–90s.

Supports comparison queries, factual deep dives, and list queries. The markdown output is a complete research report with executive summary, findings, contradictions, and source list.

## Output JSON structure (programmatic use)

All commands support `--format json` for agent consumption. Key fields:

- **search**: `results[].{title, url, snippet, source}`
- **fetch**: `{ok, status_code, text, title, links, quality_score, tactics, warnings}`
- **research**: `{sources[].{text, ok, quality_score, warnings}, answer_pack.evidence[].{claim_or_evidence, source, title}}`
- **deep-research**: `{executive_summary, findings, evidence, contradictions, knowledge_gaps, sources}`

## Best practices

- Use `--format json -o output.json` to save results and avoid truncation
- Use `research` for factual queries, `search` for quick link discovery
- Use `deep-research` only for complex/comparison queries (it's 40–90s)
- Use `--browser` flag on `fetch` for JS-heavy SPAs
- The `--max-chars` flag controls text truncation (default: 12000 for fetch, 6000 for research)
- Quality score is 0–10: >5 is reasonable content, >7 is good

For full details, see the [README](https://github.com/thanhan-a17/agentweb#readme).
