"""
Orchestrator — reusable conversation coordinator for agents.

Responsibility:
    Coordinate LLM provider (one_call) and ResponseHandler (tool execution),
    keeping conversation history per session and optionally persisting the
    full conversation via a pluggable PersistenceBackend.

Flow:
    1. Consumer sends the first prompt -> a session_id is created/returned.
    2. Provider.one_call takes the prompt to the LLM and produces an LLMResponse.
    3. ResponseHandler reads that output and either runs tools (loop continues)
       or returns the final output (loop stops).
    4. Orchestrator hands the output back to the consumer; the conversation
       continues with the next prompt on the same session_id.
    5. When the run finishes, the PersistenceBackend (if any) saves the
       conversation.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

from llm import LLMProviderType, LLMResponse
from persistence import PersistenceBackend
from response_handler import ResponseHandler, LoopState
from tools import is_loop_terminator, is_tool_failure, get_max_retries


@dataclass
class ChatSession:
    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0


@dataclass
class RunResult:
    run_id: str
    session_id: str
    output_messages: list[dict[str, Any]]
    stop_reason: str
    total_tokens: int
    final_answer: str = ""


class Orchestrator:
    def __init__(
        self,
        *,
        provider: LLMProviderType,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        thinking_budget: int | None = None,
        max_iterations: int = 10,
        agent_name: str = "orchestrator",
        persistence: PersistenceBackend | None = None,
        verbose: bool = True,
    ):
        self.provider = provider
        self.model = model or provider.model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.tools = tools
        self.thinking_budget = thinking_budget
        self.max_iterations = max_iterations
        self.agent_name = agent_name
        self.persistence = persistence
        self.verbose = verbose

        self._handler = ResponseHandler(verbose=verbose)
        self._sessions: dict[str, ChatSession] = {}

    def _log(self, message: str):
        if self.verbose:
            print(message)

    # ------------------------------------------------------------------ #
    # Session management
    # ------------------------------------------------------------------ #
    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = ChatSession(session_id=session_id)
        self._log(f"New session: {session_id}")
        return session_id

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        return list(self._sessions[session_id].messages)

    # ------------------------------------------------------------------ #
    # Prompt helpers
    # ------------------------------------------------------------------ #
    def _normalize_user_message(self, user_message: Union[str, list[Any]]) -> dict[str, Any]:
        if isinstance(user_message, str):
            return {"role": "user", "content": user_message}
        if isinstance(user_message, list):
            if all(isinstance(item, str) for item in user_message):
                return {"role": "user", "content": "\n".join(user_message)}
            return {"role": "user", "content": user_message}
        return {"role": "user", "content": str(user_message)}

    def _extract_final_answer(self, state: LoopState) -> str:
        """Return the terminator tool content or the last text block."""
        terminator = next(
            (b for b in reversed(state.output_messages)
             if b.get("type") == "tool_result" and is_loop_terminator(b.get("tool_name", ""))),
            None,
        )
        if terminator:
            return terminator.get("content", "")

        for msg in reversed(state.output_messages):
            if msg.get("type") == "text" and msg.get("content"):
                return msg["content"]
        return ""

    # ------------------------------------------------------------------ #
    # Retry logic (declarative, driven by TOOLS registry)
    # ------------------------------------------------------------------ #
    def _check_retries(
        self,
        state: LoopState,
        current_tool_ids: set[str],
        retry_counts: dict[str, int],
    ) -> str | None:
        """Check all retryable tools for failures. Returns stop reason or None."""
        for block in state.output_messages:
            if block.get("type") != "tool_result":
                continue
            if block.get("tool_use_id") not in current_tool_ids:
                continue

            tool_name = block.get("tool_name", "")
            output = block.get("content", "")
            max_ret = get_max_retries(tool_name)

            if max_ret is not None and is_tool_failure(tool_name, output):
                retry_counts[tool_name] = retry_counts.get(tool_name, 0) + 1
                self._log(
                    f"{tool_name} failed (attempt {retry_counts[tool_name]}/{max_ret})"
                )
                if retry_counts[tool_name] > max_ret:
                    self._log(f"max retries ({max_ret}) exceeded for {tool_name} — stopping")
                    return "max_tool_retries"
        return None

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    async def run(
        self,
        user_message: Union[str, list[Any]],
        session_id: str | None = None,
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        thinking_budget: int | None = None,
        max_iterations: int | None = None,
    ) -> RunResult:
        run_id = run_id or str(uuid.uuid4())

        if session_id is None:
            session_id = self.create_session()
        elif session_id not in self._sessions:
            self._sessions[session_id] = ChatSession(session_id=session_id)
            self._log(f"[session={session_id}] new session")

        session = self._sessions[session_id]

        messages: list[dict[str, Any]] = list(session.messages)
        messages.append(self._normalize_user_message(user_message))

        state = LoopState()
        final_answer: str | None = None

        call_kwargs: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "system_prompt": system_prompt or self.system_prompt,
            "tools": tools or self.tools,
            "thinking_budget": thinking_budget or self.thinking_budget,
        }
        limit = max_iterations if max_iterations is not None else self.max_iterations
        retry_counts: dict[str, int] = {}

        # -- Turn 0: first API call --
        self._log(f"[run={run_id}] turn 0 — first call...")
        llm_response = await self.provider.one_call(messages=messages, **call_kwargs)
        state = await self._handler.process_response(llm_response, state)
        self._log(f"[run={run_id}] turn 0 — stop_reason: {llm_response.stop_reason}")

        # -- Agentic loop --
        for iteration in range(1, limit + 1):
            if llm_response.stop_reason != "tool_use":
                self._log(
                    f"[run={run_id}] turn {iteration} — "
                    f"stop_reason={llm_response.stop_reason!r}, ending loop"
                )
                break

            # Check for loop-terminating tools
            terminator = next(
                (b for b in state.output_messages
                 if b.get("type") == "tool_result"
                 and is_loop_terminator(b.get("tool_name", ""))),
                None,
            )
            if terminator:
                final_answer = terminator.get("content", "")
                self._log(f"[run={run_id}] turn {iteration} — loop terminator called, ending loop")
                break

            # Collect current turn's tool IDs and results
            current_tool_ids = {
                block["id"]
                for block in llm_response.content
                if block.get("type") == "tool_use"
            }

            # Check declarative retry limits
            retry_stop = self._check_retries(state, current_tool_ids, retry_counts)
            if retry_stop:
                state.stop_reason = retry_stop
                break

            # Build tool results for the next call
            tool_results = [
                b for b in state.output_messages
                if b.get("type") == "tool_result"
                and b.get("tool_use_id") in current_tool_ids
                and not is_loop_terminator(b.get("tool_name", ""))
            ]

            turn_messages = self.provider.format_tool_turn(llm_response, tool_results)
            messages.extend(turn_messages)

            self._log(f"[run={run_id}] turn {iteration} — calling API...")
            llm_response = await self.provider.one_call(messages=messages, **call_kwargs)
            state = await self._handler.process_response(llm_response, state)
            self._log(f"[run={run_id}] turn {iteration} — stop_reason: {llm_response.stop_reason}")
        else:
            state.stop_reason = "max_iterations"
            self._log(f"[run={run_id}] max_iterations ({limit}) reached")

        # -- Persist session history --
        session.messages = messages
        session.total_tokens += state.total_tokens

        if final_answer is None:
            final_answer = self._extract_final_answer(state)

        if self.persistence is not None:
            self.persistence.save(
                session=session,
                user_prompt=self._normalize_user_message(user_message),
                final_answer=final_answer,
                state=state,
                task_id=task_id or session_id,
                agent_name=self.agent_name,
            )

        return RunResult(
            run_id=run_id,
            session_id=session_id,
            output_messages=state.output_messages,
            stop_reason=state.stop_reason,
            total_tokens=state.total_tokens,
            final_answer=final_answer,
        )
