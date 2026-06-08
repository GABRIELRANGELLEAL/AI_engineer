#!/usr/bin/env python3
"""
Executor Agent - Refactored with sub-agents orchestration
Executes step-by-step plans with internal orchestration:
- StepAnalyzer: understands what needs to be done
- PlotlyCodegen: generates Python code for Plotly specs
- ErrorRecovery: fixes compilation errors
- Orchestrator: coordinates the flow with retry logic
"""

import os
import json
import uuid
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dotenv import load_dotenv
import anthropic
from sqlalchemy.orm import Session

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"
OUTPUTS_DIR = WORKSPACE_DIR / "outputs"
SKILLS_DIR = BASE_DIR / "skills"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Skill context cache
_skill_cache: Dict[str, str] = {}


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ExecutionContext:
    """Context shared between sub-agents during execution."""
    task_id: str
    step_number: int
    step_dict: Dict
    helper_output: Dict
    output_name: str
    
    # Results from each phase
    analysis_plan: Optional[Dict] = None
    python_code: Optional[str] = None
    spec_json: Optional[Dict] = None
    error_message: Optional[str] = None
    recovery_plan: Optional[Dict] = None
    
    # Retry control
    retry_count: int = 0
    max_retries: int = 2
    
    # Logging
    phases_log: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusUpdate:
    """Status update sent to frontend in real-time."""
    status: str  # "analyzing", "generating", "compiling", "fixing", "completed", "failed"
    message: str
    details: Optional[Dict] = None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_skill_context(skill_path: str) -> Optional[str]:
    """Load skill content from SKILL.md file."""
    if skill_path in _skill_cache:
        return _skill_cache[skill_path]
    
    full_path = BASE_DIR / skill_path
    if not full_path.exists():
        return None
    
    try:
        content = full_path.read_text(encoding="utf-8")
        # Remove YAML frontmatter
        lines = content.splitlines()
        if lines and lines[0].strip() == "---":
            for i, line in enumerate(lines[1:], start=1):
                if line.strip() == "---":
                    content = "\n".join(lines[i + 1:])
                    break
        
        _skill_cache[skill_path] = content
        return content
    except Exception as e:
        print(f"[WARNING] Failed to load skill {skill_path}: {e}")
        return None


def gather_previous_artifacts(task_id: str, current_step: int) -> Dict[int, List[str]]:
    """Gather files from previous steps."""
    previous_artifacts = {}
    task_output_dir = OUTPUTS_DIR / task_id
    
    if not task_output_dir.exists():
        return previous_artifacts
    
    for i in range(1, current_step):
        step_dir = task_output_dir / f"step_{i}"
        if step_dir.exists():
            files = []
            for f in step_dir.iterdir():
                if f.is_file() and not f.name.startswith("_"):
                    rel_path = f.relative_to(WORKSPACE_DIR)
                    files.append(str(rel_path))
            if files:
                previous_artifacts[i] = files
    
    return previous_artifacts


# ============================================================================
# SUB-AGENT 1: STEP ANALYZER
# ============================================================================

def step_analyzer_agent(
    context: ExecutionContext,
    skill_context: Optional[str] = None,
    previous_artifacts: Dict[int, List[str]] = None,
    model: str = "claude-haiku-4-5-20251001"
) -> Dict:
    """
    Analyzes the step and creates a brief execution plan.
    
    INPUT: step_dict from helper + skill context
    OUTPUT: analysis_plan with what needs to be done
    """
    
    step = context.step_dict
    helper = context.helper_output
    
    skill_section = ""
    if skill_context:
        skill_section = f"""
SKILL GUIDANCE:
{skill_context[:1000]}...
"""
    
    artifacts_section = ""
    if previous_artifacts:
        artifacts_section = "PREVIOUS STEP OUTPUTS:\n"
        for step_num, files in sorted(previous_artifacts.items()):
            artifacts_section += f"Step {step_num}:\n"
            for f in files:
                artifacts_section += f"  - {f}\n"
    
    prompt = f"""
You are analyzing a step in a time series analysis pipeline.

STEP INFORMATION:
Description: {step.get('description', '')}
Rationale: {step.get('rationale', '')}
Skill needed: {helper.get('skill_needed', False)}

{skill_section}

{artifacts_section}

YOUR TASK:
Generate a BRIEF plan (2-3 sentences) for what needs to be accomplished.
Identify:
- What data files to load
- What calculations/analysis to perform
- What type of visualization makes sense

OUTPUT: Valid JSON (no markdown)
{{
    "objective": "Brief objective statement",
    "data_sources": ["path/to/file.csv"],
    "calculations_needed": ["mean", "trend", "seasonality"],
    "plot_type": "line|scatter|bar|histogram|box",
    "plot_title": "Title for the visualization",
    "brief_rationale": "Why this approach"
}}
"""
    
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}]
    )
    
    text = response.content[0].text.strip()
    
    # Parse JSON
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    analysis = json.loads(text.strip())
    return analysis


