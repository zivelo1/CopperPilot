#!/bin/bash

echo "============================================================"
echo "🚀 STARTING COMPLETE PRODUCTION SERVER WITH CELERY"
echo "============================================================"

# Ensure Redis is running
echo "Checking Redis..."
if ! pgrep -x "redis-server" > /dev/null; then
    echo "Starting Redis..."
    brew services start redis
    sleep 2
else
    echo "Redis is already running."
fi

# Verify Redis is accessible
if redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis is ready!"
else
    echo "❌ Redis is not responding. Trying to restart..."
    brew services restart redis
    sleep 3
fi

# Activate virtual environment
source venv/bin/activate

# Kill any existing servers
echo "Stopping any existing servers..."
pkill -f "uvicorn" 2>/dev/null
pkill -f "celery" 2>/dev/null
sleep 2

# Start Celery worker in background
echo "Starting Celery worker..."
celery -A celery_app worker --loglevel=info &
CELERY_PID=$!
echo "Celery worker started (PID: $CELERY_PID)"

# Give Celery time to start
sleep 3

# Start the main server
echo "Starting FastAPI server..."
echo "============================================================"
echo "Server: http://localhost:8000"
echo "To stop: Press Ctrl+C"
echo "============================================================"

# Run the main server
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

# Cleanup on exit
echo "Shutting down..."
kill $CELERY_PID 2>/dev/null
echo "Server stopped"