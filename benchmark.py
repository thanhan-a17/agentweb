#!/usr/bin/env python3
"""Benchmark suite for AgentWeb real web operations.

Measures latency, response quality, and success/failure rates across:
- DuckDuckGo search (2 queries)
- Wikipedia API search (2 queries)
- fetch_url for 3 public URLs
- research() end-to-end for 2 queries
- Blocking detection accuracy on real pages

Outputs /tmp/agentweb_benchmark.json
"""

from __future__ import annotations

import json
import time
import sys
import os

# Ensure agentweb is importable from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentweb import core
from agentweb.authenticity import ContentAuthenticity


def ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def run_search_benchmark(label: str, service: str, query: str, timeout: int = 10) -> dict:
    """Run a single-search operation and return metrics."""
    start = time.monotonic()
    errors = []
    results = []
    try:
        if service == "duckduckgo":
            results = core.search_web(query, timeout=timeout, services=["duckduckgo"])
        elif service == "wikipedia":
            results = core.search_web(query, timeout=timeout, services=["wikipedia"])
        else:
            results = core.search_web(query, timeout=timeout)
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")

    elapsed = ms(start)
    total_chars = sum(len(r.title) + len(r.snippet) for r in results)
    quality = 1.0 if results else 0.0
    # Quality: any results with snippets count as good
    if results:
        quality = min(1.0, len(results) / 3.0)  # 3+ results = full score

    return {
        "operation": "search",
        "service": service,
        "label": label,
        "query": query,
        "elapsed_ms": elapsed,
        "response_length_chars": total_chars,
        "result_count": len(results),
        "quality_score": round(quality, 3),
        "success": len(results) > 0,
        "errors": errors,
    }


def run_fetch_benchmark(label: str, url: str, timeout: int = 15) -> dict:
    """Run a single fetch_url operation and return metrics."""
    start = time.monotonic()
    errors = []
    result = None
    try:
        result = core.fetch_url(url, timeout=timeout, use_jina=True)
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")

    elapsed = ms(start)

    if result:
        text_len = len(result.text)
        title_len = len(result.title)
        q = result.quality_score()
        return {
            "operation": "fetch_url",
            "label": label,
            "url": url,
            "elapsed_ms": elapsed,
            "response_length_chars": text_len + title_len,
            "title": result.title or "",
            "status_code": result.status_code,
            "source": result.source,
            "tactics": result.tactics,
            "warnings": result.warnings,
            "quality_score": round(q, 3),
            "success": result.ok,
            "errors": errors,
        }
    else:
        return {
            "operation": "fetch_url",
            "label": label,
            "url": url,
            "elapsed_ms": elapsed,
            "response_length_chars": 0,
            "quality_score": 0.0,
            "success": False,
            "errors": errors or ["fetch_returned_none"],
        }


def run_research_benchmark(label: str, query: str, timeout: int = 15) -> dict:
    """Run a single research() operation and return metrics."""
    start = time.monotonic()
    errors = []
    pack = None
    try:
        pack = core.research(query, timeout=timeout, max_results=4, max_chars=3000)
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")

    elapsed = ms(start)

    if pack and pack.get("status"):
        sources = pack.get("sources", [])
        search_results = pack.get("search_results", [])
        evidence = pack.get("answer_pack", {}).get("evidence", [])
        total_chars = sum(
            s.get("text", "") and len(s["text"]) or 0 for s in sources
        )
        qs_scores = [s.get("quality_score", 0) for s in sources if s.get("quality_score")]
        avg_qs = round(sum(qs_scores) / len(qs_scores), 3) if qs_scores else 0.0
        return {
            "operation": "research",
            "label": label,
            "query": query,
            "elapsed_ms": elapsed,
            "response_length_chars": total_chars,
            "search_result_count": len(search_results),
            "source_count": len(sources),
            "evidence_count": len(evidence),
            "status": pack.get("status"),
            "avg_source_quality": avg_qs,
            "quality_score": round(min(10.0, avg_qs + len(sources)), 3),
            "success": pack.get("status") == "ok",
            "errors": errors,
        }
    else:
        return {
            "operation": "research",
            "label": label,
            "query": query,
            "elapsed_ms": elapsed,
            "response_length_chars": 0,
            "quality_score": 0.0,
            "success": False,
            "errors": errors or ["research_returned_none"],
        }


