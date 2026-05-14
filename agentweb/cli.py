"""Command line interface for AgentWeb."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import FetchResult, format_markdown_fetch, format_markdown_research
from .sdk import AgentWeb


def _headers(values: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values or []:
        if ":" not in value:
            raise SystemExit(f"Invalid header {value!r}; expected 'Name: value'")
        k, v = value.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def _emit(data, fmt: str, output: str | None = None) -> None:
    if fmt == "json":
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    else:
        text = str(data)
    if output:
        Path(output).expanduser().write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentweb",
        description="State-of-the-art web access CLI for AI agents: search, fetch, extract, and source-pack.",
    )
    p.add_argument("--version", action="version", version=f"AgentWeb {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="Search the web with resilient no-key providers.")
    s.add_argument("query")
    s.add_argument("--max-results", type=int, default=8)
    s.add_argument("--timeout", type=int, default=20)
    s.add_argument("--format", choices=["json", "markdown"], default="json")
    s.add_argument("--output", "-o")

    f = sub.add_parser("fetch", help="Fetch one URL using layered extraction tactics.")
    f.add_argument("url")
    f.add_argument("--timeout", type=int, default=20)
    f.add_argument("--max-chars", type=int, default=12000)
    f.add_argument("--cookies", help="Cookie header string or Netscape cookies.txt path for logged-in pages.")
    f.add_argument("--header", action="append", help="Extra request header, e.g. Authorization: Bearer TOKEN")
    f.add_argument("--no-jina", action="store_true", help="Disable Jina reader fallback.")
    f.add_argument("--browser", action="store_true", help="Try agent-browser snapshot fallback if installed.")
    f.add_argument("--format", choices=["json", "markdown"], default="json")
    f.add_argument("--output", "-o")

    r = sub.add_parser("research", help="Search + fetch top sources and emit an agent-ready evidence pack.")
    r.add_argument("query")
    r.add_argument("--max-results", type=int, default=6)
    r.add_argument("--timeout", type=int, default=20)
    r.add_argument("--max-chars", type=int, default=6000)
    r.add_argument("--format", choices=["json", "markdown"], default="json")
    r.add_argument("--output", "-o")

    dr = sub.add_parser("deep-research", help="Multi-branch deep research: decompose, parallel fetch, BM25 rank, extract evidence. No LLM.")
    dr.add_argument("query")
    dr.add_argument("--max-results", type=int, default=8)
    dr.add_argument("--timeout", type=int, default=20)
    dr.add_argument("--max-chars", type=int, default=6000)
    dr.add_argument("--refinement-loops", type=int, default=1)
    dr.add_argument("--format", choices=["json", "markdown"], default="markdown")
    dr.add_argument("--output", "-o")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    aw = AgentWeb()
    try:
        if args.command == "search":
            result = aw.search(args.query, max_results=args.max_results, timeout=args.timeout)
            results = result["results"]
            if args.format == "markdown":
                lines = [f"# AgentWeb search: {args.query}", ""]
                for i, item in enumerate(results, 1):
                    lines.append(f"{i}. [{item['title']}]({item['url']})")
                    if item.get("snippet"):
                        lines.append(f"   {item['snippet']}")
                    lines.append(f"   Source: {item['source']}")
                _emit("\n".join(lines) + "\n", "text", args.output)
            else:
                _emit({"query": args.query, "results": results, "meta": result.get("meta")}, "json", args.output)
            return 0

        if args.command == "fetch":
            result = aw.fetch(
                args.url,
                timeout=args.timeout,
                max_chars=args.max_chars,
                cookies=args.cookies,
                headers=_headers(args.header),
                use_jina=not args.no_jina,
                use_browser=args.browser,
            )
            if args.format == "markdown":
                # Reconstruct FetchResult from dict for markdown formatter
                fr = FetchResult(
                    url=result.get("url", args.url),
                    final_url=result.get("final_url", ""),
                    ok=result.get("ok", False),
                    status_code=result.get("status_code"),
                    source=result.get("source", ""),
                    title=result.get("title", ""),
                    text=result.get("text", ""),
                    markdown=result.get("markdown", ""),
                    links=result.get("links", []),
                    metadata=result.get("metadata", {}),
                    tactics=result.get("tactics", []),
                    warnings=result.get("warnings", []),
                    elapsed_ms=result.get("elapsed_ms", 0),
                )
                _emit(format_markdown_fetch(fr, max_chars=args.max_chars), "text", args.output)
            else:
                _emit(result, "json", args.output)
            return 0 if result.get("ok") else 2

        if args.command == "research":
            pack = aw.research(args.query, max_results=args.max_results, timeout=args.timeout, max_chars=args.max_chars)
            if args.format == "markdown":
                _emit(format_markdown_research(pack), "text", args.output)
            else:
                _emit(pack, "json", args.output)
            return 0

        if args.command == "deep-research":
            result = aw.deep_research(
                args.query,
                max_results=args.max_results,
                timeout=args.timeout,
                max_chars=args.max_chars,
                refinement_loops=args.refinement_loops,
            )
            if args.format == "markdown":
                _emit(result["report_markdown"], "text", args.output)
            else:
                _emit(result["report_json"], "json", args.output)
            return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        sys.stderr.write(f"agentweb: {type(exc).__name__}: {exc}\n")
        return 1
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
