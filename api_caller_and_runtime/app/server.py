"""
FastAPI server to run the Orchestrator and stream agentic loop events via SSE.

Endpoints:
    POST /run        — start a new run, returns run_id + session_id
    GET  /run/{id}/events — SSE stream of loop events for the visualizer
    GET  /           — serves index.html
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Patch ResponseHandler to emit SSE events at each step
# ---------------------------------------------------------------------------
from response_handler import ResponseHandler, LoopState
from llm import LLMResponse, get_llm_provider
from chat_orchestrator import Orchestrator
from tools import to_neutral_tools, TOOLS

app = FastAPI(title="Agentic Loop Visualizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory event store: run_id → list of events
# ---------------------------------------------------------------------------
_run_events: dict[str, list[dict[str, Any]]] = {}
_run_done: dict[str, bool] = {}


def _push(run_id: str, event: dict[str, Any]):
    """Append an event to the run's event list."""
    _run_events.setdefault(run_id, []).append(event)


# ---------------------------------------------------------------------------
# Instrumented ResponseHandler
# ---------------------------------------------------------------------------

class InstrumentedResponseHandler(ResponseHandler):
    """Subclass that emits SSE events as it processes each step."""

    def __init__(self, run_id: str, **kwargs):
        super().__init__(**kwargs)
        self.run_id = run_id
        self._iteration = 0

    def _emit(self, event_type: str, data: dict[str, Any]):
        _push(self.run_id, {"type": event_type, **data})

    async def process_response(
        self,
        response: LLMResponse,
        state: LoopState | None = None,
        verbose: bool | None = None,
    ) -> LoopState:
        self._iteration += 1
        iteration = self._iteration

        self._emit("turn_start", {
            "iteration": iteration,
            "provider": response.provider_used,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "stop_reason": response.stop_reason,
            "tokens": response.tokens_used,
        })

        # Let the parent do all the real work
        old_len = len(state.output_messages) if state is not None else 0
        result_state = await super().process_response(response, state, verbose)

        self._emit("loop_state", {
            "iteration": iteration,
            "stop_reason": result_state.stop_reason,
            "total_tokens": result_state.total_tokens,
            "message_count": len(result_state.output_messages),
        })

        # First: what the LLM asked for (tool invocations)
        for block in response.content:
            if block.get("type") == "tool_use":
                self._emit("tool_call", {
                    "iteration": iteration,
                    "tool_name": block["name"],
                    "tool_use_id": block["id"],
                    "input": block.get("input", {}),
                })

        # Then: execution results and text
        for msg in result_state.output_messages[old_len:]:
            if msg.get("type") == "text":
                self._emit("text_block", {
                    "iteration": iteration,
                    "content": msg.get("content", "")[:2000],
                })
            elif msg.get("type") == "tool_result":
                self._emit("tool_result", {
                    "iteration": iteration,
                    "tool_name": msg.get("tool_name", ""),
                    "tool_use_id": msg.get("tool_use_id", ""),
                    "content": str(msg.get("content", ""))[:300],
                })

        return result_state


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    message: str
    model: str = "claude-sonnet-4-6"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    tools: list[str] | None = None
    max_iterations: int = 10
    system_prompt: str | None = None


class RunResponse(BaseModel):
    run_id: str
    session_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    html_path = Path(__file__).parent / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(html_path)


@app.post("/run", response_model=RunResponse)
async def start_run(req: RunRequest):
    """Kick off a new Orchestrator run and stream events via /run/{id}/events."""
    run_id = str(uuid.uuid4())
    _run_events[run_id] = []
    _run_done[run_id] = False

    anthropic_key = req.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    openai_key = req.openai_api_key or os.getenv("OPENAI_API_KEY")

    if not anthropic_key and not openai_key:
        raise HTTPException(
            status_code=400,
            detail="Provide anthropic_api_key or openai_api_key (or set env vars).",
        )

    try:
        provider = get_llm_provider(
            model=req.model,
            anthropic_key=anthropic_key,
            openai_key=openai_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    handler = InstrumentedResponseHandler(run_id=run_id, verbose=False)

    tool_names = req.tools or list(TOOLS.keys())
    tools_list = to_neutral_tools(tool_names)

    orchestrator = Orchestrator(
        provider=provider,
        model=req.model,
        tools=tools_list,
        max_iterations=req.max_iterations,
        system_prompt=req.system_prompt,
        verbose=False,
    )
    # Inject our instrumented handler
    orchestrator._handler = handler

    session_id = orchestrator.create_session()

    async def _run_in_background():
        try:
            _push(run_id, {"type": "run_start", "run_id": run_id, "model": req.model})
            result = await orchestrator.run(
                user_message=req.message,
                session_id=session_id,
                run_id=run_id,
            )
            _push(run_id, {
                "type": "run_end",
                "run_id": run_id,
                "stop_reason": result.stop_reason,
                "total_tokens": result.total_tokens,
                "final_answer": result.final_answer[:3000] if result.final_answer else "",
            })
        except Exception as exc:
            _push(run_id, {"type": "run_error", "error": str(exc)})
        finally:
            _run_done[run_id] = True

    asyncio.create_task(_run_in_background())

    return RunResponse(run_id=run_id, session_id=session_id)


@app.get("/run/{run_id}/events")
async def stream_events(run_id: str):
    """SSE endpoint — streams events as they are produced by the agentic loop."""
    if run_id not in _run_events:
        raise HTTPException(status_code=404, detail="Run not found")

    async def _generator() -> AsyncGenerator[str, None]:
        cursor = 0
        while True:
            events = _run_events.get(run_id, [])
            while cursor < len(events):
                evt = events[cursor]
                yield f"data: {json.dumps(evt)}\n\n"
                cursor += 1

            if _run_done.get(run_id) and cursor >= len(_run_events.get(run_id, [])):
                yield "data: {\"type\": \"stream_end\"}\n\n"
                break

            await asyncio.sleep(0.1)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )