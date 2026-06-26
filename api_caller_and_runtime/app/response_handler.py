"""
Response handler for LLM outputs.

Handles all stop_reason variants and manages tool execution,
deciding when to continue or stop the agentic loop.
Works with normalised LLMResponse — no provider SDK imports.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    result: str


@dataclass
class LoopState:
    """Mutable state carried across iterations of the agentic loop."""
    output_messages: list[dict[str, Any]] = field(default_factory=list)
    total_tokens: int = field(default=0)
    stop_reason: str = field(default="")


# ---------------------------------------------------------------------------
# Response handler
# ---------------------------------------------------------------------------

class ResponseHandler:
    def __init__(self, tool_executor=None, verbose: bool = True):
        self._tool_executor = tool_executor
        self.verbose = verbose

    @property
    def tool_executor(self):
        if self._tool_executor is None:
            from tools import execute_tool
            self._tool_executor = execute_tool
        return self._tool_executor

    def _log(self, message: str):
        if self.verbose:
            print(message)

    def extract_text_from_content(self, content: list[dict[str, Any]]) -> str:
        """Pull all text blocks from a normalised content list."""
        parts = [
            block["text"]
            for block in content
            if block.get("type") == "text" and block.get("text")
        ]
        return "\n".join(parts).strip()

    async def _handle_success_cases(
        self,
        stop_reason: str,
        content: list[dict[str, Any]],
        state: LoopState,
        log,
    ) -> LoopState:
        """Handle end_turn and tool_use — the normal agentic loop path."""
        if stop_reason == "end_turn":
            state.stop_reason = "end_turn"
            log("stop_reason: end_turn")
            text = self.extract_text_from_content(content)
            state.output_messages.append({"type": "text", "content": text})
            log(f"text content generated: {text}")
            return state

        if stop_reason == "tool_use":
            state.stop_reason = "tool_use"
            log("stop_reason: tool_use")

            text = self.extract_text_from_content(content)
            if text:
                state.output_messages.append({"type": "text", "content": text})
                log(f"text content generated: {text}")

            for block in content:
                if block.get("type") != "tool_use":
                    continue
                tool_name = block["name"]
                tool_input = block["input"]
                tool_use_id = block["id"]

                log(f"executing tool: {tool_name}")
                result = self.tool_executor(tool_name, tool_input)

                state.output_messages.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "content": result,
                })
                log("tool executed successfully!")

            return state

    def _handle_other_cases(
        self,
        stop_reason: str,
        content: list[dict[str, Any]],
        state: LoopState,
        log,
    ) -> LoopState:
        """Handle max_tokens, content_filter, pause_turn, stop_sequence, and unknown."""
        text_content = self.extract_text_from_content(content)

        handler_map = {
            "max_tokens": "max_tokens — response may be incomplete",
            "content_filter": "content_filter — response blocked",
            "pause_turn": "pause_turn — server tools still running, continuing...",
            "stop_sequence": "stop_sequence triggered",
        }

        if stop_reason in handler_map:
            state.stop_reason = stop_reason
            if stop_reason == "pause_turn":
                text = self.extract_text_from_content(content)
                if text:
                    state.output_messages.append({"type": "text", "content": text})
            else:
                state.output_messages.append({"type": "text", "content": text_content})
            log(handler_map[stop_reason])
            return state

        state.stop_reason = stop_reason
        state.output_messages.append({"type": "text", "content": text_content})
        log(f"unknown stop_reason: {stop_reason!r} — stopping")
        return state

    async def process_response(
        self,
        response: "LLMResponse",
        state: Optional[LoopState] = None,
        verbose: Optional[bool] = None,
    ) -> LoopState:
        """
        Dispatch the response to the correct stop-reason handler.

        Parameters
        ----------
        response   Normalised LLMResponse from a provider's one_call().
        state      Mutable LoopState (messages history + counters).
                   Created fresh when omitted.
        verbose    Override the instance-level verbose flag for this call only.
        """
        _verbose = self.verbose if verbose is None else verbose

        def _log(msg: str):
            if _verbose:
                print(msg)

        if state is None:
            state = LoopState()

        state.total_tokens += response.tokens_used or 0

        _log(f"tokens: {state.total_tokens} | stop_reason: {response.stop_reason}")

        if response.stop_reason in ("end_turn", "tool_use"):
            return await self._handle_success_cases(
                response.stop_reason, response.content, state, _log,
            )

        return self._handle_other_cases(
            response.stop_reason, response.content, state, _log,
        )
