#!/usr/bin/env python3
"""
Translator Agent
Simple helper that checks if a step needs a skill and which one.
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


def _extract_json(text: str) -> Dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        return {}


def helper_contet_agent(
    plan: List,
    model_name: str = "claude-haiku-4-5-20251001"
) -> List[Dict]:
    """
    Check if steps in a plan need skills using a single API call.
    
    Args:
        plan: List of steps (from output['model_answer']['plan'])
              Each step can be:
              - Dict with "description" or "step" key
              - String (will be converted to dict)
        model_name: Claude model to use
        
    Returns:
        List of dicts with:
        [
            {
                "description": "step description",
                "rationale": "why this step is needed" (if provided),
                "skill_needed": True/False,
                "arg": "skills/skill-name/SKILL.md" or None
            },
            ...
        ]
    """
    
    # Build skill catalog once
    skill_catalog = _build_skill_catalog()
    catalog_paths = [s["path"] for s in skill_catalog]
    
    # Normalize all steps to dict format
    normalized_steps = []
    for idx, step in enumerate(plan):
        if isinstance(step, str):
            step_dict = {"step": idx + 1, "description": step}
        elif isinstance(step, dict):
            step_dict = step.copy()
            if "description" not in step_dict:
                step_dict["description"] = step_dict.get("step", f"Step {idx + 1}")
        else:
            print(f"[WARNING] Invalid step format at index {idx}: {step}")
            continue
        normalized_steps.append(step_dict)
    
    # If no valid steps, return empty
    if not normalized_steps:
        return []
    
    # Prepare steps for the prompt (include rationale if present)
    steps_list = []
    for idx, s in enumerate(normalized_steps):
        step_info = {
            "step_number": idx + 1, 
            "description": s.get("description", "")
        }
        if "rationale" in s:
            step_info["rationale"] = s["rationale"]
        steps_list.append(step_info)
    
    prompt = f"""
You are a skill matcher. Check if steps need skills to execute them.

AVAILABLE SKILLS:
{json.dumps(skill_catalog, indent=2)}

STEPS TO CHECK:
{json.dumps(steps_list, indent=2)}

YOUR TASK:
For each step, decide if it requires one of the available skills.

RULES:
1. Return "skill_needed": true ONLY if the step clearly matches a skill's description
2. Return "skill_needed": false if the step is simple (view file, list directory, simple command)
3. If skill_needed is true, set "arg" to the exact "path" from the skill catalog
4. If skill_needed is false, set "arg" to null
5. IMPORTANT: If a step includes a "rationale" field in the input, preserve it exactly in the output

EXAMPLES:
Input: {{"description": "Analyze time series data for stationarity and seasonality", "rationale": "Understanding these properties is essential for choosing the right forecasting model"}}
Output:
{{
  "description": "Analyze time series data for stationarity and seasonality",
  "rationale": "Understanding these properties is essential for choosing the right forecasting model",
  "skill_needed": true,
  "arg": "skills/analyzing-time-series/SKILL.md"
}}

Input: {{"description": "View the uploaded CSV file"}}
Output:
{{
  "description": "View the uploaded CSV file",
  "skill_needed": false,
  "arg": null
}}

Return a JSON array with one object per step, in the same order as the input steps.
Return ONLY valid JSON (no markdown fences, no extra text).
Format: [
  {{
    "description": "step 1 description",
    "rationale": "rationale if provided in input",
    "skill_needed": true/false,
    "arg": "path or null"
  }},
  ...
]
"""

    # Make single API call for all steps
    response = client.messages.create(
        model=model_name,
        max_tokens=4096,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = ""
    for block in response.content:
        if block.type == "text":
            raw += block.text
    
    parsed = _extract_json(raw.strip())
    
    # Validate response is a list
    if not isinstance(parsed, list):
        print(f"[WARNING] Expected list response, got {type(parsed)}")
        parsed = []
    
    # Validate and fix each result
    results = []
    for idx, step_dict in enumerate(normalized_steps):
        step_description = step_dict.get("description", "")
        step_rationale = step_dict.get("rationale")
        
        # Get result for this step or create default
        if idx < len(parsed) and isinstance(parsed[idx], dict):
            result = parsed[idx]
        else:
            result = {}
        
        # Ensure required fields
        result.setdefault("description", step_description)
        result.setdefault("skill_needed", False)
        result.setdefault("arg", None)
        
        # Preserve rationale from input if it exists
        if step_rationale:
            result["rationale"] = step_rationale
        
        # Validate path exists in catalog if skill_needed
        if result.get("skill_needed") and result.get("arg"):
            if result["arg"] not in catalog_paths:
                print(f"[WARNING] Invalid skill path returned: {result['arg']}")
                result["skill_needed"] = False
                result["arg"] = None
        
        results.append(result)
    
    return results