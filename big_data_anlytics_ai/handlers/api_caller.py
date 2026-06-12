#!/usr/bin/env python3
"""
Generic API caller and agentic loop for Claude API interactions.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
import anthropic

from agents.tools import execute_tool

load_dotenv()


@dataclass
class AgentResult:
    """Result from running the agent loop."""
    success: bool
    final_response: str
    stop_reason: str
    iterations: int
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def extract_text_response(response: anthropic.types.Message) -> str:
    try:
        text_parts = []
        if not response.content:
            return ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "thinking":
                continue
            if hasattr(block, "text") and block.text:
                text_parts.append(block.text)
        return "\n".join(text_parts).strip()
    except Exception as e:
        print(f"Warning: Failed to extract text from response: {e}")
        return ""


class ApiCaller:
    def __init__(
        self,
        api_key: Optional[str] = None,
        verbose: bool = True,
    ):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.verbose = verbose

    def _log(self, message: str):
        if self.verbose:
            print(message)

    async def one_call(
        self,
        prompt: Optional[Any] = None,
        *,
        messages: Optional[List[Dict[str, Any]]] = None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking_budget: Optional[int] = None,
    ) -> dict:
        if messages is not None:
            resolved_messages = messages
        elif prompt is not None:
            resolved_messages = [{"role": "user", "content": prompt}]
        else:
            raise ValueError("Either 'prompt' or 'messages' must be provided.")

        self._log(f"\nMessages: {resolved_messages}")

        request_params = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": resolved_messages,
        }
        if tools:
            request_params["tools"] = tools
        if system_prompt:
            request_params["system"] = system_prompt
        if thinking_budget:
            request_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
            request_params["temperature"] = 1.0
        else:
            request_params["temperature"] = temperature

        try:
            response = await self.client.messages.create(**request_params)
            self._log(f"\nResponse was generated successfully")
            return response
        except anthropic.RateLimitError as e:
            self._log(f"❌ Rate limit exceeded (429): {e}")
            raise
        except anthropic.AuthenticationError as e:
            self._log(f"❌ Authentication error (401): {e}")
            raise
        except anthropic.BadRequestError as e:
            self._log(f"❌ Bad request (400): {e}")
            raise
        except anthropic.APIConnectionError as e:
            self._log(f"❌ Connection error: {e}")
            raise
        except anthropic.APIStatusError as e:
            self._log(f"❌ API status error ({e.status_code}): {e}")
            raise
        except Exception as e:
            self._log(f"❌ Unexpected error: {e}")
            raise