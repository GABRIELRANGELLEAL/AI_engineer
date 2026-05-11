"""
Skill Planning Agent

This planner follows:
- receive a user prompt
- ask an LLM to produce a valid Python list of strings
- robustly parse the model output
- enforce a minimal contract before returning

Unlike the research planner, this agent plans work across the local Skills/
directory. It selects skills using ONLY the YAML front matter from each
Skills/<skill>/SKILL.md file.
"""
import json
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import re

from openai import OpenAI

client = OpenAI()

#### Functions to help the main function that is planner_agent() ####
def _clean_json_block(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip("` \n")

def _parse_yaml_header(markdown: str) -> Optional[Dict[str, str]]:
    """
    Parse only the top YAML front matter block.

    This deliberately supports the simple `key: value` shape used by the local
    Skill files and avoids importing a YAML dependency just for metadata.
    """

    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    header_lines: List[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        header_lines.append(line)
    else:
        return None

    header: Dict[str, str] = {}
    for line in header_lines:
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            header[key] = value

    return header or None


def _skills_catalog() -> Dict[str, List[str]]:
    """
    Load Skill metadata from project/Skills/*/SKILL.md using YAML headers only.

    Returns a dict mapping skill_name -> [skill_description, skill_path].
    """

    skill_files: List[Path] = []
    seen: set[Path] = set()
    skills_root = Path(__file__).resolve().parent.parent / "skills"

    for skill_file in skills_root.glob("*/SKILL.md"):
        resolved = skill_file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        skill_files.append(skill_file)

    skills: Dict[str, List[str]] = {}
    for skill_file in sorted(skill_files):
        try:
            markdown = skill_file.read_text(encoding="utf-8")
        except OSError:
            continue

        header = _parse_yaml_header(markdown)
        if not header:
            continue

        name = header.get("name", "").strip()
        description = header.get("description", "").strip()
        if name and description:
            skills[name] = [description, skill_file.as_posix()]

    return skills

def _skills_environment(skills: dict[str, List[str]]) -> List[dict[str, str]]:
    environment_skills: List[dict[str, str]] = []
    for name, skill_info in skills.items():
        description, skill_path = skill_info
        path = Path(skill_path)
        environment_skills.append(
            {
                "name": name,
                "description": description,
                "path": path.parent.as_posix() if path.name == "SKILL.md" else path.as_posix(),
            }
        )

    return environment_skills

#### Main function that agent will execute ####

def planner_agent(
    prompt: str,
    model: str = "openai:gpt-4o-mini"
) -> Tuple[List[str], List[str]]:

    skills = _skills_catalog()
    available_skill_names = set(skills)
    tools = [
        {
            "type": "shell",
            "environment": {
                "type": "local",
                "skills": _skills_environment(skills),
            },
        }
    ]

    llm_prompt = f"""
        You are a Skill Planning Agent for this application.

        Your job is to inspect the user's request, compare it against the available local skills exposed in your tool environment, and produce two outputs:
        1. A user-facing step-by-step explanation of what will be done.
        2. A machine-readable list of exact skill names that should be executed later.

        User request:
        {prompt}

        Return only valid JSON. Do not include Markdown, code fences, comments, or extra text.

        The JSON must have exactly this structure:
        {{
        "user_steps": [
            "A concise step visible to the user explaining what will happen."
        ],
        "selected_skills": [
            "exact-skill-name"
        ]
        }}

        Rules for "selected_skills":
        - Include only exact skill names from the local tool environment.
        - Do not invent, rename, translate, summarize, or partially match skill names.
        - If a skill is relevant, use its exact tool environment skill name.
        - If multiple skills are needed, list them in the order they should be executed.
        - If no available skill is relevant, return an empty list.

        Rules for "user_steps":
        - Write steps for the end user, not for a developer.
        - Explain the work that will be done based on the selected skill or skills.
        - Mention the selected skill names when useful, but keep the explanation natural.
        - Keep each step concrete and action-oriented.
        - Do not mention internal implementation details unless they are useful to the user.
        - If the request is ambiguous, ask for the missing information in the steps.
        - If no skill fits the request, explain that the current available skills do not cover the request.

        Decision rules:
        - If the request clearly matches one or more available skills, select those skills and describe the planned execution.
        - If the request is unclear but likely related to an available skill, return no selected skills and ask clarifying questions in "user_steps".
        - If the request is outside the available skills, return no selected skills and explain the limitation in "user_steps".
        - Prefer selecting fewer skills when one skill is sufficient.
        - Do not select a skill only because it is loosely related; the skill must be useful for completing the user's request.

        Output examples:

        Example 1:
        User request: "Analyze my CRM omnichannel data and summarize the main customer behavior patterns."

        Response:
        {{
        "user_steps": [
            "I will use the crm-omnichannel-analysis skill to analyze the available CRM omnichannel data.",
            "I will identify the main customer behavior patterns across channels.",
            "I will summarize the key findings in a format that is easy to review."
        ],
        "selected_skills": [
            "crm-omnichannel-analysis"
        ]
        }}

        Example 2:
        User request: "Create a logo for my company."

        Response:
        {{
        "user_steps": [
            "The current available skills do not appear to cover logo creation.",
            "Please add a skill for visual asset generation or reframe the request around one of the available skills."
        ],
        "selected_skills": []
        }}

        Example 3:
        User request: "Use the CRM skill."

        Response:
        {{
        "user_steps": [
            "Please clarify what CRM analysis you want to perform.",
            "Share what data is available and what output you expect, such as a summary, segmentation, funnel analysis, or performance report."
        ],
        "selected_skills": []
        }}
    """

    response = client.responses.create(
        model=model,
        tools=tools,
        input=llm_prompt,
    )
    raw = response.output_text

    parsed = json.loads(_clean_json_block(raw))

    user_steps = parsed.get("user_steps", [])
    selected_skills = parsed.get("selected_skills", [])

    selected_skills = [
        name for name in selected_skills
        if name in available_skill_names
    ]

    return user_steps, selected_skills


