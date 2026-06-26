# Full Specification — RAG System for PDF Q&A

## Context

Build a system that allows users to upload PDF documents and later ask questions about their contents. The system should extract information from the documents, store it for efficient retrieval via embeddings, and use an LLM to answer questions accurately.

This is a technical challenge evaluated on the following criteria: Functionality, Retrieval, LLM Use, Code Quality, API Design, and Developer UX.

---

## Technology Stack

| Component | Technology | Justification |
|---|---|---|
| Web Framework | FastAPI | Native async, Pydantic typing, automatic Swagger docs, supports multipart/form-data and JSON natively |
| PDF Extraction | PyMuPDF (fitz) | Implemented in C (fast), preserves reading order, per-page metadata (page number, dimensions) |
| Chunking | Custom implementation | Semantic chunking: respects paragraph/section boundaries, with fallback to size-based splitting + overlap |
| Embeddings | OpenAI text-embedding-3-small (primary), sentence-transformers all-MiniLM-L6-v2 (local fallback) | Factory function selects provider based on API key availability; batching and retry handled internally |
| Vector Store | ChromaDB | Runs in-process, persists to disk, stores metadata alongside vectors, no external infrastructure |
| LLM | OpenAI gpt-4o-mini (primary), Anthropic claude-sonnet-4-6 (secondary) | Provider inferred from model name prefix; fallback handled at the API layer |
| Frontend | React + Tailwind CSS | Served as static files by FastAPI, no separate server |
| Infrastructure | Docker + Docker Compose + Makefile | Single-command setup, optimized evaluator experience |

---

## Module Architecture

```
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py                  ← FastAPI entry point, mounts routes and serves static frontend
│   │   ├── config.py                ← settings via pydantic-settings + environment variables
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── documents.py     ← POST /documents (PDF upload and indexing)
│   │   │   │   ├── question.py      ← POST /question (question and answer)
│   │   │   │   ├── keys.py          ← POST /validate-keys (API key validation)
│   │   │   │   └── stats.py         ← GET /stats (aggregated metrics)
│   │   │   └── dependencies.py      ← dependency injection (providers, store)
│   │   ├── core/
│   │   │   ├── extraction.py        ← reads PDFs with PyMuPDF, returns text + per-page metadata
│   │   │   ├── chunking.py          ← semantic chunking with fallback to size + overlap
│   │   │   ├── embedding.py         ← abstract interface + OpenAI and sentence-transformers implementations
│   │   │   ├── retrivial.py         ← hybrid retrieval: semantic (ChromaDB) + keyword (BM25) with RRF fusion
│   │   │   └── llm.py               ← abstract interface + OpenAI and Anthropic implementations + fallback
│   │   └── store/
│   │       └── vector_store.py      ← ChromaDB wrapper (indexing, search, listing)
│   ├── tests/
│   │   ├── test_extraction.py
│   │   ├── test_chunking.py
│   │   ├── test_retrieval.py
│   │   └── test_api.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  ← internal routing between screens (state-based, not React Router)
│   │   ├── pages/
│   │   │   ├── SetupPage.jsx        ← API key configuration screen
│   │   │   └── MainPage.jsx         ← main screen (upload + chat)
│   │   ├── components/
│   │   │   ├── KeyInput.jsx         ← API key input field with test button and visual feedback
│   │   │   ├── FileUpload.jsx       ← drag-and-drop area for PDFs with progress
│   │   │   ├── DocumentList.jsx     ← list of indexed documents (sidebar)
│   │   │   ├── ChatWindow.jsx       ← question and answer history
│   │   │   ├── ChatInput.jsx        ← text input field + send button
│   │   │   └── References.jsx       ← collapsible cards with reference excerpts
│   │   └── index.css                ← Tailwind imports
│   ├── package.json
│   └── tailwind.config.js
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
└── README.md
```

---

## API Specification

### POST /validate-keys

Validates the API keys provided by the user. Attempts a minimal call to each API (list models or test call).

**Request:**
```json
{
  "openai_key": "sk-...",
  "anthropic_key": "sk-ant-..."
}
```
- `openai_key`: required (used for embeddings + primary LLM)
- `anthropic_key`: optional (used as LLM fallback)

