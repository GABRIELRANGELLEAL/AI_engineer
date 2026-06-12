"""
Centralized tool definitions and handlers for all agents.

All tools live in TOOLS (schema + handler). Agents pick subsets via AGENT_TOOL_SETS.
Use to_anthropic_tools() or to_openai_tools() with a list of tool names.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", str(BASE_DIR / "workspace")))

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


def handle_create_file(path: str, content: str, overwrite: bool = False) -> str:
    """Create or overwrite a file inside the workspace."""
    target = (WORKSPACE / path).resolve()

    # Security: reject any path that escapes the workspace
    try:
        target.relative_to(WORKSPACE.resolve())
    except ValueError:
        return f"Permission denied: path must be inside the workspace ({path!r})"

    if target.exists() and not overwrite:
        return (
            f"File already exists: {path}. "
            "Pass overwrite=true to replace it."
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        size_kb = target.stat().st_size / 1024
        action = "overwritten" if target.exists() else "created"
        return f"File {action}: {path} ({size_kb:.1f} KB)"
    except Exception as e:
        return f"Error creating file: {str(e)}"


_MAX_OUTPUT_CHARS = 8_000
_MAX_TIMEOUT = 120

# language name → (interpreter command, temp file extension)
_LANGUAGE_RUNNERS: dict[str, tuple[list[str], str]] = {
    "python":     ([sys.executable],        ".py"),
    "javascript": (["node"],                ".js"),
    "js":         (["node"],                ".js"),
    "typescript": (["npx", "ts-node"],      ".ts"),
    "ts":         (["npx", "ts-node"],      ".ts"),
    "bash":       (["bash"],                ".sh"),
    "shell":      (["bash"],                ".sh"),
    "sh":         (["bash"],                ".sh"),
    "r":          (["Rscript"],             ".r"),
    "ruby":       (["ruby"],                ".rb"),
    "php":        (["php"],                 ".php"),
}

# file extension → canonical language (used to auto-detect from file path)
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py":  "python",
    ".js":  "javascript",
    ".ts":  "typescript",
    ".sh":  "bash",
    ".r":   "r",
    ".rb":  "ruby",
    ".php": "php",
}


def handle_execute_code(
    code: str | None = None,
    file: str | None = None,
    language: str | None = None,
    timeout: int = 30,
) -> str:
    """Execute code in any supported language and return stdout/stderr."""
    if code is None and file is None:
        return "Error: provide either 'code' (inline snippet) or 'file' (workspace path)."
    if code is not None and file is not None:
        return "Error: provide 'code' or 'file', not both."

    timeout = min(max(1, timeout), _MAX_TIMEOUT)
    tmp_path: Path | None = None

    if file is not None:
        # --- run an existing workspace file ---
        target = (WORKSPACE / file).resolve()
        try:
            target.relative_to(WORKSPACE.resolve())
        except ValueError:
            return f"Permission denied: file must be inside the workspace ({file!r})"
        if not target.exists():
            return f"File not found: {file}"

        # infer language from extension when not explicit
        if language is None:
            language = _EXT_TO_LANGUAGE.get(target.suffix.lower())
            if language is None:
                supported = ", ".join(sorted(_EXT_TO_LANGUAGE.keys()))
                return (
                    f"Cannot infer language from extension {target.suffix!r}. "
                    f"Supported extensions: {supported}. "
                    "Pass 'language' explicitly."
                )

        script_path = target

    else:
        # --- inline code: must know the language up front ---
        if language is None:
            return "Error: 'language' is required when using inline 'code'."

        lang_key = language.lower()
        if lang_key not in _LANGUAGE_RUNNERS:
            supported = ", ".join(sorted(_LANGUAGE_RUNNERS.keys()))
            return f"Unsupported language {language!r}. Supported: {supported}"

        _, ext = _LANGUAGE_RUNNERS[lang_key]
        tmp_dir = WORKSPACE / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_str = tempfile.mkstemp(suffix=ext, dir=str(tmp_dir))
        tmp_path = Path(tmp_str)
        try:
            os.close(fd)
            tmp_path.write_text(code, encoding="utf-8")  # type: ignore[arg-type]
        except Exception as e:
            return f"Error writing temp script: {str(e)}"

        script_path = tmp_path

    lang_key = language.lower()
    if lang_key not in _LANGUAGE_RUNNERS:
        supported = ", ".join(sorted(_LANGUAGE_RUNNERS.keys()))
        return f"Unsupported language {language!r}. Supported: {supported}"

    cmd_prefix, _ = _LANGUAGE_RUNNERS[lang_key]
    cmd = cmd_prefix + [str(script_path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE),
            timeout=timeout,
        )
    except FileNotFoundError:
        return (
            f"Interpreter not found for language {language!r}: {cmd_prefix[0]!r}. "
            "Make sure it is installed and available on PATH."
        )
    except subprocess.TimeoutExpired:
        return f"Execution timed out after {timeout}s."
    except Exception as e:
        return f"Error running script: {str(e)}"
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    parts: list[str] = []

    if result.stdout:
        stdout = result.stdout
        if len(stdout) > _MAX_OUTPUT_CHARS:
            stdout = stdout[:_MAX_OUTPUT_CHARS] + f"\n[... truncated, {len(result.stdout)} total chars]"
        parts.append(f"stdout:\n{stdout}")

    if result.stderr:
        stderr = result.stderr
        if len(stderr) > _MAX_OUTPUT_CHARS:
            stderr = stderr[:_MAX_OUTPUT_CHARS] + f"\n[... truncated, {len(result.stderr)} total chars]"
        parts.append(f"stderr:\n{stderr}")

    if not parts:
        parts.append("(no output)")

    status = "OK" if result.returncode == 0 else f"exit code {result.returncode}"
    return f"[{status} | {language}]\n" + "\n".join(parts)


def handle_code_error(
    failed_code: str,
    error_output: str,
    language: str = "python",
) -> str:
    """Format a structured retry prompt after a code execution failure."""
    return (
        f"Code execution failed.\n\n"
        f"Language: {language}\n\n"
        f"Failed code:\n```{language}\n{failed_code.strip()}\n```\n\n"
        f"Error output:\n```\n{error_output.strip()}\n```\n\n"
        "Analyze the error above, correct the code, and call `execute_code` again "
        "with the fixed version."
    )


def handle_finish_loop(summary: str) -> str:
    """Signal that the agentic loop is complete and return the final response."""
    return summary


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
    "create_file": {
        "description": (
            "Create a new file (or overwrite an existing one) inside the workspace. "
            "Parent directories are created automatically. "
            "Use for saving analysis results, generated scripts, or any output files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path inside the workspace where the file will be created "
                        "(e.g., 'output/report.txt', 'scripts/analysis.py')"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write into the file",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Allow overwriting an existing file. Defaults to false.",
                },
            },
            "required": ["path", "content"],
        },
        "handler": handle_create_file,
    },
    "execute_code": {
        "description": (
            "Execute code in any supported language and return stdout/stderr. "
            "Supported languages: python, javascript, typescript, bash, r, ruby, php. "
            "Provide either 'code' (inline snippet) or 'file' (relative path inside workspace). "
            "When using 'file', language is auto-detected from the extension. "
            "The working directory is always the workspace root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Inline code to execute. "
                        "Requires 'language'. Leave empty if using 'file'."
                    ),
                },
                "file": {
                    "type": "string",
                    "description": (
                        "Relative path to a script inside the workspace "
                        "(e.g., 'scripts/analysis.py', 'scripts/process.js'). "
                        "Leave empty if using 'code'."
                    ),
                },
                "language": {
                    "type": "string",
                    "enum": [
                        "python", "javascript", "js",
                        "typescript", "ts",
                        "bash", "shell", "sh",
                        "r", "ruby", "php",
                    ],
                    "description": (
                        "Language to use. Required for inline 'code'. "
                        "Optional for 'file' (auto-detected from extension)."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max execution time in seconds (1–120). Defaults to 30.",
                },
            },
        },
        "handler": handle_execute_code,
    },
    "handle_code_error": {
        "description": (
            "Call this immediately after execute_code returns a non-zero exit code or error. "
            "Pass the code that failed and the error output received. "
            "The tool returns structured guidance so you can fix and retry execute_code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "failed_code": {
                    "type": "string",
                    "description": "The exact code that was executed and failed.",
                },
                "error_output": {
                    "type": "string",
                    "description": "The full error output (stderr / exit code message) from execute_code.",
                },
                "language": {
                    "type": "string",
                    "description": "Language of the failed code (e.g. 'python', 'javascript'). Defaults to 'python'.",
                },
            },
            "required": ["failed_code", "error_output"],
        },
        "handler": handle_code_error,
    },
    "finish_loop": {
        "description": (
            "Call when the task is fully complete. "
            "This ends the agentic loop and delivers the final response to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Final response or summary for the user",
                }
            },
            "required": ["summary"],
        },
        "handler": handle_finish_loop,
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

# this part of the code is used when you need to execute a tool
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
