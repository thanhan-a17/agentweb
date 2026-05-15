#!/usr/bin/env python3
"""Test 5 diverse deep-research queries against AgentWeb CLI."""

import json
import subprocess
import sys
import time
import os

os.chdir("/Users/agent/projects/agentweb")

QUERIES = [
    {
        "name": "comparison",
        "query": "compare Python vs Rust for web backend development in 2026",
        "desc": "Comparison query — should trigger multi-branch pipeline, route to multiple providers"
    },
    {
        "name": "factual_niche",
        "query": "what is the boiling point of water at different altitudes sea level mountain",
        "desc": "Factual/int-errogative — tests Wikipedia routing, entity extraction"
    },
    {
        "name": "recent_trending",
        "query": "latest advances in AI drug discovery 2025 2026 breakthroughs",
        "desc": "Temporal/current — tests freshness scoring, news routing, arxiv"
    },
    {
        "name": "list_comprehensive",
        "query": "list all major Y Combinator funded companies in climate tech and clean energy",
        "desc": "List query — tests breadth-first coverage, HN routing"
    },
    {
        "name": "tricky_ambiguous",
        "query": "H1 centro americano coffee best brewing methods",
        "desc": "Tricky/ambiguous — tests semantic routing fallback, keyword extraction"
    },
]

def run_deep_research(query, name, timeout=60):
    """Run agentweb deep-research and capture JSON output."""
    print(f"\n{'='*70}")
    print(f"TEST: {name}")
    print(f"Query: {query}")
    print(f"{'='*70}")

    start = time.time()

    try:
        result = subprocess.run(
            ["uv", "run", "agentweb", "deep-research", query, "--format", "json", "--max-results", "6", "--timeout", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 10
        )
        elapsed = time.time() - start

        print(f"Return code: {result.returncode}")
        print(f"Elapsed: {elapsed:.1f}s")

        if result.returncode != 0:
            print(f"STDERR: {result.stderr[:500]}")
            return {"status": "FAIL", "error": result.stderr[:500]}

        # Parse JSON from stdout
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Try to find JSON in output
            out = result.stdout
            print(f"Raw output (first 500 chars): {out[:500]}")
            print(f"STDERR: {result.stderr[:500]}")
            return {"status": "PARSE_ERROR", "raw": out[:500]}

        # Validate structure
        issues = []
        info = {}

        # Check for report_json keys (via CLI json output)
        if "query" not in data:
            issues.append("MISSING: query field in JSON output")
        if "findings" in data:
            info["has_findings"] = True
            info["finding_count"] = len(data["findings"])
        elif "report_json" in data:
            info["has_report_json"] = True
            rj = data["report_json"]
            info["finding_count"] = len(rj.get("findings", []))
            if "findings" in rj:
                info["findings_key"] = "findings (inside report_json)"
        else:
            issues.append("MISSING: no findings nor report_json in output")
            # Show what keys are present
            info["available_keys"] = list(data.keys())

        if "elapsed_seconds" not in data:
            issues.append("MISSING: elapsed_seconds in JSON output")

        if "sources" not in data:
            if "report_json" in data and "sources" in data["report_json"]:
                info["sources_via_report_json"] = True
            else:
                issues.append("MISSING: sources in JSON output")

        # Check if sources have fetch metadata (from memory: sources in report_json lack ok, source, text_len)
        if "report_json" in data:
            sources = data["report_json"].get("sources", [])
        elif "sources" in data:
            sources = data["sources"]
        else:
            sources = []

        missing_fetch_meta = []
        for s in sources[:3]:
            if "ok" not in s:
                missing_fetch_meta.append("ok")
            if "text_len" not in s:
                missing_fetch_meta.append("text_len")
            if "source" not in s and "provider" not in s:
                missing_fetch_meta.append("source/provider")
        info["missing_source_fields"] = list(set(missing_fetch_meta))

        result_data = {
            "status": "PASS" if not issues else "ISSUES",
            "name": name,
            "query": query,
            "elapsed": round(elapsed, 1),
            "issues": issues,
            "info": info,
        }

        if issues:
            for i in issues:
                print(f"  ⚠  {i}")
        if info.get("finding_count"):
            print(f"  → {info['finding_count']} findings extracted")
        print(f"  → Result: {result_data['status']}")

        return result_data

    except subprocess.TimeoutExpired:
        print(f"  ⚠  TIMEOUT after {timeout + 10}s")
        return {"status": "TIMEOUT", "name": name, "query": query, "elapsed": timeout}
    except Exception as e:
        print(f"  ⚠  ERROR: {e}")
        return {"status": "ERROR", "name": name, "query": query, "error": str(e)}


if __name__ == "__main__":
    all_results = []
    for q in QUERIES:
        r = run_deep_research(q["query"], q["name"], timeout=60)
        all_results.append(r)

    print("\n\n" + "="*70)
    print("FINAL SUMMARY")
    print("="*70)
    for r in all_results:
        status_icon = "✅" if r["status"] == "PASS" else "⚠️" if r["status"] == "ISSUES" else "❌"
        print(f"{status_icon} {r['name']}: {r['status']} ({r['elapsed']}s)")
        if r.get("issues"):
            for i in r["issues"]:
                print(f"     {i}")
