#!/usr/bin/env python3
"""
Planning agents for the multi-agent workflow.

- questioner_agent: Refines a raw user prompt into a structured brief with questions
- planner_agent: Creates human-readable step-by-step plans for user validation
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import anthropic
import ast
from typing import Any, List, Optional

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"
WORKSPACE = BASE_DIR / "workspace"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Discovery tools (read-only)
PLANNER_TOOLS = [
    {
        "name": "view_file",
        "description": "Read file contents to understand data structure, columns, format. Use this to inspect CSV files, understand data schemas, check date ranges.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to file in workspace (e.g., 'data.csv', 'uploads/sales.csv')"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "search_files",
        "description": "List files matching a pattern in workspace. Use to discover available data files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '*.csv', '*.xlsx', 'uploads/*')"
                }
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "get_file_stats",
        "description": "Get metadata about a file: size, line count, modification date. Useful for understanding data volume.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to file in workspace"
                }
            },
            "required": ["path"]
        }
    }
]


def _handle_view_file(path: str) -> str:
    """Read file contents for discovery phase."""
    target = WORKSPACE / path
    
    if not target.exists():
        return f"File not found: {path}"
    
    if not target.is_file():
        return f"Path is a directory, not a file: {path}. Use search_files to list contents."
    
    try:
        content = target.read_text(encoding="utf-8")
        
        # For CSV, TSV, XLS, and XLSX files, show first 10 lines + line count
        if target.suffix.lower() in ['.csv', '.tsv', '.xls', '.xlsx']:
            lines = content.split('\n')
            preview = '\n'.join(lines[:10])
            total_lines = len(lines)
            return f"Spreadsheet file ({target.suffix.lower()}) with {total_lines} lines. First 10 lines:\n{preview}\n\n[... {total_lines - 10} more lines]"
        
        # For other text files, limit to 2000 chars
        if len(content) > 2000:
            return f"{content[:2000]}\n\n[... file continues, {len(content)} total chars]"
        
        return content
        
    except UnicodeDecodeError:
        return f"Binary file, cannot read as text: {path}"


def _handle_search_files(pattern: str) -> str:
    """List files matching glob pattern."""
    try:
        matches = list(WORKSPACE.glob(pattern))
        
        if not matches:
            return f"No files found matching pattern: {pattern}"
        
        file_list = []
        for match in sorted(matches):
            rel_path = match.relative_to(WORKSPACE)
            size_kb = match.stat().st_size / 1024
            file_type = "dir" if match.is_dir() else "file"
            file_list.append(f"  - {rel_path} ({file_type}, {size_kb:.1f} KB)")
        
        return f"Found {len(matches)} matches for '{pattern}':\n" + "\n".join(file_list)
        
    except Exception as e:
        return f"Error searching files: {str(e)}"


def _handle_get_file_stats(path: str) -> str:
    """Get file metadata."""
    target = WORKSPACE / path
    
    if not target.exists():
        return f"File not found: {path}"
    
    try:
        stats = target.stat()
        size_kb = stats.st_size / 1024
        modified = datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
        
        result = f"File: {path}\n"
        result += f"Size: {size_kb:.1f} KB\n"
        result += f"Modified: {modified}\n"
        
        if target.suffix.lower() in ['.csv', '.tsv', '.txt']:
            try:
                with open(target, 'r', encoding='utf-8') as f:
                    line_count = sum(1 for _ in f)
                result += f"Lines: {line_count}\n"
            except:
                pass
        
        return result
        
    except Exception as e:
        return f"Error getting file stats: {str(e)}"


# Tool dispatcher
TOOL_HANDLERS = {
    "view_file": _handle_view_file,
    "search_files": _handle_search_files,
    "get_file_stats": _handle_get_file_stats,
}


def _parse_planner_response_fixed(text: str) -> dict:
    """Parse planner response and extract answer and plan."""
    text = text.strip()
    
    # Try to extract JSON/dict from code blocks first
    # Pattern: ```json ... ``` or ```python ... ``` or ``` ... ```
    code_block_pattern = r"```(?:json|python)?\s*(\{[\s\S]*?\})\s*```"
    code_match = re.search(code_block_pattern, text)
    
    if code_match:
        # Extract the dict/JSON from within code block
        text = code_match.group(1).strip()
    else:
        # Try stripping outer code fences if present
        if "```" in text:
            text = re.sub(r"^```(?:python|json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()
    
    # Try parsing as JSON
    try:
        parsed = json.loads(text)
        return {
            "answer": parsed.get("answer", ""),
            "plan": parsed.get("plan", []),
        }
    except json.JSONDecodeError:
        pass
    
    # Try parsing as Python literal
    try:
        parsed = ast.literal_eval(text)
        return {
            "answer": parsed.get("answer", ""),
            "plan": parsed.get("plan", []),
        }
    except (ValueError, SyntaxError):
        pass
    
    # If all parsing fails, treat as plain text answer with no plan
    # This happens when agent is still exploring or asking questions
    return {
        "answer": text,
        "plan": []
    }


def format_plan_as_text(result: dict[str, Any]) -> str:
    """Format planner output for downstream agents that expect a single text plan."""
    parts = [result.get("answer", "")]
    for i, step in enumerate(result.get("plan", []), start=1):
        parts.append(f"\nStep {i}: {step}")
    return "\n".join(parts).strip()

# def _extract_yaml_header(markdown: str) -> str:
#     """Return YAML frontmatter (including --- delimiters) from a SKILL.md file."""
#     lines = markdown.splitlines()
#     if not lines or lines[0].strip() != "---":
#         return ""
#     for i, line in enumerate(lines[1:], start=1):
#         if line.strip() == "---":
#             return "\n".join(lines[: i + 1])
#     return ""


# def _build_skill_catalog() -> List[dict]:
#     """Build a catalog of all skills from YAML headers in skills/*/SKILL.md."""
#     entries = []
#     if not SKILLS_DIR.is_dir():
#         return entries
    
#     for skill_dir in sorted(SKILLS_DIR.iterdir()):
#         if not skill_dir.is_dir():
#             continue
#         skill_file = skill_dir / "SKILL.md"
#         if not skill_file.exists():
#             continue
        
#         content = skill_file.read_text(encoding="utf-8")
#         header = _extract_yaml_header(content)
#         if not header:
#             continue
        
#         body = "\n".join(line for line in header.splitlines() if line.strip() != "---")
#         data = yaml.safe_load(body)
#         if not isinstance(data, dict):
#             continue
        
#         name = data.get("name")
#         description = data.get("description")
#         if not name or not description:
#             continue
        
#         entries.append({"skill_name": str(name), "description": str(description)})
    
#     return entries


# def _build_skill_catalog() -> List[dict]:
#     """Build a catalog of all skills from YAML headers in skills/*/SKILL.md."""
#     entries = []
#     if not SKILLS_DIR.is_dir():
#         return entries
    
#     for skill_dir in sorted(SKILLS_DIR.iterdir()):
#         if not skill_dir.is_dir():
#             continue
#         skill_file = skill_dir / "SKILL.md"
#         if not skill_file.exists():
#             continue
        
#         content = skill_file.read_text(encoding="utf-8")
#         header = _extract_yaml_header(content)
#         if not header:
#             continue
        
#         body = "\n".join(line for line in header.splitlines() if line.strip() != "---")
#         data = yaml.safe_load(body)
#         if not isinstance(data, dict):
#             continue
        
#         name = data.get("name")
#         description = data.get("description")
#         if not name or not description:
#             continue
        
#         entries.append({"skill_name": str(name), "description": str(description)})
    
#     return entries



def planner_agent_file(
    prompt: str,
    conversation_history: Optional[List[dict[str, str]]] = None,
    input_files: str = "",
    model_name: str = "claude-haiku-4-5-20251001",
) -> tuple[Any, dict[str, Any]]:
    """
    Generate plan with optional discovery phase.
    
    The agent can use tools to explore workspace files before creating the plan.
    Discovery loop continues until agent returns a plan (no more tool uses).
    
    Args:
        prompt: Current user message (initial prompt or follow-up reply)
        conversation_history: Optional prior messages (Anthropic format)
        input_files: String describing available input files
        model_name: Claude model to use for planning
    
    Returns:
        (raw_response, output_dict)
    """
    
    example_json = {
        "answer": "I've analyzed your data and created this plan. Does this approach work for you?",
        "plan": [
            "Load and validate the CSV file: check for missing values and data types",
            "Perform exploratory data analysis: generate summary statistics and visualizations",
        ]
    }
    
    system_prompt = f"""You are a planning agent for analytical and data processing tasks.