**Response:**
```json
{
  "openai": { "valid": true, "message": "Connected successfully" },
  "anthropic": { "valid": true, "message": "Connected successfully" }
}
```

On failure:
```json
{
  "openai": { "valid": false, "message": "Invalid API key or insufficient permissions" },
  "anthropic": { "valid": false, "message": "Not provided" }
}
```

### POST /documents

Upload and index PDFs.

**Request:**
- Content-Type: multipart/form-data
- Body: one or more PDFs under the field `files`
- Headers: `X-OpenAI-Key: sk-...`

**Response:**
```json
{
  "message": "Documents processed successfully",
  "documents_indexed": 2,
  "total_chunks": 128,
  "details": [
    {
      "filename": "motor_manual.pdf",
      "pages": 15,
      "chunks": 72,
      "processing_time_ms": 3400
    },
    {
      "filename": "specifications.pdf",
      "pages": 8,
      "chunks": 56,
      "processing_time_ms": 2100
    }
  ]
}
```

### POST /question

Ask a question about the indexed documents.

**Request:**
```json
{
  "question": "What is the power consumption of the motor?"
}
```
- Headers: `X-OpenAI-Key: sk-...`, `X-Anthropic-Key: sk-ant-...` (optional)

**Response:**
```json
{
  "answer": "The motor's power consumption is 2.3 kW.",
  "references": [
    {
      "text": "the motor xxx has requires 2.3kw to operate at a 60hz line frequency",
      "document": "motor_manual.pdf",
      "page": 3,
      "similarity_score": 0.92
    }
  ],
  "metadata": {
    "provider_used": "openai",
    "model": "gpt-4o-mini",
    "retrieval_time_ms": 45,
    "llm_time_ms": 1230,
    "total_time_ms": 1320,
    "confidence": "high"
  }
}
```

### GET /stats

Aggregated system metrics.

**Response:**
```json
{
  "documents_indexed": 5,
  "total_chunks": 312,
  "questions_answered": 23,
  "average_latency_ms": 1450,
  "provider_usage": {
    "openai": 21,
    "anthropic": 2
  }
}
```

### GET /health

Healthcheck for Docker.

**Response:**
```json
{
  "status": "healthy"
}
```

---

## Detailed Implementation by Module

### extraction.py

- Use PyMuPDF (fitz) to extract text from each page of the PDF
- Return a list of objects with: `page_number`, `text`, `filename`
- Clean the text: normalize whitespace, remove repeated headers/footers if detected
- Handle PDFs without extractable text (scanned documents) by returning a warning to the user

### chunking.py

- Implement semantic chunking with the following separation hierarchy:
  1. First try to split by `\n\n` (paragraphs/sections)
  2. Then by `\n` (line breaks)
  3. Then by `. ` (sentences)
  4. Last resort: by character
- Configurable parameters via config: `CHUNK_SIZE=512` tokens, `CHUNK_OVERLAP=50` tokens
- If a paragraph is smaller than a minimum (e.g., 50 tokens), merge it with the next one
- Each chunk must carry metadata: `filename`, `page_number`, `chunk_index`, `text`
- Implement without LangChain dependency — custom code demonstrates deeper understanding

### embedding.py

- `OpenAIEmbeddingProvider`: uses `text-embedding-3-small`, 1536-dimensional vectors, async client with exponential-backoff retry (up to 3 attempts) on rate-limit and timeout errors
- `LocalEmbeddingProvider`: uses `sentence-transformers/all-MiniLM-L6-v2`, 384-dimensional vectors, loaded lazily on first call and run in a thread pool via `asyncio.to_thread` to avoid blocking the event loop
- `get_embedding_provider(openai_key)`: factory function — returns `OpenAIEmbeddingProvider` if a key is provided, `LocalEmbeddingProvider` otherwise
- `embed_chunks_in_batches(chunks, provider, batch_size=100)`: sends texts in batches of 100 to stay within the per-request token limit; empty/whitespace texts are filtered before sending and replaced with zero vectors in the output
- Input texts are truncated to ~6150 words before embedding to stay under the 8191-token OpenAI hard limit

**Dimension consistency:** vectors from different providers are incompatible (1536 vs 384 dims). ChromaDB will reject mismatched vectors, so the same provider used during indexing must be used at query time.

