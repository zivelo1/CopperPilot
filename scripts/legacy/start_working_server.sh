#!/bin/bash

# Start the Working Circuit Design Server

echo "============================================================"
echo "🚀 STARTING CIRCUIT DESIGN AUTOMATION SERVER"
echo "============================================================"

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export OUTPUT_ROOT_DIR="output"
export PYTHONPATH="${PWD}:${PYTHONPATH}"

# Run the existing server with the complete workflow
echo "Starting server at http://localhost:8000"
echo "Use Ctrl+C to stop"
echo "============================================================"

# The server/main.py already has the complete implementation
# We just need to run it without Celery
python -c "
import sys
sys.path.insert(0, '.')

# Patch to work without Celery
import server.main as main
main.celery_app = type('MockCelery', (), {
    'send_task': lambda self, *args, **kwargs: type('Task', (), {'id': 'mock-task'})(),
    'AsyncResult': lambda self, id: type('Result', (), {'status': 'SUCCESS'})()
})()

# Import actual workflow
from workflow.circuit_workflow_complete import CircuitWorkflowComplete
import asyncio

# Replace the Celery task with direct execution
original_generate = main.generate_circuit

async def generate_circuit_direct(request):
    response = await original_generate(request, None)
    project_id = response.body.decode().split('\"project_id\":\"')[1].split('\"')[0]

    # Run workflow directly
    workflow = CircuitWorkflowComplete(project_id)
    main.active_workflows[project_id] = workflow

    # Start workflow in background
    async def run():
        try:
            # Send initial WebSocket update
            if project_id in main.active_connections:
                ws = main.active_connections[project_id]
                await ws.send_json({
                    'type': 'status',
                    'status': 'Starting',
                    'message': 'Beginning circuit generation...'
                })

            # Run with progress updates
            result = await workflow.run({'requirements': request.requirements}, use_mock_ai=True)

            # Send completion
            if project_id in main.active_connections:
                await main.active_connections[project_id].send_json({
                    'type': 'complete',
                    'status': 'Complete',
                    'result': result
                })
        except Exception as e:
            print(f'Error: {e}')

    asyncio.create_task(run())
    return response

main.generate_circuit = generate_circuit_direct

# Run server
import uvicorn
uvicorn.run(main.app, host='0.0.0.0', port=8000)
"