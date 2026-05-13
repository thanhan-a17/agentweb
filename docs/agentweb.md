# AgentWeb

AgentWeb is a CLI web-access layer for agents. It gives Hermes one command for search, scraping, SPA extraction, logged-in cookie fetches, and evidence-pack generation instead of making the agent stitch together Python scripts every time.

## Commands

```bash
agentweb search "query" --max-results 8 --format json
agentweb fetch https://example.com --format markdown
agentweb research "best local LLM serving stack" --max-results 6 --format json
agentweb deep-research "transformer inference optimization" --format json
```

`AgentWeb` is also installed as an alias for `agentweb`.

## What it does

- Uses resilient no-key search providers: DuckDuckGo HTML + Hacker News Algolia.
- Fetches pages with realistic browser headers and redirect handling.
- Extracts clean text, title, metadata, and links.
- Parses Next.js React Server Component payloads when the visible HTML is a shell.
- Falls back to Jina Reader for cleaner article extraction or blocked/low-text pages.
- Supports logged-in pages with `--cookies` as either a raw Cookie header or Netscape `cookies.txt` path.
- Optionally tries `agent-browser` snapshots with `--browser` when installed.
- Emits compact JSON/Markdown designed for LLM context, with warnings and quality scores.

## Agent usage pattern

Use `research` when the agent needs broad context:

```bash
agentweb research "pricing of browser automation APIs" --max-results 8 --format json
```

Use `fetch` when the agent already has URLs:

```bash
agentweb fetch https://docs.example.com/page --format json --max-chars 20000
```

Use cookies for user-authorized logged-in pages:

```bash
agentweb fetch https://app.example.com/dashboard --cookies ~/.cookies/example.txt
```

AgentWeb does not bypass authentication. It uses credentials/cookies the user explicitly provides.

## Deep Research

Multi-branch deep research: decomposes a query into sub-questions, parallel-fetches, ranks with BM25, and extracts evidence. No LLM required — fully algorithmic.

```bash
agentweb deep-research "impact of transformer architecture on LLM inference costs" --format json
agentweb deep-research "best local LLM serving stack" --format markdown --refinement-loops 2
```

Options: `--max-results`, `--timeout`, `--max-chars`, `--refinement-loops`, `--format` (json/markdown), `--output`.

The JSON output includes a decomposition plan, executive summary, findings with sources, contradictions, and metadata.

## LLM dependency

AgentWeb operates with **zero LLM API calls by default**. All search, fetch, research, and deep-research commands are fully self-contained — no API key required, no LLM endpoint called.

The output JSON is specifically designed for agent-side LLM processing: it includes the original query, search result snippets, full extracted page text, metadata, and keyword-matched evidence snippets. An external agent can perform its own summarization and synthesis from this raw data.
