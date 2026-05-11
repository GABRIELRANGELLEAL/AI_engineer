"""
Automated backend tests for Analytics Content Agent (FastAPI).

Test plan:
  test_upload_csv            — POST /upload-csv saves the file in workspace/
  test_create_session        — POST /session returns session_id + skills
  test_outputs_empty         — GET /outputs returns {"files": []} when empty
  test_outputs_with_file     — GET /outputs lists created files
  test_get_output_not_found  — GET /outputs/inexistente.png returns 404
  test_authorize_no_session  — POST /session/fake-id/authorize returns 404
  test_authorize_no_pending  — Authorize session with no pending tool → 400
  test_stream_text_response  — SSE emits text + done when agent uses no tools
  test_stream_tool_approve   — SSE pauses on tool_call, resumes after approve
  test_stream_tool_deny      — SSE emits tool_denied after approve {approved: false}
"""

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import _text_block, _tool_block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse(raw_text: str) -> list[dict]:
    """Parse a raw SSE body into a list of JSON event dicts."""
    events = []
    for line in raw_text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def _stream(client, session_id: str, message: str) -> list[dict]:
    """Consume a full SSE stream synchronously and return all parsed events."""
    with client.stream(
        "GET",
        f"/session/{session_id}/stream",
        params={"message": message},
    ) as resp:
        assert resp.status_code == 200
        body = resp.read().decode()
    return _parse_sse(body)


# ---------------------------------------------------------------------------
# test_upload_csv
# ---------------------------------------------------------------------------

