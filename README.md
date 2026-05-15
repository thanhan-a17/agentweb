# AgentWeb

**Web access for AI agents. No API keys. No AI bills. No setup.**

Search, fetch, research, and deep-research the web — completely free, no keys required. Uses smart search + content extraction, not language models. Predictable, auditable, costs nothing to run.

## One-Click Install for specific agents

> Copy the block for your agent framework and paste it. The agent handles everything.

### → Hermes Agent

```
I want you to install AgentWeb — a CLI tool that lets you search, fetch, research, and deep-research the web with no API keys and no AI costs.

Requirements: Python 3.10+ and either `pip` or `uv` (preferred).

Steps:
1. Check if already installed: `agentweb --version`
2. If not, install via terminal:
   - With uv (preferred): `uv tool install 'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git'`
   - Or with pip: `pip install git+https://github.com/thanhan-a17/agentweb.git`
3. Verify: run `agentweb search "Hermes Agent 2026" --format json` and confirm it returns results with quality scores.
4. Report back what's installed and that it works.

After install, remember I have AgentWeb available so you can use it whenever I need web research.
```

### → OpenCode

```
Install AgentWeb — a CLI tool for searching, fetching, researching, and deep-researching the web. No API keys, no AI model costs, works entirely via free sources.

Requirements: Python 3.10+ with uv or pip.

Steps:
1. Check if installed: `agentweb --version`
2. If not: `uv tool install 'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git'`
   (or `pip install git+https://github.com/thanhan-a17/agentweb.git`)
3. Verify with: `agentweb search "latest LLM research 2026" --format json`
4. Show me a summary of the search results to confirm it's working.

Once installed, use agentweb search/fetch/research whenever I ask you to look something up on the web.
```

### → Codex CLI

```
Install AgentWeb — a free, keyless CLI tool that gives AI agents web search, page fetch, research, and deep research capabilities. Uses DuckDuckGo, arXiv, Wikipedia, GitHub, Reddit and other free sources — no API subscriptions needed.

Requirements: Python 3.10+, uv or pip.

Steps:
1. Check: `agentweb --version`
2. Install: `uv tool install 'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git'`
3. Verify with a search: `agentweb search "transformer inference optimization 2026" --format json`
4. Summarize the results so I know it's working.

Use AgentWeb's commands (search, fetch, research, deep-research) whenever I need web data — it's faster and cheaper than alternatives.
```

## Installation

```bash
pip install git+https://github.com/thanhan-a17/agentweb.git
```

```bash
# or with uv
uv tool install git+https://github.com/thanhan-a17/agentweb.git

# with browser/crawl extras for JS-heavy sites
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
| `search` | Searches across 10+ sources — DuckDuckGo, HN, arXiv, Wikipedia, Reddit, GitHub, and more. Automatically picks the best sources for your topic. |
| `fetch` | Grabs full page content. Tries multiple methods — direct HTTP, Jina Reader, stealth browser — and picks whatever works. |
| `research` | Searches then fetches the best results. Returns an evidence pack with scores, gaps, and follow-up ideas. |
| `deep-research` | Breaks down your question, searches multiple angles, ranks findings, spots contradictions, and writes a structured report. No language model needed. |

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
| `--browser` | fetch | Try browser snapshot fallback |
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

**Built for AI agents, not humans.** Every command returns structured data with quality scores and source info — no HTML to scrape, no ads to filter.

- **No API keys.** DuckDuckGo, HN, arXiv, Wikipedia, Reddit, GitHub, Jina Reader — all free, just works.
- **No AI costs.** No language models used anywhere. Predictable, auditable, $0 to run.
- **Smart fallback.** If one method to fetch a page fails, it tries another. HTTP → Jina Reader → stealth browser, whatever it takes.
- **Topic-aware routing.** Automatically figures out what kind of query it is (tech, health, academic, etc.) and picks the best sources.
- **Content quality checks.** Detects CAPTCHAs, blocks, paywalls, and garbage — no need to maintain blocklists.

## Architecture

```
CLI · search · fetch · research · deep-research
  └─ SDK (AgentWeb class)
       └─ Core Engine
            ├─ Specialized extractors (Wikipedia, YouTube, arXiv, Reddit)
            ├─ HTTP fetch with quality scoring
            ├─ Jina Reader fallback
            └─ Browser fallback (stealth browser)
  └─ Providers (10+ free, topic-routed)
       ├─ DuckDuckGo · HN Algolia · Jina + Bing
       ├─ arXiv · Wikipedia · Reddit
       ├─ GitHub · Stack Exchange · OpenStreetMap
       └─ Twitter/X via DuckDuckGo + Jina
  └─ deep-research pipeline (no AI model)
       ├─ Query decomposition → Routing → Parallel sub-agents
       ├─ Ranking → Evidence extraction → Contradiction detection
       └─ Structured report + optional refinement
```

## Design

- **No API keys** — no subscriptions, no AI bills
- **Content quality scoring** — replaces fragile domain allow/block lists
- **Layered extraction** — every fetch tries multiple methods automatically
- **Agent-native output** — JSON with quality scores, provenance, coverage
- **No language models** — predictable, auditable, free
- **Anti-detection** — stealth browser with canvas noise, WebGL spoofing, timing jitter

### Advanced Features

- **Auth profiles** — persistent browser sessions with cookie reuse. Login once, reuse across fetches.
- **Safety guards** — input validation, secret redaction on all output paths.
- **Stealth browser** — Three preset levels (off/standard/aggressive). Canvas noise, WebGL spoofing, and more.

## License

MIT — see [LICENSE](LICENSE).