# ============================================================================
# SUB-AGENT 2: PLOTLY CODEGEN
# ============================================================================

def plotly_codegen_agent(
    context: ExecutionContext,
    model: str = "claude-sonnet-4-5-20250929"
) -> str:
    """
    Generates Python code that produces a Plotly spec.
    
    INPUT: analysis_plan (+ recovery_plan if retry)
    OUTPUT: Python code as string
    """
    
    analysis = context.analysis_plan
    recovery_hint = ""
    
    if context.recovery_plan:
        recovery_hint = f"""
RECOVERY CONTEXT (Previous attempt failed):
Error: {context.error_message}
Root cause: {context.recovery_plan.get('root_cause', '')}
Fix suggestion: {context.recovery_plan.get('fix_suggestion', '')}
Fallback approach: {context.recovery_plan.get('fallback_approach', '')}
"""
    
    prompt = f"""
Generate Python code that creates a Plotly specification.

ANALYSIS PLAN:
Objective: {analysis.get('objective', '')}
Data sources: {analysis.get('data_sources', [])}
Calculations: {analysis.get('calculations_needed', [])}
Plot type: {analysis.get('plot_type', 'line')}
Plot title: {analysis.get('plot_title', '')}

{recovery_hint}

CODE REQUIREMENTS:
1. Import necessary libraries (pandas, json, plotly.graph_objects)
2. Load data from workspace/
3. Handle missing/invalid data (use .fillna(), .dropna())
4. Perform calculations
5. Create Plotly figure
6. Convert to JSON spec with: spec = json.loads(fig.to_json())
7. Return ONLY the spec dict with keys: "data" and "layout"

IMPORTANT:
- The code will be executed with exec(), last expression is the result
- NO print statements
- NO file writes
- Handle all errors gracefully
- Ensure NaN values are converted to None in final JSON

Generate ONLY Python code (no markdown fences, no explanations):
"""
    
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}]
    )
    
    code = response.content[0].text.strip()
    
    # Remove markdown if present
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    
    return code.strip()


# ============================================================================
# COMPILER & VALIDATOR
# ============================================================================

