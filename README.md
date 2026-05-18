# AgentWeb

**Web access for AI agents. No API keys. No AI bills. No setup.**

Search, fetch, research, and deep-research the web — completely free, no keys required. Uses smart search + content extraction, not language models. Predictable, auditable, costs nothing to run.

## ⚡ Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash
```

## One-Click Install (for AI agents)

> Copy and paste to your AI assistant. The agent handles the rest.

```
Install AgentWeb.

Quickest: run `curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash`

Manual: `uv tool install 'agentweb[browser,crawl,youtube] @ git+https://github.com/thanhan-a17/agentweb.git'`
Or: `pip install git+https://github.com/thanhan-a17/agentweb.git`

Verify: `agentweb search "test" --format json`
```

## Installation

```bash
pip install git+https://github.com/thanhan-a17/agentweb.git
```

```bash
# with browser/crawl extras for JS-heavy sites
pip install 'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git'

# with YouTube transcript support
pip install 'agentweb[youtube] @ git+https://github.com/thanhan-a17/agentweb.git'

# all extras
pip install 'agentweb[browser,crawl,youtube] @ git+https://github.com/thanhan-a17/agentweb.git'
```

```bash
# or with uv
uv tool install git+https://github.com/thanhan-a17/agentweb.git

# with browser/crawl extras for JS-heavy sites
uv tool install 'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git'

# with YouTube transcript support (yt-dlp + youtube_transcript_api)
uv tool install 'agentweb[youtube] @ git+https://github.com/thanhan-a17/agentweb.git'

# with all extras
uv tool install 'agentweb[browser,crawl,youtube] @ git+https://github.com/thanhan-a17/agentweb.git'
```

```bash
# from source
git clone https://github.com/thanhan-a17/agentweb
cd agentweb
uv tool install '.[browser,crawl,youtube]'
```

To upgrade:
```bash
# Quickest — rerun the install script (upgrades uv + agentweb)
curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/install.sh | bash

# Or manually:
uv tool upgrade agentweb
# (uv handles everything, including Python version)
```

```bash
# via pip (requires Python 3.11+ already)
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
| `search` | Searches across 10+ sources — DuckDuckGo, HN, arXiv, Wikipedia, Reddit, GitHub, YouTube, and more. Automatically picks the best sources for your topic. |
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
| `--provider` | search | Restrict to specific provider (e.g. `youtube`, `reddit`, `github`) |

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

- **No API keys.** DuckDuckGo, HN, arXiv, Wikipedia, Reddit, GitHub, Jina Reader, YouTube — all free, just works.
- **No AI costs.** No language models used anywhere. Predictable, auditable, $0 to run.
- **Bot-block detection.** Automatically detects CAPTCHAs, Cloudflare challenges, Jina errors, and network blocks — marks them as failed so agents don't act on garbage.
- **Quality filtering.** Research output automatically filters sources below quality threshold (score < 3.0). Deep research applies the same gate before ranking.
- **Reddit relevance filtering.** Blocks pump subreddits enforces score and query-term overlap minimums. No more getting IBRX stock pump results when you asked about Python.
- **Comparison-aware deep research.** Queries like "A vs B" get 5 specialized branches — per-entity deep dives, direct comparison, pros/cons, and alternatives.

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
       ├─ Twitter/X via DuckDuckGo + Jina
       └─ YouTube via DuckDuckGo + Jina
  └─ deep-research pipeline (no AI model)
       ├─ Query decomposition → Per-entity comparison branches
       ├─ Routing → Parallel sub-agents → Quality gated ranking
       ├─ Evidence extraction → Contradiction detection → Source diversity metrics
       └─ Structured report with capping controls + audit metadata
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
- **YouTube transcripts** — auto-detects YouTube URLs in fetch and extracts video transcripts via yt-dlp or youtube_transcript_api. No API key, no OAuth.
- **Stealth browser** — Three preset levels (off/standard/aggressive). Canvas noise, WebGL spoofing, and more.

## License

MIT — see [LICENSE](LICENSE).
