# LLM Kit

Multi-provider agentic loop framework. Provider-agnostic orchestration for
tool-using LLM agents.

## File layout

| File | Role |
|---|---|
| `llm.py` | Provider abstraction: `AnthropicLLMProvider`, `OpenAILLMProvider`, `FallbackLLMProvider`, `LLMResponse`, `LLMError`, `extract_text_response`, `get_llm_provider` |
| `response_handler.py` | `ResponseHandler` — processes normalised `LLMResponse`, executes tools, maintains `LoopState` |
| `chat_orchestrator.py` | `Orchestrator` — drives the agentic loop, session management, `ChatSession`, `RunResult` |
| `tools.py` | Tool registry (`TOOLS`), handlers, `execute_tool`, format helpers, declarative retry (`max_retries`, `failure_check`) and loop-termination (`terminates_loop`) metadata |
| `persistence.py` | `PersistenceBackend` protocol + `SQLAlchemyPersistence` implementation |
| `__init__.py` | Public re-exports |

## Key abstractions

### LLMResponse (normalised)

Every provider's `one_call` returns an `LLMResponse` with:
- `content` — list of `{"type": "text", "text": "..."}` and `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}` blocks
- `stop_reason` — one of: `end_turn`, `tool_use`, `max_tokens`, `content_filter`, `stop_sequence`, `pause_turn`
- `provider_used`, `model`, `tokens_used`, `latency_ms`

### Provider interface

Each provider implements:
- `one_call(*, messages, model, max_tokens, temperature, system_prompt, tools, thinking_budget) -> LLMResponse`
- `format_tool_turn(response, tool_results) -> list[dict]` — builds provider-specific messages for the next API call

### Declarative tool behaviour

In the `TOOLS` registry:
- `max_retries: int` + `failure_check: Callable[[str], bool]` — the orchestrator retries failed tools generically
- `terminates_loop: bool` — the orchestrator ends the loop when this tool is invoked

### Pluggable persistence

`Orchestrator(persistence=...)` accepts any `PersistenceBackend`. Pass `None` to skip persistence. `SQLAlchemyPersistence` is the built-in implementation.

## Design invariants

- `Orchestrator` has zero `if provider == "..."` branches.
- `ResponseHandler` imports nothing from `anthropic` or `openai` — only from `llm.py`.
- `chat_orchestrator.py` has no knowledge of specific tool names — all tool-specific behaviour lives in `tools.py`.
- `llm.py` works standalone: a caller who only wants `one_call` can use it without importing other modules.