### vector_store.py

- Wrapper over ChromaDB with methods:
  - `add_documents(chunks: list[Chunk], embeddings: list[list[float]])` — indexes chunks with metadata
  - `search(query_embedding: list[float], top_k: int = 5) -> list[SearchResult]` — cosine similarity search
  - `list_documents() -> list[str]` — lists indexed documents
  - `get_stats() -> dict` — returns counts and metrics
- Persist data to disk (configurable directory, default `/app/data/chromadb`)
- Store alongside each embedding: chunk text, filename, page_number, chunk_index

### retrivial.py

Hybrid retrieval combining two strategies fused via Reciprocal Rank Fusion (RRF):

**Semantic search** — generates a query embedding and queries ChromaDB for the top `search_pool` candidates (default 50) by cosine similarity.

**Keyword search (BM25)** — runs BM25 Okapi over all indexed chunks. Implemented from scratch as `_BM25Index` (k1=1.5, b=0.75) with bilingual stop-word removal (EN + PT), so there is no external dependency.

**RRF fusion** — merges both ranked lists into a single score:

```
score(doc) = β / (k + rank_semantic) + (1 − β) / (k + rank_keyword)
```

Default values: β=0.70 (semantic weight), k=60 (standard smoothing constant from the original paper).

**Confidence classification** — based on the raw cosine similarity of the top semantic hit (not RRF score, which is not on a 0–1 scale): `high` (> 0.80), `medium` (≥ 0.60), `low` (< 0.60).

**Optional metadata filter** — results can be restricted to specific filenames before returning.

Key dataclasses returned: `RetrievalResult` (text, document, page, chunk_index, rrf_score, semantic_score, keyword_score), `RetrievalMetrics` (per-stage timings, pool sizes, confidence), `RetrievalResponse` (results + metrics).

Logs: strategy, beta, pool sizes, top RRF score, top cosine score, confidence, and per-stage timing (embed, semantic search, BM25, fusion).

### llm.py

- `OpenAILLMProvider`: wraps the async OpenAI client, uses `gpt-4o-mini`, temperature 0.1
- `AnthropicLLMProvider`: wraps the async Anthropic client, uses `claude-sonnet-4-6`, temperature 0.1
- `get_llm_provider(model, openai_key, anthropic_key)`: factory that infers the provider from the model name prefix (`gpt` → OpenAI, `claude` → Anthropic); raises `ValueError` for unsupported combinations
- Both providers return `tuple[str, int | None]` — raw text + total tokens used
- `answer_question(question, chunks, provider)`: end-to-end orchestration — builds prompt, calls LLM, parses citations, returns `LLMResponse`
- `LLMResponse` dataclass: `answer`, `referenced_chunk_indices` (0-based), `provider_used`, `model`, `tokens_used`, `latency_ms`
- Citation format enforced in the system prompt: `[USED: 1, 3, 5]` at the end of each answer; `parse_references()` extracts and converts to 0-based indices
- System prompt:

```
You are an assistant that answers questions based exclusively on the document excerpts provided.

Rules:
- Answer ONLY with information present in the provided excerpts
- At the end of your response, list the numbers of the excerpts you used in the format: [USED: 1, 3, 5]
- If the information is not in the excerpts, explicitly state that you did not find sufficient information in the available documents
- Be direct and precise
- Respond in the same language as the question
```

---

## Frontend — Two Screens

### Screen 1: Setup (SetupPage)

**Layout:** centered on screen, card with form

**Elements:**
- Title: project name and brief description ("PDF Document Q&A System")
- Input field for OpenAI API Key, with label "OpenAI API Key (required)" and lock icon
  - Password type (hides the value)
  - "Test" button next to it
  - Visual feedback: spinner while testing, green checkmark if valid, red X with error message if invalid
  - Below the field, subtle text: "Used for embeddings (text-embedding-3-small) and answers (gpt-4o-mini)"
- Input field for Anthropic API Key, with label "Anthropic API Key (optional — fallback)"
  - Same test and feedback pattern
  - Subtle text: "Used as fallback for answers (Claude Sonnet)"
