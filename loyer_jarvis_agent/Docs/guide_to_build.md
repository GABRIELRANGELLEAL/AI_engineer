# Detailed Implementation Guide — AI Legal Assistant

This document describes, step by step, what needs to be implemented at each stage of the project. Each step is independent and testable before moving to the next. Use each section as a prompt/context for an LLM to generate the corresponding code.

---

## Step 1 — Database schema

**Goal**: create the data structure in PostgreSQL using SQLAlchemy + Alembic, with pgvector support.

**What to implement**:

1. Set up a Python project with `sqlalchemy`, `alembic`, `psycopg2-binary`, `pgvector`. 
2. Create SQLAlchemy models for the following tables:
   - `cases`: id (PK), case_number (string, unique), court (string), lawyer_id (FK to a user table, even if simplified), active (bool, default true), created_at (timestamp).
   - `filings`: id (PK), case_id (FK), raw_content (text), filing_date (timestamp), status (enum: new, analyzed, confirmed, discarded), created_at.
   - `analyses`: id (PK), filing_id (FK), action_required (bool), justification (text), rag_examples_used (jsonb), lawyer_confirmed (bool, default false), created_at.
   - `tasks`: id (PK), analysis_id (FK), description (text), deadline_type (enum: request, follow_up, review, filing), due_date (date), google_calendar_event_id (string, nullable), lawyer_confirmed (bool, default false).
   - `drafts`: id (PK), task_id (FK), content (text), version (int, 1-3), chosen (bool, default false), edited_by_lawyer (bool, default false).
   - `example_bank`: id (PK), type (enum: analysis, document), content (text), embedding (vector, dimension 1536 for compatibility with OpenAI/Anthropic embeddings), metadata (jsonb), source_draft_id (nullable FK to drafts), created_at.
   - `users` (simplified): id (PK), name, email, google_calendar_token (jsonb, to store OAuth credentials).
3. Configure Alembic to generate and apply migrations.
4. Enable the `pgvector` extension in the initial migration (`CREATE EXTENSION IF NOT EXISTS vector`).
5. Create an appropriate index on the `embedding` column of `example_bank` (e.g., HNSW or IVFFlat, depending on expected volume).
6. Create a `.env.example` file with connection variables (DATABASE_URL, etc.).

**Done criteria**: running `alembic upgrade head` creates all tables without errors on a local Postgres instance with pgvector installed. Inserting and querying a test record in each table works.

---

## Step 2 — eProc scraper (Playwright)

**Goal**: a script that accesses eProc, authenticates, checks for new filings for registered cases, and saves them to the database.

**What to implement**:

1. Set up a project with `playwright` (Python), including browser installation (`playwright install`).
2. Create an authentication module:
   - Support for login via digital certificate (A1/A3) or username/password, depending on what the court requires — start with the simplest method available on the eProc test/staging environment.
   - Save session/cookies to reduce re-authentications.
3. Create a function `get_new_filings(case: Case) -> list[RawFiling]`:
   - Navigates to the case page using `case_number`.
   - Extracts the list of recent docket entries/filings (date, content, type).
   - Compares with the last filing already saved in the database for that case (avoid duplicates).
4. Create a function `save_filings(case_id, filings: list)`:
   - Inserts new filings into the `filings` table with status `new`.
5. Error handling:
   - Page load timeout → log + retry (up to 3 attempts).
   - Layout change (selector not found) → detailed error log + notification (placeholder for a future step), without halting processing of other cases.
6. Create an execution script `scraper_run.py` that iterates over all active `cases`.
7. Add structured logging (INFO level for success, ERROR for failures, including `case_number`).

**Done criteria**: running `scraper_run.py` against a real test case results in new rows in `filings` with `raw_content` correctly populated, with no duplicates on repeated runs.

---

## Step 3 — Example bank indexing (RAG)

**Goal**: populate `example_bank` with embeddings of existing documents and analyses, using LangChain only for this step.

**What to implement**:

1. Install `langchain`, `langchain-community`, `langchain-postgres` (or `langchain-pgvector`), and an embeddings library (e.g., `anthropic` or `openai` for embeddings — decide which provider).
2. Create a script `index_examples.py` that:
   - Reads a directory of input files (e.g., `.txt` or `.docx` of past documents and analyses) — define the expected input format.
   - For each file, performs appropriate chunking (e.g., `RecursiveCharacterTextSplitter`, configurable chunk_size, considering that legal documents have long sections).
   - Generates an embedding for each chunk.
   - Inserts into the `example_bank` table with the appropriate `type` (`analysis` or `document`), `content` (chunk text), `embedding`, and `metadata` (e.g., original filename, date, court).
