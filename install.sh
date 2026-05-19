#!/usr/bin/env bash
set -euo pipefail

REPO="thanhan-a17/agentweb"
REQUIRE_PYTHON="3.11"

# ── Colors ──────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       AgentWeb — Quick Install          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Ensure uv is installed ──────────────────
if ! command -v uv &>/dev/null; then
    echo -e "${YELLOW}→ uv not found. Installing uv...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the updated PATH
    if [ -f "$HOME/.local/bin/env" ]; then
        . "$HOME/.local/bin/env"
    fi
    # If still not found, add to PATH manually
    if ! command -v uv &>/dev/null; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    echo -e "${GREEN}✓ uv installed${NC}"
else
    echo -e "${GREEN}✓ uv already installed ($(uv --version))${NC}"
fi

# ── Step 2: Install AgentWeb via uv ──────────────────
echo ""
echo -e "${YELLOW}→ Installing AgentWeb (with browser + crawl support)...${NC}"
echo ""

uv tool install --reinstall \
    'agentweb[browser,crawl,youtube] @ git+https://github.com/thanhan-a17/agentweb.git' \
    2>&1 | while IFS= read -r line; do
    # Indent output so it's clearly from uv
    echo -e "  ${line}"
done

# uv tool install succeeded (set -e catches failures)
echo ""
echo -e "${GREEN}✓ AgentWeb installed!${NC}"
echo ""

# ── Step 3: Verify ──────────────────────────────────
echo -e "${YELLOW}→ Verifying installation...${NC}"
if agentweb --version &>/dev/null; then
    echo -e "  $(agentweb --version)"
    echo ""
    echo -e "${GREEN}✓ Ready to use!${NC}"
else
    echo -e "${RED}✗ agentweb command not found — check your PATH${NC}"
    echo "  Try: export PATH=\"\$HOME/.local/bin:\$PATH\""
    exit 1
fi

# ── Step 4: Install Hermes skill (if Hermes is present) ──
HERMES_DIR="${HERMES_HOME:-$HOME/.hermes}"
HERMES_SKILL_DIR="$HERMES_DIR/skills/software-development/agentweb-use"
if [ -d "$HERMES_DIR" ]; then
    echo ""
    echo -e "${YELLOW}→ Installing Hermes skill for agentweb-use...${NC}"
    mkdir -p "$HERMES_SKILL_DIR/references"
    # Download SKILL.md and reference files from the repo
    BASE_URL="https://raw.githubusercontent.com/$REPO/main/hermes-skill"
    curl -fsSL "$BASE_URL/SKILL.md" -o "$HERMES_SKILL_DIR/SKILL.md" 2>/dev/null
    for ref in agentweb-v0.2.0-test-sweep-findings.md agentweb-vs-others-comparison.md llm-benchmark-research-session.md multi-source-research-tips.md vn-coffee-market-research-pattern.md; do
        curl -fsSL "$BASE_URL/references/$ref" -o "$HERMES_SKILL_DIR/references/$ref" 2>/dev/null
    done
    echo -e "${GREEN}✓ Hermes skill installed${NC}"
else
    echo ""
    echo -e "${YELLOW}→ Hermes home not found at $HERMES_DIR — skipping Hermes skill install${NC}"
    echo "  (Hermes Agent users can install manually: HERMES_HOME=\$HERMES_DIR curl -fsSL https://raw.githubusercontent.com/$REPO/main/hermes-skill/install-hermes.sh | bash)"
fi

echo ""
echo -e "${BOLD}Quick test:${NC}"
echo "  agentweb search \"hello world\" --format json"
echo ""
echo -e "${BOLD}Documentation:${NC}"
echo "  https://github.com/$REPO"
