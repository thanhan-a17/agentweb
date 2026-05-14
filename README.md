# AgentWeb

**Web access for AI agents. No API keys. No LLM calls.**

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

## Why

**Made for agents, not humans.** Every command outputs structured JSON with quality scores, warnings, and tactics metadata — no HTML to parse, no ads to filter. Your agent feeds the output straight into context.

- **No API keys.** DuckDuckGo, HN Algolia, Jina Reader — all free, zero-config.
- **No LLM calls.** Classical NLP (regex, BM25, term scoring). Predictable, auditable, free.
- **Layered fallback.** Direct HTTP → Jina Reader → Camoufox stealth browser. Auto-escalates on bot-blocked pages.

## Commands

| Command | What it does |
|---|---|
| `search` | Parallel search across DDG + Jina + HN Algolia |
| `fetch` | Full page text extraction with layered fallbacks |
| `research` | Search + fetch + evidence extraction pipeline |
| `deep-research` | Multi-branch: query decomposition → parallel fetch → BM25 ranking → contradiction detection → report |

### Agent usage

```python
import subprocess, json

subprocess.run(["agentweb", "search", "GPT-4o pricing 2026", "--format", "json", "-o", "/tmp/search.json"])
results = json.load(open("/tmp/search.json"))["results"]
best_url = results[0]["url"]

subprocess.run(["agentweb", "fetch", best_url, "--format", "json", "-o", "/tmp/fetch.json"])
page = json.load(open("/tmp/fetch.json"))
content = page["text"]  # Clean extracted text for your LLM
```

## Architecture

```
CLI · search · fetch · research · deep-research
  └─ Core Engine
       └─ Fallback: HTTP → Jina → Browser (stealth)
```

## Design

- **Zero external API deps** — no keys, no subscriptions
- **Layered fallback** — every extraction path escalates
- **Agent-first output** — JSON with quality scores + warnings
- **Classical NLP only** — predictable, auditable, free
- **Anti-detection** — realistic headers, redirect handling, optional stealth JS

## License

MIT — see [LICENSE](LICENSE). Built by [Nous Research](https://nousresearch.com).
