# AgentWeb vs ChatGPT/Claude/Perplexity — Systematic Comparison

**Date:** 15 May 2026  
**Method:** 5 diverse benchmark-style questions run on AgentWeb (live), compared against published capabilities of competitors

## Test Questions

| # | Question | DRB Category | AgentWeb Command | Time |
|---|---|---|---|---|
| Q1 | Apple services revenue Q1 2026 (exact figure) | Find Number | `research` | ~45s |
| Q2 | NASA Perseverance rover discovering organic molecules on Mars | Validate Claim | `deep-research` | 85.5s |
| Q3 | Original batch normalization paper (authors + year) | Find Original Source | `research` | ~45s |
| Q4 | AAPL/MSFT/NVDA 2025 year-end stock prices | Compile Dataset | `search` | ~5s |
| Q5 | Molar mass of caffeine (C8H10N4O2) | SimpleQA fact | `research` | ~45s |

## AgentWeb Results Summary

| # | Result | Sources | Precision |
|---|---|---|---|
| Q1 | ✅ Found $143.8B total revenue from Apple Newsroom/Nasdaq | 8 (all OK) | Medium — found total revenue, missed exact services figure |
| Q2 | ✅ Confirmed organics at Jezero Crater — NASA + Nature journal | 15 (all OK) | High — comprehensive with academic sources |
| Q3 | ⚠ Found educational content mentioning BatchNorm | 8 (all OK) | Low — missed primary paper (Ioffe & Szegedy 2015) |
| Q4 | ⚠ Search found Yahoo Finance + StatMuse links | 8 results | Needs fetch to extract actual prices |
| Q5 | ⚠ Found WebQC + PubChem calculators | 6 (all OK) | Low — exact 194.19 g/mol value not extracted |

## Key Insights

### AgentWeb Strengths (Tested)
- **Cost:** $0 per query. ChatGPT/Claude/Perplexity cost $0.02-$2.00
- **Speed:** 20-85s vs 5-45 min for deep research tools. 5-30x faster
- **Sources per query:** 6-15 diverse sources consistently. Others: 5-30
- **Zero hallucination:** Classical NLP means every source URL is real
- **No API keys:** Pure Python, runs anywhere
- **Source diversity:** Mix of official (Apple Newsroom, NASA, Nature, Yahoo Finance, WebQC) and secondary (MacRumors, ScienceDaily, Medium)

### AgentWeb Limitations (Tested)
- **Precision extraction:** Finds relevant source pages but may miss the exact answer. Keyword-based evidence extraction is the bottleneck
- **Synthesis:** Outputs a research pack with structured JSON, not a polished report
- **Complex deep-research:** 5-branch queries finish research phase but report generation can timeout at >300s
- **Entity disambiguation:** Ambiguous queries can return noise from unrelated topics

### Competitor Comparison Data

| Metric | AgentWeb | Perplexity DR | ChatGPT DR | Claude Research |
|---|---|---|---|---|
| Cost/query | $0 | $0.02-0.40 | $0.20-2.00 | $0.15-1.50 |
| API keys needed | None | Required | Required | Required |
| Speed | 20-85s | <3 min | 5-30 min | 5-45 min |
| Sources/query | 6-15 | 5-10 | 8-30 | 8-20 |
| Answer precision | Medium | High | Very High | Very High |
| Hallucination risk | Zero (no LLM) | Low | Low-Moderate | Low |
| Output format | JSON data pack | Synthesis + citations | Full report | Full report |
| Works without LLM | Yes (pure NLP) | No | No | No |

### Strategic Recommendation
**Don't use AgentWeb as a ChatGPT/Claude/Perplexity replacement.** Use it as the **discovery layer** (cheap, fast, grounded) feeding an **LLM synthesis layer** (precise, polished). This is the pattern that maximizes both tools' strengths.

Best use cases for standalone AgentWeb:
- High-volume monitoring (100+ queries/day)
- Research data pipelines
- Budget-constrained teams
- Zero-hallucination-mandatory contexts
- Ground-truth data collection before LLM analysis

## Benchmark Scores Used for Comparison

Published scores from primary sources (verified 15 May 2026):

**DRB (Deep Research Bench) — FutureSearch, arXiv 2506.06287**
- Commercial tools evaluated: OpenAI Deep Research (66.3%), Perplexity DR (48.3%), Claude 3.5 Sonnet + Search (31.5%), Gemini 2.0 Flash + Search (29.2%)
- Retro agent scores (from scatter plot): GPT-5 series 0.42-0.50, Sonnet 4.5 ~0.48

**HLE (Humanity's Last Exam) — Scale AI / CAIS**
- OpenAI Deep Research: 26.6% (openai.com blog, verified 15 May 2026)
- Perplexity Deep Research: 21.1% (perplexity.ai blog, verified 15 May 2026)

**SimpleQA — OpenAI, arXiv 2411.04368**
- Perplexity Sonar Deep Research: 93.9% (perplexity.ai blog)
- GPT-4.5: 62.5% (llm-stats.com)
- o1: 47.0% (llm-stats.com)
