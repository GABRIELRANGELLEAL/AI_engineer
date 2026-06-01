#!/usr/bin/env python3
"""
Translator Agent
Converts human-readable plans into structured JSON execution plans.
"""

import os
import json
import yaml
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from typing import List, Dict

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Available tools definition
TOOLS = [
    {
        "name": "bash",
        "description": "Execute bash commands in an isolated Docker container",
        "args": ["command"]
    },
    {
        "name": "create_file",
        "description": "Create a new file in the outputs folder",
        "args": ["path", "content"]
    },
    {
        "name": "view",
        "description": "Read a file's content or list a directory's contents",
        "args": ["path"]
    }
]


def _extract_yaml_header(markdown: str) -> str:
    """Return YAML frontmatter from a SKILL.md file."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[: i + 1])
    return ""

def _build_skill_catalog() -> List[dict]:
    """Build a catalog of all skills with their parameters."""
    entries = []
    if not SKILLS_DIR.is_dir():
        return entries
    
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        
        content = skill_file.read_text(encoding="utf-8")
        header = _extract_yaml_header(content)
        if not header:
            continue
        
        body = "\n".join(line for line in header.splitlines() if line.strip() != "---")
        data = yaml.safe_load(body)
        if not isinstance(data, dict):
            continue
        
        name = data.get("name")
        description = data.get("description")
        if not name or not description:
            continue
        
        entries.append({
            "skill_name": str(name), 
            "description": str(description),
            "path": skill_file.as_posix()
        })
    
    return entries

def _read_skill_file(skill_name: str) -> Dict:
    """
    Read a skill file and extract its metadata and content.
    
    Returns a dict with:
    - name: Skill name
    - description: What the skill does
    - args: Expected arguments
    - content: Full skill content (for context)
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    
    if not skill_path.exists():
        return {}
    
    content = skill_path.read_text(encoding="utf-8")
    header = _extract_yaml_header(content)
    
    if not header:
        return {"skill_name": skill_name, "content": content}
    
    body = "\n".join(line for line in header.splitlines() if line.strip() != "---")
    data = yaml.safe_load(body)
    
    if not isinstance(data, dict):
        return {"skill_name": skill_name, "content": content}
    
    return {
        "skill_name": str(data.get("name", skill_name)),
        "description": str(data.get("description", "")),
        "typical_args": data.get("args", ["input_path", "output_path"]),
        "content": content
    }

def _extract_json(text: str) -> Dict:
    # Remove markdown code fences if present

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    text = text.strip()
    
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "execution_plan" in obj:
            # Validate and normalize structure
            for step in obj.get("execution_plan", []):
                # Ensure status is pending
                step["status"] = "pending"
                # Ensure tool and skill are not both set
                if step.get("tool") and step.get("skill"):
                    # Prefer skill over tool for complex operations
                    step["tool"] = None
                # Ensure at least one is set
                if not step.get("tool") and not step.get("skill"):
                    step["tool"] = "view"  # Default fallback
            
            # Limit to 10 steps (translator can add steps)
            obj["execution_plan"] = obj["execution_plan"][:10]
            return obj
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        pass
    
    # Fallback
    return {
        "user_message": "Translation failed. Please review the plan.",
        "execution_plan": []
    }

