"""
FastAPI backend for Analytics Content Agent.

This module defines the HTTP API: CSV upload, chat sessions backed by an in-memory
``sessions`` map, Server-Sent Events (SSE) streaming for the agent loop, optional
human-in-the-loop tool authorization, static listing of generated files, and optional
PostgreSQL persistence when ``DATABASE_URL`` is set.

Endpoints (summary):
  POST /upload-csv              — save CSV to workspace/
  POST /session                 — create session, select skills, return session_id
  GET  /session/{id}/stream     — SSE: run agent loop, emit events (pauses for tool auth)
  POST /session/{id}/authorize  — approve or deny pending tool call

  For Swagger/OpenAPI, tool calls block until authorize; use env ``AUTO_APPROVE_TOOLS=true``
  for local runs, or optional ``TOOL_AUTH_TIMEOUT_SEC`` to fail with an error instead of hanging.
  GET  /outputs                 — list files in outputs/
  GET  /outputs/{filename}      — serve generated file

  Optional: set ``DATABASE_URL`` for PostgreSQL persistence of sessions and turns
  (tables created on startup).
"""

# --- Standard library ----------------------------------------------------------

import asyncio  # Run blocking work in threads; asyncio.Event for tool auth handshake.
import contextlib  # Provides @asynccontextmanager for FastAPI lifespan hooks.
import json  # Serialize SSE payloads and persist tool_result rows as JSON text.
import logging  # Structured-ish logging for DB failures without crashing requests.
import os  # Read process environment (model name, feature flags, database URL).
import traceback  # Format tracebacks when a tool handler raises unexpectedly.
import uuid  # Generate opaque session identifiers (UUID4 strings).
from collections.abc import Callable  # Type hint for zero-arg callables passed to threads.

# --- Third-party (FastAPI stack) ----------------------------------------------

from fastapi import FastAPI, File, HTTPException, UploadFile  # Web framework primitives.
from fastapi.middleware.cors import CORSMiddleware  # Allow browser clients from other origins.
from fastapi.responses import FileResponse, StreamingResponse  # Binary file + SSE responses.
from pydantic import BaseModel  # Request/response validation models for JSON bodies.

# --- Local agent integration ----------------------------------------------------

from agent import (  # Sandbox agent: skills, tools, and single-turn Claude calls.
    OUTPUTS,  # Directory where artifacts (plots, exports) are written for download.
    TOOL_HANDLERS,  # Maps tool name strings to Python callables executed on approve.
    WORKSPACE,  # Directory where uploaded CSV and intermediate files live.
    _build_skills_catalog,  # Discovers skill markdown files and metadata for selection.
    _select_skills,  # LLM-assisted choice of which skill bodies to load into system prompt.
    agent_turn,  # One Messages API call: returns text blocks and tool_use blocks.
    load_skills,  # Reads selected SKILL.md files and concatenates them for ``system``.
)

# --- Optional persistence layer -------------------------------------------------

import db  # PostgreSQL helpers; all calls are no-ops when DATABASE_URL is unset.

# Module-level logger (inherits root configuration from uvicorn when run under it).
logger = logging.getLogger(__name__)

