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
    'agentweb[browser,crawl] @ git+https://github.com/thanhan-a17/agentweb.git' \
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

echo ""
echo -e "${BOLD}Quick test:${NC}"
echo "  agentweb search \"hello world\" --format json"
echo ""
echo -e "${BOLD}Documentation:${NC}"
echo "  https://github.com/$REPO"
