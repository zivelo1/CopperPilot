#!/bin/bash

# Unified Circuit Design Automation Server Shutdown Script

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}🛑 STOPPING CIRCUIT DESIGN AUTOMATION SERVER${NC}"
echo -e "${BLUE}============================================================${NC}"

# Function to kill processes safely
kill_processes() {
    local process_pattern="$1"
    local process_name="$2"

    if pgrep -f "$process_pattern" > /dev/null 2>&1; then
        echo -e "${YELLOW}Stopping ${process_name}...${NC}"
        pkill -f "$process_pattern" 2>/dev/null || true
        sleep 1

        # Check if still running and force kill if necessary
        if pgrep -f "$process_pattern" > /dev/null 2>&1; then
            echo -e "${YELLOW}Force stopping ${process_name}...${NC}"
            pkill -9 -f "$process_pattern" 2>/dev/null || true
        fi
        echo -e "${GREEN}✅ ${process_name} stopped${NC}"
    else
        echo -e "${GREEN}${process_name} not running${NC}"
    fi
}

# Stop FastAPI/Uvicorn servers
kill_processes "uvicorn.*server.main" "FastAPI server"
kill_processes "python.*server" "Python servers"
kill_processes "python.*run_server" "Run server processes"

# Stop Celery workers
kill_processes "celery.*worker" "Celery workers"
kill_processes "celery.*beat" "Celery beat"

# Stop logging server if running
kill_processes "uvicorn.*log_server" "Logging server"

# Clean up specific ports
echo -e "${YELLOW}Cleaning up ports...${NC}"

# Function to clean a port
clean_port() {
    local port=$1
    local pids=$(lsof -ti:$port 2>/dev/null)

    if [[ ! -z "$pids" ]]; then
        echo -e "${YELLOW}Cleaning port ${port}...${NC}"
        echo "$pids" | xargs kill -9 2>/dev/null || true
        echo -e "${GREEN}✅ Port ${port} cleaned${NC}"
    fi
}

# Clean main server port
clean_port 8000

# Clean logging server port
clean_port 8001

# Check Redis status (but don't stop it)
echo ""
echo -e "${BLUE}Redis Status:${NC}"
if command -v redis-cli &> /dev/null; then
    if redis-cli ping > /dev/null 2>&1; then
        echo -e "${GREEN}Redis is running (not stopped by this script)${NC}"
        echo -e "${YELLOW}To stop Redis: brew services stop redis${NC}"
    else
        echo -e "${GREEN}Redis is not running${NC}"
    fi
else
    echo -e "${YELLOW}Redis not installed${NC}"
fi

# Final verification
echo ""
echo -e "${BLUE}Verification:${NC}"

# Check if any related processes are still running
REMAINING_UVICORN=$(pgrep -f "uvicorn" 2>/dev/null | wc -l)
REMAINING_CELERY=$(pgrep -f "celery" 2>/dev/null | wc -l)

if [[ "$REMAINING_UVICORN" -eq 0 ]] && [[ "$REMAINING_CELERY" -eq 0 ]]; then
    echo -e "${GREEN}✅ All server processes stopped successfully!${NC}"
else
    echo -e "${YELLOW}⚠️  Some processes may still be running:${NC}"
    if [[ "$REMAINING_UVICORN" -gt 0 ]]; then
        echo -e "${YELLOW}  - ${REMAINING_UVICORN} Uvicorn process(es)${NC}"
    fi
    if [[ "$REMAINING_CELERY" -gt 0 ]]; then
        echo -e "${YELLOW}  - ${REMAINING_CELERY} Celery process(es)${NC}"
    fi
    echo -e "${YELLOW}Run 'ps aux | grep -E \"(uvicorn|celery)\"' to check${NC}"
fi

# Check port availability
if ! lsof -ti:8000 > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Port 8000 is free${NC}"
else
    echo -e "${YELLOW}⚠️  Port 8000 still in use${NC}"
fi

if ! lsof -ti:8001 > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Port 8001 is free${NC}"
else
    echo -e "${YELLOW}⚠️  Port 8001 still in use${NC}"
fi

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}Server shutdown complete${NC}"
echo -e "${YELLOW}To restart the server:${NC}"
echo -e "  ${GREEN}./start_server.sh           ${NC}# Production mode"
echo -e "  ${GREEN}./start_server.sh --dev     ${NC}# Development mode"
echo -e "${BLUE}============================================================${NC}"