3. Configure LangChain's connection to the existing pgvector setup (reuse the same `example_bank` table, don't create a separate LangChain table).
4. Add an incremental execution option (don't re-index already-processed files — use content hash or filename as the key).
5. Log how many chunks were indexed per file and the total.

**Done criteria**: running `index_examples.py` over a test set of files populates `example_bank` with valid embeddings (correct dimension), without duplicating on repeated runs.

---

## Step 4 — Similarity search function

**Goal**: given an input text (a filing or document context), return the N most similar examples from `example_bank`.

**What to implement**:

1. Create a function `find_similar_examples(text: str, type: Literal["analysis", "document"], top_k: int = 5) -> list[SimilarExample]`:
   - Generates an embedding for the input `text` (same model used during indexing).
   - Performs a similarity search (cosine distance) on the `example_bank` table, filtered by `type`.
   - Returns a list with `content`, `metadata`, and similarity score.
2. Add a configurable minimum similarity threshold, discarding results that are too distant.
3. Create unit tests:
   - With a known text, verify that the most relevant examples (manually inserted during test setup) are returned first.
   - Verify behavior with an empty `example_bank` (returns an empty list, not an error).
4. Create a manual test script `test_search.py` that takes text via command line and prints formatted results (truncated content + score).

**Done criteria**: `test_search.py "example filing text"` returns a list ordered by relevance, with plausible scores (e.g., 0.7-0.95 for highly similar items).

---

## Step 5 — Analysis prompt (action required?)

**Goal**: given the content of a new filing + RAG examples, Claude decides whether action is required and justifies it.

**What to implement**:

1. Create a module `prompts/filing_analysis.py` with:
   - System prompt template explaining the role (a legal assistant that analyzes case filings and decides whether they require action from the lawyer).
   - Expected output structure in JSON: `{"action_required": bool, "justification": string, "category": optional string}`.
2. Create a function `analyze_filing(filing: Filing) -> AnalysisResult`:
   - Searches for similar examples via `find_similar_examples(raw_content, type="analysis", top_k=5)`.
   - Builds the final prompt by injecting: filing content + retrieved examples (formatted as "Example 1: ... → Decision: ...").
   - Calls the Anthropic API via the official SDK (`anthropic` Python package), model to be defined (e.g., claude-sonnet).
   - Parses the returned JSON, with error handling if the model doesn't return valid JSON (retry with a correction instruction).
3. Save the result to the `analyses` table:
   - `action_required`, `justification`, `rag_examples_used` (IDs and scores of the examples used), `filing_id`.
   - Update the `filing` status to `analyzed`.
4. Create a test script `test_analysis.py` that runs this function on an existing filing in the database and prints the result.
5. Log the full prompt sent (for debugging) in debug mode.

**Done criteria**: `test_analysis.py <filing_id>` produces a coherent analysis saved to the database, with `rag_examples_used` populated.

---

## Step 6 — Deadline/task extraction prompt

**Goal**: from a lawyer-confirmed analysis, generate a list of tasks with deadline type and dates.

**What to implement**:

1. Create a module `prompts/task_extraction.py` with:
   - System prompt explaining the role (extract tasks and deadlines from the analysis of a legal filing).
   - Output structure in JSON: a list of `{"description": string, "deadline_type": "request"|"follow_up"|"review"|"filing", "due_date": "YYYY-MM-DD"}`.
   - Clear instructions on how to calculate `due_date` from relative deadlines mentioned in the filing (e.g., "5 business days from the filing date") — include the filing date in the prompt so the model can calculate correctly, and consider business days/holidays (mention the limitation if holiday calculation isn't implemented at this stage).
2. Create a function `extract_tasks(analysis: Analysis) -> list[TaskResult]`:
   - Builds the prompt with: original filing content, analysis justification, filing date.
   - Calls the Anthropic API, parses the JSON (list of tasks).
   - Same error handling/retry as Step 5.
3. Save each returned task to the `tasks` table, linked to `analysis_id`, with `lawyer_confirmed=false`.
4. Create a test script `test_extraction.py <analysis_id>` that runs this and prints the generated tasks.

**Done criteria**: `test_extraction.py <analysis_id>` creates `tasks` records with dates correctly calculated for test cases with explicit deadlines in the filing.

---

## Step 7 — Draft generation prompt

**Goal**: generate three document drafts based on past examples of similar documents.

**What to implement**:

1. Create a module `prompts/draft_generation.py` with:
   - System prompt explaining the role (a legal writer that generates document drafts based on examples of past documents and the task context).
   - Expected output: three complete draft texts (not necessarily JSON — can be long text per version, or JSON with an array of 3 strings).
2. Create a function `generate_drafts(task: Task) -> list[str]` (3 elements):
   - Searches for similar examples via `find_similar_examples(task_description + filing_context, type="document", top_k=3)`.
   - Builds the prompt including: task description, filing/analysis context, retrieved document examples (full or summarized text depending on context limits).
   - Makes 3 separate calls to Claude (or one call requesting 3 variations — evaluate which produces better diversity; initial recommendation: 3 calls with slight temperature variation or a different approach angle indicated in the prompt).
3. Save each draft to the `drafts` table, linked to `task_id`, with `version` 1/2/3, `chosen=false`, `edited_by_lawyer=false`.
4. Create a test script `test_drafts.py <task_id>` that runs this and prints the three drafts (or saves them to separate files for easier reading).

**Done criteria**: `test_drafts.py <task_id>` generates three distinct, legally coherent drafts, saved to the database.

---

## Step 8 — Orchestration with Celery + Redis

**Goal**: connect steps 1-7 into an asynchronous pipeline, with queues and retries.

**What to implement**:

1. Set up `celery` with Redis as broker and result backend.
2. Create a `celery_app.py` file with the Celery application configuration (including default retry configuration: e.g., 3 attempts, exponential backoff).
3. Create Celery tasks:
   - `task_periodic_scraping`: runs the scraper (Step 2) for all active cases. Scheduled via Celery beat (e.g., every X hours, configurable).
   - `task_analyze_filing(filing_id)`: calls `analyze_filing` (Step 5). Triggered automatically for each new filing created by scraping.
   - `task_extract_tasks(analysis_id)`: calls `extract_tasks` (Step 6). Triggered manually after Checkpoint 1 (not automatically — depends on user action, see Step 9).
   - `task_generate_drafts(task_id)`: calls `generate_drafts` (Step 7). Triggered after Checkpoint 2.
4. Define chaining: `task_periodic_scraping` → for each new filing → enqueue `task_analyze_filing`.
5. Configure Celery logging (INFO level, including relevant IDs in each task).
6. Create a `docker-compose.yml` with services: postgres (with pgvector), redis, celery worker, celery beat, and the main application — to facilitate local execution.

**Done criteria**: running `docker-compose up`, manually triggering `task_periodic_scraping`, and verifying that new filings automatically trigger `task_analyze_filing`, with results visible in the database.

---

## Step 9 — Checkpoint logic

**Goal**: implement the two pause points where the system awaits lawyer confirmation before proceeding.

**What to implement**:

1. **Checkpoint 1** (after analysis, before extracting tasks):
   - Endpoint/function `confirm_analysis(analysis_id, confirmed: bool)`:
     - If `confirmed=true`: marks `analyses.lawyer_confirmed=true` and enqueues `task_extract_tasks(analysis_id)`.
     - If `confirmed=false`: marks `filings.status="discarded"`. Optional: create an `example_bank` entry with `type="analysis"` and metadata indicating "no action required", to refine the RAG.
2. **Checkpoint 2** (after task extraction, before generating drafts and creating calendar events):
   - Endpoint/function `confirm_tasks(analysis_id, adjusted_tasks: list)`:
     - Receives a list of tasks (possibly edited by the lawyer — description/date changed).
     - Updates `tasks` records with the confirmed values, `lawyer_confirmed=true`.
     - For each task, enqueues `task_create_calendar_event(task_id)` (Step 10) and `task_generate_drafts(task_id)`.
3. Create a simple notification system (placeholder for this phase):
   - Function `notify_lawyer(type: str, reference_id: int, message: str)` that for now just records to a `notifications` table (id, lawyer_id, type, reference_id, message, read, created_at) — actual delivery (email/push) is left for future integration.
   - Call `notify_lawyer` at the end of analysis (Checkpoint 1 pending) and at the end of task extraction (Checkpoint 2 pending).
4. Create a migration for the `notifications` table.

**Done criteria**: the full flow is testable via direct calls to the functions/endpoints: analysis generated → notification created → `confirm_analysis(true)` → tasks generated → notification created → `confirm_tasks(...)` → calendar events and drafts enqueued.

---

## Step 10 — Google Calendar integration

**Goal**: create calendar events for the lawyer for confirmed tasks.

**What to implement**:

1. Configure OAuth2 with the Google Calendar API (`google-auth`, `google-auth-oauthlib`, `google-api-python-client`).
2. Create the initial authorization flow:
   - Endpoint that generates the OAuth consent URL.
   - Callback that receives the token and saves it to `users.google_calendar_token` (encrypted if possible, or at least not version-controlled).
3. Create a function `create_calendar_event(task: Task) -> str` (returns the event ID):
   - Uses the linked lawyer's token (`task.analysis.filing.case.lawyer`).
   - Creates an event with: title (task description + case number), date/time (from `due_date`, define a default time, e.g., 9 AM), detailed description including `deadline_type` and a link/reference to the case.
   - Saves the returned ID to `tasks.google_calendar_event_id`.
4. Create a Celery task `task_create_calendar_event(task_id)` that calls this function (referenced in Step 9).
5. Error handling: if the token has expired, automatically use the refresh token (the Google library already handles this); if it fails permanently, log to `notifications` for the lawyer to re-authenticate.

**Done criteria**: after `confirm_tasks`, events appear on the test lawyer's real Google Calendar, with correct data.

---

## Step 11 — REST API (FastAPI)

**Goal**: expose endpoints for the frontend to consume the entire flow.

**What to implement**:

1. FastAPI project structure: `app/main.py`, `app/routers/`, `app/schemas/` (Pydantic).
2. Main endpoints:
   - `GET /filings?status=analyzed` — lists filings pending Checkpoint 1, with the associated analysis.
   - `GET /filings/{id}` — details of a filing + analysis + RAG examples used.
   - `POST /analyses/{id}/confirm` — Checkpoint 1 (body: `{"confirmed": bool}`).
   - `GET /analyses/{id}/tasks` — lists tasks generated for an analysis (pending Checkpoint 2).
   - `POST /analyses/{id}/confirm-tasks` — Checkpoint 2 (body: list of adjusted tasks).
   - `GET /tasks/{id}/drafts` — lists the three generated drafts.
   - `POST /drafts/{id}/choose` — marks a draft as chosen (optional body: `{"edited_content": string}` if the lawyer edited it).
   - `GET /notifications?read=false` — lists pending notifications.
   - `POST /notifications/{id}/mark-read`.
   - Google Calendar OAuth endpoints (Step 10).
3. Authentication: implement simple authentication (JWT or session) to identify the lawyer — define the complexity level as needed (single-user can be simplified).
4. Configure CORS to allow access from the Next.js frontend.
5. Automatic documentation via OpenAPI (already native to FastAPI) — ensure all Pydantic schemas are well-typed to generate useful docs.

**Done criteria**: all endpoints work via Swagger UI (`/docs`), covering the full end-to-end flow manually.

---

## Step 12 — Frontend (Next.js)

**Goal**: interface for the lawyer to review filings, confirm analyses/tasks, and choose drafts.

**What to implement**:

1. Next.js project (App Router), with an HTTP client for the API (e.g., `fetch` or `axios`), typed from the OpenAPI schema if possible (e.g., `openapi-typescript`).
2. Pages:
   - `/` — dashboard: list of pending notifications (Checkpoint 1 and 2) and monitored cases.
   - `/filings/[id]` — Checkpoint 1 screen: shows filing content, AI analysis (action required? justification), RAG examples used (summarized), confirm/dismiss buttons.
   - `/analyses/[id]/tasks` — Checkpoint 2 screen: lists generated tasks (description, deadline type, date), inline editable, confirm-all button.
   - `/tasks/[id]/drafts` — draft selection screen: shows the three drafts side by side (or in tabs), allows editing the chosen text before confirming.
3. Reusable components: filing card, editable task card, draft viewer with a simple text editor (e.g., textarea or lightweight rich-text editor).
4. State and revalidation: use simple polling or revalidation on tab focus for new notifications (no need for WebSocket at this stage).
5. Simple, functional layout — elaborate design isn't a priority at this stage, but it must be usable day-to-day.

**Done criteria**: the lawyer can, via the interface, complete the entire flow for a real filing — from receiving the notification to choosing the final draft — without using `/docs` or direct API calls.

---

## General notes for the LLM implementing this

- Always create minimal tests (unit tests or manual scripts) before moving to the next step.
- Maintain consistent logging across all steps — essential for debugging the asynchronous pipeline.
- Sensitive variables (API keys, OAuth tokens, database credentials) always via environment variables, never hardcoded.
- Each step should be delivered with instructions on how to run and test it independently.