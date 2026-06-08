#!/usr/bin/env python3
"""
FastAPI entry point for the time series analysis agent.
Implements the planner phase with multi-turn conversation and task management.
"""

import os
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

from models import Base, Task, LlmInteraction
from agents.planner_agent import (
    planner_agent_file,
    build_conversation_history
)
from agents.executor_orchestrator import executor_orchestrator

# === Environment setup ===
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set in environment")

# Fix for Heroku's postgres:// URL format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# === Workspace setup ===
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# === Database setup ===
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Create tables (no drop_all)
Base.metadata.create_all(bind=engine)

# === FastAPI setup ===
app = FastAPI(title="Time Series Analysis Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Dependencies ===
def get_db():
    """Database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# === Pydantic schemas ===
class CreateTaskRequest(BaseModel):
    """Request to create a new task."""
    data_source_type: str = Field(..., description="csv or database")
    data_source_meta: dict = Field(..., description="Metadata: csv_path/csv_paths or database_id")
    prompt: str = Field(..., description="Initial user prompt")


class UploadedFileResponse(BaseModel):
    """Response for a single uploaded file."""
    name: str
    path: str


class UploadResponse(BaseModel):
    """Response after uploading files."""
    files: List[UploadedFileResponse]


class MessageRequest(BaseModel):
    """Request to send a follow-up message."""
    prompt: str = Field(..., description="User's follow-up message")


class TaskResponse(BaseModel):
    """Response with full task state."""
    task_id: str
    status: str
    data_source_type: str
    data_source_meta: dict
    prompt: str
    answer: Optional[str] = None
    plan: Optional[list] = None
    created_at: datetime
    updated_at: datetime


class PlannerTurnResponse(BaseModel):
    """Response after a planner turn."""
    task_id: str
    status: str
    answer: str
    plan: list
    interaction_id: str


class InteractionResponse(BaseModel):
    """Single interaction response."""
    id: str
    agent: str
    prompt: str
    model_answer: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


# === Helper functions ===
def _sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal."""
    # Remove any path separators and keep only alphanumeric, dots, dashes, underscores
    filename = os.path.basename(filename)
    filename = re.sub(r'[^\w\s\-\.]', '_', filename)
    return filename


def _extract_input_files(data_source_meta: dict) -> str:
    """
    Extract input_files string from data_source_meta for planner agent.
    
    Args:
        data_source_meta: Dict with csv_path, csv_paths, or database_id
        
    Returns:
        String representation of input files
    """
    # Support both csv_paths (list) and csv_path (single string) for backward compat
    if "csv_paths" in data_source_meta:
        paths = data_source_meta["csv_paths"]
        if isinstance(paths, list) and paths:
            return ", ".join(paths)
        return str(paths)
    elif "csv_path" in data_source_meta:
        return data_source_meta["csv_path"]
    elif "database_id" in data_source_meta:
        return f"database:{data_source_meta['database_id']}"
    return ""


def _run_planner_and_save(
    db: Session,
    task: Task,
    prompt: str,
    conversation_history: list
) -> dict:
    """
    Run planner agent, parse response, save interaction, update task.
    
    Args:
        db: Database session
        task: Task object
        prompt: Current user prompt
        conversation_history: Prior conversation history
        
    Returns:
        parsed response dict with answer and plan
    """
    # Extract input files from data source metadata
    data_source_meta = json.loads(task.data_source_meta)
    print(f"[DEBUG] data_source_meta: {data_source_meta}")
    input_files = _extract_input_files(data_source_meta)
    print(f"[DEBUG] input_files for planner: {input_files}")
    
    # Call planner agent
    print(f"[DEBUG] Calling planner agent...")
    raw_response, output = planner_agent_file(
        prompt=prompt,
        conversation_history=conversation_history,
        input_files=input_files
    )
    print(f"[DEBUG] Planner returned successfully")

    model_answer_dict = output["model_answer"]
    tool_uses = output.get("tool_uses", [])
    
    if isinstance(model_answer_dict, str):
        try:
            model_answer_dict = json.loads(model_answer_dict)
        except json.JSONDecodeError:
            model_answer_dict = {"answer": model_answer_dict, "plan": []}

    plan_with_numbers = []
    for i, step in enumerate(model_answer_dict.get("plan", []), 1):
        if isinstance(step, dict):
            step["step"] = i
            plan_with_numbers.append(step)
        else:
            plan_with_numbers.append({"step": i, "description": str(step)})
    model_answer_dict["plan"] = plan_with_numbers

    model_answer_json = json.dumps(model_answer_dict)
    
    # Save interaction (model_answer column is Text — must be a string)
    interaction = LlmInteraction(
        id=str(uuid.uuid4()),
        task_id=task.id,
        agent="planner",
        prompt=prompt,
        model_answer=model_answer_json,
        input_tokens=output["input_tokens"],
        output_tokens=output["output_tokens"],
        created_at=datetime.utcnow()
    )
    db.add(interaction)
    
    # Update task status and result
    has_plan = bool(model_answer_dict.get("plan"))
    task.status = "plan_ready" if has_plan else "planning"
    task.result = json.dumps({
        "answer": model_answer_dict.get("answer", ""),
        "plan": model_answer_dict.get("plan", []),
        "discovery_log": tool_uses
    })
    task.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "task_id": task.id,
        "status": task.status,
        "answer": model_answer_dict.get("answer", ""),
        "plan": model_answer_dict.get("plan", []),
        "discovery_log": tool_uses,
        "interaction_id": interaction.id
    }


