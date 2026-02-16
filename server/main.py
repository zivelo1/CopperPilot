# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Main FastAPI server for Circuit Design Automation
Replaces N8N workflow with debuggable Python server
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.config import config
from workflow.circuit_workflow import CircuitWorkflow
from ai_agents.agent_manager import AIAgentManager
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
    description="AI-powered circuit design automation platform",
    docs_url="/docs" if config.ENABLE_SWAGGER_UI else None,
    redoc_url="/redoc" if config.ENABLE_SWAGGER_UI else None
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

# Store active WebSocket connections
active_connections: Dict[str, WebSocket] = {}

# Store workflow instances (in production, use Redis or database)
active_workflows: Dict[str, CircuitWorkflow] = {}

# Request/Response Models
class GenerateRequest(BaseModel):
    requirements: str
    project_name: Optional[str] = None
    pdf_content: Optional[str] = None
    image_content: Optional[str] = None

class ProjectStatus(BaseModel):
    project_id: str
    status: str
    current_step: int
    total_steps: int
    progress: float
    eta: Optional[str]
    logs: List[Dict[str, Any]]
    error: Optional[str] = None

class DebugRequest(BaseModel):
    circuit: Dict[str, Any]
    fix_type: str = "all"  # all, net_conflicts, floating, validation

# WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, project_id: str):
        await websocket.accept()
        self.active_connections[project_id] = websocket
        logger.info(f"WebSocket connected for project: {project_id}")

    def disconnect(self, project_id: str):
        if project_id in self.active_connections:
            del self.active_connections[project_id]
            logger.info(f"WebSocket disconnected for project: {project_id}")

    async def send_update(self, project_id: str, message: dict):
        if project_id in self.active_connections:
            try:
                await self.active_connections[project_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending WebSocket message: {e}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# Root endpoint - serve frontend
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend page"""
    frontend_path = Path("frontend/index.html")
    if frontend_path.exists():
        return frontend_path.read_text()
    return """
    <html>
        <head><title>Circuit Design Automation</title></head>
        <body>
            <h1>Circuit Design Automation Server</h1>
            <p>Server is running. Frontend not yet implemented.</p>
            <p><a href="/docs">API Documentation</a></p>
        </body>
    </html>
    """

# File upload generation endpoint
@app.post("/api/generate/upload")
async def generate_circuit_with_files(
    background_tasks: BackgroundTasks,
    requirements: str = Form(...),
    pdf_file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None)
):
    """
    Generate circuit with file uploads
    """
    try:
        # Generate unique project ID (without timestamp in ID, just UUID)
        project_id = str(uuid.uuid4())[:8]

        # Process uploaded files
        pdf_content = None
        image_content = None

        if pdf_file:
            pdf_content = await pdf_file.read()
            logger.info(f"Received PDF file: {pdf_file.filename}")

        if image_file:
            image_content = await image_file.read()
            logger.info(f"Received image file: {image_file.filename}")

        # Create workflow instance
        workflow = CircuitWorkflow(project_id)
        active_workflows[project_id] = workflow

        # Prepare request data
        request_data = {
            "requirements": requirements,
            "pdf_content": pdf_content if pdf_content else None,  # Keep as bytes
            "image_content": image_content if image_content else None
        }

        # Run workflow directly in background
        background_tasks.add_task(run_workflow_task, project_id, request_data)

        logger.info(f"Started circuit generation for project: {project_id}")

        return JSONResponse({
            "project_id": project_id,
            "status": "processing",
            "message": "Circuit generation started with uploaded files."
        })

    except Exception as e:
        logger.error(f"Error starting generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Main generation endpoint
@app.post("/api/generate")
async def generate_circuit(
    background_tasks: BackgroundTasks,
    requirements: str = Form(...),
    pdf_file: Optional[UploadFile] = File(None)
):
    """
    Main endpoint to start circuit generation
    Replaces N8N webhook trigger
    """
    try:
        # Generate unique project ID (without timestamp in ID, just UUID)
        project_id = str(uuid.uuid4())[:8]

        # Create workflow instance
        workflow = CircuitWorkflow(project_id)
        active_workflows[project_id] = workflow

        # Prepare request data
        request_data = {
            "requirements": requirements,
            "pdf_content": None,
            "files": []
        }

        # Process PDF file if uploaded
        if pdf_file:
            pdf_content = await pdf_file.read()
            request_data["files"] = [{
                "mimeType": "application/pdf",
                "data": pdf_content
            }]
            logger.info(f"PDF file uploaded: {pdf_file.filename}, size: {len(pdf_content)} bytes")

        # Run workflow directly in background (without Celery for now)
        background_tasks.add_task(run_workflow_task, project_id, request_data)

        logger.info(f"Started circuit generation for project: {project_id}")

        return JSONResponse({
            "project_id": project_id,
            "task_id": project_id,  # Use project_id as task_id
            "status": "processing",
            "message": "Circuit generation started. Connect to WebSocket for real-time updates."
        })

    except Exception as e:
        logger.error(f"Error starting generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Continue endpoint for clarification responses
@app.post("/api/continue")
async def continue_workflow(
    background_tasks: BackgroundTasks,
    requirements: str = Form(...),
    project_id: str = Form(...),
    clarification_response: str = Form(default="false")
):
    """
    Continue workflow with clarification response
    Uses existing project instead of creating new one
    """
    try:
        # Get existing workflow
        if project_id not in active_workflows:
            raise HTTPException(status_code=404, detail="Project not found")

        workflow = active_workflows[project_id]

        # Prepare updated request data with clarification response
        request_data = {
            "requirements": requirements,
            "chatInput": requirements,
            "is_clarification": True,
            "project_id": project_id
        }

        # Continue workflow in background
        background_tasks.add_task(continue_workflow_task, project_id, request_data)

        return JSONResponse({
            "success": True,
            "project_id": project_id,
            "message": "Continuing workflow with clarification"
        })

    except Exception as e:
        logger.error(f"Error continuing workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Status endpoint
@app.get("/api/status/{project_id}")
async def get_status(project_id: str):
    """Get current status of circuit generation"""
    if project_id not in active_workflows:
        raise HTTPException(status_code=404, detail="Project not found")

    workflow = active_workflows[project_id]

    # Get task status
    celery_status = workflow.status

    # Check if workflow needs clarification
    workflow_state = getattr(workflow, 'state', {})
    needs_clarification = workflow_state.get('needs_clarification', False)
    questions = workflow_state.get('clarification_questions', '')

    return {
        "project_id": project_id,
        "status": workflow.status,
        "current_step": workflow.current_step,
        "total_steps": workflow.total_steps,
        "progress": workflow.get_progress(),
        "eta": workflow.eta,
        "logs": workflow.get_recent_logs(20),
        "needs_clarification": needs_clarification,
        "questions": questions
    }

# Download packaged ZIP from Step 6
@app.get("/api/download/{project_id}")
async def download_package(project_id: str):
    """Return the packaged ZIP for a completed project, if available."""
    if project_id not in active_workflows:
        raise HTTPException(status_code=404, detail="Project not found")

    workflow = active_workflows[project_id]
    output_dir = workflow.output_dir
    if not output_dir:
        raise HTTPException(status_code=404, detail="Output directory not found")

    zip_path = output_dir.parent / f"{project_id}_circuit_design.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Package not found. Run Step 6 packaging first.")

    return FileResponse(path=str(zip_path), filename=zip_path.name, media_type="application/zip")

# Debug endpoints (THE KEY FEATURE!)
@app.post("/api/debug/test-fix-logic")
async def test_fix_logic(request: DebugRequest):
    """
    Test fix logic without running expensive AI calls
    This is what N8N couldn't do!
    """
    try:
        from workflow.fix_net_conflicts import fix_net_conflicts, validate_circuit
        from workflow.circuit_supervisor import supervise_circuit

        circuit = request.circuit

        # Run through fix pipeline
        results = {
            "original": {
                "circuit": circuit,
                "validation": validate_circuit(circuit)
            }
        }

        # Apply fixes based on request
        if request.fix_type in ["all", "net_conflicts"]:
            fixed = fix_net_conflicts(circuit)
            results["after_net_conflicts"] = {
                "circuit": fixed,
                "validation": validate_circuit(fixed)
            }
            circuit = fixed

        if request.fix_type in ["all", "floating"]:
            # Use Circuit Supervisor for comprehensive fixing
            fixed = supervise_circuit(circuit)
            results["after_floating_fix"] = {
                "circuit": fixed,
                "validation": validate_circuit(fixed)
            }
            circuit = fixed

        if request.fix_type in ["all", "validation"]:
            # Use Circuit Supervisor for comprehensive validation
            fixed = supervise_circuit(circuit)
            results["after_safety_net"] = {
                "circuit": fixed,
                "validation": validate_circuit(fixed)
            }

        # Calculate improvements
        original_issues = results["original"]["validation"].get("issues", [])
        final_validation = list(results.values())[-1]["validation"]
        final_issues = final_validation.get("issues", [])

        improvements = {
            "issues_fixed": len(original_issues) - len(final_issues),
            "success": final_validation.get("valid", False),
            "remaining_issues": final_issues
        }

        return JSONResponse({
            "success": True,
            "pipeline_results": results,
            "improvements": improvements,
            "execution_time": "< 1 second (vs 30 minutes in N8N!)"
        })

    except Exception as e:
        logger.error(f"Error in debug test: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/debug/{project_id}/{step}")
async def debug_step(project_id: str, step: str):
    """
    Get detailed debug information for a specific step
    Returns all inputs, outputs, and intermediate states
    """
    log_dir = config.LOGS_DIR / project_id

    if not log_dir.exists():
        raise HTTPException(status_code=404, detail="Project logs not found")

    logs = {}
    for log_file in log_dir.glob(f"*{step}*.json"):
        with open(log_file) as f:
            logs[log_file.stem] = json.load(f)

    return JSONResponse({
        "project_id": project_id,
        "step": step,
        "logs": logs,
        "log_files": [str(f.name) for f in log_dir.glob(f"*{step}*")]
    })

@app.post("/api/replay/{project_id}/{step}")
async def replay_step(project_id: str, step: str):
    """
    Replay a specific step with saved inputs
    No AI costs, instant debugging!
    """
    try:
        # Load saved input for this step
        input_file = config.LOGS_DIR / project_id / f"{step}_input.json"

        if not input_file.exists():
            raise HTTPException(status_code=404, detail="Step input not found")

        with open(input_file) as f:
            step_input = json.load(f)

        # Import the appropriate step function
        if step == "fix_net_conflicts":
            from workflow.fix_net_conflicts import fix_net_conflicts
            result = fix_net_conflicts(step_input)
        elif step == "validate_circuit":
            from workflow.fix_net_conflicts import validate_circuit
            result = validate_circuit(step_input)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown step: {step}")

        return JSONResponse({
            "success": True,
            "step": step,
            "input": step_input,
            "output": result,
            "message": "Step replayed successfully without AI calls"
        })

    except Exception as e:
        logger.error(f"Error replaying step: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Internal endpoint for Celery to send WebSocket updates
@app.post("/internal/ws-update/{project_id}")
async def internal_ws_update(project_id: str, update: dict):
    """Internal endpoint for background tasks to send WebSocket updates"""
    await manager.send_update(project_id, update)
    return {"success": True}

# WebSocket endpoint for real-time updates
@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """WebSocket for real-time progress updates"""
    await manager.connect(websocket, project_id)

    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "project_id": project_id,
            "message": "Connected to circuit generation workflow"
        })

        # Keep connection alive and handle messages
        while True:
            data = await websocket.receive_text()

            # Handle client messages if needed
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(project_id)
        logger.info(f"WebSocket disconnected: {project_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(project_id)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check for monitoring"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "ai_provider": "anthropic",
            "debug_mode": config.DEBUG_MODE,
            "cache_enabled": config.ENABLE_CACHE
        }
    }

# List all projects
@app.get("/api/projects")
async def list_projects():
    """List all projects in storage"""
    projects = []

    for project_dir in config.PROJECTS_DIR.glob("*"):
        if project_dir.is_dir():
            # Get basic info about each project
            info_file = project_dir / "info.json"
            if info_file.exists():
                with open(info_file) as f:
                    info = json.load(f)
                    projects.append(info)

    return JSONResponse({
        "count": len(projects),
        "projects": sorted(projects, key=lambda x: x.get("created", ""), reverse=True)
    })

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize server on startup"""
    logger.info("Starting Circuit Design Automation Server")

    # Validate configuration
    try:
        config.validate()
        logger.info("Configuration validated successfully")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise

    # Initialize AI agent manager
    AIAgentManager.initialize()

    logger.info(f"Server started on {config.SERVER_HOST}:{config.SERVER_PORT}")
    logger.info(f"API Documentation: http://localhost:{config.SERVER_PORT}/docs")

# Continue workflow task
async def continue_workflow_task(project_id: str, request_data: dict):
    """Continue workflow task after clarification"""
    try:
        workflow = active_workflows.get(project_id)
        if not workflow:
            logger.error(f"Workflow not found: {project_id}")
            return

        # Pass the WebSocket manager to workflow
        workflow.websocket_manager = manager

        # Send WebSocket update
        await manager.send_update(project_id, {
            "type": "status",
            "status": "Continuing with clarification",
            "message": "Processing your additional information..."
        })

        # Continue the workflow with clarification response
        result = await workflow.continue_with_clarification(request_data)

        # Send completion update
        if result.get("success"):
            if result.get("needs_clarification"):
                # Still needs more clarification
                workflow.state = {
                    'needs_clarification': True,
                    'clarification_questions': result.get("questions", "")
                }
                await manager.send_update(project_id, {
                    "type": "clarification",
                    "questions": result.get("questions", ""),
                    "project_id": project_id
                })
            else:
                # Continue with normal workflow
                await manager.send_update(project_id, {
                    "type": "status",
                    "status": "Proceeding to circuit generation",
                    "message": "Information complete, generating circuits..."
                })
        else:
            await manager.send_update(project_id, {
                "type": "error",
                "error": result.get("error", "Unknown error occurred")
            })

    except Exception as e:
        logger.error(f"Error in continue workflow task: {e}")
        await manager.send_update(project_id, {
            "type": "error",
            "error": str(e)
        })

# Shutdown event
async def run_workflow_task(project_id: str, request_data: dict):
    """Run workflow task without Celery"""
    try:
        workflow = active_workflows.get(project_id)
        if not workflow:
            logger.error(f"Workflow not found: {project_id}")
            return

        # Pass the WebSocket manager to workflow
        workflow.websocket_manager = manager

        # Send initial WebSocket update
        await manager.send_update(project_id, {
            "type": "status",
            "status": "Starting workflow",
            "message": "Beginning circuit generation process..."
        })

        # Run the workflow
        result = await workflow.run(request_data)

        # Send completion update
        if result.get("success"):
            if result.get("needs_clarification"):
                # Store clarification state
                workflow.state = {
                    'needs_clarification': True,
                    'clarification_questions': result.get("questions", "")
                }
                # Send clarification request
                await manager.send_update(project_id, {
                    "type": "clarification",
                    "questions": result.get("questions", ""),
                    "project_id": project_id
                })
            else:
                # Normal completion
                await manager.send_update(project_id, {
                    "type": "complete",
                    "status": "Complete",
                    "message": "Circuit generation completed successfully!",
                    "output_dir": result.get("output_dir")
                })
        else:
            await manager.send_update(project_id, {
                "type": "error",
                "error": result.get("error", "Unknown error occurred")
            })

    except Exception as e:
        logger.error(f"Error in workflow task: {e}")
        await manager.send_update(project_id, {
            "type": "error",
            "error": str(e)
        })

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down server")

    # Close all WebSocket connections
    for project_id in list(manager.active_connections.keys()):
        manager.disconnect(project_id)

    logger.info("Server shutdown complete")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=config.DEBUG_MODE
    )
