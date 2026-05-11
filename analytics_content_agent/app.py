"""
FastAPI backend for Analytics Content Agent.

Endpoints:
  POST /upload-csv              — save CSV to workspace/
  POST /session                 — create session, select skills, return session_id
  GET  /session/{id}/stream     — SSE: run agent loop, emit events
  POST /session/{id}/authorize  — approve or deny pending tool call
  GET  /outputs                 — list files in outputs/
  GET  /outputs/{filename}      — serve generated file
"""

import asyncio
import json
import os
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


# ─── Session ──────────────────────────────────────────────────────────────────

class Session:
    def __init__(self, system: str = ""):
        self.messages: list = []
        self.system: str = system
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
    """Save uploaded CSV to workspace/."""
    WORKSPACE.mkdir(exist_ok=True)
    dest = WORKSPACE / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": file.filename}


class SessionRequest(BaseModel):
    csv_name: str
    model: str = MODEL_NAME


@app.post("/session")
async def create_session(body: SessionRequest):
    """Create session, auto-select skills, return session_id."""
    catalog = await asyncio.to_thread(_build_skills_catalog)
    skills = await asyncio.to_thread(
        _select_skills, f"analisar {body.csv_name}", catalog, body.model
    )
    system = await asyncio.to_thread(load_skills, skills) if skills else ""
    session_id = str(uuid.uuid4())
    sessions[session_id] = Session(system=system)
    return {"session_id": session_id, "skills": skills}


@app.get("/session/{session_id}/stream")
async def stream_session(session_id: str, message: str):
    """SSE: run agent loop, emit events, pause on tool calls for auth."""
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        session.messages.append({"role": "user", "content": message})

        # Emit selected skills info once (derived from system prompt presence)
        if session.system:
            yield _sse({"type": "skills_selected"})

        while True:
            # Call agent (blocking Anthropic HTTP) in thread
            try:
                text_blocks, tool_blocks = await asyncio.to_thread(
                    agent_turn,
                    messages=session.messages,
                    system=session.system,
                    model_name=MODEL_NAME,
                )
            except Exception as exc:
                yield _sse({"type": "error", "message": str(exc)})
                break

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
            tool_results = []
            for block in tool_blocks:
                session.pending = {"id": block.id, "name": block.name, "input": block.input}
                session.auth_event.clear()

                yield _sse({
                    "type": "tool_call",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

                # Pause until /authorize is called
                await session.auth_event.wait()

                if session.auth_approved:
                    handler = TOOL_HANDLERS.get(block.name)
                    if handler:
                        result = await asyncio.to_thread(handler, **block.input)
                    else:
                        result = f"Tool desconhecida: {block.name}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                    yield _sse({"type": "tool_result", "id": block.id, "content": str(result)})
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