# === Routes ===
@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/uploads/csv", response_model=UploadResponse)
async def upload_csv_files(files: List[UploadFile] = File(...)):
    """
    Upload one or more CSV files.
    
    Args:
        files: List of uploaded CSV files
        
    Returns:
        List of uploaded file info with paths relative to workspace
    """
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    uploaded_files = []
    
    # Create batch directory with timestamp
    batch_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    batch_dir = UPLOADS_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    
    for file in files:
        # Validate file extension
        if not file.filename.lower().endswith('.csv'):
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} is not a CSV file"
            )
        
        # Read and check size
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} exceeds 50MB limit"
            )
        
        # Sanitize filename and save
        safe_filename = _sanitize_filename(file.filename)
        file_path = batch_dir / safe_filename
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Return path relative to workspace
        relative_path = f"uploads/{batch_id}/{safe_filename}"
        uploaded_files.append({
            "name": file.filename,
            "path": relative_path
        })
    
    return {"files": uploaded_files}


@app.post("/tasks", response_model=PlannerTurnResponse)
def create_task(request: CreateTaskRequest, db: Session = Depends(get_db)):
    """
    Create a new task and run initial planner turn.
    
    Args:
        request: Task creation request with data source and prompt
        db: Database session
        
    Returns:
        Task ID, status, answer, plan, and interaction ID
    """
    # Validate data_source_type
    if request.data_source_type not in ["csv", "database"]:
        raise HTTPException(
            status_code=400,
            detail="data_source_type must be 'csv' or 'database'"
        )
    
    # Create task
    task = Task(
        id=str(uuid.uuid4()),
        prompt=request.prompt,
        status="planning",
        data_source_type=request.data_source_type,
        data_source_meta=json.dumps(request.data_source_meta),
        result=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()
    
    # Run planner with empty history
    try:
        print(f"[DEBUG] Creating task with data_source_meta: {request.data_source_meta}")
        result = _run_planner_and_save(db, task, request.prompt, [])
        print(f"[DEBUG] Task created successfully: {task.id}")
        return result
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Task creation failed:\n{error_details}")
        task.status = "error"
        task.result = json.dumps({"error": str(e)})
        task.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=500, detail=f"Planner error: {str(e)}")


