#!/usr/bin/env python3
"""
Executor Orchestrator

Orchestrates the execution of a single step from the planner's plan.
Coordinates context_builder, code_generator, and code_runner modules.

Flow:
    1. Decide output_type (chat vs card)
    2. For chat: return instant response
    3. For card: context → code → run → (retry once if failed) → validate
    4. Persist to llm_interactions
    5. Return standardized StepExecutionResult
"""

import json
import uuid
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session

from .executor_context_builder import build_context, ExecutionContextPackage
from .executor_code_generator import generate_code, CodeGenerationResult
from .executor_code_runner import run_code, CodeRunResult

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"


# Forward declaration - will be imported inside function to avoid circular import
Task = None
LlmInteraction = None


@dataclass
class StepExecutionResult:
    """
    Standardized result format expected by frontend.
    Matches TypeScript interface StepExecutionResult in frontend/src/types.ts
    """
    task_id: str
    step_number: int
    total_steps: int
    step_description: str
    status: str  # "completed" | "error"
    summary: str
    generated_files: List[str]
    all_artifacts: Dict[int, List[str]]
    next_step_ready: bool
    tool_uses_count: int
    input_tokens: int
    output_tokens: int
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)


def _extract_csv_paths(data_source_meta: dict) -> List[str]:
    """
    Extract CSV paths from task's data_source_meta.
    
    Args:
        data_source_meta: Dict with csv_path, csv_paths, or database_id
        
    Returns:
        List of relative paths from workspace root
    """
    if "csv_paths" in data_source_meta:
        paths = data_source_meta["csv_paths"]
        if isinstance(paths, list):
            return paths
        return [paths]
    elif "csv_path" in data_source_meta:
        return [data_source_meta["csv_path"]]
    elif "database_id" in data_source_meta:
        # TODO: handle database sources
        return []
    return []


def _gather_all_artifacts(task_id: str, current_step: int) -> Dict[int, List[str]]:
    """
    Gather all artifacts from all completed steps (including current).
    
    Args:
        task_id: Task ID
        current_step: Current step number (1-indexed)
        
    Returns:
        Dict mapping step_number to list of artifact paths
    """
    artifacts = {}
    outputs_dir = WORKSPACE_DIR / "outputs" / task_id
    
    if not outputs_dir.exists():
        return artifacts
    
    for step_num in range(1, current_step + 1):
        step_dir = outputs_dir / f"step_{step_num}"
        
        if not step_dir.exists():
            continue
        
        step_files = [
            str(f.relative_to(WORKSPACE_DIR))
            for f in step_dir.iterdir()
            if f.is_file()
        ]
        
        if step_files:
            artifacts[step_num] = step_files
    
    return artifacts


def _extract_summary_from_ui_json(ui_json_path: Path) -> str:
    """
    Extract summary text from ui.json for collapsed card view.
    Uses first text block or falls back to title.
    
    Args:
        ui_json_path: Path to ui.json file
        
    Returns:
        Summary string (max 200 chars)
    """
    if not ui_json_path.exists():
        return "Analysis completed."
    
    try:
        with open(ui_json_path, "r", encoding="utf-8") as f:
            ui_data = json.load(f)
        
        # Try to get first text block
        for block in ui_data.get("blocks", []):
            if block.get("type") == "text":
                content = block.get("content", "")
                # Remove markdown, truncate
                summary = content.replace("**", "").replace("##", "").strip()
                if summary:
                    return summary[:200] + ("..." if len(summary) > 200 else "")
        
        # Fallback to title
        title = ui_data.get("title", "")
        if title:
            return title
        
        return "Analysis completed."
        
    except Exception:
        return "Analysis completed."


def _execute_chat_step(
    task_id: str,
    step: dict,
    step_number: int,
    total_steps: int,
    all_artifacts: Dict[int, List[str]],
) -> StepExecutionResult:
    """
    Execute a 'chat' output_type step (instant response, no LLM/code).
    
    Args:
        task_id: Task ID
        step: Step dict from plan
        step_number: Current step number
        total_steps: Total steps in plan
        all_artifacts: Accumulated artifacts from previous steps
        
    Returns:
        StepExecutionResult with status="completed"
    """
    description = step.get("description", "Step completed")
    next_step_ready = step_number < total_steps  # Ready if not last step
    
    return StepExecutionResult(
        task_id=task_id,
        step_number=step_number,
        total_steps=total_steps,
        step_description=description,
        status="completed",
        summary=f"Chat response: {description[:100]}",
        generated_files=[],
        all_artifacts=all_artifacts,
        next_step_ready=next_step_ready,
        tool_uses_count=0,
        input_tokens=0,
        output_tokens=0,
    )


