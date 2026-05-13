"""
FastAPI backend for Analytics Content Agent.

Endpoints:
  POST /upload-csv              — save CSV to workspace/
  POST /session                 — create session, select skills, return session_id
  GET  /session/{id}/stream     — SSE: run agent loop, emit events (pauses for tool auth)
  POST /session/{id}/authorize  — approve or deny pending tool call

  For Swagger/OpenAPI, tool calls block until authorize; use env ``AUTO_APPROVE_TOOLS=true``
  for local runs, or optional ``TOOL_AUTH_TIMEOUT_SEC`` to fail with an error instead of hanging.
  GET  /outputs                 — list files in outputs/
  GET  /outputs/{filename}      — serve generated file
"""

import asyncio
import json
import os
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agent import (
    OUTPUTS,
    TOOL_HANDLERS,
    WORKSPACE,
    _build_skills_catalog,
    _select_skills,
    agent_turn,
    load_skills,
)

app = FastAPI(title="Analytics Content Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-5-20250929")


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _tool_auth_timeout_sec() -> float | None:
    raw = os.getenv("TOOL_AUTH_TIMEOUT_SEC", "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def _max_agent_iterations() -> int:
    raw = os.getenv("MAX_AGENT_ITERATIONS", "40").strip()
    try:
        v = int(raw)
        return max(1, min(v, 500))
    except ValueError:
        return 40


def _max_agent_turn_recovery() -> int:
    """How many times we may recover from a failed ``agent_turn`` (API error) per stream."""
    raw = os.getenv("MAX_AGENT_TURN_RECOVERY", "2").strip()
    try:
        v = int(raw)
        return max(0, min(v, 10))
    except ValueError:
        return 2


def _format_tool_exception(exc: BaseException, *, max_tb_chars: int = 4000) -> str:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(tb) > max_tb_chars:
        tb = tb[:max_tb_chars] + "\n... (traceback truncated)"
    return (
        "[Tool execution failed]\n"
        f"Exception: {type(exc).__name__}: {exc}\n\n"
        f"Traceback:\n{tb}"
    )


# ─── Session ──────────────────────────────────────────────────────────────────

class Session:
    def __init__(self, system: str = "", csv_name: str = ""):
        self.messages: list = []
        self.system: str = system
        self.csv_name: str = csv_name
        self.pending: dict | None = None        # tool call waiting for auth
        self.auth_event: asyncio.Event = asyncio.Event()
        self.auth_approved: bool = False


sessions: dict[str, Session] = {}


# ─── SSE helper ───────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """
    Accept one file via multipart/form-data and write it to ``WORKSPACE``.

    - ``File(...)`` binds the upload body field named ``file`` and makes it required.
    - ``async`` / ``await file.read()`` use non-blocking I/O friendly to the ASGI event loop.
    """
    # Idempotent: create workspace directory if missing.
    WORKSPACE.mkdir(exist_ok=True)
    # Destination path uses the client-provided filename (no .csv validation here).
    dest = WORKSPACE / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": file.filename}

class SessionRequest(BaseModel):
    """Filename of the CSV in ``workspace/`` (same as ``POST /upload-csv`` response ``filename``)."""

    csv_name: str
    model: str = MODEL_NAME

@app.post("/session")
async def create_session(body: SessionRequest):
    """Create session, auto-select skills, return session_id.

    ``csv_name`` is used for skill selection and is sent to the model on the first
    chat message so it can open the file via tools (upload the file first with
    ``POST /upload-csv``).
    """
    catalog = await asyncio.to_thread(_build_skills_catalog)
    skills = await asyncio.to_thread(
        _select_skills, f"analisar {body.csv_name}", catalog, body.model
    )
    system = await asyncio.to_thread(load_skills, skills) if skills else ""
    session_id = str(uuid.uuid4())
    sessions[session_id] = Session(system=system, csv_name=body.csv_name.strip())
    return {"session_id": session_id, "skills": skills}


@app.get(
    "/session/{session_id}/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Server-Sent Events (not JSON). Each event is a line `data: <json>\\n\\n` "
                "with types such as `text`, `tool_call`, `tool_result`, `done`, `error`."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'data: {"type":"text","content":"Hello"}\n\n'
                        'data: {"type":"done"}\n\n'
                    ),
                },
            },
        },
    },
)
async def stream_session(session_id: str, message: str) -> StreamingResponse:
    """SSE: run agent loop, emit events, pause on tool calls for auth.

    After each ``tool_call`` event the server waits for ``POST .../authorize`` unless
    ``AUTO_APPROVE_TOOLS`` is set (recommended for ``/docs`` / Swagger, which cannot
    approve mid-stream). If ``TOOL_AUTH_TIMEOUT_SEC`` is set, waiting ends with an
    ``error`` event instead of hanging indefinitely.

    Tool execution errors are returned to the model as ``tool_result`` with ``is_error`` and
    do not abort the stream. Optional env: ``MAX_AGENT_ITERATIONS`` (default 40),
    ``MAX_AGENT_TURN_RECOVERY`` (default 2) for failed ``agent_turn`` API calls.
    """
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        user_text = message
        if not session.messages and session.csv_name:
            user_text = (
                "[Workspace: the CSV for this session is available at the relative path "
                f"`{session.csv_name}` inside the workspace (after a successful POST /upload-csv). "
                "Use the `view` tool or bash on that path to read and analyze it.]\n\n"
                + message
            )
        session.messages.append({"role": "user", "content": user_text})

        # Emit selected skills info once (derived from system prompt presence)
        if session.system:
            yield _sse({"type": "skills_selected"})

        max_iterations = _max_agent_iterations()
        recovery_left = _max_agent_turn_recovery()
        iteration = 0

        while True:
            iteration += 1
            if iteration > max_iterations:
                yield _sse({
                    "type": "error",
                    "message": (
                        f"Stopped: exceeded MAX_AGENT_ITERATIONS ({max_iterations}). "
                        "Increase the limit or start a shorter task."
                    ),
                })
                break

            # Call agent (blocking Anthropic HTTP) in thread
            try:
                text_blocks, tool_blocks = await asyncio.to_thread(
                    agent_turn,
                    messages=session.messages,
                    system=session.system,
                    model_name=MODEL_NAME,
                )
            except Exception as exc:
                if recovery_left <= 0:
                    yield _sse({"type": "error", "message": str(exc)})
                    break
                recovery_left -= 1
                yield _sse({
                    "type": "text",
                    "content": (
                        "[Model call failed — asking for a recovery plan. "
                        f"Attempts remaining after this message: {recovery_left}]"
                    ),
                })
                session.messages.append({
                    "role": "user",
                    "content": (
                        "The previous assistant model request failed with this error:\n\n"
                        f"{type(exc).__name__}: {exc}\n\n"
                        "Explain briefly what likely went wrong and give a concrete "
                        "step-by-step plan to fix it (environment, API keys, model name, "
                        "network). If the user should retry with a simpler prompt, say so. "
                        "Do not assume tools will work until the issue is addressed."
                    ),
                })
                continue

            # Emit text blocks
            for tb in text_blocks:
                yield _sse({"type": "text", "content": tb.text})

            # Build assistant message for history
            response_content = [
                {"type": "text", "text": tb.text} for tb in text_blocks
            ] + [
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                for b in tool_blocks
            ]

            if not tool_blocks:
                session.messages.append({"role": "assistant", "content": response_content})
                yield _sse({"type": "done"})
                break

            # Process each tool call sequentially, requiring auth for each
            tool_results: list[dict] = []
            for block in tool_blocks:
                session.pending = {"id": block.id, "name": block.name, "input": block.input}
                session.auth_event.clear()

                yield _sse({
                    "type": "tool_call",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

                if _env_truthy("AUTO_APPROVE_TOOLS"):
                    session.auth_approved = True
                    session.auth_event.set()
                else:
                    tmo = _tool_auth_timeout_sec()
                    try:
                        if tmo is None:
                            await session.auth_event.wait()
                        else:
                            await asyncio.wait_for(session.auth_event.wait(), timeout=tmo)
                    except asyncio.TimeoutError:
                        session.pending = None
                        yield _sse({
                            "type": "error",
                            "message": (
                                f"Timed out ({tmo}s) waiting for POST "
                                f"/session/{session_id}/authorize. "
                                "Swagger cannot send approve while this GET is open — use the "
                                "frontend, curl/EventSource in two terminals, set "
                                "AUTO_APPROVE_TOOLS=true in .env for local testing, or set "
                                "TOOL_AUTH_TIMEOUT_SEC to see this message after a limit."
                            ),
                        })
                        return

                if session.auth_approved:
                    handler = TOOL_HANDLERS.get(block.name)
                    if handler:
                        try:
                            result = await asyncio.to_thread(handler, **block.input)
                        except Exception as exc:
                            err_text = _format_tool_exception(exc)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": err_text,
                                "is_error": True,
                            })
                            yield _sse({
                                "type": "tool_result",
                                "id": block.id,
                                "content": err_text,
                                "error": True,
                            })
                        else:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(result),
                            })
                            yield _sse({
                                "type": "tool_result",
                                "id": block.id,
                                "content": str(result),
                            })
                    else:
                        result = f"Tool desconhecida: {block.name}"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                            "is_error": True,
                        })
                        yield _sse({
                            "type": "tool_result",
                            "id": block.id,
                            "content": str(result),
                            "error": True,
                        })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Tool call denied by user.",
                    })
                    yield _sse({"type": "tool_denied", "id": block.id, "name": block.name})

            session.pending = None
            session.messages.append({"role": "assistant", "content": response_content})
            session.messages.append({"role": "user", "content": tool_results})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class AuthBody(BaseModel):
    approved: bool


@app.post("/session/{session_id}/authorize")
async def authorize(session_id: str, body: AuthBody):
    """Approve or deny the pending tool call in a session."""
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.pending is None:
        raise HTTPException(status_code=400, detail="No pending tool call")
    session.auth_approved = body.approved
    session.auth_event.set()
    return {"ok": True}


@app.get("/outputs")
async def list_outputs():
    """List files available in outputs/."""
    OUTPUTS.mkdir(exist_ok=True)
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
            ".csv", ".xlsx", ".pdf", ".docx", ".txt", ".html"}
    files = [
        {"filename": p.name, "url": f"/outputs/{p.name}"}
        for p in sorted(OUTPUTS.iterdir())
        if p.is_file() and p.suffix.lower() in exts
    ]
    return {"files": files}


@app.get("/outputs/{filename}")
async def get_output(filename: str):
    """Serve a file from outputs/."""
    path = OUTPUTS / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
