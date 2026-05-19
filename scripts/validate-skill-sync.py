#!/usr/bin/env python3
"""Validate that hermes-skill/SKILL.md documents all CLI flags.

Checks that every CLI argument defined in agentweb/cli.py for the 4 commands
(search, fetch, research, deep-research) has at least a mention in
hermes-skill/SKILL.md. Exits non-zero if any flag is undocumented.

Usage:
    python scripts/validate-skill-sync.py
    # From project root: uv run python scripts/validate-skill-sync.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "agentweb" / "cli.py"
SKILL_PATH = REPO_ROOT / "hermes-skill" / "SKILL.md"


def _get_cli_flags() -> dict[str, set[str]]:
    """Parse CLI args from cli.py for each command."""
    tree = ast.parse(CLI_PATH.read_text())
    commands: dict[str, set[str]] = {}  # command_name -> set of flag names
    current_cmd = None

    for node in ast.walk(tree):
        # Look for subparser creation: s.add_argument("--foo")
        if not isinstance(node, ast.Call):
            continue
        func = getattr(node.func, "attr", None)
        if func != "add_argument":
            continue

        # Try to infer which command parser we're in
        # The subparser variable names are: s, f, r, dr for search/fetch/research/deep-research
        # Walk up to find the subparser expression
        args = getattr(node, "args", [])
        if not args:
            continue
        first_arg = args[0]
        if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
            continue
        arg_str = first_arg.value
        if not arg_str.startswith("--"):
            continue

        # Determine which command this belongs to by finding the enclosing function/expression
        # We'll track this differently - parse build_parser() more carefully
        pass

    # Simpler approach: just extract from the build_parser function text
    text = CLI_PATH.read_text()

    # Find each subparser and its arguments
    patterns = [
        ("search", r's\s*=\s*sub\.add_parser\("search".*?(?=\n\s*(?:f|r|dr)\s*=\s*sub\.add_parser)'),
        ("fetch", r'f\s*=\s*sub\.add_parser\("fetch".*?(?=\n\s*r\s*=\s*sub\.add_parser)'),
        ("research", r'r\s*=\s*sub\.add_parser\("research".*?(?=\n\s*dr\s*=\s*sub\.add_parser)'),
        ("deep-research", r'dr\s*=\s*sub\.add_parser\("deep-research".*?(?=\n\s*return\s+p)'),
    ]

    for cmd_name, pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if not m:
            commands[cmd_name] = set()
            continue
        block = m.group(0)
        flags: set[str] = set()
        for flag_match in re.finditer(r'\.add_argument\("(--[\w-]+)', block):
            flag_name = flag_match.group(1)
            # Exclude common non-user-facing flags
            if flag_name not in ("--format", "--output", "--version"):
                flags.add(flag_name)
        commands[cmd_name] = flags

    return commands


def _get_skill_flags() -> set[str]:
    """Extract flag mentions from SKILL.md."""
    text = SKILL_PATH.read_text()
    flags: set[str] = set()
    for m in re.finditer(r'`(--[\w-]+)`', text):
        flags.add(m.group(1))
    return flags


def main() -> int:
    if not CLI_PATH.exists():
        print(f"❌ CLI not found: {CLI_PATH}")
        return 1
    if not SKILL_PATH.exists():
        print(f"❌ SKILL.md not found: {SKILL_PATH}")
        return 1

    cli_flags = _get_cli_flags()
    skill_flags = _get_skill_flags()

    all_ok = True
    for cmd, flags in cli_flags.items():
        for flag in flags:
            if flag not in skill_flags:
                print(f"❌ {cmd}: flag {flag} not documented in hermes-skill/SKILL.md")
                all_ok = False

    if all_ok:
        print("✅ All CLI flags are documented in hermes-skill/SKILL.md")
        return 0
    else:
        print("\n💡 Add `--flag-name` mentions to hermes-skill/SKILL.md under the relevant command section.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
