# LLM Search/Research Benchmark Research — 15 May 2026

**Goal:** Find the top 3 LLM search/research benchmarks with published scores for ChatGPT Deep Research, Claude Research, and Perplexity Deep Research, then run AgentWeb on representative tasks.

## Benchmarks Selected

### 1. DRB (Deep Research Bench) — FutureSearch
- **URL:** https://futuresearch.ai/deep-research-bench/
- **Paper:** arXiv 2506.06287 (ICLR 2026)
- **Type:** 89-169 multi-step web research tasks, 8 categories
- **Methodology:** Frozen web snapshots via "RetroSearch" for reproducibility. Features: frozen Serper API + cached page snapshots.
- **Key scores (from scatter plot, May 2025 eval):**
  - GPT-5 series: 0.42–0.50
  - Claude Sonnet 4.5: ~0.48
  - Claude Haiku 4.5: ~0.455
  - Gemini 3 Flash: 0.48–0.50
  - Gemini 3 Pro: ~0.462
- **Categories tested:** Find Number, Derive Number, Find Dataset, Compile Dataset, Gather Evidence, Validate Claim, Find Original Source
- **Data extraction notes:** Page is NextJS RSC payload — table cells empty in fetch. Scatter plot data extracted via `browser_vision`.

### 2. SimpleQA — OpenAI
- **URL:** https://llm-stats.com/benchmarks/simpleqa
- **Paper:** arXiv 2411.04368
- **Type:** 4,326 short-form factuality questions, single indisputable answers
- **Methodology:** Adversarially collected against GPT-4 responses. Automated grading via API. 46+ models tested.
- **Key scores (from llm-stats.com leaderboard, as of 15 May 2026):**
  - DeepSeek-V3.2-Exp: 97.1%
  - Grok 4 Fast: 95.0%
  - DeepSeek-V3.1: 93.4%
  - GPT-4.5: 62.5%
  - Gemini 2.5 Pro: 50.8%
  - o1: 47.0%
  - GPT-4o: ~38%
- **Perplexity-specific:** Sonar Deep Research scored **93.9%** (self-reported, Feb 2025 launch blog)

### 3. HLE (Humanity's Last Exam) — Scale AI / CAIS
- **URL:** https://lastexam.ai/
- **Type:** 3,000 expert-level multi-domain questions
- **Methodology:** Questions at the boundary of human knowledge, curated by domain experts.
- **Key scores:**
  - OpenAI Deep Research (o3-based): **26.6%** (launch blog, Feb 2025)
  - Perplexity Deep Research (Sonar): **21.1%** (launch blog, Feb 2025)
  - Claude Research: not publicly reported
  - Gemini Deep Research: not publicly reported

## AgentWeb Task Execution Results

| Task Type | Query | AgentWeb Command | Result |
|---|---|---|---|
| SimpleQA | "Atomic mass of most stable Fermium isotope" | `research` | ✅ 257 u (Fm-257), 8 sources converging, 85KB output |
| DRB-style | "Nvidia Q4 2025 data center revenue from official earnings" | `deep-research` | ⚠ Timed out at 120s (5 branches, needed >120s) |
| HLE-style | "mRNA vs viral vector COVID booster efficacy with clinical trials" | `deep-research` | ⚠ Timed out at 120s (5 branches, needed >120s) |

**Key finding:** `research` command handles factoid-style questions well (30-50s). `deep-research` with 5+ branches needs ≥180s timeout.

## Best Sources for LLM Benchmark Data

| Priority | Source | Why | AgentWeb-friendly? |
|---|---|---|---|
| 1 | arXiv papers (arxiv.org) | Peer-reviewed, static, authoritative | ✅ Yes (abstract extraction works) |
| 2 | llm-stats.com | Comprehensive leaderboards, updated frequently | ⚠ NextJS (text extractable from RSC payload) |
| 3 | glasp.co | Comparison tables in markdown | ✅ Yes (Jina reader works) |
| 4 | Official company blogs | Primary source for self-reported scores | ✅ Yes |
| 5 | aimultiple.com | DR-50/DR-2T benchmarks | ⚠ NextJS, chart data needs browser |
| 6 | lmcouncil.ai | Multi-benchmark comparison | ⚠ NextJS |

## Verification Methodology

- Cross-reference ≥2 independent sources for every score
- Check publication date (LLM scores change fast)
- Note self-reported vs independent verification
- Confirm the specific model/tool version tested
- Check whether benchmark uses frozen data (DRB) or is live-verified (SimpleQA automated grading)
