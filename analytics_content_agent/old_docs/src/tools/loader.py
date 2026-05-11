"""
Skill Loader

Loads a local skill from disk by exact name. A "skill" is any folder under
`skills/` that contains a `SKILL.md` with a YAML front matter block of the
form:

    ---
    name: my-skill
    description: What it does in one line.
    ---

This module is intentionally standalone: it does not import any LLM client
or heavy dependency, so it can be reused from agents, executors, and tests
without side effects on import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / "skills"


@dataclass(frozen=True)
class LoadedSkill:
    """Full local skill content plus metadata from its YAML front matter."""

    name: str
    description: str
    path: Path
    content: str


def project_root() -> Path:
    """Return the absolute path to the project root."""

    return PROJECT_ROOT


def resolve_project_path(path: str | Path) -> Path:
    """
    Resolve a user/tool path and ensure it stays inside the project.

    Raises ValueError if the resolved path escapes PROJECT_ROOT. Use this in
    every tool that touches the file system on behalf of the LLM.
    """

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    resolved = candidate.resolve()
    if resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents:
        raise ValueError(f"Path escapes project root: {path}")

    return resolved


def _parse_yaml_header(markdown: str) -> Optional[Dict[str, str]]:
    """
    Parse only the top YAML front matter block of a Markdown file.

    Supports the simple `key: value` shape used by SKILL.md files and avoids
    importing a full YAML library just for metadata.
    """

    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    header_lines: list[str] = []
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


def load_skill(skill_name: str) -> LoadedSkill:
    """
    Load a local skill by exact name from `skills/<slug>/SKILL.md`.

    The match is done against the `name` field of the YAML front matter, not
    against the folder name, so renaming a folder does not break lookups as
    long as the front matter stays consistent.

    Raises ValueError if no skill with that name is found.
    """

    if not SKILLS_ROOT.is_dir():
        raise ValueError(f"Skills directory not found: {SKILLS_ROOT}")

    for skill_file in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError:
            continue

        header = _parse_yaml_header(content)
        if not header:
            continue

        name = header.get("name", "").strip()
        if name != skill_name:
            continue

        description = header.get("description", "").strip()
        return LoadedSkill(
            name=name,
            description=description,
            path=skill_file,
            content=content,
        )

    raise ValueError(f"Skill not found: {skill_name}")


__all__ = [
    "LoadedSkill",
    "PROJECT_ROOT",
    "SKILLS_ROOT",
    "load_skill",
    "project_root",
    "resolve_project_path",
]
