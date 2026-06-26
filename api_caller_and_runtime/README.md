# Agentic Loop Orchestrator

![Python](https://img.shields.io/badge/-Python-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/-FastAPI-009688?logo=fastapi&logoColor=white)
![Anthropic](https://img.shields.io/badge/-Anthropic-191919?logo=anthropic&logoColor=white)
![OpenAI](https://img.shields.io/badge/-OpenAI-412991?logo=openai&logoColor=white)
![Docker](https://img.shields.io/badge/-Docker-2496ED?logo=docker&logoColor=white)
![SSE](https://img.shields.io/badge/-SSE%20Streaming-6366F1)


![banner](app/image_readme.png)

> **Provider-agnostic agentic loop framework** with multi-turn tool execution, session management, real-time SSE streaming, and pluggable persistence

---


<div align="center">

**Multi-Provider LLM · Agentic Tool Loop · SSE Visualizer · Pluggable Persistence**

</div>

## 🧠 How It Works

```
User Prompt
     │
     ▼
┌──────────────────────────┐
│       Orchestrator       │  manages sessions, history, retry logic
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│    LLM Provider Layer    │  AnthropicLLMProvider · OpenAILLMProvider · FallbackLLMProvider
└──────────┬───────────────┘
           │  LLMResponse (normalised)
           ▼
┌──────────────────────────┐
│     ResponseHandler      │  dispatches on stop_reason
└──────────┬───────────────┘
           │
     ┌─────┴──────┐
     │            │
  end_turn     tool_use ──► execute_tool() ──► tool result
     │            │                                 │
     │            └──────────── loop continues ◄────┘
     │
     ▼
  RunResult → final_answer + output_messages + token count
           │
           ▼
  PersistenceBackend (optional) → SQLAlchemy / custom
```

### Agentic Loop Detail

Each iteration follows a strict pattern:

1. **LLM call** — provider returns a normalised `LLMResponse`
2. **ResponseHandler** — dispatches on `stop_reason` (`end_turn`, `tool_use`, `max_tokens`, `pause_turn`, `content_filter`, `stop_sequence`)
3. **Tool execution** — each `tool_use` block is dispatched to its handler; results are collected
4. **Loop termination checks** — declarative retry limits, `terminates_loop` flag on any tool, or `max_iterations` cap
5. **Session history update** — full conversation is preserved per `session_id`
6. **Persistence** — optional backend saves interaction after every run

---

## 🚀 Features

- **Provider-agnostic** — swap between Claude and GPT with a single `model` string; a `FallbackLLMProvider` chains them transparently
- **Declarative tool registry** — define tools once in `TOOLS`; set `max_retries`, `failure_check`, and `terminates_loop` flags directly on the schema
- **Automatic retry logic** — the orchestrator tracks per-tool failure counts and stops the loop when the limit is exceeded
- **Session management** — multi-turn conversations are tracked in-memory per `session_id`, with full history passed on every call
- **Real-time SSE visualizer** — `InstrumentedResponseHandler` emits structured events (`turn_start`, `tool_call`, `tool_result`, `text_block`, `run_end`) for live UI rendering
- **Pluggable persistence** — `SQLAlchemyPersistence` ships out of the box; implement `PersistenceBackend` protocol for any storage backend
- **Thinking budget** — pass `thinking_budget` to enable extended reasoning on Anthropic models
- **Dockerized** — single-container setup, zero config beyond an API key

---

## 📁 Project Structure

```
.
├── chat_orchestrator.py   # Orchestrator — session management + agentic loop
├── llm.py                 # LLM providers: Anthropic, OpenAI, Fallback + LLMResponse
├── response_handler.py    # Dispatches on stop_reason, runs tools, updates LoopState
├── tools.py               # TOOLS registry — schemas, handlers, retry/termination config
├── persistence.py         # PersistenceBackend protocol + SQLAlchemyPersistence
├── server.py              # FastAPI server — /run, /run/{id}/events (SSE), index.html
├── requirements.txt
└── docker-compose.yml
```

---

## ⚙️ Setup

### Prerequisites

- Docker (recommended), or Python 3.11+
- An Anthropic or OpenAI API key

### Environment Variables

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...            # optional — only if using GPT models

# Optional — only needed for persistence
DATABASE_URL=postgresql://user:pass@host/db
WORKSPACE_DIR=/path/to/workspace # defaults to ../workspace
```

### Running with Docker

```bash
docker compose up --build
```

### Running locally

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

Then open [http://localhost:8000](http://localhost:8000) for the SSE visualizer.

---

## 📡 API Reference

### `POST /run`
Kicks off a new orchestrator run in the background and returns IDs immediately.

**Request body:**
```json
{
  "message": "List all CSV files and summarise their columns",
  "model": "claude-sonnet-4-6",
  "anthropic_api_key": "sk-ant-...",
  "tools": ["view_file", "search_files", "execute_code", "finish_loop"],
  "max_iterations": 10,
  "system_prompt": "You are a data analysis assistant."
}
```

**Response:**
```json
{
  "run_id": "a1b2c3...",
  "session_id": "d4e5f6..."
}
```

---

### `GET /run/{run_id}/events`
SSE stream of live events produced by the agentic loop.

**SSE Event types:**

| Event | Key fields |
|-------|-----------|
| `run_start` | `run_id`, `model` |
| `turn_start` | `iteration`, `provider`, `model`, `latency_ms`, `stop_reason`, `tokens` |
| `tool_call` | `iteration`, `tool_name`, `tool_use_id`, `input` |
| `tool_result` | `iteration`, `tool_name`, `tool_use_id`, `content` |
| `text_block` | `iteration`, `content` |
| `loop_state` | `iteration`, `stop_reason`, `total_tokens`, `message_count` |
| `run_end` | `stop_reason`, `total_tokens`, `final_answer` |
| `run_error` | `error` |
| `stream_end` | *(connection close signal)* |

---

## 🧩 Component Details

### `Orchestrator` (`chat_orchestrator.py`)

The central coordinator. Accepts a provider, model config, tool list, and optional persistence backend.

```python
from chat_orchestrator import Orchestrator
from llm import AnthropicLLMProvider

provider = AnthropicLLMProvider(api_key="sk-ant-...", model="claude-sonnet-4-6")

orchestrator = Orchestrator(
    provider=provider,
    tools=to_neutral_tools(["search_files", "view_file", "execute_code", "finish_loop"]),
    max_iterations=15,
    system_prompt="You are a helpful data analyst.",
)

result = await orchestrator.run("Summarise all CSV files in the workspace")
print(result.final_answer)
```

Key parameters:

| Parameter | Description |
|-----------|-------------|
| `provider` | Any `LLMProviderType` (Anthropic, OpenAI, or Fallback) |
| `tools` | Neutral tool list from `to_neutral_tools()` |
| `max_iterations` | Hard cap on agentic loop turns (default: 10) |
| `thinking_budget` | Token budget for Anthropic extended thinking |
| `persistence` | Any `PersistenceBackend` implementation |

---

### `LLM Providers` (`llm.py`)

All providers share the same interface — `one_call()` returns a normalised `LLMResponse` and `format_tool_turn()` builds the next message batch.

```python
# Auto-select provider by model name
from llm import get_llm_provider

provider = get_llm_provider(
    model="claude-sonnet-4-6",
    anthropic_key="sk-ant-..."
)

# Or chain providers with automatic fallback
from llm import FallbackLLMProvider

robust = FallbackLLMProvider(primary=claude_provider, fallback=gpt_provider)
```

---

### `Tool Registry` (`tools.py`)

Every tool is a plain dict with a `handler` function plus optional lifecycle flags:

```python
TOOLS["execute_code"] = {
    "description": "...",
    "input_schema": { ... },
    "handler": handle_execute_code,
    "max_retries": 3,                      # retry up to 3 times on failure
    "failure_check": _is_code_failure,     # callable(output) → bool
}

TOOLS["finish_loop"] = {
    "description": "...",
    "input_schema": { ... },
    "handler": handle_finish_loop,
    "terminates_loop": True,               # calling this ends the agentic loop
}
```

**Built-in tools:**

| Tool | Purpose |
|------|---------|
| `view_file` | Read file contents from the workspace |
| `search_files` | Glob-pattern file discovery |
| `get_file_stats` | File metadata (size, line count, modified date) |
| `create_file` | Write or overwrite files in the workspace |
| `execute_code` | Run inline or file-based scripts (Python, JS, TS, Bash, R, Ruby, PHP) |
| `handle_code_error` | Structured retry prompt after `execute_code` failures |
| `finish_loop` | Signal task completion and deliver the final answer |

---

### `ResponseHandler` (`response_handler.py`)

Dispatches every `LLMResponse` to the right handler based on `stop_reason`, executes tool calls, and updates `LoopState`.

| `stop_reason` | Behaviour |
|---------------|-----------|
| `end_turn` | Extracts text, appends to output, stops loop |
| `tool_use` | Executes each tool, appends results, continues loop |
| `max_tokens` | Saves partial text, stops loop |
| `pause_turn` | Saves text, loop continues (server-side tools still running) |
| `content_filter` | Saves text, stops loop |
| `stop_sequence` | Saves text, stops loop |

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| LLM | Anthropic Claude · OpenAI GPT |
| Streaming | Server-Sent Events (SSE) |
| Persistence | SQLAlchemy (optional) |
| Code execution | Python · Node.js · Bash · R · Ruby · PHP |
| Container | Docker Compose |

---