# decorator is same thing of:
# async def lifespan(app: FastAPI):
#     ...code...
# f = contextlib.asynccontextmanager(lifespan)
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context: runs once at application startup and once at shutdown.

    On startup, if ``DATABASE_URL`` is configured, creates SQL tables via ``db.init_db``.
    Failures are logged but do not prevent the API from serving traffic (degraded mode).

    Args:
        app: The FastAPI application instance (unused here but required by the protocol).

    Yields:
        Control back to the ASGI server between startup and shutdown.
    """
    # Only touch the database when explicitly configured., ++++++
    if db.enabled():
        # DB driver is blocking; avoid stalling the event loop during DDL.
        try:
            await asyncio.to_thread(db.init_db)  # CREATE TABLE IF NOT EXISTS, etc.
        except Exception:
            # Do not crash the whole app if Postgres is down or URL is wrong.
            logger.exception("PostgreSQL init_db failed; continuing without DB")
    # Hand off to request handling until process shutdown.
    yield


# FastAPI app with OpenAPI title and lifespan hook for DB initialization.
app = FastAPI(title="Analytics Content Agent API", lifespan=lifespan)

# Permissive CORS for local dev (tighten origins in production if needed).
app.add_middleware(
    CORSMiddleware,  # Middleware class from Starlette/FastAPI.
    allow_origins=["*"],  # Reflect any Origin header (dev convenience).
    allow_methods=["*"],  # Allow GET/POST/OPTIONS/... without enumerating.
    allow_headers=["*"],  # Allow custom headers from SPAs or proxies.
)

# Default Anthropic model id; may be overridden per session request body.
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-5-20250929")


def _env_truthy(name: str) -> bool:
    """
    Interpret common truthy string values from the environment.

    Used for feature flags such as ``AUTO_APPROVE_TOOLS`` so operators can toggle
    behavior without code changes.

    Args:
        name: Environment variable name to read.

    Returns:
        True if the variable is set to a recognized \"on\" value, else False.
    """
    # Normalize: strip whitespace and compare case-insensitively.
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _tool_auth_timeout_sec() -> float | None:
    """
    Optional wall-clock timeout while waiting for POST /authorize after a tool_call SSE.

    When unset or invalid, the stream waits indefinitely for authorization (unless
    ``AUTO_APPROVE_TOOLS`` short-circuits the wait).

    Returns:
        Positive float seconds, or None for no timeout.
    """
    # Read raw string from environment (empty means disabled).
    raw = os.getenv("TOOL_AUTH_TIMEOUT_SEC", "").strip()
    # Empty string disables the timeout feature entirely.
    if not raw:
        return None
    try:
        # Parse as float to allow sub-second values if ever needed.
        v = float(raw)
        # Reject zero or negative: would be meaningless or busy-loop-prone semantics.
        return v if v > 0 else None
    except ValueError:
        # Malformed env: behave as if unset rather than crashing import-time.
        return None


def _max_agent_iterations() -> int:
    """
    Upper bound on agent/model loop iterations per single GET /stream request.

    Prevents infinite tool loops from burning API credits when the model misbehaves.

    Returns:
        Integer between 1 and 500 inclusive.
    """
    # Default \"40\" matches a reasonable cap for multi-step analytics tasks.
    raw = os.getenv("MAX_AGENT_ITERATIONS", "40").strip()
    try:
        v = int(raw)
        # Clamp to sane bounds: at least one iteration, at most 500.
        return max(1, min(v, 500))
    except ValueError:
        # Bad env: fall back to built-in default of 40 iterations.
        return 40


def _max_agent_turn_recovery() -> int:
    """
    How many times we may recover from a failed ``agent_turn`` (API error) per stream.

    After each failure we inject a synthetic user message asking the model to explain
    the outage; when this budget hits zero we surface a terminal ``error`` SSE event.

    Returns:
        Integer between 0 and 10 inclusive (0 means fail immediately on first API error).
    """
    # Default \"2\" allows a couple of self-healing explanations before giving up.
    raw = os.getenv("MAX_AGENT_TURN_RECOVERY", "2").strip()
    try:
        v = int(raw)
        # Clamp: allow disabling recovery entirely (0) up to a small hard cap (10).
        return max(0, min(v, 10))
    except ValueError:
        # Malformed env: use conservative default of 2 recovery attempts.
        return 2


def _format_tool_exception(exc: BaseException, *, max_tb_chars: int = 4000) -> str:
    """
    Build a human-readable string for tool execution failures to feed back to the model.

    The model sees this inside a ``tool_result`` with ``is_error`` so it can adjust.

    Args:
        exc: The exception raised inside a tool handler.
        max_tb_chars: Truncate traceback text beyond this many characters.

    Returns:
        Multi-line string including type, message, and traceback (possibly truncated).
    """
    # Standard library formatting of the active traceback chain.
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    # Avoid sending megabytes of traceback if dependency stacks are huge.
    if len(tb) > max_tb_chars:
        tb = tb[:max_tb_chars] + "\n... (traceback truncated)"
    # Prefix helps the model recognize this as tool infrastructure, not user content.
    return (
        "[Tool execution failed]\n"
        f"Exception: {type(exc).__name__}: {exc}\n\n"
        f"Traceback:\n{tb}"
    )


# ─── In-memory session state (not replicated across workers) ──────────────────


class Session:
    """
    One live chat session: Anthropic message list, system prompt, tool auth latch, DB seq.

    This is distinct from ``db.ChatSessionRow``: the latter is durable metadata; this class
    holds the mutable conversation state used by ``agent_turn`` across SSE chunks.
    """

    def __init__(self, system: str = "", csv_name: str = "") -> None:
        """
        Initialize empty message history and synchronization primitives.

        Args:
            system: Concatenated skill markdown (or empty when no skills selected).
            csv_name: Workspace-relative filename hint for first-message context injection.
        """
        # Anthropic-compatible message list (roles: user/assistant; content blocks).
        self.messages: list = []
        # System prompt string passed to ``agent_turn`` (skills or generic fallback in agent).
        self.system: str = system
        # Remember which CSV name was bound at POST /session for workspace hints.
        self.csv_name: str = csv_name
        # When non-None, holds the tool_use block currently awaiting POST /authorize.
        self.pending: dict | None = None  # tool call waiting for auth
        # Event object used to park the SSE generator until authorize unblocks it.
        self.auth_event: asyncio.Event = asyncio.Event()
        # Last authorization decision for the pending tool (written by authorize route).
        self.auth_approved: bool = False
        # Monotonic counter for ``turn_index`` rows in PostgreSQL for this RAM session.
        self.turn_seq: int = 0


# Global registry of live sessions keyed by UUID string from POST /session.
sessions: dict[str, Session] = {}


def _next_turn_index(session: Session) -> int:
    """
    Allocate the next sequential ``turn_index`` for PostgreSQL ``turns`` rows.

    Must be called from the same async task that owns the session to avoid races.

    Args:
        session: The in-memory session whose counter should advance.

    Returns:
        The new positive integer turn index (1-based after first increment).
    """
    # Pre-increment pattern: first call returns 1, second returns 2, etc.
    session.turn_seq += 1
    return session.turn_seq


async def _db_thread(fn: Callable[[], None]) -> None:
    """
    Run a synchronous DB callable in a worker thread without blocking the event loop.

    Args:
        fn: Zero-argument callable (often a lambda wrapping ``_persist_*`` helpers).
    """
    # Skip entirely when persistence is disabled (no DATABASE_URL).
    if not db.enabled():
        return
    # asyncio.to_thread schedules ``fn`` on the default thread pool executor.
    await asyncio.to_thread(fn)


def _persist_chat_session(session_id: str, system: str, csv_name: str, model_name: str) -> None:
    """
    Insert or merge one row in ``chat_sessions`` (runs inside ``_db_thread``).

    Args:
        session_id: Primary key string shared with the in-memory ``Session`` map.
        system: Full system prompt text at session creation time.
        csv_name: Sanitized CSV filename associated with this chat.
        model_name: Model id used during skill selection (informational column).
    """
    try:
        # merge() allows idempotent re-registration if logic ever retries.
        db.insert_chat_session(
            session_id,
            system_prompt=system,
            csv_name=csv_name,
            model_name=model_name,
        )
    except Exception:
        # Chat must continue even if audit trail write fails.
        logger.exception("insert_chat_session failed session_id=%s", session_id)


def _persist_turn(
    session_id: str,
    turn_index: int,
    turn_kind: str,
    *,
    user_prompt: str | None = None,
    text_blocks: list | None = None,
    tool_blocks: list | None = None,
) -> None:
    """
    Insert one ``turns`` row describing a single logical message in the chat history.

    Args:
        session_id: Foreign key to ``chat_sessions.id``.
        turn_index: Monotonic per-session sequence number.
        turn_kind: Semantic label: user, assistant, tool_results, internal_recovery, system_error.
        user_prompt: Plain text or JSON text payload depending on ``turn_kind``.
        text_blocks: Serialized assistant text blocks (may be empty list).
        tool_blocks: Serialized assistant tool_use blocks (may be empty list).
    """
    try:
        db.insert_turn(
            session_id,
            turn_index=turn_index,
            turn_kind=turn_kind,
            user_prompt=user_prompt,
            text_blocks=text_blocks,
            tool_blocks=tool_blocks,
        )
    except Exception:
        # Do not raise into SSE generator: persistence is best-effort.
        logger.exception("insert_turn failed session_id=%s kind=%s", session_id, turn_kind)


# ─── SSE wire format helper ─────────────────────────────────────────────────────


def _sse(data: dict) -> str:
    """
    Format one Server-Sent Event frame carrying a JSON object payload.

    Args:
        data: Serializable dict (event type discriminated by ``type`` key).

    Returns:
        UTF-8 string including ``data:`` prefix and double newline terminator.
    """
    # ensure_ascii=False preserves non-English characters in user-visible streams.
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ─── HTTP route handlers ────────────────────────────────────────────────────────


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """
    Accept one file via multipart/form-data and write it to ``WORKSPACE``.

    The multipart field name must be ``file`` (FastAPI ``File(...)`` default binding).

    Args:
        file: Starlette wrapper around the uploaded bytes stream and filename metadata.

    Returns:
        JSON dict with key ``filename`` echoing the stored basename.
    """
    # Ensure destination directory exists even on first upload after fresh clone.
    WORKSPACE.mkdir(exist_ok=True)
    # Trust client-provided filename as relative path segment (no path traversal checks here).
    dest = WORKSPACE / file.filename
    # Async read keeps large uploads from blocking other concurrent requests.
    content = await file.read()
    # Binary write preserves CSV encoding exactly as uploaded.
    dest.write_bytes(content)
    # Client uses this string later in POST /session ``csv_name`` and stream hints.
    return {"filename": file.filename}


class SessionRequest(BaseModel):
    """
    JSON body for POST /session: which CSV to analyze and which model to use for skill picking.

    Attributes:
        csv_name: Filename under ``workspace/`` (must match a prior upload).
        model: Anthropic model id string forwarded to the lightweight skill-selection call.
    """

    csv_name: str  # Required: ties session to a concrete on-disk artifact.
    model: str = MODEL_NAME  # Optional override; defaults to module-level MODEL_NAME.


@app.post("/session")
async def create_session(body: SessionRequest):
    """
    Create a new chat session: pick skills, load system prompt, register in RAM and DB.

    ``csv_name`` drives skill selection text (\"analisar …\") and first-stream workspace hint.

    Args:
        body: Validated request payload (csv_name + optional model).

    Returns:
        JSON with new ``session_id`` UUID and list of selected ``skills`` names.
    """
    # Build the skill catalog off the hot path of the event loop (disk + YAML parsing).
    catalog = await asyncio.to_thread(_build_skills_catalog)
    # Ask the small model which skill folders matter for this CSV name.
    skills = await asyncio.to_thread(
        _select_skills, f"Analyze the CSV file: {body.csv_name}", catalog, body.model
    )
    # Load full markdown for chosen skills only (can be large; keep in thread).
    system = await asyncio.to_thread(load_skills, skills) if skills else ""
    # Opaque id clients pass back on every subsequent /stream and /authorize call.
    session_id = str(uuid.uuid4())
    # Store mutable session state for the lifetime of this worker process.
    sessions[session_id] = Session(system=system, csv_name=body.csv_name.strip())
    # Best-effort durable row mirroring system prompt and csv binding.
    await _db_thread(
        lambda: _persist_chat_session(
            session_id, system, body.csv_name.strip(), body.model
        )
    )
    # Skills list is returned to UI for transparency / debugging.
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
    """
    SSE: run agent loop, emit events, pause on tool calls for auth.

    After each tool_call event the server waits for POST .../authorize unless
    AUTO_APPROVE_TOOLS is set (recommended for /docs / Swagger, which cannot
    approve mid-stream). If TOOL_AUTH_TIMEOUT_SEC is set, waiting ends with an
    error event instead of hanging indefinitely.

    Tool execution errors are returned to the model as tool_result with is_error and
    do not abort the stream. Optional env: MAX_AGENT_ITERATIONS (default 40),
    MAX_AGENT_TURN_RECOVERY (default 2) for failed agent_turn API calls.

    When DATABASE_URL is set, each distinct message in the model history is stored
    as a row in turns (user, assistant, tool_results, internal_recovery,
    system_error).

    Args:
        session_id: UUID previously returned by POST /session.
        message: Raw user text for this stream invocation (query parameter).

    Returns:
        StreamingResponse emitting = text/event-stream frames until done or fatal error.
    """
    # Resolve in-memory session or 404 if unknown/expired server restart.
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        """
        Async generator yielding SSE strings for one complete user message processing run.

        Mutates ``session.messages`` in lockstep with Anthropic's expected conversation shape:
        user → assistant [+ tools] → user tool_results → assistant … until end_turn.

        Yields:
            str: SSE-formatted frames from ``_sse``.

        Returns:
            Implicit None when generator completes (connection closes).
        """
        # Start from the literal query param; may be rewritten for first-turn workspace hint.
        user_text = message
        # Only the first message in a session gets the CSV path reminder (if csv_name set).
        if not session.messages and session.csv_name:
            # Prefix gives the model a concrete relative path without trusting user spelling.
            user_text = (
                "[Workspace: the CSV for this session is available at the relative path "
                f"`{session.csv_name}` inside the workspace (after a successful POST /upload-csv). "
                "Use the `view` tool or bash on that path to read and analyze it.]\n\n"
                + message
            )
        # Append the user turn to Anthropic history before any model call.
        session.messages.append({"role": "user", "content": user_text})
        # Allocate DB turn index and persist the exact user-visible/user-model payload.
        ui = _next_turn_index(session)
        await _db_thread(
            lambda: _persist_turn(
                session_id, ui, "user", user_prompt=user_text
            )
        )

        # Optional UI hint that skills were injected (system non-empty).
        if session.system:
            yield _sse({"type": "skills_selected"})

        # Read iteration cap once per stream (env may change between requests in theory).
        max_iterations = _max_agent_iterations()
        # Remaining synthetic recovery user messages after model HTTP failures.
        recovery_left = _max_agent_turn_recovery()
        # Counts model loop iterations including tool rounds.
        iteration = 0

        while True:
            # Count this pass through the loop as one logical iteration toward the cap.
            iteration += 1
            if iteration > max_iterations:
                # Hard stop: emit SSE error and persist terminal system_error row.
                err_msg = (
                    f"Stopped: exceeded MAX_AGENT_ITERATIONS ({max_iterations}). "
                    "Increase the limit or start a shorter task."
                )
                yield _sse({"type": "error", "message": err_msg})
                ei = _next_turn_index(session)
                await _db_thread(
                    lambda: _persist_turn(
                        session_id, ei, "system_error", user_prompt=err_msg
                    )
                )
                break

            # Primary remote call: may raise on network/auth/rate limit issues.
            try:
                text_blocks, tool_blocks = await asyncio.to_thread(
                    agent_turn,
                    messages=session.messages,
                    system=session.system,
                    model_name=MODEL_NAME,
                )
            except Exception as exc:
                if recovery_left <= 0:
                    # No budget left: surface raw error to client and stop streaming.
                    yield _sse({"type": "error", "message": str(exc)})
                    ei = _next_turn_index(session)
                    await _db_thread(
                        lambda: _persist_turn(
                            session_id, ei, "system_error", user_prompt=str(exc)
                        )
                    )
                    break
                # Consume one recovery attempt from the budget.
                recovery_left -= 1
                # Inform the human viewer that we are inserting a self-help user message.
                yield _sse({
                    "type": "text",
                    "content": (
                        "[Model call failed — asking for a recovery plan. "
                        f"Attempts remaining after this message: {recovery_left}]"
                    ),
                })
                # Long instruction string instructing the model to diagnose infra issues.
                recovery_content = (
                    "The previous assistant model request failed with this error:\n\n"
                    f"{type(exc).__name__}: {exc}\n\n"
                    "Explain briefly what likely went wrong and give a concrete "
                    "step-by-step plan to fix it (environment, API keys, model name, "
                    "network). If the user should retry with a simpler prompt, say so. "
                    "Do not assume tools will work until the issue is addressed."
                )
                # Synthetic user message becomes the next item in ``session.messages``.
                session.messages.append({
                    "role": "user",
                    "content": recovery_content,
                })
                ri = _next_turn_index(session)
                await _db_thread(
                    lambda: _persist_turn(
                        session_id,
                        ri,
                        "internal_recovery",
                        user_prompt=recovery_content,
                    )
                )
                continue

            # Stream assistant-visible text tokens as individual SSE events.
            for tb in text_blocks:
                yield _sse({"type": "text", "content": tb.text})

            # Rebuild the assistant message structure expected by Anthropic for history replay.
            response_content = [
                {"type": "text", "text": tb.text} for tb in text_blocks
            ] + [
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                for b in tool_blocks
            ]

            # Persist assistant model output (text + parallel tool requests) as one DB row.
            ai = _next_turn_index(session)
            tbs = db.serialize_text_blocks(text_blocks)
            tols = db.serialize_tool_blocks(tool_blocks)
            await _db_thread(
                lambda: _persist_turn(
                    session_id,
                    ai,
                    "assistant",
                    text_blocks=tbs,
                    tool_blocks=tols,
                )
            )

            if not tool_blocks:
                # Terminal assistant reply with no tools: append and finish stream.
                session.messages.append({"role": "assistant", "content": response_content})
                yield _sse({"type": "done"})
                break

            # Accumulate tool_result blocks in API order for the follow-up user message.
            tool_results: list[dict] = []
            # Each tool_use must be authorized and executed sequentially (simpler UX).
            for block in tool_blocks:
                # Expose pending tool to /authorize handler via shared session object.
                session.pending = {"id": block.id, "name": block.name, "input": block.input}
                # Reset event so wait() blocks until authorize sets it again.
                session.auth_event.clear()

                # Notify frontends to show approve/deny UI for this tool invocation.
                yield _sse({
                    "type": "tool_call",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

                if _env_truthy("AUTO_APPROVE_TOOLS"):
                    # Dev mode: skip human approval gate entirely.
                    session.auth_approved = True
                    session.auth_event.set()
                else:
                    # Optional timeout around waiting for external POST /authorize.
                    tmo = _tool_auth_timeout_sec()
                    try:
                        if tmo is None:
                            await session.auth_event.wait()
                        else:
                            await asyncio.wait_for(session.auth_event.wait(), timeout=tmo)
                    except asyncio.TimeoutError:
                        # Clear pending so future authorize calls get 400 No pending.
                        session.pending = None
                        err_msg = (
                            f"Timed out ({tmo}s) waiting for POST "
                            f"/session/{session_id}/authorize. "
                            "Swagger cannot send approve while this GET is open — use the "
                            "frontend, curl/EventSource in two terminals, set "
                            "AUTO_APPROVE_TOOLS=true in .env for local testing, or set "
                            "TOOL_AUTH_TIMEOUT_SEC to see this message after a limit."
                        )
                        yield _sse({"type": "error", "message": err_msg})
                        ti = _next_turn_index(session)
                        await _db_thread(
                            lambda: _persist_turn(
                                session_id, ti, "system_error", user_prompt=err_msg
                            )
                        )
                        return

                if session.auth_approved:
                    # Map Anthropic tool name string to local Python implementation.
                    handler = TOOL_HANDLERS.get(block.name)
                    if handler:
                        try:
                            # Tools may call Docker or filesystem; keep off event loop.
                            result = await asyncio.to_thread(handler, **block.input)
                        except Exception as exc:
                            # Capture full traceback text for model self-correction attempts.
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
                            # Normal tool stdout/stderr string payload.
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
                        # Unknown tool name: synthesize an error result for the model.
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
                    # User explicitly denied this tool call in POST /authorize.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Tool call denied by user.",
                    })
                    yield _sse({"type": "tool_denied", "id": block.id, "name": block.name})

            # End of tool round: clear pending sentinel before mutating history further.
            session.pending = None
            tri = _next_turn_index(session)
            tr_body = json.dumps(tool_results, ensure_ascii=False)
            await _db_thread(
                lambda: _persist_turn(
                    session_id,
                    tri,
                    "tool_results",
                    user_prompt=tr_body,
                )
            )
            # Append assistant message with tool_use blocks then user message with results.
            session.messages.append({"role": "assistant", "content": response_content})
            session.messages.append({"role": "user", "content": tool_results})

    # Starlette will iterate this async generator to bytes on the wire.
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",  # Disable intermediary caching of partial stream.
            "X-Accel-Buffering": "no",  # Hint nginx (if any) not to buffer SSE.
            "Connection": "keep-alive",  # Encourage HTTP keep-alive for long streams.
        },
    )


class AuthBody(BaseModel):
    """
    JSON body for POST /session/{id}/authorize.

    Attributes:
        approved: True to execute handler; False to inject denial tool_result text.
    """

    approved: bool  # Required boolean gate for the pending tool call.


@app.post("/session/{session_id}/authorize")
async def authorize(session_id: str, body: AuthBody):
    """
    Approve or deny the single pending tool call blocked inside GET /stream.

    Wakes ``session.auth_event`` so the generator can proceed after recording decision.

    Args:
        session_id: Same UUID path parameter used when opening the SSE stream.
        body: Parsed JSON containing the boolean approval flag.

    Returns:
        Small JSON confirmation ``{"ok": true}`` on success.

    Raises:
        HTTPException: 404 unknown session, or 400 when no tool is awaiting auth.
    """
    # Lookup live session object shared with the streaming coroutine.
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.pending is None:
        raise HTTPException(status_code=400, detail="No pending tool call")
    # Persist operator choice for the branch logic in the tool execution loop.
    session.auth_approved = body.approved
    # Unblock the waiter inside event_generator (may be immediate if auto-approved path).
    session.auth_event.set()
    return {"ok": True}


@app.get("/outputs")
async def list_outputs():
    """
    List downloadable artifact files discovered under ``OUTPUTS`` with allowed extensions.

    Returns:
        JSON object with ``files`` array of {filename, url} objects sorted by name.
    """
    # Ensure listing endpoint does not 500 when outputs directory absent on fresh deploy.
    OUTPUTS.mkdir(exist_ok=True)
    # Only expose common binary/text artifact types (not arbitrary server files).
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
            ".csv", ".xlsx", ".pdf", ".docx", ".txt", ".html"}
    # Build stable sorted list for deterministic UI rendering.
    files = [
        {"filename": p.name, "url": f"/outputs/{p.name}"}
        for p in sorted(OUTPUTS.iterdir())
        if p.is_file() and p.suffix.lower() in exts
    ]
    return {"files": files}


@app.get("/outputs/{filename}")
async def get_output(filename: str):
    """
    Serve a single file from ``OUTPUTS`` by basename (no directory traversal).

    Args:
        filename: Path segment under outputs/ (must match a real file name only).

    Returns:
        FileResponse streaming bytes with inferred media type.

    Raises:
        HTTPException: 404 if missing or not a plain file.
    """
    # Join trusted OUTPUTS root with user-supplied filename segment.
    path = OUTPUTS / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
