# AgentWeb

AgentWeb is a CLI web-access layer for agents. It gives Hermes one command for search, scraping, SPA extraction, logged-in cookie fetches, and evidence-pack generation instead of making the agent stitch together Python scripts every time.

## Commands

```bash
agentweb search "query" --max-results 8 --format json
agentweb fetch https://example.com --format markdown
agentweb research "best local LLM serving stack" --max-results 6 --format json
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