def test_upload_csv(client, tmp_workspace):
    """POST /upload-csv should save the file inside workspace/."""
    content = b"date,meantemp\n2013-01-01,10.0\n"
    resp = client.post(
        "/upload-csv",
        files={"file": ("test.csv", io.BytesIO(content), "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"filename": "test.csv"}

    saved = tmp_workspace / "workspace" / "test.csv"
    assert saved.exists()
    assert saved.read_bytes() == content


# ---------------------------------------------------------------------------
# test_create_session
# ---------------------------------------------------------------------------

def test_create_session(client):
    """POST /session should return a session_id and a skills list."""
    resp = client.post("/session", json={"csv_name": "test.csv"})
    assert resp.status_code == 200

    data = resp.json()
    assert "session_id" in data
    assert isinstance(data["session_id"], str)
    assert len(data["session_id"]) > 0
    assert "skills" in data
    assert isinstance(data["skills"], list)


# ---------------------------------------------------------------------------
# test_outputs_empty
# ---------------------------------------------------------------------------

def test_outputs_empty(client):
    """GET /outputs should return {'files': []} when outputs/ is empty."""
    resp = client.get("/outputs")
    assert resp.status_code == 200
    assert resp.json() == {"files": []}


# ---------------------------------------------------------------------------
# test_outputs_with_file
# ---------------------------------------------------------------------------

def test_outputs_with_file(client, tmp_workspace):
    """GET /outputs should list image files that exist in outputs/."""
    out_dir = tmp_workspace / "outputs"
    (out_dir / "chart.png").write_bytes(b"\x89PNG\r\n")

    resp = client.get("/outputs")
    assert resp.status_code == 200

    files = resp.json()["files"]
    assert len(files) == 1
    assert files[0]["filename"] == "chart.png"
    assert files[0]["url"] == "/outputs/chart.png"


# ---------------------------------------------------------------------------
# test_get_output_not_found
# ---------------------------------------------------------------------------

def test_get_output_not_found(client):
    """GET /outputs/inexistente.png should return 404."""
    resp = client.get("/outputs/inexistente.png")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# test_authorize_no_session
# ---------------------------------------------------------------------------

def test_authorize_no_session(client):
    """POST /session/fake-id/authorize should return 404."""
    resp = client.post("/session/fake-id/authorize", json={"approved": True})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# test_authorize_no_pending
# ---------------------------------------------------------------------------

def test_authorize_no_pending(client, session_id):
    """POST authorize on a session with no pending tool call should return 400."""
    resp = client.post(f"/session/{session_id}/authorize", json={"approved": True})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# test_stream_text_response
# ---------------------------------------------------------------------------

def test_stream_text_response(client, session_id, mock_agent_turn):
    """SSE should emit text + done when the agent returns only text blocks."""
    mock_agent_turn.return_value = (
        [_text_block("Olá! Aqui estão os dados.")],
        [],
    )

    events = _stream(client, session_id, "mostre as primeiras 5 linhas")

    types = [e["type"] for e in events]
    assert "text" in types
    assert "done" in types
    assert "tool_call" not in types

    text_event = next(e for e in events if e["type"] == "text")
    assert "Olá" in text_event["content"]


# ---------------------------------------------------------------------------
# Async helpers for streaming tests
# ---------------------------------------------------------------------------

async def _async_stream_events(ac: AsyncClient, session_id: str, message: str) -> list[dict]:
    """Consume an SSE stream line-by-line and return all parsed events."""
    events: list[dict] = []
    async with ac.stream(
        "GET",
        f"/session/{session_id}/stream",
        params={"message": message},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[len("data:"):].strip()))
                except json.JSONDecodeError:
                    pass
    return events


async def _make_async_client():
    """Build an AsyncClient wired to the FastAPI app."""
    import app as app_module
    return AsyncClient(
        transport=ASGITransport(app=app_module.app),
        base_url="http://test",
    )


# ---------------------------------------------------------------------------
# test_stream_tool_approve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_tool_approve(tmp_workspace, mock_skills):
    """
    SSE should pause at tool_call, resume after POST /authorize {approved:true},
    and emit tool_result followed by done.

    Uses AsyncClient + asyncio tasks so the stream consumer and the authorize
    POST share the same event loop — this is the only reliable way to test
    asyncio.Event-based pause/resume without crossing event-loop boundaries.
    """
    import app as app_module

    app_module.sessions.clear()

    tool = _tool_block(name="view", input={"path": "test.csv"}, tool_id="tool_view_001")
    text = _text_block("Vou visualizar o arquivo.")

    with patch("app.agent_turn", side_effect=[
        ([text], [tool]),
        ([_text_block("Aqui estão os dados.")], []),
    ]):
        with patch("app.TOOL_HANDLERS", {"view": lambda **kw: "col1,col2\nval1,val2"}):
            async with await _make_async_client() as ac:
                sess_resp = await ac.post("/session", json={"csv_name": "test.csv"})
                assert sess_resp.status_code == 200
                sid = sess_resp.json()["session_id"]

                events: list[dict] = []

                async def consume():
                    events.extend(await _async_stream_events(ac, sid, "mostre as primeiras 5 linhas"))

                stream_task = asyncio.create_task(consume())

                # Wait until the generator has emitted tool_call (pending is set)
                for _ in range(100):
                    sess = app_module.sessions.get(sid)
                    if sess and sess.pending is not None:
                        break
                    await asyncio.sleep(0.05)

                auth_resp = await ac.post(f"/session/{sid}/authorize", json={"approved": True})
                assert auth_resp.status_code == 200

                await asyncio.wait_for(stream_task, timeout=10)

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert "done" in types
    assert "tool_denied" not in types


# ---------------------------------------------------------------------------
# test_stream_tool_deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_tool_deny(tmp_workspace, mock_skills):
    """
    SSE should emit tool_denied after POST /authorize {approved:false}.
    The agent handles denial gracefully and eventually emits done.
    """
    import app as app_module

    app_module.sessions.clear()

    tool = _tool_block(
        name="bash",
        input={"command": "ls /workspace", "description": "listar arquivos"},
        tool_id="tool_bash_002",
    )
    text = _text_block("Vou listar os arquivos.")

    with patch("app.agent_turn", side_effect=[
        ([text], [tool]),
        ([_text_block("Entendido, operação cancelada.")], []),
    ]):
        async with await _make_async_client() as ac:
            sess_resp = await ac.post("/session", json={"csv_name": "test.csv"})
            assert sess_resp.status_code == 200
            sid = sess_resp.json()["session_id"]

            events: list[dict] = []

            async def consume():
                events.extend(await _async_stream_events(ac, sid, "liste os arquivos do workspace"))

            stream_task = asyncio.create_task(consume())

            for _ in range(100):
                sess = app_module.sessions.get(sid)
                if sess and sess.pending is not None:
                    break
                await asyncio.sleep(0.05)

            deny_resp = await ac.post(f"/session/{sid}/authorize", json={"approved": False})
            assert deny_resp.status_code == 200

            await asyncio.wait_for(stream_task, timeout=10)

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_denied" in types
    assert "tool_result" not in types
    assert "done" in types
