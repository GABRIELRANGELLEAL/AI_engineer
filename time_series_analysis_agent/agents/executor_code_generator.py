#!/usr/bin/env python3
"""
Code Generator for Executor Agent

Transforms execution context into a complete, self-contained Python script
that reads CSVs, performs analysis, and writes ui.json output.

Uses AgentLoop with thinking_budget from planner to optimize LLM usage.
Supports single retry with previous error feedback.
"""

import re
import json
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from .agent_loop import AgentLoop, AgentConfig
from .executor_context_builder import ExecutionContextPackage

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class CodeGenerationResult:
    """Result from code generation."""
    code: str
    input_tokens: int
    output_tokens: int
    success: bool
    error: Optional[str] = None
    raw_response: Optional[str] = None
    """Full LLM response for debugging/audit"""


def _build_code_generation_prompt(
    context: ExecutionContextPackage,
    previous_error: Optional[str] = None,
) -> tuple[str, str]:
    """
    Build the system + user prompt for code generation.
    
    Args:
        context: Execution context with step, workspace, data, etc.
        previous_error: Optional error from previous code execution (for retry)
        
    Returns:
        Tuple of (system_prompt, user_message)
    """
    system_prompt = """
        You are an expert Python data analyst specializing in analysis.

        Your task: Generate a COMPLETE, EXECUTABLE Python script that:
        1. Reads CSV files from the specified workspace paths
        2. Performs the analysis described in the STEP section
        3. Creates visualization blocks (text, tables, plots) following the UI.JSON CONTRACT
        4. Writes the output to the exact ui_json_path specified

        CRITICAL REQUIREMENTS:
        - Use ONLY the column names shown in DATA PREVIEW (do NOT guess or hallucinate)
        - Use ONLY the file paths shown in WORKSPACE PATHS
        - Follow the PLOTLY CONTRACT examples for plotting (use plotly.express or graph_objects)
        - Handle datetime parsing with pd.to_datetime() where needed
        - Use json.dumps(..., ensure_ascii=False, default=str) to handle numpy/datetime types
        - Include at least ONE text block with analysis insights (markdown format)
        - Tables and plots are optional, use only if needed for the analysis
        - The script must be self-contained (no imports from local modules)

        OUTPUT FORMAT:
        - Return ONLY the Python code, wrapped in ```python code fences
        - No explanations before or after the code
        - The script should run without any modifications

        PLOTTING GUIDELINES:
        - For simple time series: use plotly.express (px.line, px.bar, px.scatter)
        - For complex layouts (ACF/PACF, decomposition): use plotly.graph_objects with subplots
        - Always convert fig to JSON with: spec = json.loads(fig.to_json())
        - Only include spec["data"] and spec["layout"] in the plot block (NOT config or frames)
        - For large series (>2000 points), downsample before plotting to avoid performance issues

        ERROR HANDLING:
        - Use try/except blocks for data loading and transformations
        - If a column is missing, use alternative columns or skip that part gracefully
        - Print informative error messages to help debug issues
    """

    # Build user message with context
    user_parts = [
        "Generate a Python script for this analysis step.",
        "",
        context.to_prompt_text(),
    ]
    
    # Add retry context if this is a retry attempt
    if previous_error:
        user_parts.extend([
            "",
            "## PREVIOUS EXECUTION ERROR",
            "Your previous script failed with this error:",
            "```",
            previous_error,
            "```",
            "",
            "Fix the script to handle this error. Do NOT change the analysis goal.",
            "Common fixes:",
            "- Check column names match DATA PREVIEW exactly (case-sensitive)",
            "- Add pd.to_datetime() for date columns",
            "- Handle missing values with .dropna() or .fillna()",
            "- Use default=str in json.dumps() for datetime/numpy serialization",
        ])
    
    return system_prompt, "\n".join(user_parts)


def _extract_code_from_response(response_text: str) -> str:
    """
    Extract Python code from LLM response.
    
    Handles various formats:
    - ```python ... ```
    - ``` ... ```
    - Raw code without fences
    
    Args:
        response_text: Full response from LLM
        
    Returns:
        Extracted Python code
    """
    # Try to extract from code fences first
    # Pattern: ```python ... ``` or ``` ... ``` (flexible with newlines)
    code_fence_pattern = r"```(?:python)?\s*\n?(.*?)\n?```"
    matches = re.findall(code_fence_pattern, response_text, re.DOTALL)
    
    if matches:
        # Return first code block found
        return matches[0].strip()
    
    # If no code fences, check if the whole response looks like code
    # (starts with import/from or has function definitions)
    if response_text.strip().startswith(("import ", "from ", "def ", "#")):
        return response_text.strip()
    
    # Fallback: return as-is and let validation fail
    return response_text.strip()


