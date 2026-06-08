#!/usr/bin/env python3
"""
Code Runner for Executor Agent

Executes generated Python scripts in isolated subprocess with:
- Timeout control (default 60s)
- Stdout/stderr capture
- Output validation (ui.json existence and format)
- Artifact listing

Safety measures:
- Runs with workspace as cwd (relative paths work)
- Kills process on timeout
- Captures all errors for retry logic
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"


@dataclass
class CodeRunResult:
    """
    Result from running generated code.
    
    Attributes:
        success: True if script executed successfully and produced valid ui.json
        returncode: Process exit code (0 = success)
        stdout: Standard output from script
        stderr: Standard error (includes traceback if failed)
        ui_json_valid: True if ui.json exists and is valid JSON with blocks
        generated_files: List of all files created in step directory (relative to workspace)
        error: Human-readable error message (None if success)
    """
    success: bool
    returncode: int
    stdout: str
    stderr: str
    ui_json_valid: bool
    generated_files: List[str]
    error: Optional[str] = None


def _validate_ui_json(ui_json_path: Path) -> tuple[bool, Optional[str]]:
    """
    Validate that ui.json exists and has correct structure.
    
    Args:
        ui_json_path: Absolute path to ui.json file
        
    Returns:
        (is_valid, error_message)
    """
    if not ui_json_path.exists():
        return False, f"Output file not created: {ui_json_path.name}"
    
    try:
        with open(ui_json_path, "r", encoding="utf-8") as f:
            ui_data = json.load(f)
        
        # Check required fields
        if not isinstance(ui_data, dict):
            return False, "ui.json must be a dictionary"
        
        if "blocks" not in ui_data:
            return False, "ui.json missing 'blocks' field"
        
        if not isinstance(ui_data["blocks"], list):
            return False, "'blocks' must be a list"
        
        # Valid
        return True, None
        
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in ui.json: {str(e)}"
    except Exception as e:
        return False, f"Error reading ui.json: {str(e)}"


def _list_generated_files(step_dir: Path) -> List[str]:
    """
    List all files created in the step directory.
    
    Args:
        step_dir: Absolute path to step directory
        
    Returns:
        List of paths relative to workspace root
    """
    if not step_dir.exists():
        return []
    
    files = [
        str(f.relative_to(WORKSPACE_DIR))
        for f in step_dir.iterdir()
        if f.is_file()
    ]
    
    return sorted(files)


def run_code(
    code: str,
    script_path: str,
    ui_json_path: str,
    timeout: int = 60,
) -> CodeRunResult:
    """
    Execute generated Python code in isolated subprocess.
    
    Flow:
        1. Create step directory if needed
        2. Save code to script.py
        3. Execute with subprocess (cwd=workspace)
        4. Capture stdout/stderr
        5. Validate ui.json was created
        6. List all generated files
        7. Return structured result
    
    Args:
        code: Python code to execute (complete script)
        script_path: Where to save script (relative to workspace, e.g., "outputs/abc/step_1/script.py")
        ui_json_path: Expected ui.json path (relative to workspace)
        timeout: Max execution time in seconds (default 60)
        
    Returns:
        CodeRunResult with success status and details
        
    Notes:
        - Script runs with workspace as working directory
        - Paths in script should be relative to workspace
        - Timeout kills process and returns error
        - On failure, stderr contains full traceback for retry
    """
    # Convert paths to absolute
    script_abs = WORKSPACE_DIR / script_path
    ui_json_abs = WORKSPACE_DIR / ui_json_path
    step_dir = script_abs.parent
    
    # Initialize output variables for error handling
    returncode = -1
    stdout = ""
    stderr = ""
    ui_json_valid = False
    generated_files = []
    
    try:
        # 1. Create step directory
        step_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. Save script
        with open(script_abs, "w", encoding="utf-8") as f:
            f.write(code)
        
        print(f"[CODE_RUNNER] Script saved to: {script_abs}")
        
    except Exception as e:
        return CodeRunResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=f"Failed to save script: {str(e)}",
            ui_json_valid=False,
            generated_files=[],
            error=f"Script setup failed: {str(e)}",
        )
    
    # 3. Execute script
    try:
        print(f"[CODE_RUNNER] Executing script with timeout={timeout}s...")
        
        # Run with workspace as cwd so relative paths work
        # Use sys.executable to ensure same Python interpreter
        result = subprocess.run(
            [sys.executable, str(script_abs)],
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
        
        print(f"[CODE_RUNNER] Script finished with returncode={returncode}")
        
        # Show output for debugging (preview only, full content preserved below)
        if stdout:
            preview = stdout[:500] + ("..." if len(stdout) > 500 else "")
            print(f"[STDOUT] {preview}")
        if stderr:
            preview = stderr[:500] + ("..." if len(stderr) > 500 else "")
            print(f"[STDERR] {preview}")
        
    except subprocess.TimeoutExpired:
        error_msg = f"Script execution exceeded timeout of {timeout}s"
        print(f"[CODE_RUNNER] {error_msg}")
        
        generated_files = _list_generated_files(step_dir)
        
        return CodeRunResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=error_msg,
            ui_json_valid=False,
            generated_files=generated_files,
            error=error_msg,
        )
        
    except Exception as e:
        error_msg = f"Script execution failed: {str(e)}"
        print(f"[CODE_RUNNER] {error_msg}")
        
        generated_files = _list_generated_files(step_dir)
        
        return CodeRunResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=error_msg,
            ui_json_valid=False,
            generated_files=generated_files,
            error=error_msg,
        )
    
    # 4. Validate output
    try:
        ui_json_valid, validation_error = _validate_ui_json(ui_json_abs)
    except Exception as e:
        print(f"[CODE_RUNNER] Unexpected error during ui.json validation: {str(e)}")
        validation_error = f"Validation error: {str(e)}"
        ui_json_valid = False
    
    # 5. List generated files
    generated_files = _list_generated_files(step_dir)
    
    # 6. Determine success
    success = returncode == 0 and ui_json_valid
    
    # 7. Build error message if failed
    error = None
    if not success:
        if returncode != 0:
            error = f"Script exited with code {returncode}"
            if stderr:
                error += f"\n\nTraceback:\n{stderr}"
        elif not ui_json_valid:
            error = validation_error or "ui.json validation failed"
    
    return CodeRunResult(
        success=success,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        ui_json_valid=ui_json_valid,
        generated_files=generated_files,
        error=error,
    )
