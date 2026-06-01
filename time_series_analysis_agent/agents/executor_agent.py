#!/usr/bin/env python3
"""
Executor Agent
Executes structured JSON plans using tools and skills from workspace.
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any
from dotenv import load_dotenv
import anthropic

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"
WORKSPACE = BASE_DIR / "workspace"
OUTPUTS = BASE_DIR / "outputs"

# Create directories if needed
WORKSPACE.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ─── Tool Handlers ────────────────────────────────────────────────────────────

def handle_bash(command: str, **_) -> str:
    """Execute a bash command inside an isolated Docker container."""
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", "512m",
                "--cpus", "1",
                "-v", f"{WORKSPACE}:/home/sandbox/workspace",
                "-v", f"{OUTPUTS}:/home/sandbox/outputs",
                "-w", "/home/sandbox/workspace",
                "claude-sandbox",
                "bash", "-c", command
            ],
            capture_output=True,
            text=True,
            timeout=60
        )
    except FileNotFoundError:
        return (
            "[bash tool] Docker not found. "
            "Install Docker Desktop and verify `docker` command works. "
            "To read files without sandbox, use the `view` tool."
        )
    
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]: {result.stderr}"
    return output or "(no output)"


def handle_create_file(path: str, content: str, **_) -> str:
    """Create a new file in the outputs folder."""
    target = OUTPUTS / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"✅ File created: outputs/{path}"


def handle_view(path: str, **_) -> str:
    """View file contents or list directory contents."""
    # Try workspace first
    target = WORKSPACE / path
    
    if not target.exists():
        return {
            "status": "error",
            "location": target,
            "content": f"❌ Not found in workspace"
        }
    
    # if target.is_dir():
    #     items = sorted(target.iterdir())
    #     base = WORKSPACE if target.is_relative_to(WORKSPACE) else OUTPUTS
    #     location = "workspace" if target.is_relative_to(WORKSPACE) else "outputs"
    #     listing = "\n".join(f"  - {i.relative_to(base)}" for i in items)
    #     return f"📁 Contents of {location}/{path}:\n{listing}"
    
    content = target.read_text(encoding="utf-8")
    
    return {
        "status": "Found",
        "location": target,
        "content": content
    }


# Tool name to handler mapping
TOOL_HANDLERS = {
    "bash": handle_bash,
    "create_file": handle_create_file,
    "view": handle_view,
}


# ─── Skill Executor ───────────────────────────────────────────────────────────

def _content_after_yaml_header(markdown: str) -> str:
    """Remove YAML frontmatter from markdown and return only content."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return markdown
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            rest = lines[i + 1:]
            return "\n".join(rest).lstrip("\n")
    return markdown


