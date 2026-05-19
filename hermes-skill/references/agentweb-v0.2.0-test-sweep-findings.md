# AgentWeb v0.2.0 — Live Test Sweep Findings

**Date:** May 15, 2026  
**Source invocation:** `cd ~/projects/agentweb && uv run agentweb`  
**Test count:** 30+ cases across all 4 commands  

## Commands Summary

| Command | Verdict | Bugs |
|---------|---------|------|
| `search` | ✅ Stable | 0 |
| `fetch` | ✅ Stable (2 warnings) | 0 |
| `research` | ✅ Reliable | 0 |
| `deep-research` | ⚠️ Working but schema-truncated | 3 documentation/serialization issues |

## Bug 1: Deep-research CLI emits only `report_json`

**Location:** `agentweb/cli.py` line 164  
**Code:** `_emit(result["report_json"], "json", args.output)`  
**Impact:** The full `result` dict (which has `elapsed_seconds`, `report_markdown`, `report_json`) gets truncated to just `report_json`. Consumers lose:
- `elapsed_seconds` (always null in JSON output)
- `report_markdown` (only available via `--format markdown`)

**Reproduction:**
```bash
uv run agentweb deep-research "test query" --format json -o /tmp/out.json
python3 -c "import json; d=json.load(open('/tmp/out.json')); print(d.get('elapsed_seconds'))"  # → None
python3 -c "import json; d=json.load(open('/tmp/out.json')); print(d.get('report_markdown', 'MISSING'))"  # → MISSING
```

**Expected:** Top-level keys should include `elapsed_seconds` and `report_markdown` alongside `report_json`.

## Bug 2: Deep-research sources lack fetch metadata

**Location:** `agentweb/deep_research.py` lines 1792-1804  
**Impact:** The `sources` array in `report_json` only contains ranking metadata (title, url, quality_score, total_score, bm25_score, authority_boost, novel_score, suppression_reason). Missing: `ok`, `status_code`, `source` (tactic), `text`, `text_len`, `tactics`, `warnings`, `links`, `metadata`.

**Reproduction:**
```bash
uv run agentweb deep-research "prompt engineering" --format json -o /tmp/out.json
python3 -c "
import json
d = json.load(open('/tmp/out.json'))
s = d['sources'][0]
for field in ['ok','status_code','source','text','text_len','tactics']:
    print(f'{field}: {s.get(field, \"MISSING\")}')"
# → All MISSING
```

## Bug 3: README/json field name mismatch

**Location:** `agentweb/deep_research.py` `build_report()`  
**Impact:** The documented field name `key_findings` doesn't exist. The actual field is `findings`. Also `evidence` is not a top-level field — it's merged into `findings` with type classifications. `knowledge_gaps` doesn't exist in the JSON output.

**Reproduction:**
```bash
uv run agentweb deep-research "test" --format json -o /tmp/out.json
python3 -c "import json; d=json.load(open('/tmp/out.json')); print('key_findings' in d, 'findings' in d, 'evidence' in d)"
# → False True False
```

## Warning 1: `ok=true` with boilerplate content

**Observation:** example.com returns `ok=true`, `quality_score=2.948`, `text_len=369` — all boilerplate with no substance. The quality scoring is length-biased and doesn't detect "no real content" pages.

**Reproduction:**
```bash
uv run agentweb fetch https://example.com --format json -o /tmp/out.json
python3 -c "
import json
d = json.load(open('/tmp/out.json'))
print(f'ok={d[\"ok\"]} score={d[\"quality_score\"]} text_len={len(d[\"text\"])}')
print(f'text={repr(d[\"text\"][:100])}')"
# → ok=True, but page is literally a 1-paragraph placeholder
```

## Warning 2 (RESOLVED): `--no-jina` on HN

**Previous observation (May 2026, earlier test):** Using `--no-jina` on news.ycombinator.com hung until the timeout period (30s).

**Current status (May 15, 2026):** This is now **resolved**. HN returns 200 via direct HTTP with 4,002 chars, quality_score 3.6, and `source: direct_http`. The Jina reader fallback still works as an alternative but is no longer required for HN.

**Verification:**
```bash
uv run agentweb fetch https://news.ycombinator.com --no-jina --format json -o /tmp/hn.json
python3 -c "
import json
with open('/tmp/hn.json') as f:
    d = json.load(f)
print(f'ok={d[\\\"ok\\\"]} status={d[\\\"status_code\\\"]} source={d[\\\"source\\\"]} quality={d[\\\"quality_score\\\"]} text_len={len(d[\\\"text\\\"])}')
"
# → ok=True status=200 source=direct_http quality=3.601 text_len=4002
```

## Validated Behaviors

| Feature | Status | Evidence |
|---------|--------|----------|
| Range syntax `8-12` | ✅ Works | Resolves to 10 (midpoint) via `_parse_int_or_range()` |
| JSON output to `-o` | ✅ Works | Confirms bytes written on stderr |
| Markdown format | ✅ Works | Clean rendered output with source tags |
| SDK `AgentWeb().search()` | ✅ Works | Returns dict with results list |
| SDK `AgentWeb().fetch()` | ✅ Works | Returns FetchResult dict |
| `search` max-results=0 | ✅ Works | Returns 1 result (clamped) |
| Empty query | ✅ Clean error | `NoResults` |
| Bad URL | ✅ Clean error | `AgentWebError` with DNS detail |
| 404 status | ✅ Clean error | `AgentWebError` |
| Custom header via `--header` | ✅ Works | Passes through to HTTP request |
| Wikipedia fetch | ✅ Works | Uses `wikipedia_api` tactic, title detected |
| arXiv fetch | ✅ Works | Uses `arxiv_abstract` tactic, abstract extracted |
| Google fetch | ✅ Works | Uses `jina_reader` fallback (direct blocked) |
| Research evidence extraction | ✅ Works | 3-4 evidence items per query, source-attributed |