def _validate_generated_code(code: str) -> tuple[bool, Optional[str]]:
    """
    Robust validation of generated code.
    
    Checks:
    - Code is not empty and reasonably sized
    - Contains required imports (pandas, json)
    - Contains UI JSON output logic
    - No obvious syntax errors (compile check)
    - Code size is within reasonable bounds
    
    Args:
        code: Generated Python code
        
    Returns:
        (is_valid, error_message)
    """
    if not code or len(code.strip()) < 50:
        return False, "Generated code is too short or empty"
    
    if len(code) > 50000:
        return False, "Generated code is too large (>50k chars, likely malformed)"
    
    # Check for required imports (pandas and json)
    has_pandas = "pandas" in code or "pd" in code
    has_json = "json" in code
    
    if not has_pandas:
        return False, "Generated code missing pandas import (required for CSV reading)"
    
    if not has_json:
        return False, "Generated code missing json import (required for ui.json output)"
    
    # Check for UI JSON output logic
    has_ui_json_ref = "ui_json_path" in code or "output_dir" in code
    has_json_dump = "json.dump" in code or "json.dumps" in code
    
    if not (has_ui_json_ref and has_json_dump):
        return False, "Generated code must contain ui.json output logic (path reference + json.dump)"
    
    # Try to compile (syntax check)
    try:
        compile(code, "<generated>", "exec")
    except SyntaxError as e:
        return False, f"Syntax error in generated code: {e}"
    
    return True, None


def generate_code(
    context: ExecutionContextPackage,
    previous_error: Optional[str] = None,
    model: str = "claude-haiku-4-5-20251001",
    verbose: bool = False,
) -> CodeGenerationResult:
    """
    Generate Python code for the execution step.
    
    Args:
        context: Execution context package with all necessary information
        previous_error: Optional error from previous execution (for retry)
        model: Claude model to use for generation
        verbose: Enable verbose logging in AgentLoop
        
    Returns:
        CodeGenerationResult with generated code and metadata
    """
    try:
        # Build prompt
        system_prompt, user_message = _build_code_generation_prompt(context, previous_error)
        
        # Get thinking budget from step (None for simple steps, 2000-10000 for complex)
        thinking_budget = context.step.get("thinking_budget")
        
        # Configure agent loop
        config = AgentConfig(
            tools=[],  # No tools - just code generation
            model=model,
            max_tokens=6144,  # Sufficient for code + comments (reduced from 8192)
            temperature=1.0,  # Required for thinking mode
            system_prompt=system_prompt,
            thinking_budget=thinking_budget,
            max_iterations=1,  # Single pass - no tool loop
        )
        
        # Run generation
        loop = AgentLoop(config=config, verbose=verbose)
        result = loop.run(user_message=user_message)
        
        if not result.success:
            return CodeGenerationResult(
                code="",
                input_tokens=result.metadata.get("input_tokens", 0),
                output_tokens=result.metadata.get("output_tokens", 0),
                success=False,
                error=f"Code generation failed: {result.error or 'Unknown error'}",
                raw_response=result.final_response,
            )
        
        # Extract code from response
        code = _extract_code_from_response(result.final_response)
        
        # Validate generated code
        is_valid, validation_error = _validate_generated_code(code)
        if not is_valid:
            return CodeGenerationResult(
                code=code,
                input_tokens=result.metadata.get("input_tokens", 0),
                output_tokens=result.metadata.get("output_tokens", 0),
                success=False,
                error=f"Code validation failed: {validation_error}",
                raw_response=result.final_response,
            )
        
        # Success
        return CodeGenerationResult(
            code=code,
            input_tokens=result.metadata.get("input_tokens", 0),
            output_tokens=result.metadata.get("output_tokens", 0),
            success=True,
            error=None,
            raw_response=result.final_response,
        )
        
    except Exception as e:
        # Catch-all for unexpected errors
        import traceback
        error_trace = traceback.format_exc()
        print(f"[ERROR] Code generation exception:\n{error_trace}")
        
        return CodeGenerationResult(
            code="",
            input_tokens=0,
            output_tokens=0,
            success=False,
            error=f"Unexpected error: {str(e)}",
            raw_response=None,
        )