def _execute_card_step(
    task_id: str,
    output_name: str,
    step: dict,
    csv_paths: List[str],
    step_number: int,
    total_steps: int,
    all_artifacts: Dict[int, List[str]],
    db: Session,
) -> StepExecutionResult:
    """
    Execute a 'card' output_type step (full pipeline: context → code → run).
    
    Flow:
        1. Build context deterministically
        2. Generate code via LLM with thinking_budget
        3. Run code via subprocess
        4. Retry once if failed (with error feedback)
        5. Extract summary from ui.json
        6. Persist to llm_interactions
        7. Return structured result
    
    Args:
        task_id: Task ID
        output_name: Output name prefix
        step: Step dict from plan
        csv_paths: CSV file paths
        step_number: Current step number
        total_steps: Total steps in plan
        all_artifacts: Accumulated artifacts from previous steps
        db: Database session for llm_interactions
        
    Returns:
        StepExecutionResult with status="completed" or "error"
    """
    description = step.get("description", "")
    next_step_ready = step_number < total_steps  # Ready if not last step
    
    # 1. Build context
    try:
        skill_context = step.get("skill_context") if "skill_context" in step else None
        
        context = build_context(
            task_id=task_id,
            output_name=output_name,
            step=step,
            csv_paths=csv_paths,
            current_step=step_number,
            skill_context=skill_context,
        )
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[ERROR] Context building failed:\n{error_trace}")
        
        return StepExecutionResult(
            task_id=task_id,
            step_number=step_number,
            total_steps=total_steps,
            step_description=description,
            status="error",
            summary=f"Context building failed: {str(e)}",
            generated_files=[],
            all_artifacts=all_artifacts,
            next_step_ready=False,
            tool_uses_count=0,
            input_tokens=0,
            output_tokens=0,
        )
    
    # 2. Generate code
    print(f"[EXECUTOR] Generating code for step {step_number}...")
    gen_result = generate_code(context, previous_error=None)
    
    if not gen_result.success:
        print(f"[ERROR] Code generation failed: {gen_result.error}")
        
        return StepExecutionResult(
            task_id=task_id,
            step_number=step_number,
            total_steps=total_steps,
            step_description=description,
            status="error",
            summary=f"Code generation failed: {gen_result.error}",
            generated_files=[],
            all_artifacts=all_artifacts,
            next_step_ready=False,
            tool_uses_count=0,
            input_tokens=gen_result.input_tokens,
            output_tokens=gen_result.output_tokens,
        )
    
    # 3. Run code (first attempt)
    print(f"[EXECUTOR] Running generated code for step {step_number}...")
    ui_json_path = WORKSPACE_DIR / context.workspace["ui_json_path"]
    
    run_result = run_code(
        code=gen_result.code,
        script_path=context.workspace["script_path"],
        ui_json_path=context.workspace["ui_json_path"],
        timeout=60,
    )
    
    # 4. Retry once if failed
    if not run_result.success:
        print(f"[EXECUTOR] First execution failed, retrying with error feedback...")
        
        # Retry with error feedback
        gen_result_retry = generate_code(context, previous_error=run_result.stderr)
        
        if gen_result_retry.success:
            print(f"[EXECUTOR] Retrying execution with fixed code...")
            run_result = run_code(
                code=gen_result_retry.code,
                script_path=context.workspace["script_path"],
                ui_json_path=context.workspace["ui_json_path"],
                timeout=60,
            )
            # Update tokens from retry
            gen_result.input_tokens += gen_result_retry.input_tokens
            gen_result.output_tokens += gen_result_retry.output_tokens
        else:
            print(f"[ERROR] Retry code generation also failed")
    
    # 5. Extract summary from ui.json
    summary = "Code execution failed"
    if run_result.success and ui_json_path.exists():
        summary = _extract_summary_from_ui_json(ui_json_path)
    elif run_result.error:
        summary = run_result.error[:200]  # Truncate error to 200 chars
    
    # 6. Persist to llm_interactions
    try:
        from main import LlmInteraction
        
        # Build model_answer as JSON string (following planner pattern)
        model_answer_dict = {
            "code_generated": True,
            "script_path": context.workspace["script_path"],
            "execution_status": "completed" if run_result.success else "failed",
            "returncode": run_result.returncode,
            "ui_json_valid": run_result.ui_json_valid,
            "summary": summary
        }
        
        interaction = LlmInteraction(
            id=str(uuid.uuid4()),
            task_id=task_id,
            agent="executor",
            prompt=context.to_prompt_text()[:2000],  # Truncate prompt to avoid oversized records
            model_answer=json.dumps(model_answer_dict, ensure_ascii=False),
            input_tokens=gen_result.input_tokens,
            output_tokens=gen_result.output_tokens,
            created_at=datetime.utcnow()
        )
        db.add(interaction)
        db.commit()
        print(f"[EXECUTOR] Interaction persisted to database")
        
    except Exception as persist_error:
        print(f"[WARNING] Failed to persist LLM interaction: {persist_error}")
        # Don't fail the whole execution if persistence fails
    
    # 7. Build and return result
    next_step = step_number == total_steps  # Not ready if last step
    
    return StepExecutionResult(
        task_id=task_id,
        step_number=step_number,
        total_steps=total_steps,
        step_description=description,
        status="completed" if run_result.success else "error",
        summary=summary,
        generated_files=run_result.generated_files,
        all_artifacts=all_artifacts,
        next_step_ready=not next_step,  # Ready if there are more steps
        tool_uses_count=0,
        input_tokens=gen_result.input_tokens,
        output_tokens=gen_result.output_tokens,
    )


