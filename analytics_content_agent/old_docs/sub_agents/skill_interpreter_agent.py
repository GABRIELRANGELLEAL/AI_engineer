"""
Skill Interpreter Agent

Reads a local skill (SKILL.md + companion files) and produces a structured
"skill profile" describing how the skill can be executed:

- runtime (python, node, shell, none)
- execution strategy (sequential_scripts, single_script, no_execution)
- steps (entrypoints, args, produced artifacts)
- inputs / outputs / dependencies / references

The interpreter is intentionally hybrid:

1) Deterministic scan of the skill folder to extract objective facts
   (file list, Python imports, bash-like commands inside SKILL.md, etc.).
2) An LLM call that turns those facts + SKILL.md prose into a semantic
   profile (purpose, ordering, inputs, outputs).
3) Pydantic validation to enforce a stable contract for downstream agents.

The profile is intentionally generic. It does NOT adapt to any specific
user request - that is the job of the Code/Execution Planner that runs
after this agent.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import List, Literal, Optional

from aisuite import Client
from pydantic import BaseModel, Field, ValidationError

from src.aux_functions import clean_json_block
from src.tools.loader import LoadedSkill, load_skill, project_root


client = Client()


# ============================================================
# Pydantic schema for the skill profile
# ============================================================


class SkillStep(BaseModel):
    """One executable step inside a skill."""

    id: str = Field(..., description="Stable identifier for the step.")
    runtime: Literal["python", "node", "shell", "none"]
    entrypoint: str = Field(
        ...,
        description="Project-relative path to the script or file to execute.",
    )
    purpose: str = Field("", description="Short human description of this step.")
    required_args: List[str] = Field(default_factory=list)
    optional_args: List[str] = Field(default_factory=list)
    produces: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)


class SkillInput(BaseModel):
    """A user-provided input expected by the skill."""

    name: str
    type: str = Field(..., description="csv, json, text, image, other, ...")
    required: bool = True
    description: str = ""


class SkillProfile(BaseModel):
    """Full structured description of a local skill."""

    skill_name: str
    description: str
    kind: Literal["scripted_skill", "pure_documentation", "hybrid"]
    runtime: Literal["python", "node", "shell", "none", "mixed"]
    execution_strategy: Literal[
        "sequential_scripts",
        "single_script",
        "no_execution",
    ]
    steps: List[SkillStep] = Field(default_factory=list)
    inputs: List[SkillInput] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    notes: str = ""


# ============================================================
# Deterministic scanner of the skill folder
# ============================================================

_SCRIPT_EXTENSIONS = {".py", ".js", ".ts", ".sh"}
_REFERENCE_EXTENSIONS = {".md", ".txt", ".rst"}
_SCAN_FILE_LIMIT = 200
_SCRIPT_BYTES_LIMIT = 20000
_SCRIPT_PREVIEW_CHARS = 1500


def _project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root()).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_python_imports(source: str) -> List[str]:
    """Return top-level Python module names imported by a source file."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imports.add(node.module.split(".")[0])

    return sorted(imports)