@app.post("/tasks/{task_id}/messages", response_model=PlannerTurnResponse)
def send_message(
    task_id: str,
    request: MessageRequest,
    db: Session = Depends(get_db)
):
    """
    Send a follow-up message to continue the conversation.
    
    Args:
        task_id: Task ID
        request: Message request with prompt
        db: Database session
        
    Returns:
        Task ID, status, answer, plan, and interaction ID
    """
    # Load task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Reject if already executing or completed
    if task.status in ["executing", "completed"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot send messages while task is executing or completed"
        )
    
    # If task was proceeded but not yet executing, reset to plan_ready to allow edits
    if task.status == "proceeded":
        task.status = "plan_ready"
        # Remove selected_steps to allow re-selection
        if task.result:
            result = json.loads(task.result)
            result.pop("selected_steps", None)
            task.result = json.dumps(result)
        task.updated_at = datetime.utcnow()
        db.commit()
    
    # Load conversation history (planner only — executor prompts are technical)
    interactions = (
        db.query(LlmInteraction)
        .filter(
            LlmInteraction.task_id == task_id,
            LlmInteraction.agent == "planner",
        )
        .order_by(LlmInteraction.created_at)
        .all()
    )
    conversation_history = build_conversation_history(interactions)
    
    # Run planner
    try:
        result = _run_planner_and_save(db, task, request.prompt, conversation_history)
        return result
    except Exception as e:
        task.status = "error"
        task.result = json.dumps({"error": str(e)})
        task.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=500, detail=f"Planner error: {str(e)}")


class ProceedRequest(BaseModel):
    """Request to proceed with selected steps."""
    selected_steps: List[int] = Field(..., description="List of step numbers to execute")
    
    class Config:
        validate_assignment = True
    
    @property
    def is_valid(self) -> bool:
        return self.selected_steps and len(self.selected_steps) > 0


@app.post("/tasks/{task_id}/proceed")
def proceed_task(task_id: str, request: ProceedRequest, db: Session = Depends(get_db)):
    """
    Mark task as proceeded (ready for translator/executor phase).
    
    Args:
        task_id: Task ID
        request: Proceed request with selected steps
        db: Database session
        
    Returns:
        Success message
    """
    print(f"[DEBUG] Proceed request received: task_id={task_id}, selected_steps={request.selected_steps}")
    
    # Load task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    print(f"[DEBUG] Task status: {task.status}")
    
    # Validate status
    if task.status not in ["planning", "plan_ready"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot proceed from status '{task.status}'"
        )
    
    # Validate plan exists
    if task.result:
        result = json.loads(task.result)
        if not result.get("plan"):
            raise HTTPException(
                status_code=400,
                detail="Cannot proceed without a plan"
            )
    else:
        raise HTTPException(status_code=400, detail="No result available")
    
    # Validate selected steps
    if not request.selected_steps:
        print(f"[DEBUG] Selected steps is empty: {request.selected_steps}")
        raise HTTPException(
            status_code=400,
            detail="Must select at least one step to execute"
        )
    
    plan = result.get("plan", [])
    print(f"[DEBUG] Plan items: {plan}")
    
    # Extract valid step numbers - handle both string and dict formats
    valid_steps = []
    for i, item in enumerate(plan, 1):
        if isinstance(item, dict):
            if "step" in item:
                valid_steps.append(item["step"])
            else:
                # If dict doesn't have step, use index
                valid_steps.append(i)
        else:
            # If string, use index (1-based)
            valid_steps.append(i)
    
    print(f"[DEBUG] Valid steps: {valid_steps}, Selected steps: {request.selected_steps}")
    invalid_steps = [s for s in request.selected_steps if s not in valid_steps]
    
    if invalid_steps:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step numbers: {invalid_steps}"
        )
    
    # Save selected steps in result
    result["selected_steps"] = sorted(request.selected_steps)
    task.result = json.dumps(result)
    
    # Update status
    task.status = "proceeded"
    task.updated_at = datetime.utcnow()
    db.commit()
    
    return {"status": "ok", "task_id": task_id, "message": "Task proceeded", "selected_steps": request.selected_steps}


class ExecuteStartRequest(BaseModel):
    """Request to prepare execution plan."""
    output_name: str = Field(..., description="Base name for output files (e.g., 'analysis_results')")


class ExecuteStepRequest(BaseModel):
    """Request to execute a specific step."""
    step_number: int = Field(..., description="Step number to execute (1-indexed)")