def executor_orchestrator(
    task_id: str,
    output_name: str,
    steps: List[dict],
    current_step: int,
    db: Session,
) -> dict:
    """
    Execute a single step from the planner's plan.
    
    This is the main entry point called by main.py's execute_step endpoint.
    
    Args:
        task_id: Task ID
        output_name: Output name prefix (e.g., "analysis_results")
        steps: Full list of steps from planner
        current_step: Step number to execute (1-indexed)
        db: SQLAlchemy database session
        
    Returns:
        dict matching StepExecutionResult schema for frontend
        
    Raises:
        ValueError: If step_number is out of range or task not found
    """
    try:
        # Validate step number
        if current_step < 1 or current_step > len(steps):
            raise ValueError(f"Invalid step number {current_step}. Must be between 1 and {len(steps)}")
        
        step = steps[current_step - 1]
        total_steps = len(steps)
        
        # Import Task model (avoiding circular import)
        from main import Task
        
        # Get task to extract csv_paths
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        data_source_meta = json.loads(task.data_source_meta)
        csv_paths = _extract_csv_paths(data_source_meta)
        
        # Gather all artifacts from previous steps (not including current)
        # Current step artifacts will be added after execution
        all_artifacts = _gather_all_artifacts(task_id, current_step - 1)
        
        # Decide execution path based on output_type
        output_type = step.get("output_type", "card")
        
        if output_type == "chat":
            result = _execute_chat_step(
                task_id=task_id,
                step=step,
                step_number=current_step,
                total_steps=total_steps,
                all_artifacts=all_artifacts,
            )
        else:  # card
            result = _execute_card_step(
                task_id=task_id,
                output_name=output_name,
                step=step,
                csv_paths=csv_paths,
                step_number=current_step,
                total_steps=total_steps,
                all_artifacts=all_artifacts,
                db=db,
            )
        
        # Update artifacts to include current step files
        all_artifacts = _gather_all_artifacts(task_id, current_step)
        result.all_artifacts = all_artifacts
        
        # Note: LLM interaction persistence happens inside _execute_card_step
        # Only card-type steps use LLM, so persistence is handled there
        
        return result.to_dict()
        
    except Exception as e:
        # Catch-all for unexpected errors
        error_trace = traceback.format_exc()
        print(f"[ERROR] Executor orchestrator failed:\n{error_trace}")
        
        # Return error result
        error_result = StepExecutionResult(
            task_id=task_id,
            step_number=current_step,
            total_steps=len(steps),
            step_description=steps[current_step - 1].get("description", "") if current_step <= len(steps) else "",
            status="error",
            summary=f"Execution failed: {str(e)}",
            generated_files=[],
            all_artifacts={},
            next_step_ready=False,
            tool_uses_count=0,
            input_tokens=0,
            output_tokens=0,
        )
        return error_result.to_dict()