def compile_and_validate(
    code: str,
    task_id: str,
    step_number: int
) -> tuple[bool, Dict | str]:
    """
    Executes Python code and validates output.
    
    Returns:
        (success, spec_json | error_message)
    """
    
    step_output_dir = OUTPUTS_DIR / task_id / f"step_{step_number}"
    step_output_dir.mkdir(parents=True, exist_ok=True)
    
    script_path = step_output_dir / "_temp_codegen.py"
    
    try:
        # Wrap code to capture result
        wrapped_code = f"""
import sys
import json
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path

# Set working directory
import os
os.chdir(r'{WORKSPACE_DIR}')

# Execute code
{code}
"""
        
        script_path.write_text(wrapped_code, encoding='utf-8')
        
        # Execute with timeout
        result = subprocess.run(
            ["python", str(script_path)],
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown execution error"
            return False, error_msg
        
        # Try to parse output as JSON
        output = result.stdout.strip()
        
        # If code uses exec and returns value, it won't print
        # So we need a different approach - use eval
        exec_globals = {
            'pd': __import__('pandas'),
            'go': __import__('plotly.graph_objects'),
            'json': json,
            'Path': Path,
        }
        exec_locals = {}
        
        # Change to workspace
        import os
        old_cwd = os.getcwd()
        os.chdir(WORKSPACE_DIR)
        
        try:
            exec(code, exec_globals, exec_locals)
            
            # Find the spec variable or last expression result
            if 'spec' in exec_locals:
                spec = exec_locals['spec']
            else:
                # Try to find dict result
                for key, val in exec_locals.items():
                    if isinstance(val, dict) and 'data' in val and 'layout' in val:
                        spec = val
                        break
                else:
                    return False, "Code did not produce 'spec' variable with Plotly structure"
            
            # Validate structure
            if not isinstance(spec, dict):
                return False, "Result is not a dict"
            
            if 'data' not in spec or not isinstance(spec['data'], list):
                return False, "Missing 'data' key or not a list"
            
            if 'layout' not in spec or not isinstance(spec['layout'], dict):
                return False, "Missing 'layout' key or not a dict"
            
            # Clean NaN/Infinity values
            spec_json_str = json.dumps(spec, allow_nan=False)
            spec_clean = json.loads(spec_json_str)
            
            return True, spec_clean
            
        finally:
            os.chdir(old_cwd)
        
    except subprocess.TimeoutExpired:
        return False, "Code execution timeout (>15s)"
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON structure: {str(e)}"
    except Exception as e:
        return False, f"Execution error: {str(e)}"
    finally:
        # Clean up temp file
        if script_path.exists():
            try:
                script_path.unlink()
            except:
                pass


# ============================================================================
# SUB-AGENT 3: ERROR RECOVERY
# ============================================================================

def error_recovery_agent(
    context: ExecutionContext,
    model: str = "claude-haiku-4-5-20251001"
) -> Dict:
    """
    Analyzes compilation error and suggests fix strategy.
    
    INPUT: error_message + analysis_plan + failed code
    OUTPUT: recovery_plan with specific suggestions
    """
    
    prompt = f"""
CODE GENERATION ERROR - SUGGEST FIX

ORIGINAL PLAN:
{json.dumps(context.analysis_plan, indent=2)}

ERROR MESSAGE:
{context.error_message}

FAILED CODE (first 500 chars):
```
{context.python_code[:500]}...
```

YOUR TASK:
Analyze the error and suggest a specific fix strategy.

OUTPUT: Valid JSON (no markdown)
{{
    "root_cause": "describe what went wrong",
    "fix_suggestion": "specific action to fix (e.g., 'use df.fillna(0) before plotting')",
    "fallback_approach": "if fix won't work, simpler alternative (e.g., 'use bar chart instead')",
    "code_hint": "specific code snippet to try"
}}
"""
    
    response = client.messages.create(
        model=model,
        max_tokens=800,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}]
    )
    
    text = response.content[0].text.strip()
    
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    recovery = json.loads(text.strip())
    return recovery


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def execution_orchestrator(
    context: ExecutionContext,
    skill_context: Optional[str] = None,
    previous_artifacts: Dict = None,
    status_callback: Optional[Callable[[StatusUpdate], None]] = None,
) -> Dict:
    """
    Orchestrates the execution flow: analyze → codegen → compile → (retry if error) → success.
    """
    
    def emit_status(status: str, message: str, **details):
        """Send status update to frontend."""
        if status_callback:
            status_callback(StatusUpdate(
                status=status,
                message=message,
                details=details or None
            ))
    
    # ---- PHASE 1: ANALYZE STEP ----
    emit_status("analyzing_step", "Analisando objetivo do passo...")
    
    try:
        context.analysis_plan = step_analyzer_agent(
            context,
            skill_context=skill_context,
            previous_artifacts=previous_artifacts
        )
        context.phases_log["analysis"] = {"status": "success"}
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Analysis failed: {str(e)}",
            "phase": "analysis"
        }
    
    # ---- PHASE 2-3: CODEGEN + COMPILE (with retry) ----
    for attempt in range(context.max_retries + 1):
        emit_status(
            "generating_code",
            f"Gerando código Plotly (tentativa {attempt + 1}/{context.max_retries + 1})..."
        )
        
        try:
            context.python_code = plotly_codegen_agent(context)
        except Exception as e:
            context.error_message = f"Codegen error: {str(e)}"
            continue
        
        emit_status("compiling", "Compilando e validando código...")
        
        success, result = compile_and_validate(
            context.python_code,
            context.task_id,
            context.step_number
        )
        
        if success:
            # ✅ SUCCESS
            context.spec_json = result
            context.phases_log["codegen"] = {
                "status": "success",
                "attempts": attempt + 1
            }
            emit_status("completed", "Código compilou com sucesso!")
            
            return {
                "status": "completed",
                "spec": context.spec_json,
                "analysis": context.analysis_plan,
            }
        else:
            # ❌ ERROR
            context.error_message = result
            context.phases_log["codegen"] = {
                "status": "error",
                "attempt": attempt + 1,
                "error": result[:200]
            }
            
            if attempt < context.max_retries:
                # Try recovery
                emit_status(
                    "fixing_error",
                    f"Erro detectado: {result[:100]}...",
                    attempt=attempt + 1
                )
                
                try:
                    context.recovery_plan = error_recovery_agent(context)
                    emit_status(
                        "fixing_error",
                        f"Tentando fix: {context.recovery_plan.get('fix_suggestion', '')}",
                        root_cause=context.recovery_plan.get('root_cause', '')
                    )
                    context.retry_count += 1
                except Exception as e:
                    context.recovery_plan = None
                    emit_status("fixing_error", f"Recovery failed: {str(e)}")
                
                # Loop continues with recovery context
            else:
                # All retries exhausted
                emit_status("failed", f"Falha após {context.max_retries + 1} tentativas")
                
                return {
                    "status": "failed",
                    "error": context.error_message,
                    "recovery_attempted": context.retry_count > 0,
                    "phase": "codegen"
                }
    
    return {
        "status": "failed",
        "error": "Unknown error in orchestration",
        "phase": "unknown"
    }


# ============================================================================
# ENTRY POINT (compatible with main.py)
# ============================================================================