def run_blocking_detection_test() -> dict:
    """Test blocking detection accuracy with known real pages.

    Detects whether known-clean and known-blocked patterns are correctly identified.
    """
    test_pages = [
        # Known publicly accessible pages (should NOT look blocked)
        ("https://example.com", False, "basic_accessible"),
        ("https://httpbin.org/get", False, "api_accessible"),
        ("https://en.wikipedia.org/wiki/Python_(programming_language)", False, "wiki_accessible"),
        # Typical blocking patterns (likely blocked/difficult pages)
        # These help test if our detection catches real blocking patterns
        # cloudflare pages often have "checking your browser"
        ("https://www.cloudflare.com", True, "cloudflare_may_block"),
    ]

    results = []
    correct = 0
    for url, expected_blocked, label in test_pages:
        start = time.monotonic()
        try:
            result = core.fetch_url(url, timeout=10, use_jina=True)
        except Exception as e:
            elapsed = ms(start)
            results.append({
                "test": label,
                "url": url,
                "elapsed_ms": elapsed,
                "success": False,
                "detected_blocked": True,
                "expected_blocked": expected_blocked,
                "prediction_correct": expected_blocked is True,
                "error": str(e),
                "quality_score": 0.0,
            })
            if expected_blocked:
                correct += 1
            continue

        elapsed = ms(start)
        combined_text = f"{result.title or ''} {result.text or ''}"
        detected_blocked = ContentAuthenticity.is_blocked(combined_text, "", result.status_code)
        # Also check quality score being very negative
        if result.quality_score() < -5.0:
            detected_blocked = True

        prediction_correct = detected_blocked == expected_blocked
        if prediction_correct:
            correct += 1

        results.append({
            "test": label,
            "url": url,
            "elapsed_ms": elapsed,
            "ok": result.ok,
            "status_code": result.status_code,
            "source": result.source,
            "detected_blocked": detected_blocked,
            "expected_blocked": expected_blocked,
            "prediction_correct": prediction_correct,
            "quality_score": round(result.quality_score(), 3),
            "warnings": result.warnings,
            "response_length_chars": len(result.text) + len(result.title),
        })

    return {
        "operation": "blocking_detection",
        "tests": results,
        "accuracy": round(correct / len(test_pages), 3),
        "total_tests": len(test_pages),
        "correct": correct,
    }


