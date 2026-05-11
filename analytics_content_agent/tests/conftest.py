"""
Shared fixtures for the Analytics Content Agent test suite.

Key design decisions:
- agent_turn is mocked at the FastAPI import boundary so no Anthropic calls are
  made during tests.
- WORKSPACE and OUTPUTS directories are replaced with pytest tmp_path equivalents
  so tests never pollute the real filesystem.
- The TestClient is synchronous; async SSE generators are consumed via the
  streaming=True flag on httpx requests.
"""

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers to build fake Anthropic response blocks
# ---------------------------------------------------------------------------

def _text_block(text: str) -> SimpleNamespace:
    """Minimal stand-in for an Anthropic TextBlock."""
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, input: dict, tool_id: str = "tool_abc123") -> SimpleNamespace:
    """Minimal stand-in for an Anthropic ToolUseBlock."""
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input)


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_workspace(tmp_path: Path, monkeypatch) -> Path:
    """
    Replace agent.WORKSPACE and agent.OUTPUTS with temporary directories so
    tests never write to the real workspace/ or outputs/ folders.
    """
    ws = tmp_path / "workspace"
    out = tmp_path / "outputs"
    ws.mkdir()
    out.mkdir()

    import agent
    import app as app_module

    monkeypatch.setattr(agent, "WORKSPACE", ws)
    monkeypatch.setattr(agent, "OUTPUTS", out)
    monkeypatch.setattr(app_module, "WORKSPACE", ws, raising=False)
    monkeypatch.setattr(app_module, "OUTPUTS", out)

    return tmp_path


@pytest.fixture()
def mock_agent_turn():
    """
    Patch agent_turn inside app.py so no real Anthropic API calls are made.

    Returns the MagicMock so individual tests can configure return_value.

    Default return value: one text block, no tool blocks.
    """
    default_text = _text_block("Resposta padrão do agente.")
    with patch("app.agent_turn", return_value=([default_text], [])) as mock:
        yield mock


@pytest.fixture()
def mock_skills(monkeypatch):
    """
    Patch _build_skills_catalog, _select_skills, and load_skills inside app.py
    so skill discovery and selection never touch the filesystem or Anthropic.
    """
    import app as app_module

    monkeypatch.setattr(app_module, "_build_skills_catalog", lambda: {})
    monkeypatch.setattr(app_module, "_select_skills", lambda *a, **kw: [])
    monkeypatch.setattr(app_module, "load_skills", lambda names: "")


@pytest.fixture()
def client(tmp_workspace, mock_skills) -> TestClient:
    """
    Return a synchronous TestClient with isolated workspace/outputs and mocked
    skill helpers.  agent_turn is NOT mocked here; tests that need it should
    also use mock_agent_turn (or call it explicitly).
    """
    # Import app after monkeypatches are applied
    import app as app_module

    # Reset in-memory sessions between tests
    app_module.sessions.clear()

    return TestClient(app_module.app, raise_server_exceptions=True)


@pytest.fixture()
def session_id(client, mock_agent_turn) -> str:
    """Create a session and return its ID for use in dependent tests."""
    resp = client.post("/session", json={"csv_name": "test.csv"})
    assert resp.status_code == 200
    return resp.json()["session_id"]
