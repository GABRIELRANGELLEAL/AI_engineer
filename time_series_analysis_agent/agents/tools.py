"""
Centralized tool definitions and handlers for all agents.

All tools live in TOOLS (schema + handler). Agents pick subsets via AGENT_TOOL_SETS.
Use to_anthropic_tools() or to_openai_tools() with a list of tool names.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = BASE_DIR / "workspace"

Provider = Literal["anthropic", "openai"]

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_view_file(path: str) -> str:
    """Read file contents for discovery phase."""
    target = WORKSPACE / path

    if not target.exists():
        return f"File not found: {path}"

    if not target.is_file():
        return (
            f"Path is a directory, not a file: {path}. "
            "Use search_files to list contents."
        )

    try:
        content = target.read_text(encoding="utf-8")

        if target.suffix.lower() in [".csv", ".tsv", ".xls", ".xlsx"]:
            lines = content.split("\n")
            preview = "\n".join(lines[:10])
            total_lines = len(lines)
            return (
                f"Spreadsheet file ({target.suffix.lower()}) with {total_lines} lines. "
                f"First 10 lines:\n{preview}\n\n[... {total_lines - 10} more lines]"
            )

        if len(content) > 2000:
            return f"{content[:2000]}\n\n[... file continues, {len(content)} total chars]"

        return content

    except UnicodeDecodeError:
        return f"Binary file, cannot read as text: {path}"


def handle_search_files(pattern: str) -> str:
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


def handle_get_file_stats(path: str) -> str:
    """Get file metadata."""
    target = WORKSPACE / path

    if not target.exists():
        return f"File not found: {path}"

    try:
        stats = target.stat()
        size_kb = stats.st_size / 1024
        modified = datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M")

        result = f"File: {path}\n"
        result += f"Size: {size_kb:.1f} KB\n"
        result += f"Modified: {modified}\n"

        if target.suffix.lower() in [".csv", ".tsv", ".txt"]:
            try:
                with open(target, "r", encoding="utf-8") as f:
                    line_count = sum(1 for _ in f)
                result += f"Lines: {line_count}\n"
            except OSError:
                pass

        return result

    except Exception as e:
        return f"Error getting file stats: {str(e)}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {
    "view_file": {
        "description": (
            "Read file contents to understand data structure, columns, format. "
            "Use this to inspect CSV files, understand data schemas, check date ranges."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path to file in workspace "
                        "(e.g., 'data.csv', 'uploads/sales.csv')"
                    ),
                }
            },
            "required": ["path"],
        },
        "handler": handle_view_file,
    },
    "search_files": {
        "description": (
            "List files matching a pattern in workspace. "
            "Use to discover available data files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '*.csv', '*.xlsx', 'uploads/*')",
                }
            },
            "required": ["pattern"],
        },
        "handler": handle_search_files,
    },
    "get_file_stats": {
        "description": (
            "Get metadata about a file: size, line count, modification date. "
            "Useful for understanding data volume."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to file in workspace",
                }
            },
            "required": ["path"],
        },
        "handler": handle_get_file_stats,
    },
}


def to_anthropic_tools(tool_names: list[str]) -> list[dict]:
    """Convert a list of tool names to Anthropic Messages API format."""
    return [
        {
            "name": name,
            "description": TOOLS[name]["description"],
            "input_schema": TOOLS[name]["input_schema"],
        }
        for name in tool_names
    ]


def to_openai_tools(tool_names: list[str]) -> list[dict]:
    """Convert a list of tool names to OpenAI Chat Completions API format."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOLS[name]["description"],
                "parameters": TOOLS[name]["input_schema"],
            },
        }
        for name in tool_names
    ]

def execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Execute a tool safely with error handling."""
    if tool_name not in TOOLS:
        return f"❌ Unknown tool: {tool_name}"

    handler = TOOLS[tool_name]["handler"]
    try:
        result = handler(**tool_input)
        return result
    except TypeError as e:
        return f"❌ Invalid arguments: {str(e)}"
    except Exception as e:
        return f"❌ Error: {str(e)}"
