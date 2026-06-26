"""
Multi-provider LLM abstraction layer.

Each provider normalises its native response into a common LLMResponse so
that ResponseHandler and Orchestrator never import provider SDKs directly.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------- Canonical stop reasons ----------

STOP_REASONS = frozenset({
    "end_turn",
    "tool_use",
    "max_tokens",
    "content_filter",
    "stop_sequence",
    "pause_turn",
})

# ---------- Domain types ----------


@dataclass
class LLMResponse:
    """Provider-agnostic response returned by every provider's ``one_call``."""

    content: list[dict[str, Any]]
    stop_reason: str
    provider_used: str
    model: str
    tokens_used: int | None
    latency_ms: int


class LLMError(Exception):
    """Raised when an LLM call fails for any reason."""


# ---------- Utility ----------


def extract_text_response(content: list[dict[str, Any]]) -> str:
    """Pull all text from a normalised content block list."""
    parts = [
        block["text"]
        for block in content
        if block.get("type") == "text" and block.get("text")
    ]
    return "\n".join(parts).strip()


# ---------- Providers ----------

_ANTHROPIC_STOP_MAP: dict[str, str] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop_sequence",
    "pause_turn": "pause_turn",
}

_OPENAI_STOP_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


class AnthropicLLMProvider:
    """Wraps the Anthropic async client (Messages API)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key, timeout=30.0)
        self.name = "anthropic"
        self.model = model

    async def one_call(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        thinking_budget: int | None = None,
    ) -> LLMResponse:
        from anthropic import APIError

        resolved_model = model or self.model
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                for t in tools
            ]
        if system_prompt:
            kwargs["system"] = system_prompt
        if thinking_budget:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            kwargs["temperature"] = 1.0
        else:
            kwargs["temperature"] = temperature

        start = time.monotonic()
        try:
            resp = await self.client.messages.create(**kwargs)
        except APIError as exc:
            raise LLMError(f"Anthropic error: {exc}") from exc

        elapsed = int((time.monotonic() - start) * 1000)

        content: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "thinking":
                continue
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        stop_reason = _ANTHROPIC_STOP_MAP.get(resp.stop_reason, resp.stop_reason)
        tokens = resp.usage.input_tokens + resp.usage.output_tokens

        logger.debug(
            "anthropic one_call model=%s tokens=%d latency_ms=%d stop=%s",
            resolved_model, tokens, elapsed, stop_reason,
        )

        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            provider_used=self.name,
            model=resolved_model,
            tokens_used=tokens,
            latency_ms=elapsed,
        )

    def format_tool_turn(
        self,
        response: LLMResponse,
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the assistant + user messages to append after tool execution."""
        return [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["tool_use_id"],
                        "content": r["content"],
                    }
                    for r in tool_results
                ],
            },
        ]


class OpenAILLMProvider:
    """Wraps the OpenAI async client (Chat Completions API)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, timeout=30.0)
        self.name = "openai"
        self.model = model

    async def one_call(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        thinking_budget: int | None = None,
    ) -> LLMResponse:
        from openai import APIError

        resolved_model = model or self.model

        request_messages: list[dict[str, Any]] = []
        if system_prompt:
            request_messages.append({"role": "system", "content": system_prompt})
        request_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": request_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

        start = time.monotonic()
        try:
            resp = await self.client.chat.completions.create(**kwargs)
        except APIError as exc:
            raise LLMError(f"OpenAI error: {exc}") from exc

        elapsed = int((time.monotonic() - start) * 1000)
        choice = resp.choices[0]

        content: list[dict[str, Any]] = []
        if choice.message.content:
            content.append({"type": "text", "text": choice.message.content})
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments),
                })

        stop_reason = _OPENAI_STOP_MAP.get(choice.finish_reason, choice.finish_reason)
        tokens = resp.usage.total_tokens if resp.usage else None

        logger.debug(
            "openai one_call model=%s tokens=%s latency_ms=%d stop=%s",
            resolved_model, tokens, elapsed, stop_reason,
        )

        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            provider_used=self.name,
            model=resolved_model,
            tokens_used=tokens,
            latency_ms=elapsed,
        )

    def format_tool_turn(
        self,
        response: LLMResponse,
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the assistant + tool messages to append after tool execution."""
        tool_calls = [
            {
                "id": block["id"],
                "type": "function",
                "function": {
                    "name": block["name"],
                    "arguments": json.dumps(block["input"]),
                },
            }
            for block in response.content
            if block["type"] == "tool_use"
        ]
        text = "\n".join(
            b["text"] for b in response.content if b["type"] == "text"
        ) or None

        messages: list[dict[str, Any]] = [
            {"role": "assistant", "content": text, "tool_calls": tool_calls},
        ]
        for r in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": r["tool_use_id"],
                "content": r["content"],
            })
        return messages


class FallbackLLMProvider:
    """Tries the primary provider; on LLMError transparently retries with the fallback."""

    def __init__(self, primary: "LLMProviderType", fallback: "LLMProviderType"):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.model = primary.model
        self._active = primary

    async def one_call(self, **kwargs: Any) -> LLMResponse:
        try:
            result = await self.primary.one_call(**kwargs)
            self._active = self.primary
            return result
        except LLMError as exc:
            logger.warning(
                "primary LLM failed (%s), falling back to %s: %s",
                self.primary.name, self.fallback.name, exc,
            )
            self.name = self.fallback.name
            self.model = self.fallback.model
            self._active = self.fallback
            return await self.fallback.one_call(**kwargs)

    def format_tool_turn(
        self,
        response: LLMResponse,
        tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return self._active.format_tool_turn(response, tool_results)


LLMProviderType = AnthropicLLMProvider | OpenAILLMProvider | FallbackLLMProvider

# ---------- Factory ----------


def get_llm_provider(
    model: str,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
) -> LLMProviderType:
    """Instantiate the correct provider based on the model name."""
    if model.startswith("gpt") and openai_key:
        return OpenAILLMProvider(api_key=openai_key, model=model)
    if model.startswith("claude") and anthropic_key:
        return AnthropicLLMProvider(api_key=anthropic_key, model=model)
    raise ValueError(f"Unsupported model or missing API key: {model}")