- "Get Started" button at the bottom
  - Disabled until the OpenAI key is successfully validated
  - Enabled as soon as the OpenAI key is validated (Anthropic is optional)

**Behavior:**
- Keys are stored only in React state (browser memory, not localStorage)
- Sent via headers in each subsequent request
- Never persisted on the backend

### Screen 2: Main (MainPage)

**Layout:** left sidebar (fixed width ~300px) + main area on the right

**Left sidebar:**
- PDF upload area at the top
  - Drag-and-drop or click to select
  - Accepts multiple files
  - On upload, shows step-by-step progress: "Extracting text... Generating chunks... Creating embeddings... Done!"
  - After indexing, shows summary: "manual.pdf — 15 pages, 72 chunks"
- List of indexed documents below
  - Each document with name, page count, chunk count
  - Visual indicator that it is indexed

**Main area (chat):**
- Question and answer history, chat-style
- Each system response contains:
  - Answer text (primary highlight)
  - Confidence indicator based on similarity score: "High confidence" (score > 0.8), "Medium confidence" (0.6–0.8), "Low confidence" (< 0.6)
  - Indication of which provider/model generated the response
  - Collapsible reference cards, each showing: text excerpt, document name, page number, similarity score
  - Subtle response time display (e.g., "1.3s")
- Input field at the bottom with send button
- Loading state while processing (spinner or skeleton)
- If no documents are indexed, show a message guiding the user to upload

---

## Infrastructure

### .env.example (committed to the repo)
```
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=gpt-4o-mini
CHUNK_SIZE=512
CHUNK_OVERLAP=50
TOP_K=5
LOG_LEVEL=INFO
```

### Dockerfile
- Base: `python:3.12-slim`
- Install system dependencies for PyMuPDF in a separate layer
- Copy `requirements.txt` first, run `pip install` (dependency caching)
- Copy built frontend into `static/` folder
- Copy backend code
- Create a non-root user to run the application
- Expose port 8000
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

### docker-compose.yml
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - chroma_data:/app/data
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  chroma_data:
```

### Makefile
```makefile
setup:          copies .env.example to .env
build-frontend: builds React into static/
run:            docker-compose up --build
dev:            runs backend and frontend in dev mode
test:           runs tests with pytest
down:           docker-compose down
clean:          removes volumes and persisted data
```

---

## Logging

- Use `structlog` or standard `logging` with structured format
- Log each pipeline step with timing:
  - Upload: `INFO | action=extract | file=manual.pdf | pages=15 | time_ms=450`
  - Chunking: `INFO | action=chunk | file=manual.pdf | chunks=72 | time_ms=120`
  - Embedding: `INFO | action=embed | chunks=72 | time_ms=800`
  - Retrieval: `INFO | action=retrieve | question="motor consumption" | top_score=0.92 | time_ms=45`
  - LLM: `INFO | action=llm_call | provider=openai | model=gpt-4o-mini | tokens=580 | time_ms=1230`
  - Total: `INFO | action=question_answered | total_ms=1320`


## README.md

Should contain:
1. **Title and description** — brief project overview
2. **Architecture diagram** (Mermaid or ASCII) showing the flow: PDF → Extraction → Chunking → Embedding → ChromaDB → Retrieval → LLM → Response
3. **Quick setup** in 3 steps: clone, configure `.env`, `make run`
4. **Usage examples** with curl showing: document upload, question with an existing answer, question without an answer in the documents
5. **Technical decisions** explaining the choice of each component and why
6. **Limitations and next steps**: what would be done with more time (re-ranking, OCR for scanned PDFs, response caching, authentication, rate limiting)

---

## Complete User Flow

1. Opens `localhost:8000` in the browser
2. Setup screen appears → pastes OpenAI key → clicks "Test" → green checkmark appears
3. Optionally pastes Anthropic key → clicks "Test" → green checkmark
4. "Get Started" button becomes enabled → clicks → transitions to main screen
5. In the sidebar, drags 2 PDFs → sees step-by-step progress → "128 chunks indexed"
6. In the chat, types "What is the motor's energy consumption?"
7. Sees loading → answer appears with text, high confidence indicator, collapsible references showing excerpt, document, and page
8. Continues asking questions
9. Asks a question about something not in the documents → system responds that it did not find sufficient information
