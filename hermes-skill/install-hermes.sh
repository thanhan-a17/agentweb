#!/usr/bin/env bash
# Install agentweb Hermes skill — for existing agentweb users
# Usage: curl -fsSL https://raw.githubusercontent.com/thanhan-a17/agentweb/main/hermes-skill/install-hermes.sh | bash
set -euo pipefail

REPO="thanhan-a17/agentweb"
SKILL_DIR="$HOME/.hermes/skills/software-development/agentweb-use"
BASE_URL="https://raw.githubusercontent.com/$REPO/main/hermes-skill"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ ! -d "$HOME/.hermes" ]; then
    echo -e "${RED}✗ ~/.hermes not found — Hermes Agent not installed${NC}"
    exit 1
fi

echo -e "${YELLOW}→ Installing agentweb-use Hermes skill...${NC}"
mkdir -p "$SKILL_DIR/references"
curl -fsSL "$BASE_URL/SKILL.md" -o "$SKILL_DIR/SKILL.md"
for ref in agentweb-v0.2.0-test-sweep-findings.md agentweb-vs-others-comparison.md llm-benchmark-research-session.md multi-source-research-tips.md vn-coffee-market-research-pattern.md; do
    curl -fsSL "$BASE_URL/references/$ref" -o "$SKILL_DIR/references/$ref"
done
echo -e "${GREEN}✓ agentweb-use skill installed to $SKILL_DIR${NC}"