def translator_agent(
    human_plan: str,
    model_name: str = "claude-sonnet-4-5-20250929"
) -> str:
    """
    Translate a human-readable plan into a structured JSON execution plan.
    
    Takes the output from planner_agent and converts it into a machine-executable
    format with proper tool/skill calls, code, and paths.
    
    The translator is autonomous and can:
    - Create additional steps if needed for proper execution
    - Generate executable code for tool-based steps
    - Provide skill paths for skill-based steps
    
    Args:
        human_plan: The human-readable plan from planner_agent
        model_name: Claude model to use for translation
    
    Returns:
        Dict with structure:
        {
            "user_message": "Brief confirmation message",
            "execution_plan": [
                {
                    "step": 1,
                    "description": "Step description",
                    "tool": "tool_name" or null,
                    "skill": null,
                    "code": "actual code to execute" (for tool steps),
                    "path": null,
                    "args": {"param": "value"},
                    "rationale": "Why this step is needed",
                    "status": "pending"
                },
                {
                    "step": 2,
                    "description": "Step description",
                    "tool": null,
                    "skill": "skill_name",
                    "code": null,
                    "path": "skills/skill_name/SKILL.md" (for skill steps),
                    "args": {"param": "value"},
                    "rationale": "Why this step is needed",
                    "status": "pending"
                }
            ]
        }
    """
    
    print("building skill catalog")
    skill_catalog = _build_skill_catalog()
    
    example_json = {
        "execution_plan": [
            {
                "step": 1,
                "description": "Inspect the CSV file structure",
                "tool": "view",
                "skill": None,
                "args": {"path": "path informed by the user"},
                "status": "pending"
            },
            {
                "step": 2,
                "description": "Perform time series analysis",
                "tool": None,
                "skill": "analyzing-time-series",
                "args": {
                    # Find the 'analyzing-time-series' skill and set its path
                    "path": "projetct/skills/skill_name/SKILL.md"
             
                },
                "status": "pending"
            },
            {
                "step": 3,
                "description": "Run Python script to generate forecast",
                "tool": "bash",
                "skill": None,
                "args": {"command": "python scripts/forecast.py test.csv outputs/forecast.json"},
                "status": "pending"
            },
            {
                "step": 4,
                "description": "Create final HTML report",
                "tool": "create_file",
                "skill": None,
                "args": {"path": "report.html", "content": "<html><head><title>Analysis Report</title></head><body><h1>Time Series Analysis</h1>{{RESULTS}}</body></html>"},
                "status": "pending"
            }
        ]
    }
    
    prompt = f"""
        You are a translation agent that converts human-readable plans into structured JSON execution plans.

        Your goal is to take a natural language plan and output a valid JSON structure that can be executed by a machine.

        You have FULL AUTONOMY to:
        1. Determine which tools or skills are needed for each step
        2. Create additional intermediate steps if needed for proper execution
        3. Generate executable code for tool-based steps
        4. Provide skill paths for skill-based steps

        AVAILABLE TOOLS (for basic operations):
        {json.dumps(TOOLS, indent=2)}

        AVAILABLE SKILLS (for complex analytical tasks):
        {json.dumps(skill_catalog, indent=2)}

        CRITICAL TRANSLATION RULES:

        1. Each step uses EITHER a tool OR a skill, NEVER both:

        2. EXAMPLE OUTPUT FORMAT (follow this structure exactly):
        {json.dumps(example_json, indent=2)}

        4. YOU CAN ADD STEPS:
        - If the human plan is missing important steps, add them
        - Example: If plan says "analyze and create report" but doesn't mention reading the data first, ADD a view step
        - Common additions: validation steps, intermediate saves, error checks

        5. REQUIRED FIELDS FOR EVERY STEP:
        - step: integer (1, 2, 3, ...)
        - description: clear, actionable description
        - tool: tool name or null
        - skill: skill name or null
        - args: dictionary with parameters
        - status: always "pending"

        7. ARGS FIELD:
        - For tools: use exact parameter names from AVAILABLE TOOLS
        - For skills: use the path of the skill
        - Always include all required parameters

        8. Maximum 10 steps (you can add up to 2 extra steps if needed)

        9. Return ONLY valid JSON (no markdown, no code fences, no explanations)
        
        HUMAN-READABLE PLAN TO TRANSLATE:
        {human_plan}
    """
    print('sending the message to the Claude')
    response = client.messages.create(
        model=model_name,
        max_tokens=3072,
        temperature=0.1,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = ""
    for block in response.content:
        if block.type == "text":
            raw += block.text
    
    raw = raw.strip()
    print('raw response was generated')
    return raw
