"""
Code/Execution Planner Agent

Receives:
- a user prompt
- a SkillProfile produced by skill_interpreter_agent

Produces a structured plan that turns the generic skill description into
a concrete execution recipe for the Sandbox Executor.

Two possible outputs:

1) ExecutionPlan (status="ready") - ready to run.
2) ClarificationRequest (status="needs_clarification") - the planner
   identified missing information and asks the user before executing.

Design rules followed:
- The LLM only proposes the plan. This module validates it.
- Commands are always argv arrays, never shell strings.
- All paths are project-relative and validated against PROJECT_ROOT.
- Generated files (when the LLM has to write code) live under
  runs/<plan_id>/workspace/ to keep them isolated and easy to clean up.
- Outputs go to outputs/ or runs/.
- The planner is conservative: if anything is ambiguous, it should ask
  for clarification instead of guessing.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import List, Literal, Optional, Union

from aisuite import Client
from pydantic import BaseModel, Field, ValidationError

from src.aux_functions import clean_json_block
from src.tools.loader import resolve_project_path
from sub_agents.skill_interpreter_agent import SkillProfile


client = Client()


# ============================================================
# Policy constants
# ============================================================


_RUNTIME_BINARIES: dict[str, set[str]] = {
    "python": {"python", "python3", "python.exe", "python3.exe"},
    "node": {"node", "node.exe"},
}

_ALLOWED_OUTPUT_PREFIXES = ("outputs/", "runs/")
_FORBIDDEN_PATH_PARTS = {".env", ".git", "__pycache__", "node_modules"}
_SHELL_METACHARS = ("&&", "||", ";", "|", ">", "<", "`", "$(")

_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 600
_MIN_TIMEOUT = 1


# ============================================================
# Pydantic schema
# ============================================================


class FileToCreate(BaseModel):
    """A file the planner wants the executor to materialize before running."""

    path: str = Field(
        ...,
        description="Project-relative path under runs/<plan_id>/workspace/.",
    )
    content: str = Field(..., description="Full text content of the file.")


class ExecutionCommand(BaseModel):
    """A single command the executor will run."""

    id: str = Field(..., description="Stable id, unique inside the plan.")
    runtime: Literal["python", "node", "shell"]
    cwd: str = Field(..., description="Project-relative working directory.")
    argv: List[str] = Field(
        ...,
        min_length=1,
        description="Argument vector. argv[0] must be the runtime binary.",
    )
    timeout_seconds: int = Field(
        _DEFAULT_TIMEOUT,
        ge=_MIN_TIMEOUT,
        le=_MAX_TIMEOUT,
    )
    depends_on: List[str] = Field(default_factory=list)
    expected_artifacts: List[str] = Field(default_factory=list)
    purpose: str = ""


class ExecutionPlan(BaseModel):
    """Concrete, ready-to-execute plan for one user request."""

    status: Literal["ready"]
    plan_id: str
    skill_name: str
    summary: str = ""
    files_to_create: List[FileToCreate] = Field(default_factory=list)
    commands: List[ExecutionCommand] = Field(..., min_length=1)
    artifacts_to_return: List[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    risks: List[str] = Field(default_factory=list)


class ClarificationRequest(BaseModel):
    """Returned when the planner cannot safely produce a plan yet."""

    status: Literal["needs_clarification"]
    skill_name: str
    missing_information: List[str] = Field(default_factory=list)
    question_for_user: str


PlanResponse = Union[ExecutionPlan, ClarificationRequest]


# ============================================================
# Validation
# ============================================================


class PlanValidationError(ValueError):
    """Raised when the LLM-produced plan violates safety/structural rules."""


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _is_under_project(path: str) -> bool:
    try:
        resolve_project_path(path)
        return True
    except ValueError:
        return False


def _path_has_forbidden_part(path: str) -> bool:
    parts = re.split(r"[\\/]+", path)
    return any(part in _FORBIDDEN_PATH_PARTS for part in parts)


def _has_output_prefix(path: str) -> bool:
    return _normalize_path(path).startswith(_ALLOWED_OUTPUT_PREFIXES)


def _detect_cycles(commands: List[ExecutionCommand]) -> Optional[str]:
    """Return a printable cycle path, or None if the dependency graph is a DAG."""

    graph = {cmd.id: list(cmd.depends_on) for cmd in commands}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: List[str]) -> Optional[str]:
        if node in visiting:
            return " -> ".join(stack + [node])
        if node in visited:
            return None
        visiting.add(node)
        for dep in graph.get(node, []):
            cycle = visit(dep, stack + [node])
            if cycle:
                return cycle
        visiting.discard(node)
        visited.add(node)
        return None

    for cmd_id in graph:
        cycle = visit(cmd_id, [])
        if cycle:
            return cycle
    return None


def _argv_uses_generated_file(cmd: ExecutionCommand, plan: ExecutionPlan) -> bool:
    generated_basenames = {
        _normalize_path(f.path).rsplit("/", 1)[-1] for f in plan.files_to_create
    }
    return any(
        _normalize_path(arg).rsplit("/", 1)[-1] in generated_basenames
        for arg in cmd.argv
    )


def _argv_uses_skill_entrypoint(cmd: ExecutionCommand, profile: SkillProfile) -> bool:
    entrypoint_basenames = {
        _normalize_path(step.entrypoint).rsplit("/", 1)[-1] for step in profile.steps
    }
    if not entrypoint_basenames:
        return False
    return any(
        _normalize_path(arg).rsplit("/", 1)[-1] in entrypoint_basenames
        for arg in cmd.argv[1:]
    )


def _argv_has_shell_metachars(argv: List[str]) -> Optional[str]:
    for arg in argv:
        for token in _SHELL_METACHARS:
            if token in arg:
                return token
    return None


def _validate_plan_safety(
    plan: ExecutionPlan,
    profile: SkillProfile,
    allow_shell: bool,
) -> None:
    if not plan.commands:
        raise PlanValidationError("Plan must contain at least one command.")

    ids = [c.id for c in plan.commands]
    if len(set(ids)) != len(ids):
        raise PlanValidationError(f"Duplicate command ids: {ids}")

    id_set = set(ids)
    for cmd in plan.commands:
        for dep in cmd.depends_on:
            if dep not in id_set:
                raise PlanValidationError(
                    f"Command '{cmd.id}' depends on unknown command '{dep}'."
                )

    cycle = _detect_cycles(plan.commands)
    if cycle:
        raise PlanValidationError(
            f"Cycle detected in command dependencies: {cycle}"
        )

    for cmd in plan.commands:
        if cmd.runtime == "shell" and not allow_shell:
            raise PlanValidationError(
                f"Command '{cmd.id}': shell runtime is disabled by policy."
            )

        if not _is_under_project(cmd.cwd):
            raise PlanValidationError(
                f"Command '{cmd.id}': cwd '{cmd.cwd}' escapes project root."
            )
        if _path_has_forbidden_part(cmd.cwd):
            raise PlanValidationError(
                f"Command '{cmd.id}': cwd '{cmd.cwd}' touches a forbidden path."
            )

        if cmd.runtime in _RUNTIME_BINARIES:
            if cmd.argv[0] not in _RUNTIME_BINARIES[cmd.runtime]:
                raise PlanValidationError(
                    f"Command '{cmd.id}': argv[0] '{cmd.argv[0]}' not allowed "
                    f"for runtime '{cmd.runtime}'."
                )

        bad_token = _argv_has_shell_metachars(cmd.argv)
        if bad_token:
            raise PlanValidationError(
                f"Command '{cmd.id}': argv contains shell metacharacter "
                f"'{bad_token}'. Use separate argv elements instead."
            )

        if profile.kind == "scripted_skill":
            if not (
                _argv_uses_skill_entrypoint(cmd, profile)
                or _argv_uses_generated_file(cmd, plan)
            ):
                raise PlanValidationError(
                    f"Command '{cmd.id}': argv does not reference any "
                    f"SkillProfile entrypoint or generated file."
                )

        for art in cmd.expected_artifacts:
            if not _has_output_prefix(art):
                raise PlanValidationError(
                    f"Command '{cmd.id}': artifact '{art}' must live under "
                    f"outputs/ or runs/."
                )
            if not _is_under_project(art):
                raise PlanValidationError(
                    f"Command '{cmd.id}': artifact '{art}' escapes project root."
                )

    workspace_prefix = f"runs/{plan.plan_id}/workspace/"
    for f in plan.files_to_create:
        normalized = _normalize_path(f.path)
        if not normalized.startswith(workspace_prefix):
            raise PlanValidationError(
                f"files_to_create '{f.path}' must live under "
                f"'{workspace_prefix}'."
            )
        if not _is_under_project(f.path):
            raise PlanValidationError(
                f"files_to_create '{f.path}' escapes project root."
            )
        if _path_has_forbidden_part(f.path):
            raise PlanValidationError(
                f"files_to_create '{f.path}' touches a forbidden path."
            )

    for art in plan.artifacts_to_return:
        if not _has_output_prefix(art):
            raise PlanValidationError(
                f"artifacts_to_return '{art}' must live under outputs/ or runs/."
            )
        if not _is_under_project(art):
            raise PlanValidationError(
                f"artifacts_to_return '{art}' escapes project root."
            )


# ============================================================
# Prompt
# ============================================================


def _planner_prompt(prompt: str, profile: SkillProfile, plan_id: str) -> str:
    profile_json = profile.model_dump_json(indent=2)

    return f"""
        You are a Code/Execution Planner Agent for this application.

        You produce a JSON plan that the Sandbox Executor will run later.
        You do NOT execute anything yourself.

        Inputs

        User request:
        ---
        {prompt}
        ---

        SkillProfile (produced earlier by the Skill Interpreter):
        ---
        {profile_json}
        ---

        Plan id (use this exact value): {plan_id}

        Project policies
        - All paths must be project-relative.
        - Outputs must live under outputs/ or runs/.
        - Files you generate must live under runs/{plan_id}/workspace/.
        - Never reference .env, .git, __pycache__, or node_modules.

        Return EXACTLY ONE JSON object. No Markdown, no fences, no comments.
        It must match one of the two shapes below.

        Shape A - ready to execute:
        {{
          "status": "ready",
          "plan_id": "{plan_id}",
          "skill_name": "{profile.skill_name}",
          "summary": "Short human description of what will run.",
          "files_to_create": [
            {{
              "path": "runs/{plan_id}/workspace/script.py",
              "content": "# generated python source"
            }}
          ],
          "commands": [
            {{
              "id": "stable-id",
              "runtime": "python | node",
              "cwd": "project-relative-dir",
              "argv": ["python", "script.py", "--flag", "value"],
              "timeout_seconds": 120,
              "depends_on": [],
              "expected_artifacts": ["outputs/.../file"],
              "purpose": "What this command does."
            }}
          ],
          "artifacts_to_return": ["outputs/.../summary.txt"],
          "requires_confirmation": false,
          "risks": []
        }}

        Shape B - missing information:
        {{
          "status": "needs_clarification",
          "skill_name": "{profile.skill_name}",
          "missing_information": ["input csv path"],
          "question_for_user": "Which CSV file should I analyze?"
        }}

        Hard rules
        - Use only entrypoints listed in SkillProfile.steps. Do not invent files.
        - argv MUST be a list of strings, never a single shell command line.
        - argv[0] must be the runtime binary: "python", "python3", or "node".
        - Do NOT use shell metacharacters: && || ; | > < ` $().
        - Do NOT install dependencies, do NOT call sudo, do NOT delete files.
        - timeout_seconds must be in [{_MIN_TIMEOUT}, {_MAX_TIMEOUT}].
        - command ids must be unique inside the plan.
        - depends_on must reference existing command ids and form a DAG.
        - If SkillProfile.execution_strategy == "no_execution", return
          needs_clarification explaining the skill is documentation only.
        - If the user request is missing required inputs (see SkillProfile.inputs),
          return needs_clarification.
        - When SkillProfile has multiple steps with depends_on, mirror the
          ordering in commands using the same ids.
        - Reuse optional_args from SkillProfile when the user provided values
          for them; otherwise omit the optional argument.

        Be conservative. When in doubt, return needs_clarification instead of
        guessing values for required inputs.
    """


# ============================================================
# Public entrypoint
# ============================================================


def execution_planner_agent(
    prompt: str,
    skill_profile: SkillProfile,
    model: str = "openai:gpt-4o-mini",
    plan_id: Optional[str] = None,
    allow_shell: bool = False,
) -> PlanResponse:
    """
    Build a concrete execution plan from a user prompt and a SkillProfile.

    Returns either an ExecutionPlan (status="ready") or a ClarificationRequest
    (status="needs_clarification"). Validation is applied to the ready plan
    before returning, and PlanValidationError is raised if it fails.
    """

    final_plan_id = plan_id or f"plan_{uuid.uuid4().hex[:12]}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": _planner_prompt(prompt, skill_profile, final_plan_id),
            }
        ],
        temperature=0,
    )
    raw = response.choices[0].message.content or ""

    try:
        payload = json.loads(clean_json_block(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"execution_planner_agent: invalid JSON from LLM: {exc}\n"
            f"Raw response:\n{raw}"
        ) from exc

    status = payload.get("status")

    if status == "needs_clarification":
        try:
            return ClarificationRequest(**payload)
        except ValidationError as exc:
            raise ValueError(
                f"execution_planner_agent: invalid clarification schema: {exc}"
            ) from exc

    if status == "ready":
        try:
            plan = ExecutionPlan(**payload)
        except ValidationError as exc:
            raise ValueError(
                f"execution_planner_agent: invalid execution plan schema: {exc}"
            ) from exc

        if plan.plan_id != final_plan_id:
            plan = plan.model_copy(update={"plan_id": final_plan_id})

        _validate_plan_safety(plan, skill_profile, allow_shell=allow_shell)
        return plan

    raise ValueError(
        f"execution_planner_agent: unknown status '{status}' returned by LLM."
    )


__all__ = [
    "ClarificationRequest",
    "ExecutionCommand",
    "ExecutionPlan",
    "FileToCreate",
    "PlanResponse",
    "PlanValidationError",
    "execution_planner_agent",
]