@app.post("/tasks/{task_id}/execute/start")
def start_execution(task_id: str, request: ExecuteStartRequest, db: Session = Depends(get_db)):
    """
    Prepare execution: load the planner's plan and initialize execution state.
    
    Args:
        task_id: Task ID
        request: Execution start parameters
        db: Database session
        
    Returns:
        Execution state with plan steps ready for the executor
    """
    # Load task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Validate status
    if task.status != "proceeded":
        raise HTTPException(
            status_code=400,
            detail=f"Task must be 'proceeded' to execute (current: '{task.status}')"
        )
    
    # Load plan and selected steps
    if not task.result:
        raise HTTPException(status_code=400, detail="No plan available")
    
    result = json.loads(task.result)
    plan = result.get("plan", [])
    selected_steps = result.get("selected_steps", [])
    
    if not plan:
        raise HTTPException(status_code=400, detail="Cannot execute without a plan")
    
    if not selected_steps:
        raise HTTPException(status_code=400, detail="No steps selected for execution")
    
    # Filter plan to include only selected steps
    filtered_plan = []
    for i, step in enumerate(plan, 1):
        step_num = None
        if isinstance(step, dict) and "step" in step:
            step_num = step["step"]
        else:
            # Use 1-based index if no step field
            step_num = i
        
        if step_num in selected_steps:
            filtered_plan.append(step)
    
    try:
        print(f"[DEBUG] Starting execution for task {task_id} with {len(filtered_plan)} selected steps (out of {len(plan)} total)")
        
        execution_state = {
            "output_name": request.output_name,
            "steps": filtered_plan,
            "selected_steps": selected_steps,
            "current_step": 0,
            "completed_steps": []
        }
        
        result["execution_state"] = execution_state
        task.result = json.dumps(result)
        task.status = "executing"
        task.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "status": "ok",
            "task_id": task_id,
            "task_status": "executing",
            "execution_state": execution_state,
            "total_steps": len(filtered_plan)
        }
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Execution start failed:\n{error_details}")
        
        task.status = "failed"
        task.result = json.dumps({
            **result,
            "error": str(e)
        })
        db.commit()
        
        raise HTTPException(status_code=500, detail=f"Execution start failed: {str(e)}")


@app.post("/tasks/{task_id}/execute/step")
def execute_step(task_id: str, request: ExecuteStepRequest, db: Session = Depends(get_db)):
    """
    Execute a specific step of the plan.
    
    This endpoint executes ONE step and returns results.
    The frontend should call this for each step with user permission.
    
    Args:
        task_id: Task ID
        request: Step execution request
        db: Database session
        
    Returns:
        Step execution results
    """
    # Load task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Validate status — must have called /execute/start first
    if task.status != "executing":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Task must be 'executing' before running a step "
                f"(current: '{task.status}'). Call /execute/start first."
            ),
        )
    
    # Load execution state
    if not task.result:
        raise HTTPException(status_code=400, detail="No execution state available")
    
    result = json.loads(task.result)
    execution_state = result.get("execution_state")
    
    if not execution_state:
        raise HTTPException(
            status_code=400,
            detail="No execution state found. Call /execute/start first."
        )
    
    steps = execution_state.get("steps", [])
    output_name = execution_state.get("output_name", "output")
    
    if not steps:
        raise HTTPException(status_code=400, detail="No steps to execute")
    
    # Validate step number
    step_number = request.step_number
    if step_number < 1 or step_number > len(steps):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid step number {step_number}. Must be between 1 and {len(steps)}"
        )
    
    try:
        # Execute step
        print(f"[DEBUG] Executing step {step_number} for task {task_id}")
        
        exec_result = executor_orchestrator(
            task_id=task_id,
            output_name=output_name,
            steps=steps,
            current_step=step_number,
            db=db
        )
        
        # Update execution state
        completed_steps = execution_state.get("completed_steps", [])
        if step_number not in completed_steps:
            completed_steps.append(step_number)
        
        execution_state["current_step"] = step_number
        execution_state["completed_steps"] = completed_steps
        execution_state["last_execution"] = exec_result
        
        result["execution_state"] = execution_state
        
        # Update task status
        if step_number == len(steps) and exec_result.get("status") == "completed":
            task.status = "completed"
        else:
            task.status = "executing"
        
        task.result = json.dumps(result)
        task.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "status": "ok",
            "task_id": task_id,
            "task_status": task.status,
            "execution_result": exec_result
        }
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Step execution failed:\n{error_details}")
        
        task.status = "failed"
        task.result = json.dumps({
            **result,
            "execution_error": str(e)
        })
        db.commit()
        
        raise HTTPException(status_code=500, detail=f"Step execution failed: {str(e)}")