def executor_agent(
    task_id: str,
    output_name: str,
    steps: List[Dict],
    current_step: int = 1,
    db: Session = None,
    model_name: str = "claude-sonnet-4-5-20250929",
    status_callback: Optional[Callable] = None,
) -> Dict:
    """
    Entry point for executing a single step.
    
    Args:
        task_id: Unique task identifier
        output_name: Base name for output files
        steps: List of step dicts from helper_contet_agent
        current_step: Which step to execute (1-indexed)
        db: SQLAlchemy session for logging
        model_name: Claude model (currently not used, agents have fixed models)
        status_callback: Optional callback for real-time status updates
        
    Returns:
        Dict with execution results
    """
    
    # Validate step number
    if current_step < 1 or current_step > len(steps):
        return {
            "task_id": task_id,
            "status": "error",
            "error": f"Invalid step number {current_step}. Must be between 1 and {len(steps)}"
        }
    
    step_dict = steps[current_step - 1]
    
    # Load skill context if needed
    skill_context = None
    if step_dict.get("skill_needed") and step_dict.get("arg"):
        skill_context = load_skill_context(step_dict["arg"])
    
    # Gather previous artifacts
    previous_artifacts = gather_previous_artifacts(task_id, current_step)
    
    # Create execution context
    context = ExecutionContext(
        task_id=task_id,
        step_number=current_step,
        step_dict=step_dict,
        helper_output={
            "skill_needed": step_dict.get("skill_needed", False),
            "arg": step_dict.get("arg"),
            "description": step_dict.get("description", ""),
            "rationale": step_dict.get("rationale", ""),
        },
        output_name=output_name,
    )
    
    # Execute orchestration
    result = execution_orchestrator(
        context,
        skill_context=skill_context,
        previous_artifacts=previous_artifacts,
        status_callback=status_callback,
    )
    
    # If successful, build and save ui.json
    if result["status"] == "completed":
        ui_json = {
            "step_number": current_step,
            "title": context.analysis_plan.get("plot_title", "Analysis Results"),
            "blocks": [
                {
                    "type": "text",
                    "content": f"## {context.analysis_plan.get('objective', '')}\n\n{context.analysis_plan.get('brief_rationale', '')}"
                },
                {
                    "type": "plot",
                    "title": context.analysis_plan.get("plot_title", "Visualization"),
                    "library": "plotly",
                    "spec": context.spec_json,
                }
            ]
        }
        
        ui_filename = f"{output_name}_{current_step}_ui.json"
        step_output_dir = OUTPUTS_DIR / task_id / f"step_{current_step}"
        step_output_dir.mkdir(parents=True, exist_ok=True)
        
        ui_path = step_output_dir / ui_filename
        ui_path.write_text(json.dumps(ui_json, indent=2), encoding='utf-8')
        
        # Build artifacts list
        all_artifacts = dict(previous_artifacts)
        rel_ui_path = ui_path.relative_to(WORKSPACE_DIR)
        all_artifacts[current_step] = [str(rel_ui_path)]
        
        return {
            "task_id": task_id,
            "step_number": current_step,
            "total_steps": len(steps),
            "step_description": step_dict.get("description", ""),
            "status": "completed",
            "summary": context.analysis_plan.get("objective", "Step completed"),
            "generated_files": [str(rel_ui_path)],
            "all_artifacts": all_artifacts,
            "next_step_ready": True,
            "phases_log": context.phases_log,
        }
    else:
        # Execution failed
        return {
            "task_id": task_id,
            "step_number": current_step,
            "total_steps": len(steps),
            "step_description": step_dict.get("description", ""),
            "status": "error",
            "summary": f"Step failed: {result.get('error', 'Unknown error')}",
            "error": result.get("error", "Unknown error"),
            "recovery_attempted": result.get("recovery_attempted", False),
            "generated_files": [],
            "next_step_ready": False,
            "phases_log": context.phases_log,
        }


# ============================================================================
# LOGGING TO DATABASE
# ============================================================================

def log_step_to_db(
    db: Session,
    task_id: str,
    step_number: int,
    prompt: str,
    result: Dict,
    raw_response: Any = None
):
    """Log step execution to PostgreSQL llm_interactions table."""
    from main import LlmInteraction
    
    interaction_id = str(uuid.uuid4())
    
    interaction = LlmInteraction(
        id=interaction_id,
        task_id=task_id,
        agent=f"executor_orchestrator_step_{step_number}",
        prompt=prompt[:5000],  # Truncate if too long
        model_answer=json.dumps(result),
        input_tokens=result.get("input_tokens", 0),
        output_tokens=result.get("output_tokens", 0),
        raw_response={},
        created_at=datetime.utcnow()
    )
    
    db.add(interaction)
    db.commit()
