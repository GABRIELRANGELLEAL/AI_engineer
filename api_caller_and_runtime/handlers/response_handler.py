"""
Response handler for Claude API outputs.

Handles all stop_reason variants and manages the tool execution loop,
deciding when to continue or stop the agentic loop.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import anthropic


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    tool_use_id: str
    tool_name: str
    tool_input: Dict[str, Any]
    result: str


@dataclass
class model_response:
    """Mutable state carried across iterations of the agentic loop."""
    output_messages: List[Dict[str, Any]] = field(default_factory=list)
    total_input_tokens: int = field(default=0)
    total_output_tokens: int = field(default=0)
    stop_reason: str = field(default="")

# output_messages: flat list of blocks — {"type": "text"} or {"type": "tool_result", "tool_use_id": ..., "tool_name": ..., "content": ...}
# ---------------------------------------------------------------------------
# Response handler
# ---------------------------------------------------------------------------

class ResponseHandler:
    def __init__(self, tool_executor=None, verbose: bool = True):
        self._tool_executor = tool_executor
        self.verbose = verbose

    @property
    def tool_executor(self):
        """Lazy fallback: usa agents.tools.execute_tool se nenhum executor foi injetado."""
        if self._tool_executor is None:
            from handlers.tools import execute_tool
            self._tool_executor = execute_tool
        return self._tool_executor

    def _log(self, message: str):
        if self.verbose:
            print(message)

    def extract_text_from_content(self, content: List[Dict[str, Any]]) -> str:
        """Pull all text blocks from a dumped response content list."""
        parts = [
            block["text"]
            for block in content
            if block.get("type") == "text" and block.get("text")
        ]
        return "\n".join(parts).strip()

    async def _handle_success_cases(
        self,
        stop_reason: str,
        data: Dict[str, Any],
        state: "model_response",
        log,
    ) -> "model_response":
        """Handle end_turn and tool_use — the normal agentic loop path."""
        content = data.get("content", [])

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
        data: Dict[str, Any],
        state: "model_response",
        log,
    ) -> "model_response":
        """Handle max_tokens, content_filter, pause_turn, stop_sequence, and unknown."""
        content = data.get("content", [])
        text_content = self.extract_text_from_content(content)

        if stop_reason == "max_tokens":
            state.stop_reason = "max_tokens"
            state.output_messages.append({"type": "text", "content": text_content})
            log("⚠️  max_tokens — response may be incomplete")
            return state

        if stop_reason == "content_filter":
            state.stop_reason = "content_filter"
            state.output_messages.append({"type": "text", "content": text_content})
            log("🚫 content_filter — response blocked")
            return state

        if stop_reason == "pause_turn":
            state.stop_reason = "pause_turn"
            text = self.extract_text_from_content(content)
            if text:
                state.output_messages.append({"type": "text", "content": text})
            log("⏸️  pause_turn — server tools still running, continuing...")
            return state

        if stop_reason == "stop_sequence":
            state.stop_reason = "stop_sequence"
            state.output_messages.append({"type": "text", "content": text_content})
            log("🛑 stop_sequence triggered")
            return state

        state.stop_reason = stop_reason
        state.output_messages.append({"type": "text", "content": text_content})
        log(f"❓ unknown stop_reason: {stop_reason!r} — stopping")
        return state

    async def process_response(
        self,
        response: anthropic.types.Message,
        state: Optional["model_response"] = None,
        verbose: Optional[bool] = None,
    ) -> "model_response":
        """
        Dispatch the response to the correct stop-reason handler.

        Parameters
        ----------
        response   SDK Message returned by client.messages.create()
        state      Mutable model_response (messages history + counters).
                   Created fresh when omitted.
        verbose    Override the instance-level verbose flag for this call only.
                   Pass False to silence all logs for a single call without
                   changing the handler's default setting.

        Returns
        -------
        state : model_response
            Updated state (messages, tokens, tool history, final_text, etc.)
        """
        _verbose = self.verbose if verbose is None else verbose

        def _log(msg: str):
            if _verbose:
                print(msg)

        if state is None:
            state = model_response()
        response_dict = response.model_dump()
        usage = response_dict.get("usage", {})

        state.total_input_tokens += usage.get("input_tokens", 0)
        state.total_output_tokens += usage.get("output_tokens", 0)

        stop_reason = response_dict.get("stop_reason", "")

        _log(f"tokens in/out: {usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}")

        if stop_reason in ("end_turn", "tool_use"):
            return await self._handle_success_cases(stop_reason, response_dict, state, _log)

        return self._handle_other_cases(stop_reason, response_dict, state, _log)
