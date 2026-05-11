"""
Sandbox Executor

Materializes an ExecutionPlan produced by the Code/Execution Planner Agent
and runs each command in a controlled subprocess environment.

What this module guarantees:
- Re-validates the plan before running (defense in depth, even if the
  planner already validated). Path traversal, shell metacharacters and
  runtime binary whitelists are checked again here.
- Always invokes subprocess with `shell=False` and an argv list, never a
  shell string.
- Uses a small environment allowlist by default. LLM-generated code does
  NOT inherit secrets from the parent process (no OPENAI_API_KEY, etc).
- Per-command timeout, capped stdout/stderr capture, no stdin attached.
- Topological execution by `depends_on`. Downstream commands are skipped
  if any dependency failed or timed out.
- Generated files (`files_to_create`) are materialized only inside
  `runs/<plan_id>/workspace/`.
- Writes a structured `run_log.json` under `runs/<plan_id>/` for auditing.

What this module deliberately does NOT do:
- It does not install dependencies. The runtime (python/node) and any
  third-party packages must already be available on PATH or in a venv.
- It does not provide network isolation. For real isolation, run the
  parent process inside Docker/firejail/etc.
- It does not enforce CPU/memory limits at the OS level. Use cgroups or
  Docker for that. Timeouts here only bound wall-clock time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Iterable, List, Literal, Optional

from pydantic import BaseModel, Field

from src.tools.loader import project_root, resolve_project_path
from sub_agents.execution_planner_agent import (
    ExecutionCommand,
    ExecutionPlan,
    PlanValidationError,
)


# ============================================================
# Policy constants (mirror of the planner's, kept independent
# so the executor can refuse a malformed plan even if the
# planner is bypassed).
# ============================================================


_RUNTIME_BINARIES: dict[str, set[str]] = {
    "python": {"python", "python3", "python.exe", "python3.exe"},
    "node": {"node", "node.exe"},
}

_ALLOWED_OUTPUT_PREFIXES = ("outputs/", "runs/")
_FORBIDDEN_PATH_PARTS = {".env", ".git", "__pycache__", "node_modules"}
_SHELL_METACHARS = ("&&", "||", ";", "|", ">", "<", "`", "$(")

_DEFAULT_ENV_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
}

_DEFAULT_MAX_STREAM_CHARS = 10000
_TRUNCATION_NOTICE = "\n[...truncated by sandbox executor...]\n"


# ============================================================
# Result schemas
# ============================================================


CommandStatus = Literal["success", "failed", "timeout", "skipped", "blocked"]
PlanStatus = Literal["success", "partial", "failed"]


class CommandResult(BaseModel):
    """Outcome of a single command in the plan."""

    id: str
    status: CommandStatus
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    artifacts: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ExecutionResult(BaseModel):
    """Outcome of a full ExecutionPlan."""

    plan_id: str
    status: PlanStatus
    run_dir: str
    log_path: str
    commands: List[CommandResult]
    artifacts_returned: List[str] = Field(default_factory=list)


# ============================================================
# Re-validation (defense in depth)
# ============================================================


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


def _argv_has_shell_metachars(argv: List[str]) -> Optional[str]:
    for arg in argv:
        for token in _SHELL_METACHARS:
            if token in arg:
                return token
    return None


def _revalidate_for_execution(plan: ExecutionPlan, allow_shell: bool) -> None:
    """Re-check the most dangerous rules before touching the OS."""

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

    workspace_prefix = f"runs/{plan.plan_id}/workspace/"
    for f in plan.files_to_create:
        normalized = _normalize_path(f.path)
        if not normalized.startswith(workspace_prefix):
            raise PlanValidationError(
                f"files_to_create '{f.path}' must live under '{workspace_prefix}'."
            )
        if not _is_under_project(f.path):
            raise PlanValidationError(
                f"files_to_create '{f.path}' escapes project root."
            )
        if _path_has_forbidden_part(f.path):
            raise PlanValidationError(
                f"files_to_create '{f.path}' touches a forbidden path."
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

        bad = _argv_has_shell_metachars(cmd.argv)
        if bad:
            raise PlanValidationError(
                f"Command '{cmd.id}': argv contains shell metacharacter '{bad}'."
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
# Helpers
# ============================================================


def _topological_order(commands: List[ExecutionCommand]) -> List[ExecutionCommand]:
    """Kahn's algorithm. Plan is already validated as a DAG."""

    by_id = {cmd.id: cmd for cmd in commands}
    indegree: dict[str, int] = {cmd.id: len(cmd.depends_on) for cmd in commands}
    dependents: dict[str, list[str]] = {cmd.id: [] for cmd in commands}
    for cmd in commands:
        for dep in cmd.depends_on:
            dependents[dep].append(cmd.id)

    queue: deque[str] = deque(
        [cmd_id for cmd_id, deg in indegree.items() if deg == 0]
    )
    ordered: List[ExecutionCommand] = []

    while queue:
        cmd_id = queue.popleft()
        ordered.append(by_id[cmd_id])
        for nxt in dependents[cmd_id]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(commands):
        raise PlanValidationError(
            "Cycle or unreachable command detected during topological sort."
        )
    return ordered


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    head = text[: max(limit - len(_TRUNCATION_NOTICE), 0)]
    return head + _TRUNCATION_NOTICE


def _safe_env(extra_env: Optional[dict[str, str]]) -> dict[str, str]:
    """Build a minimal, scrubbed environment for the child process."""

    base: dict[str, str] = {}
    for key in _DEFAULT_ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value is not None:
            base[key] = value

    base.setdefault("PYTHONIOENCODING", "utf-8")
    base.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    if extra_env:
        for key, value in extra_env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"env entry must be str/str, got {key!r}={value!r}")
            base[key] = value

    return base


