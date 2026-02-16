# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simple FastAPI server that works without Celery for immediate testing
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64

# Add parent to path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from workflow.circuit_workflow import CircuitWorkflow
from utils.logger import setup_logger

# Setup logging
logger = setup_logger(__name__)

# CORS: Read allowed origins from environment (comma-separated list)
_allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000"
).split(",")

# Create FastAPI app
app = FastAPI(
    title="Circuit Design Automation Server",
    version="1.0.0",
    description="AI-powered circuit design automation platform"
)

# Add CORS middleware — origins configured via ALLOWED_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Store active WebSocket connections and workflows
active_connections: Dict[str, WebSocket] = {}
active_workflows: Dict[str, CircuitWorkflow] = {}

# Request Models
class GenerateRequest(BaseModel):
    requirements: str
    pdf_content: Optional[str] = None
    image_content: Optional[str] = None

# Root endpoint - serve frontend
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend page"""
    frontend_path = Path("frontend/index.html")
    if frontend_path.exists():
        return frontend_path.read_text()
    return "<h1>Frontend not found</h1>"

# Main generation endpoint - SIMPLIFIED VERSION
@app.post("/api/generate")
async def generate_circuit(request: GenerateRequest):
    """
    Main endpoint to start circuit generation - runs directly without Celery
    """
    try:
        # Generate project ID
        project_id = str(uuid.uuid4())[:8]

        logger.info(f"Starting circuit generation for project: {project_id}")

        # Create workflow instance
        workflow = CircuitWorkflow(project_id)
        active_workflows[project_id] = workflow

        # Start the workflow in background
        asyncio.create_task(run_workflow(project_id, request.dict()))

        return JSONResponse({
            "project_id": project_id,
            "status": "started",
            "message": "Circuit generation started. Connect to WebSocket for updates.",
            "websocket_url": f"ws://{os.getenv('HOST', 'localhost')}:{os.getenv('PORT', '8000')}/ws/{project_id}"
        })

    except Exception as e:
        logger.error(f"Error starting generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def run_workflow(project_id: str, requirements: Dict):
    """Run the workflow and send updates via WebSocket"""
    try:
        workflow = active_workflows[project_id]

        # Send initial status
        await send_ws_update(project_id, {
            "type": "status",
            "status": "Started",
            "message": "Beginning circuit generation workflow..."
        })

        # Run the actual workflow
        result = await workflow.run(requirements)

        # Send completion
        await send_ws_update(project_id, {
            "type": "complete",
            "status": "Complete",
            "result": result,
            "output_dir": str(workflow.output_dir)
        })

    except Exception as e:
        logger.error(f"Workflow error: {e}")
        await send_ws_update(project_id, {
            "type": "error",
            "error": str(e)
        })

async def send_ws_update(project_id: str, message: dict):
    """Send update to WebSocket if connected"""
    if project_id in active_connections:
        try:
            await active_connections[project_id].send_json(message)
        except:
            pass

# WebSocket endpoint
@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """WebSocket for real-time progress updates"""
    await websocket.accept()
    active_connections[project_id] = websocket

    logger.info(f"WebSocket connected for project: {project_id}")

    # Send initial connection message
    await websocket.send_json({
        "type": "connected",
        "project_id": project_id,
        "message": "Connected to circuit generation workflow"
    })

    try:
        # Keep connection alive
        while True:
            data = await websocket.receive_text()

            # Handle ping/pong
            if data == "ping":
                await websocket.send_json({"type": "pong"})

            # Check workflow status
            if project_id in active_workflows:
                workflow = active_workflows[project_id]
                await websocket.send_json({
                    "type": "progress",
                    "progress": workflow.get_progress(),
                    "step": workflow.current_step,
                    "status": workflow.status,
                    "eta": workflow.eta
                })

    except WebSocketDisconnect:
        if project_id in active_connections:
            del active_connections[project_id]
        logger.info(f"WebSocket disconnected: {project_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if project_id in active_connections:
            del active_connections[project_id]

# Status endpoint
@app.get("/api/status/{project_id}")
async def get_status(project_id: str):
    """Get current status of circuit generation"""
    if project_id not in active_workflows:
        raise HTTPException(status_code=404, detail="Project not found")

    workflow = active_workflows[project_id]

    return {
        "project_id": project_id,
        "status": workflow.status,
        "current_step": workflow.current_step,
        "total_steps": workflow.total_steps,
        "progress": workflow.get_progress(),
        "eta": workflow.eta,
        "output_dir": str(workflow.output_dir) if hasattr(workflow, 'output_dir') else None
    }

# List output files
@app.get("/api/outputs/{project_id}")
async def list_outputs(project_id: str):
    """List all generated output files"""
    if project_id not in active_workflows:
        raise HTTPException(status_code=404, detail="Project not found")

    workflow = active_workflows[project_id]
    output_dir = workflow.output_dir

    if not output_dir.exists():
        return {"files": []}

    files = []
    for file_path in output_dir.rglob("*"):
        if file_path.is_file():
            files.append({
                "path": str(file_path.relative_to(output_dir)),
                "size": file_path.stat().st_size,
                "modified": file_path.stat().st_mtime
            })

    return {"project_id": project_id, "files": files}

# Download output file
@app.get("/api/download/{project_id}/{file_path:path}")
async def download_file(project_id: str, file_path: str):
    """Download a specific output file"""
    if project_id not in active_workflows:
        raise HTTPException(status_code=404, detail="Project not found")

    workflow = active_workflows[project_id]
    full_path = workflow.output_dir / file_path

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path, filename=full_path.name)

# Health check
@app.get("/health")
async def health_check():
    """Health check for monitoring"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "active_workflows": len(active_workflows)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("DEBUG_MODE", "false").lower() == "true",
    )