def main():
    print("=" * 60)
    print("AgentWeb Real Web Benchmark Suite")
    print("=" * 60)

    all_results = {
        "benchmark_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {},
        "operations": [],
    }

    results_list = []

    # ── 1. Search benchmarks ──────────────────────────────────────────────
    print("\n--- Search Benchmarks ---")

    # DuckDuckGo searches
    searches = [
        ("DDG: Python async programming", "duckduckgo", "Python async programming best practices 2025"),
        ("DDG: LLM quantization methods", "duckduckgo", "LLM quantization methods comparison 2025"),
        ("Wiki: Large language model", "wikipedia", "Large language model"),
        ("Wiki: Machine learning", "wikipedia", "Machine learning"),
    ]

    for label, service, query in searches:
        r = run_search_benchmark(label, service, query, timeout=10)
        results_list.append(r)
        status = "✓" if r["success"] else "✗"
        print(f"  {status} {label}: {r['elapsed_ms']}ms, {r['result_count']} results, quality={r['quality_score']}")

    # ── 2. Fetch benchmarks ──────────────────────────────────────────────
    print("\n--- Fetch Benchmarks ---")

    fetches = [
        ("Example.com", "https://example.com"),
        ("HTTPBin GET", "https://httpbin.org/get"),
        ("Wikipedia Python", "https://en.wikipedia.org/wiki/Python_(programming_language)"),
    ]

    for label, url in fetches:
        r = run_fetch_benchmark(label, url, timeout=15)
        results_list.append(r)
        status = "✓" if r["success"] else "✗"
        src = r.get("source", "?")
        print(f"  {status} {label}: {r['elapsed_ms']}ms, {r['response_length_chars']} chars, src={src}, qs={r['quality_score']}")

    # ── 3. Research end-to-end benchmarks ────────────────────────────────
    print("\n--- Research Benchmarks ---")

    researches = [
        ("Research: Python web frameworks", "best Python web framework for async APIs 2025"),
        ("Research: Local LLM hardware", "best hardware for running local LLMs 2025"),
    ]

    for label, query in researches:
        r = run_research_benchmark(label, query, timeout=15)
        results_list.append(r)
        status = "✓" if r["success"] else "✗"
        print(f"  {status} {label}: {r['elapsed_ms']}ms, {r['source_count']} sources, {r['evidence_count']} evidence, qs={r['quality_score']}")

    # ── 4. Blocking detection benchmarks ────────────────────────────────
    print("\n--- Blocking Detection ---")

    block_results = run_blocking_detection_test()
    results_list.append(block_results)
    print(f"  Accuracy: {block_results['accuracy']} ({block_results['correct']}/{block_results['total_tests']})")
    for t in block_results["tests"]:
        icon = "✓" if t["prediction_correct"] else "✗"
        detected = "BLOCKED" if t["detected_blocked"] else "OK"
        expected = "BLOCKED" if t["expected_blocked"] else "OK"
        print(f"    {icon} {t['test']}: detected={detected}, expected={expected}, qs={t['quality_score']}")

    # ── Aggregate stats ───────────────────────────────────────────────────
    print("\n--- Summary ---")

    all_ops = [r for r in results_list if r["operation"] != "blocking_detection"]
    search_ops = [r for r in all_ops if r["operation"] == "search"]
    fetch_ops = [r for r in all_ops if r["operation"] == "fetch_url"]
    research_ops = [r for r in all_ops if r["operation"] == "research"]

    total_elapsed = sum(r["elapsed_ms"] for r in all_ops)
    total_success = sum(1 for r in all_ops if r["success"])
    total_ops = len(all_ops)

    summary = {
        "total_operations": total_ops,
        "successful": total_success,
        "failed": total_ops - total_success,
        "success_rate": round(total_success / total_ops, 3) if total_ops else 0,
        "total_elapsed_ms": total_elapsed,
        "avg_elapsed_ms": round(total_elapsed / total_ops) if total_ops else 0,
        "search": {
            "count": len(search_ops),
            "avg_elapsed_ms": round(sum(r["elapsed_ms"] for r in search_ops) / len(search_ops)) if search_ops else 0,
            "avg_results": round(sum(r["result_count"] for r in search_ops) / len(search_ops), 1) if search_ops else 0,
            "success_rate": round(sum(1 for r in search_ops if r["success"]) / len(search_ops), 3) if search_ops else 0,
        },
        "fetch": {
            "count": len(fetch_ops),
            "avg_elapsed_ms": round(sum(r["elapsed_ms"] for r in fetch_ops) / len(fetch_ops)) if fetch_ops else 0,
            "avg_response_chars": round(sum(r["response_length_chars"] for r in fetch_ops) / len(fetch_ops)) if fetch_ops else 0,
            "avg_quality_score": round(sum(r["quality_score"] for r in fetch_ops) / len(fetch_ops), 3) if fetch_ops else 0,
            "success_rate": round(sum(1 for r in fetch_ops if r["success"]) / len(fetch_ops), 3) if fetch_ops else 0,
        },
        "research": {
            "count": len(research_ops),
            "avg_elapsed_ms": round(sum(r["elapsed_ms"] for r in research_ops) / len(research_ops)) if research_ops else 0,
            "avg_sources": round(sum(r.get("source_count", 0) for r in research_ops) / len(research_ops), 1) if research_ops else 0,
            "avg_quality_score": round(sum(r["quality_score"] for r in research_ops) / len(research_ops), 3) if research_ops else 0,
            "success_rate": round(sum(1 for r in research_ops if r["success"]) / len(research_ops), 3) if research_ops else 0,
        },
        "blocking_detection_accuracy": block_results.get("accuracy", 0),
        "blocking_detection_correct": block_results.get("correct", 0),
        "blocking_detection_total": block_results.get("total_tests", 0),
    }

    all_results["summary"] = summary
    all_results["operations"] = results_list

    output_path = "/tmp/agentweb_benchmark.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"RESULTS saved to {output_path}")
    print(f"{'='*60}")
    print(f"Total operations: {summary['total_operations']}")
    print(f"Success rate: {summary['success_rate']*100:.1f}% ({summary['successful']}/{summary['total_operations']})")
    print(f"Total time: {summary['total_elapsed_ms']}ms | Avg: {summary['avg_elapsed_ms']}ms")
    print(f"  Search:   {summary['search']['success_rate']*100:.0f}% success, avg {summary['search']['avg_elapsed_ms']}ms, avg {summary['search']['avg_results']} results")
    print(f"  Fetch:    {summary['fetch']['success_rate']*100:.0f}% success, avg {summary['fetch']['avg_elapsed_ms']}ms, avg qs={summary['fetch']['avg_quality_score']}")
    print(f"  Research: {summary['research']['success_rate']*100:.0f}% success, avg {summary['research']['avg_elapsed_ms']}ms, avg {summary['research']['avg_sources']} sources, avg qs={summary['research']['avg_quality_score']}")
    print(f"  Blocking Detection: {summary['blocking_detection_accuracy']*100:.0f}% accuracy ({summary['blocking_detection_correct']}/{summary['blocking_detection_total']})")
    print(f"{'='*60}")
    return summary


if __name__ == "__main__":
    main()
