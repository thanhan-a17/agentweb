# AgentWeb

AgentWeb is a CLI web-access layer for agents. It gives Hermes one command for search, scraping, SPA extraction, logged-in cookie fetches, and evidence-pack generation instead of making the agent stitch together Python scripts every time.

## Commands

```bash
agentweb search "query" --max-results 8 --format json
agentweb search "query" --service wikipedia --service wikidata
agentweb services --format markdown
agentweb fetch https://example.com --format markdown
agentweb research "best local LLM serving stack" --max-results 6 --format json
agentweb crawl https://docs.example.com --depth 3 --max-pages 20 --format json
```

`AgentWeb` is also installed as an alias for `agentweb`.

## What it does

- Uses broad no-key discovery providers: DuckDuckGo HTML, Wikipedia OpenSearch, Wikidata, OpenAlex, Crossref, arXiv, PubMed, GitHub, plus Hacker News as a niche tech signal.
- Routes queries through subject profiles so academic, medical, software, startup, humanities, and entity-heavy searches get the right services without hand-tuning.
- Fetches pages with realistic browser headers and redirect handling.
- Extracts clean text, title, metadata, links, JSON-LD structured data, and Next.js React Server Component payloads.
- Falls back to Jina Reader for cleaner article extraction or low-text pages.
- Filters blocker/login/verification pages out of evidence packs instead of treating them as successful sources.
- Marks empty or unusable research packs as `status: degraded` and returns exit code 2.
- Supports logged-in pages with `--cookies` as either a raw Cookie header or Netscape `cookies.txt` path.
- Optionally tries `agent-browser` snapshots with `--browser` when installed.
- Optionally tries Camoufox browser rendering for bot-protected pages with `--camoufox` on `fetch`; `research` uses Camoufox fallback by default when installed, disable with `--no-camoufox`.
- Optionally takes full-page screenshots with `--screenshot` on `fetch`, `research`, or `crawl`. Uses Playwright (soft dependency, no hard install required) — returns `screenshot_path` in output and gracefully warns `screenshot_unavailable` if Playwright is missing.
- BF-crawls from a seed URL with `crawl` — follows links up to `--depth` levels, stops at `--max-pages`, deduplicates by canonical URL, and emits the same evidence-pack format as `research`.
- Emits compact JSON/Markdown designed for LLM context, with warnings, rejected sources, and quality scores.

## Agent usage pattern

Use `research` when the agent needs broad context:

```bash
agentweb research "pricing of browser automation APIs" --max-results 8 --format json
```

Use `services` and `--service` when the subject matter demands precision:

```bash
agentweb services --format markdown
agentweb search "gene therapy clinical trial retinal disease" --service pubmed --service openalex --format json
agentweb research "new transformer preprint sparse attention" --service arxiv --service crossref --format json
```

If `--service` is omitted, AgentWeb infers a subject profile and chooses a balanced provider set automatically.

Use `fetch` when the agent already has URLs:

```bash
agentweb fetch https://docs.example.com/page --format json --max-chars 20000
agentweb fetch https://example.com/protected --camoufox --format markdown
```

Use cookies for user-authorized logged-in pages:

```bash
agentweb fetch https://app.example.com/dashboard --cookies ~/.cookies/example.txt
```

AgentWeb does not bypass authentication. It uses credentials/cookies the user explicitly provides.

Use `crawl` when the agent needs to explore a site's structure:

```bash
agentweb crawl https://docs.example.com --depth 2 --max-pages 15 --format json
agentweb crawl https://docs.example.com --depth 1 --max-pages 5 --screenshot --format json
```

Use `--screenshot` on any fetch/crawl/research command for visual context:

```bash
agentweb fetch https://example.com --screenshot --format json
agentweb research "new CSS features shipping in 2026" --screenshot --format json
```
