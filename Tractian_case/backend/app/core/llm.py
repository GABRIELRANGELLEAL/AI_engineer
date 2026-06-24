import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------- Domain types ----------

@dataclass
class LLMResponse:
    """Structured response returned by the RAG pipeline.

    Carries the clean answer, cited chunk indices, and metadata
    (provider, model, tokens, latency) so the API layer can build
    the response payload without knowing any LLM internals.
    """
    answer: str
    referenced_chunk_indices: list[int]  # Zero-based indices into the chunks list
    provider_used: str                   # "openai" | "anthropic"
    model: str                           # e.g. "gpt-4o-mini", "claude-sonnet-4-6"
    tokens_used: int | None              # Total tokens (input + output), None if unavailable
    latency_ms: int                      # Wall-clock time of the LLM call


class LLMError(Exception):
    """Raised when an LLM call fails for any reason (auth, rate-limit, server)."""


# ---------- Providers ----------

class OpenAILLMProvider:
    """Wraps the OpenAI async client (ChatCompletion API)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.name = "openai"
        self.model = model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1000,
    ) -> tuple[str, int | None]:
        from openai import APIError
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return resp.choices[0].message.content, resp.usage.total_tokens
        except APIError as e:
            raise LLMError(f"OpenAI error: {e}") from e


class AnthropicLLMProvider:
    """Wraps the Anthropic async client (Messages API)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(api_key=api_key)
        self.name = "anthropic"
        self.model = model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1000,
    ) -> tuple[str, int | None]:
        from anthropic import APIError
        try:
            resp = await self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            tokens = resp.usage.input_tokens + resp.usage.output_tokens
            return resp.content[0].text, tokens
        except APIError as e:
            raise LLMError(f"Anthropic error: {e}") from e


class FallbackLLMProvider:
    """Tries the primary provider; on LLMError transparently retries with the fallback."""

    def __init__(self, primary: "LLMProviderType", fallback: "LLMProviderType"):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.model = primary.model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1000,
    ) -> tuple[str, int | None]:
        try:
            return await self.primary.generate(system_prompt, user_prompt, max_tokens)
        except LLMError as e:
            logger.warning(
                "primary LLM failed (%s), falling back to %s: %s",
                self.primary.name, self.fallback.name, e,
            )
            self.name = self.fallback.name
            self.model = self.fallback.model
            return await self.fallback.generate(system_prompt, user_prompt, max_tokens)


# Type alias for any LLM provider
LLMProviderType = OpenAILLMProvider | AnthropicLLMProvider | FallbackLLMProvider


# ---------- Factory ----------

def get_llm_provider(
    model: str,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
) -> LLMProviderType:
    """Instantiate the correct provider based on the model name.

    The model name already implies the provider — no need for a
    separate 'provider' parameter.  Called from dependencies.py
    with values extracted from the request headers.
    """
    if model.startswith("gpt") and openai_key:
        return OpenAILLMProvider(api_key=openai_key, model=model)
    if model.startswith("claude") and anthropic_key:
        return AnthropicLLMProvider(api_key=anthropic_key, model=model)
    raise ValueError(f"Unsupported model or missing API key: {model}")


# ---------- Prompt construction and parsing ----------

SYSTEM_PROMPT = """
You are an assistant that answers questions based exclusively on the document excerpts provided.

Rules:
- Answer ONLY with information present in the provided excerpts
- At the end of your response, list the numbers of the excerpts you used in the format: [USED: 1, 3, 5]
- If the information is not in the excerpts, explicitly state that you did not find sufficient information in the available documents
- Be direct and precise
- Respond in the same language as the question
"""


def build_user_prompt(question: str, chunks: list) -> str:
    """Format numbered document excerpts + question into the user prompt.

    Each excerpt is labelled with source filename and page number
    so the LLM can trace answers back to the original PDF.
    """
    parts = ["Excerpts:\n"]
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] (source: {c.filename}, page {c.page_number})\n{c.text}\n")
    parts.append(f"\nQuestion: {question}")
    return "\n".join(parts)


def parse_references(answer: str) -> tuple[str, list[int]]:
    """Extract the [USED: 1, 3, 5] citation marker from the LLM answer.

    Returns (clean_answer, zero_based_indices).
    Converts 1-based (human-readable) to 0-based (internal use).
    """
    match = re.search(r"\[USED:\s*([\d,\s]+)\]\s*$", answer)
    if not match:
        return answer.strip(), []
    indices = [int(n) - 1 for n in match.group(1).split(",") if n.strip().isdigit()]
    return answer[: match.start()].strip(), indices


# ---------- High-level orchestration ----------

async def answer_question(
    question: str,
    chunks: list,
    provider: LLMProviderType,
) -> LLMResponse:
    """End-to-end RAG answer pipeline:

    1. Build prompt with the retrieved document chunks
    2. Call the LLM provider chosen by the user
    3. Parse citation markers from the raw response
    4. Package everything into an LLMResponse for the API layer
    """
    user_prompt = build_user_prompt(question, chunks)

    start = time.monotonic()
    text, tokens = await provider.generate(SYSTEM_PROMPT, user_prompt)
    elapsed = int((time.monotonic() - start) * 1000)

    logger.info(
        "llm_call provider=%s model=%s tokens=%s latency_ms=%d",
        provider.name, provider.model, tokens, elapsed,
    )

    clean_answer, indices = parse_references(text)

    return LLMResponse(
        answer=clean_answer,
        referenced_chunk_indices=indices,
        provider_used=provider.name,
        model=provider.model,
        tokens_used=tokens,
        latency_ms=elapsed,
    )