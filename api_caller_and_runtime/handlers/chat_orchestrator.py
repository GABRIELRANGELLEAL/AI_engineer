"""
Orchestrator — reusable conversation coordinator for agents.

Responsibility:
    Coordinate ApiCaller (LLM call) and ResponseHandler (tool execution / output),
    keeping the conversation history per session and persisting the full
    conversation to the database at the end of a run.

Flow:
    1. Consumer sends the first prompt -> a session_id is created/returned.
    2. ApiCaller takes the prompt to the LLM and produces an output.
    3. ResponseHandler reads that output and either runs tools (loop continues)
       or returns the final output (loop stops).
    4. Orchestrator hands the output back to the consumer; the conversation
       continues with the next prompt on the same session_id.
    5. When the run finishes, the Orchestrator persists the whole conversation
       to the database.
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from handlers.api_caller import ApiCaller
from handlers.response_handler import ResponseHandler, model_response

# Matches the failure prefix produced by handle_execute_code:
#   "[exit code N | lang]"  or  "Execution timed out after Ns."
_CODE_FAILURE_RE = re.compile(r"^\[exit code \d+")


def _is_code_failure(output: str) -> bool:
    """Return True when execute_code ran but exited with an error or timed out."""
    return bool(_CODE_FAILURE_RE.match(output)) or output.startswith("Execution timed out")


@dataclass
class ChatSession:
    session_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0


@dataclass
class RunResult:
    run_id: str
    session_id: str
    output_messages: List[Dict[str, Any]]
    stop_reason: str
    total_input_tokens: int
    total_output_tokens: int
    final_answer: str = ""


class Orchestrator:
    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking_budget: Optional[int] = None,
        max_iterations: int = 10,
        max_code_retries: int = 3,
        agent_name: str = "orchestrator",
        persist: bool = True,
        db_session_factory: Optional[Any] = None,
        verbose: bool = True,
        api_key: Optional[str] = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.tools = tools
        self.thinking_budget = thinking_budget
        self.max_iterations = max_iterations
        self.max_code_retries = max_code_retries
        self.agent_name = agent_name
        self.persist = persist
        self.verbose = verbose

        self._caller = ApiCaller(api_key=api_key, verbose=verbose)
        self._handler = ResponseHandler(verbose=verbose)
        self._sessions: Dict[str, ChatSession] = {}
        self._session_factory = db_session_factory

    def _log(self, message: str):
        if self.verbose:
            print(message)

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #
    def create_session(self) -> str:
        """Open a new conversation and return its session_id to the consumer."""
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = ChatSession(session_id=session_id)
        self._log(f"New session: {session_id}")
        return session_id

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        return list(self._sessions[session_id].messages)

    # ------------------------------------------------------------------ #
    # Prompt helpers
    # ------------------------------------------------------------------ #
    def _normalize_user_message(self, user_message: Union[str, List[Any]]) -> Dict[str, Any]:
        if isinstance(user_message, str):
            return {"role": "user", "content": user_message}
        if isinstance(user_message, list):
            if all(isinstance(item, str) for item in user_message):
                return {"role": "user", "content": "\n".join(user_message)}
            return {"role": "user", "content": user_message}
        return {"role": "user", "content": str(user_message)}

    def _extract_final_answer(self, state: model_response) -> str:
        """Return the last text block from state, or the finish_loop content if present."""
        finish_block = next(
            (b for b in reversed(state.output_messages)
             if b.get("type") == "tool_result" and b.get("tool_name") == "finish_loop"),
            None,
        )
        if finish_block:
            return finish_block.get("content", "")

        for msg in reversed(state.output_messages):
            if msg.get("type") == "text" and msg.get("content"):
                return msg["content"]
        return ""

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    async def run(
        self,
        user_message: Union[str, List[Any]],
        session_id: Optional[str] = None,
        *,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking_budget: Optional[int] = None,
        max_iterations: Optional[int] = None,
        max_code_retries: Optional[int] = None,
        persist: Optional[bool] = None,
    ) -> RunResult:
        """
        Drive one consumer turn: prompt -> ApiCaller -> ResponseHandler -> output.

        Each call generates a unique run_id that identifies the full exchange
        (all turns triggered by a single user prompt).  A session_id is created
        automatically on the first call and groups multiple runs together.
        The whole conversation is persisted to the database when the run finishes.
        """
        run_id = run_id or str(uuid.uuid4())

        if session_id is None:
            session_id = self.create_session()
        elif session_id not in self._sessions:
            self._sessions[session_id] = ChatSession(session_id=session_id)
            self._log(f"[session={session_id}] new session")

        session = self._sessions[session_id]

        # Working messages list: carry session history, then add this user turn
        messages: List[Dict[str, Any]] = list(session.messages)
        messages.append(self._normalize_user_message(user_message))

        state = model_response()
        final_answer: Optional[str] = None

        call_kwargs = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "system_prompt": system_prompt or self.system_prompt,
            "tools": tools or self.tools,
            "thinking_budget": thinking_budget or self.thinking_budget,
        }
        limit = max_iterations if max_iterations is not None else self.max_iterations
        retry_limit = max_code_retries if max_code_retries is not None else self.max_code_retries
        code_retry_count = 0

        # ── Turn 0: first API call ──────────────────────────────────────
        self._log(f"[run={run_id}] turn 0 — first call...")
        response = await self._caller.one_call(messages=messages, **call_kwargs)
        state = await self._handler.process_response(response, state)
        self._log(f"[run={run_id}] turn 0 — stop_reason: {response.stop_reason}")

        # ── Agentic loop ────────────────────────────────────────────────
        for iteration in range(1, limit + 1):
            if response.stop_reason != "tool_use":
                self._log(
                    f"[run={run_id}] turn {iteration} — "
                    f"stop_reason={response.stop_reason!r}, ending loop"
                )
                break

            # Detect finish_loop in the results produced this turn
            finish_block = next(
                (b for b in state.output_messages
                 if b.get("type") == "tool_result" and b.get("tool_name") == "finish_loop"),
                None,
            )
            if finish_block:
                final_answer = finish_block.get("content", "")
                self._log(f"[run={run_id}] turn {iteration} — finish_loop called, ending loop")
                break

            # IDs of tool calls requested in *this* turn only
            current_tool_ids = {b.id for b in response.content if b.type == "tool_use"}

            # ── Code-execution retry guard ──────────────────────────────
            failed_executions = [
                b for b in state.output_messages
                if b.get("type") == "tool_result"
                and b.get("tool_name") == "execute_code"
                and b.get("tool_use_id") in current_tool_ids
                and _is_code_failure(b.get("content", ""))
            ]
            if failed_executions:
                code_retry_count += 1
                self._log(
                    f"[run={run_id}] execute_code failed "
                    f"(attempt {code_retry_count}/{retry_limit})"
                )
                if code_retry_count > retry_limit:
                    state.stop_reason = "max_code_retries"
                    self._log(
                        f"[run={run_id}] max_code_retries ({retry_limit}) exceeded — stopping"
                    )
                    break
            # ────────────────────────────────────────────────────────────

            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": b["type"],
                        "tool_use_id": b["tool_use_id"],
                        "content": b["content"],
                    }
                    for b in state.output_messages
                    if b.get("type") == "tool_result"
                    and b.get("tool_name") != "finish_loop"
                    and b.get("tool_use_id") in current_tool_ids
                ],
            })

            self._log(f"[run={run_id}] turn {iteration} — calling API...")
            response = await self._caller.one_call(messages=messages, **call_kwargs)
            state = await self._handler.process_response(response, state)
            self._log(f"[run={run_id}] turn {iteration} — stop_reason: {response.stop_reason}")
        else:
            state.stop_reason = "max_iterations"
            self._log(f"[run={run_id}] max_iterations ({limit}) reached")

        # ── Persist session history (serialise SDK objects → dicts) ─────
        serialised_content = response.model_dump().get("content", [])
        session.messages = messages
        session.messages.append({"role": "assistant", "content": serialised_content})
        session.total_input_tokens += state.total_input_tokens
        session.total_output_tokens += state.total_output_tokens

        if final_answer is None:
            final_answer = self._extract_final_answer(state)

        should_persist = self.persist if persist is None else persist
        if should_persist:
            self._persist_conversation(
                session=session,
                user_prompt=self._normalize_user_message(user_message),
                final_answer=final_answer,
                state=state,
                task_id=task_id or session_id,
            )

        return RunResult(
            run_id=run_id,
            session_id=session_id,
            output_messages=state.output_messages,
            stop_reason=state.stop_reason,
            total_input_tokens=state.total_input_tokens,
            total_output_tokens=state.total_output_tokens,
            final_answer=final_answer,
        )

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _get_session_factory(self):
        """Lazily build a SQLAlchemy session factory from DATABASE_URL."""
        if self._session_factory is not None:
            return self._session_factory

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            self._log("⚠️  DATABASE_URL not set — skipping conversation persistence")
            return None

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(database_url, echo=False)
        self._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return self._session_factory

    def _persist_conversation(
        self,
        *,
        session: ChatSession,
        user_prompt: Dict[str, Any],
        final_answer: str,
        state: model_response,
        task_id: str,
    ) -> None:
        """Write the whole conversation to the llm_interactions table."""
        factory = self._get_session_factory()
        if factory is None:
            return

        try:
            from models import LlmInteraction
        except Exception as exc:
            self._log(f"⚠️  Could not import LlmInteraction — skipping persistence: {exc}")
            return

        prompt_content = user_prompt.get("content", "")
        prompt_text = (
            prompt_content
            if isinstance(prompt_content, str)
            else json.dumps(prompt_content, ensure_ascii=False)
        )
        model_answer = final_answer or json.dumps(
            state.output_messages, ensure_ascii=False
        )

        db = factory()
        try:
            interaction = LlmInteraction(
                id=str(uuid.uuid4()),
                task_id=task_id,
                agent=self.agent_name,
                prompt=prompt_text,
                model_answer=model_answer,
                input_tokens=state.total_input_tokens,
                output_tokens=state.total_output_tokens,
                raw_response=session.messages,
                created_at=datetime.utcnow(),
            )
            db.add(interaction)
            db.commit()
            self._log(f"Conversation persisted (session={session.session_id})")
        except Exception as exc:
            db.rollback()
            self._log(f"⚠️  Failed to persist conversation: {exc}")
        finally:
            db.close()