def _extract_skill_md_commands(content: str) -> List[str]:
    """Extract command-like lines from fenced code blocks in SKILL.md."""

    commands: List[str] = []
    pattern = re.compile(
        r"```(?:bash|sh|shell|powershell)?\n(.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    for block in pattern.findall(content):
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            commands.append(stripped)
    return commands


def _scan_skill_folder(skill: LoadedSkill) -> dict:
    """Collect objective facts about the skill folder for the LLM prompt."""

    skill_dir = skill.path.parent
    scripts: List[dict] = []
    references: List[str] = []
    other_files: List[str] = []
    requirements: Optional[str] = None

    files = sorted(skill_dir.rglob("*"))[: _SCAN_FILE_LIMIT]
    for file in files:
        if not file.is_file():
            continue

        rel = _project_relative(file)
        suffix = file.suffix.lower()

        if file.name.lower() == "requirements.txt":
            try:
                requirements = file.read_text(encoding="utf-8")[: _SCRIPT_BYTES_LIMIT]
            except OSError:
                requirements = None
            continue

        if suffix in _SCRIPT_EXTENSIONS:
            try:
                source = file.read_text(encoding="utf-8")[: _SCRIPT_BYTES_LIMIT]
            except OSError:
                source = ""

            scripts.append(
                {
                    "path": rel,
                    "language": suffix.lstrip("."),
                    "imports": _extract_python_imports(source) if suffix == ".py" else [],
                    "preview": source[:_SCRIPT_PREVIEW_CHARS],
                }
            )
        elif suffix in _REFERENCE_EXTENSIONS and file != skill.path:
            references.append(rel)
        else:
            other_files.append(rel)

    return {
        "skill_dir": _project_relative(skill_dir),
        "scripts": scripts,
        "references": references,
        "other_files": other_files,
        "requirements_txt": requirements,
        "skill_md_commands": _extract_skill_md_commands(skill.content),
    }


# ============================================================
# LLM-driven semantic interpretation
# ============================================================


def _interpreter_prompt(skill: LoadedSkill, scan: dict) -> str:
    return f"""
        You are a Skill Interpreter Agent for this application.

        Goal: read the SKILL.md and the deterministic scan of the skill folder,
        then produce a structured profile that describes HOW the skill can be
        executed in general terms. Do not adapt to any specific user request.

        Skill metadata:
        name: {skill.name}
        description: {skill.description}
        path: {skill.path.as_posix()}

        Full SKILL.md:
        ---
        {skill.content}
        ---

        Deterministic scan (objective facts about the skill folder):
        {json.dumps(scan, ensure_ascii=False, indent=2)}

        Return ONLY valid JSON. Do not include Markdown, code fences, comments,
        or extra text. The JSON must match exactly this shape:

        {{
          "skill_name": "{skill.name}",
          "description": "Short description of what the skill does.",
          "kind": "scripted_skill | pure_documentation | hybrid",
          "runtime": "python | node | shell | none | mixed",
          "execution_strategy": "sequential_scripts | single_script | no_execution",
          "steps": [
            {{
              "id": "stable-id",
              "runtime": "python | node | shell | none",
              "entrypoint": "project-relative path to the script",
              "purpose": "Short description of this step.",
              "required_args": ["arg-name"],
              "optional_args": ["--flag"],
              "produces": ["relative/output/path"],
              "depends_on": ["id-of-previous-step"]
            }}
          ],
          "inputs": [
            {{
              "name": "input_file",
              "type": "csv | json | text | image | other",
              "required": true,
              "description": "What this input represents."
            }}
          ],
          "outputs": ["expected/output/file"],
          "dependencies": ["package-name"],
          "references": ["path/to/reference.md"],
          "notes": "Free-text notes useful for the execution planner."
        }}

        Rules:
        - Use only entrypoint paths that already appear in the scan. Do not
          invent files. Paths must be project-relative.
        - If the skill is documentation only, set kind="pure_documentation",
          runtime="none", execution_strategy="no_execution" and steps=[].
        - For Python scripts, include third-party packages in "dependencies".
          Skip standard-library modules and skip imports that resolve to other
          files inside the same skill folder (those are local helpers, not deps).
        - Order steps in the order they should run; use "depends_on" to make
          ordering explicit when one step depends on artifacts from another.
        - Keep ids short, kebab-case, and unique inside this profile.
        - Quote arg names exactly as they appear in the script CLI or SKILL.md.
        - Prefer outputs/dependencies/references that the SKILL.md explicitly
          mentions; only infer when the SKILL.md is silent.
    """


# ============================================================
# Public entrypoint
# ============================================================


_PROFILE_CACHE: dict[str, SkillProfile] = {}


def skill_interpreter_agent(
    skill_name: str,
    model: str = "openai:gpt-4o-mini",
    use_cache: bool = True,
) -> SkillProfile:
    """
    Interpret a local skill and return a validated SkillProfile.

    The result is cached in-process by skill name so repeated calls during
    the same run do not re-query the LLM. Pass `use_cache=False` to force
    a fresh interpretation.
    """

    if use_cache and skill_name in _PROFILE_CACHE:
        return _PROFILE_CACHE[skill_name]

    skill = load_skill(skill_name)
    scan = _scan_skill_folder(skill)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _interpreter_prompt(skill, scan)}],
        temperature=0,
    )
    raw = response.choices[0].message.content or ""

    try:
        payload = json.loads(clean_json_block(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"skill_interpreter_agent: invalid JSON from LLM for skill "
            f"'{skill_name}': {exc}\nRaw response:\n{raw}"
        ) from exc

    try:
        profile = SkillProfile(**payload)
    except ValidationError as exc:
        raise ValueError(
            f"skill_interpreter_agent: profile schema validation failed for "
            f"skill '{skill_name}': {exc}"
        ) from exc

    if use_cache:
        _PROFILE_CACHE[skill_name] = profile

    return profile


def clear_profile_cache() -> None:
    """Drop the in-process profile cache."""

    _PROFILE_CACHE.clear()


__all__ = [
    "SkillInput",
    "SkillProfile",
    "SkillStep",
    "clear_profile_cache",
    "skill_interpreter_agent",
]
