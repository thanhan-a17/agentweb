"""Command line interface for AgentWeb."""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    from . import __version__
except ImportError:  # Editable CLI can be shadowed by Hermes' namespace path.
    try:
        __version__ = version("agentweb")
    except PackageNotFoundError:
        __version__ = "0.1.0"
from .core import (
    fetch_url,
    format_markdown_fetch,
    format_markdown_research,
    list_search_services,
    research,
    search_web,
)


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
    s.add_argument("--service", action="append", help="Restrict discovery to a service; repeatable. Use 'all' for every service.")
    s.add_argument("--format", choices=["json", "markdown"], default="json")
    s.add_argument("--output", "-o")

    svc = sub.add_parser("services", help="List available search/discovery services.")
    svc.add_argument("--format", choices=["json", "markdown"], default="json")
    svc.add_argument("--output", "-o")

    f = sub.add_parser("fetch", help="Fetch one URL using layered extraction tactics.")
    f.add_argument("url")
    f.add_argument("--timeout", type=int, default=20)
    f.add_argument("--max-chars", type=int, default=12000)
    f.add_argument("--cookies", help="Cookie header string or Netscape cookies.txt path for logged-in pages.")
    f.add_argument("--header", action="append", help="Extra request header, e.g. Authorization: Bearer TOKEN")
    f.add_argument("--no-jina", action="store_true", help="Disable Jina reader fallback.")
    f.add_argument("--camoufox", action="store_true", help="Try Camoufox browser fallback for bot-protected pages if installed.")
    f.add_argument("--browser", action="store_true", help="Try agent-browser snapshot fallback if installed.")
    f.add_argument("--format", choices=["json", "markdown"], default="json")
    f.add_argument("--output", "-o")

    r = sub.add_parser("research", help="Search + fetch top sources and emit an agent-ready evidence pack.")
    r.add_argument("query")
    r.add_argument("--max-results", type=int, default=6)
    r.add_argument("--timeout", type=int, default=20)
    r.add_argument("--max-chars", type=int, default=6000)
    r.add_argument("--service", action="append", help="Restrict discovery to a service; repeatable. Use 'all' for every service.")
    r.add_argument("--no-camoufox", action="store_true", help="Disable Camoufox fallback during source fetching.")
    r.add_argument("--format", choices=["json", "markdown"], default="json")
    r.add_argument("--output", "-o")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "search":
            results = [r.to_dict() for r in search_web(args.query, max_results=args.max_results, timeout=args.timeout, services=args.service)]
            if args.format == "markdown":
                lines = [f"# AgentWeb search: {args.query}", ""]
                for i, item in enumerate(results, 1):
                    lines.append(f"{i}. [{item['title']}]({item['url']})")
                    if item.get("snippet"):
                        lines.append(f"   {item['snippet']}")
                    lines.append(f"   Source: {item['source']}")
                _emit("\n".join(lines) + "\n", "text", args.output)
            else:
                _emit({"query": args.query, "results": results}, "json", args.output)
            return 0

        if args.command == "services":
            services = list_search_services()
            if args.format == "markdown":
                lines = ["# AgentWeb services", ""]
                for item in services:
                    lines.append(f"- `{item['name']}` — {', '.join(item['subjects'])}")
                _emit("\n".join(lines) + "\n", "text", args.output)
            else:
                _emit({"services": services}, "json", args.output)
            return 0

        if args.command == "fetch":
            result = fetch_url(
                args.url,
                timeout=args.timeout,
                max_chars=args.max_chars,
                cookies=args.cookies,
                headers=_headers(args.header),
                use_jina=not args.no_jina,
                use_browser=args.browser,
                use_camoufox=args.camoufox,
            )
            if args.format == "markdown":
                _emit(format_markdown_fetch(result, max_chars=args.max_chars), "text", args.output)
            else:
                _emit(result.to_dict(max_chars=args.max_chars), "json", args.output)
            return 0 if result.ok else 2

        if args.command == "research":
            pack = research(
                args.query,
                max_results=args.max_results,
                timeout=args.timeout,
                max_chars=args.max_chars,
                use_camoufox=not args.no_camoufox,
                services=args.service,
            )
            if args.format == "markdown":
                _emit(format_markdown_research(pack), "text", args.output)
            else:
                _emit(pack, "json", args.output)
            return 0 if pack.get("status") == "ok" else 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        sys.stderr.write(f"agentweb: {type(exc).__name__}: {exc}\n")
        return 1
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
