#!/usr/bin/env python3
"""
Comprehensive stress test for agentweb search, research, and deep-research.
Evaluates: speed, relevance, factual quality, depth, transparency.
"""
import json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentweb.core import search_web, research
from agentweb.deep_research import deep_research

QUERIES = {
    "search": [
        # Simple factual
        "Tesla stock price today",
        # Complex technical
        "PyTorch vs TensorFlow performance benchmark 2024",
        # Niche
        "CRISPR Cas9 off-target effects recent advances",
        # Multi-entity
        "NVIDIA RTX 5090 vs AMD RX 8900 release date specs",
    ],
    "research": [
        # Broad sector
        "renewable energy investment trends 2024 2025",
        # Technical deep-dive
        "Retrieval Augmented Generation RAG architecture best practices",
        # Current events
        "SpaceX Starship latest test flight results",
    ],
    "deep_research": [
        # Strategic decision support
        "Should enterprises choose OpenAI GPT-4o or Anthropic Claude 3.5 Sonnet for production AI agents",
        # Market analysis
        "Global semiconductor market outlook 2025 AI chip demand supply chain",
        # Current tech product comparison
        "iPhone 16 Pro vs Samsung Galaxy S25 Ultra camera battery performance comparison 2025",
    ],
}


def test_search():
    print("\n=== SEARCH STRESS TEST ===")
    results = []
    for q in QUERIES["search"]:
        start = time.time()
        try:
            res = search_web(q, max_results=8)
            elapsed = time.time() - start
            # Evaluate
            has_results = len(res) > 0
            top_relevant = any(q.split()[0].lower() in (r.title + r.snippet).lower() for r in res[:3])
            print(f"  [{elapsed:.1f}s] '{q[:50]}...' -> {len(res)} results, relevant={top_relevant}")
            results.append({"query": q, "elapsed": elapsed, "ok": has_results and top_relevant, "count": len(res)})
        except Exception as e:
            print(f"  FAIL '{q[:50]}...': {e}")
            results.append({"query": q, "elapsed": -1, "ok": False, "error": str(e)})
    ok_count = sum(1 for r in results if r["ok"])
    print(f"  PASS RATE: {ok_count}/{len(results)}")
    return results


def test_research():
    print("\n=== RESEARCH STRESS TEST ===")
    results = []
    for q in QUERIES["research"]:
        start = time.time()
        try:
            res = research(q, max_results=8, timeout=20)
            elapsed = time.time() - start
            sources = res.get("sources", [])
            coverage = res.get("coverage", {})
            # Quality checks
            has_sources = len(sources) > 0
            has_quality_filter = "quality_passed" in coverage
            avg_quality = sum(s.get("quality_score", 0) for s in sources) / max(1, len(sources))
            ok = has_sources and has_quality_filter and avg_quality >= 2.0
            print(f"  [{elapsed:.1f}s] '{q[:50]}...' -> {len(sources)} sources, coverage={coverage}, avg_quality={avg_quality:.1f}")
            results.append({"query": q, "elapsed": elapsed, "ok": ok, "sources": len(sources), "avg_quality": avg_quality, "coverage": coverage})
        except Exception as e:
            print(f"  FAIL '{q[:50]}...': {e}")
            results.append({"query": q, "elapsed": -1, "ok": False, "error": str(e)})
    ok_count = sum(1 for r in results if r["ok"])
    print(f"  PASS RATE: {ok_count}/{len(results)}")
    return results


def test_deep_research():
    print("\n=== DEEP RESEARCH STRESS TEST ===")
    results = []
    for q in QUERIES["deep_research"]:
        start = time.time()
        try:
            res = deep_research(q, max_results=6, timeout=15)
            elapsed = time.time() - start
            report = res.get("report_json", {})
            metadata = report.get("metadata", {})
            sources = report.get("sources", [])
            findings = report.get("findings", [])
            plan = report.get("plan", {})

            # Quality checks
            has_branches = plan.get("branches", []) and len(plan["branches"]) > 1
            has_findings = len(findings) > 0
            has_sources = len(sources) > 0
            has_diversity = metadata.get("source_diversity", {}).get("unique_domains", 0) >= 2
            has_capping = "capping" in metadata
            has_pipeline = "evidence_pipeline" in metadata
            has_fetch_meta = any("tactics" in s for s in sources)
            avg_quality = sum(s.get("quality_score", 0) for s in sources) / max(1, len(sources))

            ok = has_branches and has_findings and has_sources and has_diversity and has_capping and has_pipeline and avg_quality >= 2.0
            print(f"  [{elapsed:.1f}s] '{q[:60]}...' -> branches={len(plan.get('branches', []))}, findings={len(findings)}, sources={len(sources)}, domains={metadata.get('source_diversity', {}).get('unique_domains', 0)}, avg_quality={avg_quality:.1f}")
            results.append({
                "query": q, "elapsed": elapsed, "ok": ok,
                "branches": len(plan.get("branches", [])),
                "findings": len(findings),
                "sources": len(sources),
                "diversity": metadata.get("source_diversity", {}),
                "capping": metadata.get("capping", {}),
                "pipeline": metadata.get("evidence_pipeline", {}),
                "avg_quality": avg_quality,
            })
        except Exception as e:
            print(f"  FAIL '{q[:50]}...': {e}")
            import traceback
            traceback.print_exc()
            results.append({"query": q, "elapsed": -1, "ok": False, "error": str(e)})
    ok_count = sum(1 for r in results if r["ok"])
    print(f"  PASS RATE: {ok_count}/{len(results)}")
    return results


def main():
    print("AgentWeb Stress Test Suite")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    search_results = test_search()
    research_results = test_research()
    deep_results = test_deep_research()

    summary = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "search": {"total": len(search_results), "passed": sum(1 for r in search_results if r["ok"])},
        "research": {"total": len(research_results), "passed": sum(1 for r in research_results if r["ok"])},
        "deep_research": {"total": len(deep_results), "passed": sum(1 for r in deep_results if r["ok"])},
        "details": {
            "search": search_results,
            "research": research_results,
            "deep_research": deep_results,
        },
    }

    out_path = "/tmp/agentweb-stress-results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults written to {out_path}")

    total = summary["search"]["total"] + summary["research"]["total"] + summary["deep_research"]["total"]
    passed = summary["search"]["passed"] + summary["research"]["passed"] + summary["deep_research"]["passed"]
    print(f"OVERALL: {passed}/{total} tests passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
