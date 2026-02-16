#!/bin/bash
# Start the Circuit Design Automation Server

echo "Starting Circuit Design Automation Server..."

# Activate virtual environment
source venv/bin/activate

# Export environment variables
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Start the server with auto-reload for development
echo "Server starting on http://localhost:8000"
echo "Press Ctrl+C to stop"
echo ""

python3 -m uvicorn server.main:app --reload --host 0.0.0.0 --port 8000