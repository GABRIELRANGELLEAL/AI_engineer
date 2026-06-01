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
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime, TIMESTAMP
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.dialects.postgresql import JSONB
from dotenv import load_dotenv

from agents.planner_agent import (
    planner_agent_file,
    serialize_raw_response,
    build_conversation_history,
    format_plan_as_text,
)
from agents.translator_agent import translator_agent, _extract_json
from agents.executor_agent import executor_agent

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
Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Task(Base):
    """Task table: stores user tasks and their current state."""
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True, index=True)
    prompt = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    data_source_type = Column(String, nullable=False)
    data_source_meta = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmInteraction(Base):
    """LLM interactions table: audit log of all agent calls."""
    __tablename__ = "llm_interactions"
    
    id = Column(String, primary_key=True, index=True)
    task_id = Column(String, nullable=False, index=True)
    agent = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    model_answer = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    raw_response = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
        raw_response=serialize_raw_response(raw_response),
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
    
    # Reject if already proceeded
    if task.status == "proceeded":
        raise HTTPException(
            status_code=400,
            detail="Cannot send messages after task has been proceeded"
        )
    
    # Load conversation history
    interactions = (
        db.query(LlmInteraction)
        .filter(LlmInteraction.task_id == task_id)
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


@app.post("/tasks/{task_id}/proceed")
def proceed_task(task_id: str, db: Session = Depends(get_db)):
    """
    Mark task as proceeded (ready for translator/executor phase).
    
    Args:
        task_id: Task ID
        db: Database session
        
    Returns:
        Success message
    """
    # Load task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
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
    
    # Update status
    task.status = "proceeded"
    task.updated_at = datetime.utcnow()
    db.commit()
    
    return {"status": "ok", "task_id": task_id, "message": "Task proceeded"}


class ExecuteRequest(BaseModel):
    """Request to execute plan with optional step selection."""
    selected_steps: Optional[List[int]] = None


@app.post("/tasks/{task_id}/execute")
def execute_task(task_id: str, request: ExecuteRequest = None, db: Session = Depends(get_db)):
    """
    Execute the approved plan: translator -> executor.
    
    Args:
        task_id: Task ID
        request: Optional selected steps to execute
        db: Database session
        
    Returns:
        Execution results
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
    
    # Load plan
    if not task.result:
        raise HTTPException(status_code=400, detail="No plan available")
    
    result = json.loads(task.result)
    plan = result.get("plan", [])
    
    if not plan:
        raise HTTPException(status_code=400, detail="Cannot execute without a plan")
    
    # Filter plan by selected steps if provided
    selected_steps = request.selected_steps if request else None
    if selected_steps:
        # Filter plan to only include selected steps
        filtered_plan = []
        for item in plan:
            step_num = item if isinstance(item, dict) and "step" in item else plan.index(item) + 1
            if isinstance(item, dict):
                step_num = item.get("step", plan.index(item) + 1)
            else:
                step_num = plan.index(item) + 1
            
            if step_num in selected_steps:
                filtered_plan.append(item)
        
        if not filtered_plan:
            raise HTTPException(status_code=400, detail="No valid steps selected")
        
        plan = filtered_plan
        result["plan"] = plan
    
    try:
        # Format plan for translator
        plan_text = format_plan_as_text(result)
        
        # Translate to execution plan
        print(f"[DEBUG] Translating plan for task {task_id}")
        raw_translation = translator_agent(plan_text)
        execution_plan = _extract_json(raw_translation)
        
        if not execution_plan or not execution_plan.get("execution_plan"):
            raise ValueError("Translator returned invalid execution plan")
        
        # Execute
        print(f"[DEBUG] Executing plan for task {task_id}")
        exec_result = executor_agent(execution_plan)
        
        # Update task
        task.status = "completed" if exec_result["status"] == "completed" else "failed"
        task.result = json.dumps({
            **result,
            "execution_result": exec_result
        })
        task.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "status": "ok",
            "task_id": task_id,
            "task_status": task.status,
            "execution": exec_result
        }
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[ERROR] Execution failed:\n{error_details}")
        
        task.status = "failed"
        task.result = json.dumps({
            **result,
            "execution_error": str(e)
        })
        task.updated_at = datetime.utcnow()
        db.commit()
        
        raise HTTPException(status_code=500, detail=f"Execution error: {str(e)}")


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
