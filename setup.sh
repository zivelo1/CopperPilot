#!/bin/bash
# CopperPilot — Setup Script
# Creates virtual environment, installs dependencies, and validates configuration.

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}  CopperPilot — Setup${NC}"
echo -e "${BLUE}==========================================${NC}"
echo ""

# ── Step 1: Check Python version ──────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Checking Python version...${NC}"
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}Error: Python 3 is not installed.${NC}"
    echo "  Install it from: https://www.python.org/downloads/"
    echo "  macOS: brew install python@3.12"
    echo "  Ubuntu: sudo apt install python3.12 python3.12-venv"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    echo -e "${RED}Error: Python 3.11+ is required (found $PYTHON_VERSION).${NC}"
    echo "  Install a newer version from: https://www.python.org/downloads/"
    exit 1
fi
echo -e "${GREEN}  Python $PYTHON_VERSION${NC}"

# ── Step 2: Create virtual environment ────────────────────────────────────────
echo -e "${YELLOW}[2/5] Setting up virtual environment...${NC}"
if [ ! -d "venv" ]; then
    $PYTHON_CMD -m venv venv
    echo -e "${GREEN}  Created virtual environment in ./venv/${NC}"
else
    echo -e "${GREEN}  Virtual environment already exists${NC}"
fi

# Activate
source venv/bin/activate

# ── Step 3: Install dependencies ──────────────────────────────────────────────
echo -e "${YELLOW}[3/5] Installing dependencies...${NC}"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo -e "${GREEN}  All dependencies installed${NC}"

# ── Step 4: Create .env file ─────────────────────────────────────────────────
echo -e "${YELLOW}[4/5] Checking environment configuration...${NC}"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}  Created .env from .env.example${NC}"
    echo ""
    echo -e "${RED}  ┌─────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}  │  ACTION REQUIRED: Configure your API key        │${NC}"
    echo -e "${RED}  │                                                  │${NC}"
    echo -e "${RED}  │  Edit .env and set ANTHROPIC_API_KEY             │${NC}"
    echo -e "${RED}  │  Get a key: https://console.anthropic.com       │${NC}"
    echo -e "${RED}  └─────────────────────────────────────────────────┘${NC}"
    echo ""
else
    # Check if ANTHROPIC_API_KEY is configured
    if grep -q "your-anthropic-api-key-here" .env 2>/dev/null; then
        echo -e "${YELLOW}  .env exists but ANTHROPIC_API_KEY is not configured${NC}"
        echo -e "${YELLOW}  Edit .env and set your Anthropic API key${NC}"
    else
        echo -e "${GREEN}  .env is configured${NC}"
    fi
fi

# ── Step 5: Create runtime directories ────────────────────────────────────────
echo -e "${YELLOW}[5/5] Creating runtime directories...${NC}"
mkdir -p output logs
echo -e "${GREEN}  output/ and logs/ directories ready${NC}"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}==========================================${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${BLUE}==========================================${NC}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Configure your API key (if not done):"
echo "     ${BLUE}nano .env${NC}"
echo "     Set: ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "  2. Start the server:"
echo "     ${BLUE}./start_server.sh${NC}"
echo ""
echo "  3. Open in your browser:"
echo "     ${BLUE}http://localhost:8000${NC}"
echo ""
echo "  Optional:"
echo "  - Add Mouser/Digikey API keys in .env for BOM generation"
echo "  - Install KiCad 9 for full ERC/DRC validation"
echo "  - Install Redis for async task processing: brew install redis"
echo ""