def _materialize_files(plan: ExecutionPlan, run_root: Path) -> None:
    for spec in plan.files_to_create:
        target = resolve_project_path(spec.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.content, encoding="utf-8")


def _collect_artifacts(paths: Iterable[str]) -> List[str]:
    """Return only the project-relative paths that actually exist."""

    found: List[str] = []
    for raw in paths:
        try:
            absolute = resolve_project_path(raw)
        except ValueError:
            continue
        if absolute.exists():
            try:
                found.append(absolute.relative_to(project_root()).as_posix())
            except ValueError:
                found.append(absolute.as_posix())
    return found


def _save_stream(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8", errors="replace")


# ============================================================
# Public entrypoint
# ============================================================


def run_execution_plan(
    plan: ExecutionPlan,
    *,
    allow_shell: bool = False,
    runs_dir: Optional[Path] = None,
    max_stream_chars: int = _DEFAULT_MAX_STREAM_CHARS,
    extra_env: Optional[dict[str, str]] = None,
) -> ExecutionResult:
    """
    Execute an ExecutionPlan in a controlled subprocess environment.

    Parameters
    ----------
    plan
        Validated ExecutionPlan returned by execution_planner_agent.
    allow_shell
        Allow commands with runtime="shell". Default False.
    runs_dir
        Override for the runs/ root. Defaults to <project_root>/runs.
    max_stream_chars
        Per-command cap for stdout and stderr capture.
    extra_env
        Additional environment variables to inject. They are merged on top
        of the curated allowlist; secrets from the parent process are NOT
        passed through unless added here explicitly.
    """

    _revalidate_for_execution(plan, allow_shell=allow_shell)

    runs_root = (runs_dir or project_root() / "runs").resolve()
    run_root = runs_root / plan.plan_id
    workspace = run_root / "workspace"
    logs_dir = run_root / "logs"
    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    _materialize_files(plan, run_root)

    env = _safe_env(extra_env)
    ordered = _topological_order(plan.commands)

    by_id: dict[str, ExecutionCommand] = {c.id: c for c in plan.commands}
    results: dict[str, CommandResult] = {}

    def upstream_failed(cmd: ExecutionCommand) -> Optional[str]:
        for dep in cmd.depends_on:
            dep_result = results.get(dep)
            if dep_result is None:
                return dep
            if dep_result.status != "success":
                return dep
        return None

    for cmd in ordered:
        blocking_dep = upstream_failed(cmd)
        if blocking_dep is not None:
            results[cmd.id] = CommandResult(
                id=cmd.id,
                status="skipped",
                error=f"Upstream dependency '{blocking_dep}' did not succeed.",
            )
            continue

        try:
            cwd_path = resolve_project_path(cmd.cwd)
        except ValueError as exc:
            results[cmd.id] = CommandResult(
                id=cmd.id,
                status="blocked",
                error=f"Invalid cwd: {exc}",
            )
            continue

        if not cwd_path.is_dir():
            results[cmd.id] = CommandResult(
                id=cmd.id,
                status="blocked",
                error=f"cwd does not exist: {cmd.cwd}",
            )
            continue

        start = time.perf_counter()
        stdout = ""
        stderr = ""
        exit_code: Optional[int] = None
        status: CommandStatus = "failed"
        error: Optional[str] = None

        try:
            completed = subprocess.run(
                cmd.argv,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                shell=False,
                env=env,
                timeout=cmd.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = completed.returncode
            status = "success" if exit_code == 0 else "failed"
            if status == "failed":
                error = f"Non-zero exit code: {exit_code}"
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            status = "timeout"
            error = f"Timed out after {cmd.timeout_seconds}s"
        except FileNotFoundError as exc:
            status = "blocked"
            error = f"Runtime binary not found: {exc}"
        except OSError as exc:
            status = "failed"
            error = f"OS error while launching command: {exc}"

        duration = time.perf_counter() - start

        _save_stream(logs_dir / f"{cmd.id}.stdout.txt", stdout)
        _save_stream(logs_dir / f"{cmd.id}.stderr.txt", stderr)

        results[cmd.id] = CommandResult(
            id=cmd.id,
            status=status,
            exit_code=exit_code,
            stdout=_truncate(stdout, max_stream_chars),
            stderr=_truncate(stderr, max_stream_chars),
            duration_seconds=round(duration, 4),
            artifacts=_collect_artifacts(cmd.expected_artifacts),
            error=error,
        )

    ordered_results = [results[cmd.id] for cmd in plan.commands]

    statuses = {r.status for r in ordered_results}
    if statuses == {"success"}:
        plan_status: PlanStatus = "success"
    elif "success" in statuses:
        plan_status = "partial"
    else:
        plan_status = "failed"

    artifacts_to_check = list(plan.artifacts_to_return)
    if not artifacts_to_check:
        for cmd in plan.commands:
            artifacts_to_check.extend(cmd.expected_artifacts)
    artifacts_returned = _collect_artifacts(artifacts_to_check)

    log_path = run_root / "run_log.json"
    log_payload = {
        "plan_id": plan.plan_id,
        "skill_name": plan.skill_name,
        "summary": plan.summary,
        "status": plan_status,
        "started_at": time.time(),
        "commands": [r.model_dump() for r in ordered_results],
        "artifacts_returned": artifacts_returned,
    }
    log_path.write_text(
        json.dumps(log_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return ExecutionResult(
        plan_id=plan.plan_id,
        status=plan_status,
        run_dir=str(run_root.relative_to(project_root()).as_posix()),
        log_path=str(log_path.relative_to(project_root()).as_posix()),
        commands=ordered_results,
        artifacts_returned=artifacts_returned,
    )


__all__ = [
    "CommandResult",
    "ExecutionResult",
    "run_execution_plan",
]
