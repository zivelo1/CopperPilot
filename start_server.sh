#!/bin/bash

# Unified Circuit Design Automation Server Startup Script
# Supports both production (with Celery) and development modes

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
MODE="production"
PORT=8000
HOST="0.0.0.0"
RELOAD=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dev|--development)
      MODE="development"
      RELOAD="--reload"
      shift
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --dev, --development  Run in development mode (no Celery, with reload)"
      echo "  --port PORT          Specify port (default: 8000)"
      echo "  --host HOST          Specify host (default: 0.0.0.0)"
      echo "  --help, -h           Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0                   # Run in production mode"
      echo "  $0 --dev            # Run in development mode"
      echo "  $0 --port 8080      # Run on port 8080"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}🚀 CIRCUIT DESIGN AUTOMATION SERVER${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}Mode: ${MODE}${NC}"
echo -e "${GREEN}Host: ${HOST}:${PORT}${NC}"

# Check Python virtual environment
if [[ ! -d "venv" ]]; then
    echo -e "${RED}❌ Virtual environment not found!${NC}"
    echo "Please run ./setup.sh first"
    exit 1
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Set environment variables
export OUTPUT_ROOT_DIR="output"
export PYTHONPATH="${PWD}:${PYTHONPATH}"

# Load environment variables from .env if it exists
if [[ -f ".env" ]]; then
    echo -e "${YELLOW}Loading environment variables from .env...${NC}"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo -e "${YELLOW}Warning: .env file not found${NC}"
fi

# Stop any existing servers
echo -e "${YELLOW}Stopping any existing servers...${NC}"
pkill -f "uvicorn.*server.main" 2>/dev/null || true
pkill -f "celery.*worker" 2>/dev/null || true

# Wait for ports to be released
sleep 2

# Production mode with Celery
if [[ "$MODE" == "production" ]]; then
    echo -e "${YELLOW}Checking Redis for Celery...${NC}"

    # Check if Redis is available
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Redis is ready!${NC}"
            REDIS_AVAILABLE=true
        else
            echo -e "${YELLOW}⚠️  Redis not responding, trying to start...${NC}"
            if command -v brew &> /dev/null; then
                brew services start redis 2>/dev/null || true
                sleep 3
                if redis-cli ping > /dev/null 2>&1; then
                    echo -e "${GREEN}✅ Redis started successfully!${NC}"
                    REDIS_AVAILABLE=true
                else
                    echo -e "${YELLOW}⚠️  Redis unavailable, running without Celery${NC}"
                    REDIS_AVAILABLE=false
                fi
            else
                echo -e "${YELLOW}⚠️  Redis not available, running without Celery${NC}"
                REDIS_AVAILABLE=false
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  Redis not installed, running without Celery${NC}"
        REDIS_AVAILABLE=false
    fi

    # Start Celery if Redis is available
    if [[ "$REDIS_AVAILABLE" == "true" ]]; then
        echo -e "${YELLOW}Starting Celery worker...${NC}"
        celery -A celery_app worker --loglevel=info > logs/celery.log 2>&1 &
        CELERY_PID=$!
        echo -e "${GREEN}Celery worker started (PID: $CELERY_PID)${NC}"
        sleep 3
    fi
fi

# Create necessary directories
mkdir -p output logs

# Start the FastAPI server
echo -e "${YELLOW}Starting FastAPI server...${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}🌐 Web Interface: http://localhost:${PORT}${NC}"
echo -e "${GREEN}📚 API Docs: http://localhost:${PORT}/docs${NC}"
echo -e "${GREEN}🔄 WebSocket: ws://localhost:${PORT}/ws/{project_id}${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Function to handle shutdown
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"

    # Kill Celery if it was started
    if [[ ! -z "$CELERY_PID" ]]; then
        kill $CELERY_PID 2>/dev/null || true
        echo -e "${GREEN}Celery worker stopped${NC}"
    fi

    # Kill any remaining processes
    pkill -f "uvicorn.*server.main" 2>/dev/null || true

    echo -e "${GREEN}✅ Server stopped successfully${NC}"
    exit 0
}

# Set up trap for clean shutdown
trap cleanup SIGINT SIGTERM

# Run the server
if [[ "$MODE" == "development" ]]; then
    echo -e "${YELLOW}Running in development mode with auto-reload${NC}"
    venv/bin/python3 -m uvicorn server.main:app --host $HOST --port $PORT --reload
else
    echo -e "${YELLOW}Running in production mode${NC}"
    venv/bin/python3 -m uvicorn server.main:app --host $HOST --port $PORT
fi

# Cleanup will be called by trap