def execute_skill(skill_path_str: str, args: Dict, context: str) -> str:
    """
    Execute a skill with the given arguments and context.
    
    Skills are markdown files that provide instructions to Claude.
    The executor loads the skill and follows its instructions.
    
    Args:
        skill_path_str: Path to skill file (e.g., "skills/analyzing-time-series/SKILL.md")
        args: Arguments to pass to the skill
        context: Execution context from previous steps
    """
    skill_path = BASE_DIR / skill_path_str
    
    if not skill_path.exists():
        return f"❌ Skill file not found: {skill_path_str}"
    
    # Load skill instructions
    skill_content = skill_path.read_text(encoding="utf-8")
    skill_instructions = _content_after_yaml_header(skill_content)
    
    # Build prompt with skill instructions
    args_str = json.dumps(args, indent=2)
    
    prompt = f"""
{skill_instructions}

CONTEXT:
{context}

ARGUMENTS:
{args_str}

Execute the skill according to the instructions above using the provided arguments.
You have access to the following tools:
- bash: Run commands in Docker sandbox
- view: Read files from workspace or outputs
- create_file: Create files in outputs folder
- str_replace: Edit files in outputs folder

IMPORTANT:
- Input files are in workspace/ folder
- Output files go to outputs/ folder
- Use relative paths (e.g., "data.csv" not "workspace/data.csv")
"""
    
    # Define available tools for Claude
    tools = [
        {
            "name": "bash",
            "description": "Execute bash commands in Docker sandbox",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Bash command to execute"}
                },
                "required": ["command"]
            }
        },
        {
            "name": "create_file",
            "description": "Create a file in outputs folder",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path in outputs"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "view",
            "description": "Read file or list directory",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to view"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "str_replace",
            "description": "Edit file in outputs",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"}
                },
                "required": ["path", "old_str", "new_str"]
            }
        }
    ]
    
    # Execute with tool use loop
    messages = [{"role": "user", "content": prompt}]
    output_log = []
    
    max_iterations = 20
    for iteration in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=messages,
            tools=tools
        )
        
        # Process response
        assistant_content = []
        
        for block in response.content:
            if block.type == "text":
                output_log.append(f"[Skill Output] {block.text}")
                assistant_content.append(block)
            elif block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                
                # Execute tool
                if tool_name in TOOL_HANDLERS:
                    result = TOOL_HANDLERS[tool_name](**tool_input)
                    output_log.append(f"[Tool: {tool_name}] {result}")
                    
                    # Add to conversation
                    assistant_content.append(block)
                else:
                    result = f"❌ Unknown tool: {tool_name}"
                    output_log.append(result)
        
        # Update messages
        messages.append({"role": "assistant", "content": assistant_content})
        
        # Check if done (no more tool uses)
        if response.stop_reason == "end_turn":
            break
        
        # Add tool results
        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                tool_name = block.name
                if tool_name in TOOL_HANDLERS:
                    result = TOOL_HANDLERS[tool_name](**block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
        
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            break
    
    return "\n".join(output_log)


# ─── Main Executor ────────────────────────────────────────────────────────────

def executor_agent(execution_plan: Dict) -> Dict:
    """
    Execute a structured JSON plan step-by-step.
    
    Args:
        execution_plan: Dict from translator_agent with format:
        {
            "user_message": "...",
            "execution_plan": [
                {
                    "step": 1,
                    "description": "...",
                    "tool": "tool_name" or null,
                    "skill": "skill_name" or null,
                    "code": "executable code" or null (for tools),
                    "path": "skills/skill_name/SKILL.md" or null (for skills),
                    "args": {...},
                    "rationale": "...",
                    "status": "pending"
                },
                ...
            ]
        }
    
    Returns:
        Dict with execution results:
        {
            "status": "completed" or "failed",
            "results": [
                {
                    "step": 1,
                    "description": "...",
                    "status": "success" or "error",
                    "output": "Tool/skill output",
                    "error": "Error message if failed"
                },
                ...
            ]
        }
    """
    
    results = []
    context_history = []
    
    steps = execution_plan.get("execution_plan", [])
    
    print(f"\n{'='*80}")
    print(f"EXECUTING PLAN: {len(steps)} steps")
    print(f"{'='*80}\n")
    
    for step_data in steps:
        step_num = step_data.get("step", 0)
        description = step_data.get("description", "No description")
        tool = step_data.get("tool")
        skill = step_data.get("skill")
        code = step_data.get("code")
        path = step_data.get("path")
        args = step_data.get("args", {})
        rationale = step_data.get("rationale", "")
        
        print(f"\n{'─'*80}")
        print(f"STEP {step_num}: {description}")
        print(f"Rationale: {rationale}")
        if tool:
            print(f"Tool: {tool}")
            if code:
                print(f"Code: {code[:100]}...")
        if skill:
            print(f"Skill: {skill}")
            print(f"Path: {path}")
        print(f"{'─'*80}")
        
        step_result = {
            "step": step_num,
            "description": description,
            "status": "pending",
            "output": "",
            "error": None
        }
        
        try:
            # Build context from previous steps
            context = f"Execution context: {execution_plan.get('user_message', '')}\n\n"
            context += "Previous steps:\n"
            for prev in context_history:
                context += f"- Step {prev['step']}: {prev['description']}\n"
                context += f"  Output: {prev['output'][:200]}...\n\n"
            
            # Execute tool or skill
            if tool:
                print(f"🔧 Executing tool: {tool}")
                if tool in TOOL_HANDLERS:
                    # Use code field if available, otherwise use args
                    if code and tool == "bash":
                        output = TOOL_HANDLERS[tool](command=code)
                    elif code and tool == "create_file":
                        # Extract path from args, use code as content
                        file_path = args.get("path", "output.txt")
                        output = TOOL_HANDLERS[tool](path=file_path, content=code)
                    else:
                        output = TOOL_HANDLERS[tool](**args)
                    
                    step_result["status"] = "success"
                    step_result["output"] = output
                    print(f"✅ {output}")
                else:
                    raise ValueError(f"Unknown tool: {tool}")
            
            elif skill:
                print(f"🎯 Executing skill: {skill}")
                if not path:
                    raise ValueError(f"Skill step missing 'path' field")
                
                output = execute_skill(path, args, context)
                step_result["status"] = "success"
                step_result["output"] = output
                print(f"✅ Skill completed")
            
            else:
                raise ValueError("Step must have either 'tool' or 'skill'")
            
            # Add to context history
            context_history.append(step_result)
            
        except Exception as e:
            error_msg = f"❌ Error: {str(e)}"
            step_result["status"] = "error"
            step_result["error"] = str(e)
            print(error_msg)
            
            # Stop on error
            results.append(step_result)
            break
        
        results.append(step_result)
    
    # Determine overall status
    all_success = all(r["status"] == "success" for r in results)
    overall_status = "completed" if all_success else "failed"
    
    print(f"\n{'='*80}")
    print(f"EXECUTION {overall_status.upper()}: {len(results)} steps processed")
    print(f"{'='*80}\n")
    
    return {
        "status": overall_status,
        "results": results
    }


if __name__ == "__main__":
    # Test the executor
    test_plan = {
        "user_message": "Analyzing test data",
        "execution_plan": [
            {
                "step": 1,
                "description": "List workspace contents",
                "tool": "view",
                "skill": None,
                "args": {"path": "."},
                "rationale": "See what files are available",
                "status": "pending"
            }
        ]
    }
    
    result = executor_agent(test_plan)
    print("\n" + "="*80)
    print("EXECUTION RESULT")
    print("="*80)
    print(json.dumps(result, indent=2))