@app.get("/tasks/{task_id}/execute/status")
def get_execution_status(task_id: str, db: Session = Depends(get_db)):
    """
    Get current execution status and progress.
    
    Args:
        task_id: Task ID
        db: Database session
        
    Returns:
        Current execution state
    """
    # Load task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if not task.result:
        raise HTTPException(status_code=400, detail="No execution state available")
    
    result = json.loads(task.result)
    execution_state = result.get("execution_state")
    
    if not execution_state:
        return {
            "status": "not_started",
            "task_id": task_id,
            "task_status": task.status,
            "message": "Execution not started. Call /execute/start first."
        }
    
    steps = execution_state.get("steps", [])
    current_step = execution_state.get("current_step", 0)
    completed_steps = execution_state.get("completed_steps", [])
    
    return {
        "status": "ok",
        "task_id": task_id,
        "task_status": task.status,
        "total_steps": len(steps),
        "current_step": current_step,
        "completed_steps": completed_steps,
        "completed_count": len(completed_steps),
        "execution_state": execution_state
    }


@app.get("/workspace/files/{file_path:path}")
def get_workspace_file(file_path: str):
    """
    Serve files from workspace directory.
    
    Args:
        file_path: Relative path from workspace root (e.g., 'outputs/task-id/step_1/file.json')
        
    Returns:
        File content with appropriate content-type
    """
    # Security: prevent directory traversal
    safe_path = Path(file_path).as_posix()
    if ".." in safe_path or safe_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    target = WORKSPACE_DIR / safe_path
    
    # Check if file exists and is within workspace
    try:
        target = target.resolve()
        WORKSPACE_DIR.resolve()
        
        if not str(target).startswith(str(WORKSPACE_DIR.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {str(e)}")
    
    # Determine content type
    suffix = target.suffix.lower()
    content_types = {
        '.json': 'application/json',
        '.csv': 'text/csv',
        '.txt': 'text/plain',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.pdf': 'application/pdf'
    }
    
    content_type = content_types.get(suffix, 'application/octet-stream')
    
    # Return file
    from fastapi.responses import FileResponse
    return FileResponse(
        path=target,
        media_type=content_type,
        filename=target.name
    )


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    """
    Get current task state.
    
    Args:
        task_id: Task ID
        db: Database session
        
    Returns:
        Full task state including latest answer and plan
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Parse result
    answer = None
    plan = None
    if task.result:
        result = json.loads(task.result)
        answer = result.get("answer")
        plan = result.get("plan")
    
    return {
        "task_id": task.id,
        "status": task.status,
        "data_source_type": task.data_source_type,
        "data_source_meta": json.loads(task.data_source_meta),
        "prompt": task.prompt,
        "answer": answer,
        "plan": plan,
        "created_at": task.created_at,
        "updated_at": task.updated_at
    }


@app.get("/tasks/{task_id}/interactions", response_model=list[InteractionResponse])
def get_interactions(task_id: str, db: Session = Depends(get_db)):
    """
    Get all planner interactions for a task.
    
    Args:
        task_id: Task ID
        db: Database session
        
    Returns:
        List of interactions ordered by created_at
    """
    # Verify task exists
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Load interactions
    interactions = (
        db.query(LlmInteraction)
        .filter(LlmInteraction.task_id == task_id)
        .order_by(LlmInteraction.created_at)
        .all()
    )
    
    return [
        {
            "id": interaction.id,
            "agent": interaction.agent,
            "prompt": interaction.prompt,
            "model_answer": interaction.model_answer,
            "input_tokens": interaction.input_tokens,
            "output_tokens": interaction.output_tokens,
            "created_at": interaction.created_at
        }
        for interaction in interactions
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
