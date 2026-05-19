# Multi-Source Research with AgentWeb — Worked Examples

## When to Use Multi-Angle vs Single Query

| Scenario | Approach | Why |
|---|---|---|
| Specific known entity ("DeepSeek V4 Flash") | `deep-research` first, then supplement with `fetch` | Deep-research's BM25 ranking handles narrow queries well |
| Vague/ambiguous topic ("Le J' Cafe") | `search` → identify sources → `fetch` top 3-5 | Need to find what it IS first before extracting detail |
| Open-ended community question ("how are people using X for Y") | Multiple `search` queries with different angles → parallel `fetch` → Python extraction | No single query captures all angles |
| Conflicting claims / comparison ("X vs Y") | Progressive refinement: deep-research → targeted parallel fetch → gap search → credibility-ranked synthesis | Need decomposition first, then source authority weighting to resolve contradictions |

## Handling Truncated Content

`fetch` truncates at `--max-chars` (default 12000). When the content cuts off mid-sentence:

1. Re-fetch with higher `--max-chars 20000` to get more
2. If the page is a Next.js/single-page app, try `--format markdown` to get cleaner extraction
3. If `execute_code` isn't available and you need deeper content, use `grep` / `head` / `tail` on the JSON file in terminal:
   ```bash
   python3 -c "import json; d=json.load(open('/tmp/f.json')); print(d.get('text','')[:500])"
   ```

## When deep-research Underperforms

`deep-research` with intent "general" (low effort) may produce shallow results. Signals:
- Only 1 branch generated
- Key findings are obvious/repetitive
- No contradictions found (likely means low source diversity)

If that happens, fall back to manual multi-angle search + fetch. It takes more tool calls but produces better depth.

## YouTube Content Repurposing Pattern

For extracting structured content from video transcripts:
```python
terminal("agentweb fetch \"https://youtube.com/watch?v=ID\" --max-chars 15000 -o /tmp/yt.json")
# Then extract transcript segments with keyword matching
```

The `youtube-content` skill handles this natively — use that when available.

## Source Credibility Classification

When synthesizing multiple sources, classify each into a credibility tier and weight accordingly:

| Tier | Label | Examples | How to identify |
|------|-------|----------|-----------------|
| 1 | **Primary** | Official company blogs (openai.com, blog.google), published papers, independent benchmark orgs (artificialanalysis.ai, benchlm.ai, lmcouncil.ai) | .edu, .org (known), official product domains; disclose methodology; run their own evals |
| 2 | **Secondary** | Reputable tech journalism (Ars Technica, The Verge, TechCrunch), expert analysis with methodology disclosure | Named author, disclosed methodology, editorial standards, corrections policy |
| 3 | **Tertiary** | Aggregators, re-reporters, promotional blogs, AI-generated content farms | No original research; cites other articles; thinly veiled product promotion; no author bio |
| 4 | **Developer tests** | Individual blog posts, small-sample experiments, GitHub gists | Small N, single-perspective, no controls; useful for qualitative feel and real-world gotchas, not for precise head-to-head claims |

**When claims conflict:** Tier 1 wins unless contradicted by multiple Tier 2 sources that agree. Version/date information is critical — two sources can both be correct for different model versions (this is the #1 cause of apparent contradictions in fast-moving fields like LLMs). Always check: what specific version/date was tested?

**Signs of re-reporting chain (tertiary content):**
- Article claims from "OpenAI's blog" but doesn't link it
- Benchmark numbers that exactly match a single source but presented as independent
- No new data, only commentary
- Publication date after the original announcement but before any independent testing
- Overly uniform positivity or negativity (no tradeoffs mentioned)

## Benchmark Score Verification Checklist

When researching LLM/model benchmark scores, verify each data point before using it:

- [ ] Cross-reference the score from ≥2 independent sources
- [ ] Check the publication date — LLM scores change fast and older scores for the same model name may be for a different version
- [ ] Confirm the specific model/tool version tested (e.g., "o3-based Deep Research" vs "GPT-4o with browsing")
- [ ] Verify the benchmark methodology is disclosed (peer-reviewed paper, human baseline, automated grading, etc.)
- [ ] Note whether scores are self-reported (vendor blog) vs independently verified (third-party eval)
- [ ] For deep-research tools: distinguish between "model capability" benchmarks (SimpleQA, HLE) and "agent tool-use" benchmarks (DRB, GAIA)
- [ ] Check whether the benchmark uses frozen data (DRB RetroSearch) or live web (SimpleQA)

**Data extraction for JS-rendered leaderboards:**
- Many modern leaderboards use NextJS/RSC/React that `agentweb fetch` cannot extract via HTTP/Jina
- Strategy: fetch the arXiv paper or blog post first (static text) → those usually contain the published scores
- Fallback: `agentweb fetch --browser` + `browser_vision` on screenshots
- Last resort: check for API endpoints at `/api/leaderboard` or similar paths

**Known reliable benchmark data sources:**
- arXiv papers (peer-reviewed, static)
- Official company blogs (primary source)
- llm-stats.com (comprehensive but NextJS — text-extractable from RSC payload)
- glasp.co (comparison tables in static markdown)
- lmcouncil.ai (multi-benchmark comparison)