DISCOVERY PHASE:
You have tools to explore the workspace before creating a plan:
- view_file: Read file contents (shows first 10 lines for CSV)
- search_files: Find files matching patterns (e.g., "*.csv")
- get_file_stats: Get file metadata (size, line count, modified date)

Use these tools to understand:
- What data files are available
- Data structure (columns, data types, formats)
- Data quality issues (missing values, date ranges)
- File sizes and complexity

PLANNING PHASE:
After exploring (or if you already have enough context), create a step-by-step plan.

When request is vague or missing details:
- Ask clarifying questions in "answer"
- Return empty "plan" list
- User will reply with more context

When you have enough context:
- Return a detailed step-by-step plan (max 7 steps)
- Each step should have: description + rationale
- Format as valid Python dict (no markdown, no code fences)

INPUT FILES CONTEXT:
{input_files}

OUTPUT FORMAT:
{json.dumps(example_json, indent=2)}
"""
    
    # Initialize conversation
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": prompt})
    
    # Discovery loop (max 8 iterations)
    max_iterations = 8
    tool_use_log = []
    
    for iteration in range(max_iterations):
        raw_response = client.messages.create(
            model=model_name,
            max_tokens=2048,
            temperature=0.3,
            system=system_prompt,
            messages=messages,
            tools=PLANNER_TOOLS
        )
        
        # Check for tool uses
        has_tool_use = any(block.type == "tool_use" for block in raw_response.content)
        
        if not has_tool_use:
            # Agent finished discovery and returned final response
            text = ""
            for block in raw_response.content:
                if block.type == "text":
                    text += block.text
            
            model_answer = _parse_planner_response_fixed(text.strip())
            
            output = {
                "prompt": prompt,
                "model_answer": model_answer,
                "input_tokens": raw_response.usage.input_tokens,
                "output_tokens": raw_response.usage.output_tokens,
                "tool_uses": tool_use_log
            }
            
            return raw_response, output
        
        # Process tool uses (discovery phase)
        assistant_content = []
        tool_results = []
        
        for block in raw_response.content:
            assistant_content.append(block)
            
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                
                # Execute tool
                if tool_name in TOOL_HANDLERS:
                    result = TOOL_HANDLERS[tool_name](**tool_input)
                else:
                    result = f"Unknown tool: {tool_name}"
                
                # Log for debugging/frontend
                tool_use_log.append({
                    "iteration": iteration + 1,
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result[:200] + "..." if len(result) > 200 else result
                })
                
                # Add tool result to conversation
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })
        
        # Continue conversation
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})
    
    # Max iterations reached without plan
    fallback_response = {
        "answer": "Discovery phase took too long. Please provide more specific requirements.",
        "plan": []
    }
    
    output = {
        "prompt": prompt,
        "model_answer": fallback_response,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_uses": tool_use_log
    }
    
    return None, output


def serialize_raw_response(raw) -> dict:
    """
    Serialize Anthropic response with tool uses for JSONB storage.
    
    Args:
        raw: Anthropic message response object
        
    Returns:
        dict suitable for JSON storage
    """
    if raw is None:
        return {}
    
    # Extract text content and tool uses
    text_content = ""
    tool_uses = []
    
    for block in raw.content:
        if block.type == "text":
            text_content += block.text
        elif block.type == "tool_use":
            tool_uses.append({
                "id": block.id,
                "name": block.name,
                "input": block.input
            })
    
    return {
        "id": raw.id,
        "model": raw.model,
        "role": raw.role,
        "content": text_content,
        "tool_uses": tool_uses,
        "stop_reason": raw.stop_reason,
        "usage": {
            "input_tokens": raw.usage.input_tokens,
            "output_tokens": raw.usage.output_tokens
        }
    }


def build_conversation_history(interactions: list) -> list[dict]:
    """
    Build Anthropic conversation history from stored interactions.
    
    Args:
        interactions: List of LlmInteraction rows ordered by created_at
        
    Returns:
        List of message dicts in Anthropic format
    """
    messages = []
    for interaction in interactions:
        messages.append({"role": "user", "content": interaction.prompt})
        # model_answer is stored as JSON text in the database
        assistant_content = interaction.model_answer
        if isinstance(assistant_content, str):
            try:
                parsed = json.loads(assistant_content)
                if isinstance(parsed, dict) and "answer" in parsed:
                    assistant_content = json.dumps(parsed)
            except json.JSONDecodeError:
                pass
        elif isinstance(assistant_content, dict):
            assistant_content = json.dumps(assistant_content)
        messages.append({"role": "assistant", "content": assistant_content})
    return messages
