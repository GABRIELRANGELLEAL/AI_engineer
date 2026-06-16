# Step 1: Database Schema with SQLAlchemy + Alembic + pgvector

This step creates the complete database schema for the Legal AI Assistant system using PostgreSQL with pgvector support for embeddings.

## Overview

**Goal**: Create the data structure in PostgreSQL using SQLAlchemy + Alembic, with pgvector support.

**What's included**:
- SQLAlchemy ORM models for all entities
- Alembic migrations for version control
- pgvector extension setup for embeddings
- Initial test data script
- Environment configuration

## Architecture

### Database Tables

1. **users** — Lawyer profiles with Google Calendar OAuth tokens
2. **cases** — Legal cases being monitored
3. **filings** — New documents/publications from case portals
4. **analyses** — AI analysis of whether action is required
5. **tasks** — Extracted tasks with deadlines
6. **drafts** — Generated document versions (3 per task)
7. **example_bank** — Vector embeddings of past analyses and documents (RAG)

### Key Design Decisions

- **1536-dimensional embeddings**: Compatible with OpenAI and Anthropic embeddings
- **IVFFlat index**: Good balance between speed and memory for vector similarity search
- **Enums for status/types**: Type safety without separate lookup tables
- **Nullable fields**: Google Calendar event ID (before calendar integration), RAG examples (varies by analysis)

## Prerequisites

### System Requirements

1. **PostgreSQL 12+** with pgvector extension
   ```bash
   # Ubuntu/Debian
   sudo apt-get install postgresql-contrib postgresql-14-pgvector
   
   # macOS with Homebrew
   brew install postgresql pgvector
   
   # Windows: Download PostgreSQL installer with pgvector option
   ```

2. **Python 3.10+**

### Install Dependencies

```bash
pip install -r requirements.txt
```

## Setup Instructions

### 1. Configure Database Connection

Copy `.env.example` to `.env` and update with your database credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```
DATABASE_URL=postgresql://user:password@localhost:5432/legal_assistant_db
```

### 2. Create Database

```bash
# Create the database
psql -U postgres -c "CREATE DATABASE legal_assistant_db;"

# Enable pgvector extension
psql -U postgres -d legal_assistant_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. Apply Migrations

The project uses Alembic for migrations. The initial migration creates all tables and sets up pgvector.

```bash
# Upgrade to latest version
alembic upgrade head

# Check migration status
alembic current
alembic history
```

## File Structure

```
Step_1/
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variables template
├── models.py                 # SQLAlchemy ORM models
├── database.py               # Database connection and utilities
├── test_database.py          # Test script for verification
├── alembic.ini              # Alembic configuration
├── alembic/
│   ├── env.py               # Alembic environment configuration
│   └── versions/
│       └── 001_initial_schema.py  # Initial migration script
└── README.md                # This file
```

## Models Reference

### User
```python
- id (PK)
- name: str
- email: str (unique)
- google_calendar_token: JSON (OAuth credentials)
- created_at: datetime
```

### Case
```python
- id (PK)
- case_number: str (unique)
- court: str
- lawyer_id: FK(User)
- active: bool (default: true)
- created_at: datetime
```

### Filing
```python
- id (PK)
- case_id: FK(Case)
- raw_content: text
- filing_date: datetime
- status: enum (new, analyzed, confirmed, discarded)
- created_at: datetime
```

### Analysis
```python
- id (PK)
- filing_id: FK(Filing)
- action_required: bool
- justification: text
- rag_examples_used: JSON (array of example IDs and similarity scores)
- lawyer_confirmed: bool (default: false)
- created_at: datetime
```

### Task
```python
- id (PK)
- analysis_id: FK(Analysis)
- description: text
- deadline_type: enum (request, follow_up, review, filing)
- due_date: date
- google_calendar_event_id: str (nullable, filled after integration)
- lawyer_confirmed: bool (default: false)
- created_at: datetime
```

### Draft
```python
- id (PK)
- task_id: FK(Task)
- content: text
- version: int (1, 2, or 3)
- chosen: bool (default: false)
- edited_by_lawyer: bool (default: false)
- created_at: datetime
```

### ExampleBank
```python
- id (PK)
- type: enum (analysis, document)
- content: text
- embedding: vector(1536)
- metadata: JSON (filename, date, court, etc.)
- source_draft_id: FK(Draft) (nullable, for feedback loop)
- created_at: datetime
```

## Testing

### Run Full Test Suite

The `test_database.py` script tests:
- Creating records in each table
- Setting relationships between tables
- Retrieving data with joins
- Vector embeddings storage (1536 dimensions)

```bash
python test_database.py
```

Expected output:
```
Testing User creation...
✓ User created: John Doe (ID: 1)

Testing Case creation...
✓ Case created: 0001234-56.2026.8.26.0100 (ID: 1)

...

✓ ALL TESTS PASSED!

Database statistics:
  - Users: 1
  - Cases: 1
  - Filings: 1
  - Analyses: 1
  - Tasks: 1
  - Drafts: 1
  - Examples: 1
```

### Manual Database Inspection

```bash
# Connect to the database
psql -U user -d legal_assistant_db

# List tables
\dt

# Check pgvector extension
\dx vector

# Query example data
SELECT id, type, embedding <-> '[0,0,...,0]'::vector as distance FROM example_bank LIMIT 5;
```

## Verification Checklist

- [x] `alembic upgrade head` runs without errors
- [x] All tables created in PostgreSQL
- [x] pgvector extension enabled
- [x] IVFFlat index on embeddings created
- [x] Can insert test records in all tables
- [x] Can retrieve records with relationships
- [x] Embeddings stored and retrievable (1536 dimensions)

## Indexes

For optimal performance, the following indexes are created:

| Table | Column | Type |
|-------|--------|------|
| cases | lawyer_id | B-tree |
| filings | case_id | B-tree |
| filings | status | B-tree |
| analyses | filing_id | B-tree |
| tasks | analysis_id | B-tree |
| tasks | due_date | B-tree |
| drafts | task_id | B-tree |
| example_bank | type | B-tree |
| example_bank | embedding | IVFFlat (cosine) |

## Rollback

To downgrade all migrations:

```bash
alembic downgrade base
```

To downgrade to a specific revision:

```bash
alembic downgrade 001
```

## Common Issues

### pgvector extension not found

```
ERROR: could not open extension control file
```

**Solution**: Install pgvector in PostgreSQL
```bash
# Ubuntu
sudo apt-get install postgresql-14-pgvector

# macOS
brew install pgvector

# Then reconnect and create extension
CREATE EXTENSION vector;
```

### Connection refused

**Solution**: Ensure PostgreSQL is running and credentials in `.env` are correct
```bash
# Check PostgreSQL status
pg_isready -h localhost -p 5432

# Or start PostgreSQL
sudo service postgresql start  # Linux
brew services start postgresql  # macOS
```

### Vector index creation fails

If IVFFlat index creation fails on small datasets, it will fall back gracefully. For production, ensure sufficient data before creating the index.

## Next Steps

Once this step is complete:
1. Run `test_database.py` to verify everything works
2. Move to **Step 2**: Implement the eProc scraper
3. In **Step 3**: Populate `example_bank` with real legal documents

## Running with Docker

For a complete PostgreSQL + pgvector setup:

```bash
docker run --name postgres-pgvector \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=legal_assistant_db \
  -p 5432:5432 \
  -d pgvector/pgvector:pg15
```

Then update your `.env`:
```
DATABASE_URL=postgresql://postgres:password@localhost:5432/legal_assistant_db
```

## Support

For Alembic migrations help:
```bash
alembic --help
alembic revision --help
```

For SQLAlchemy ORM documentation:
- https://docs.sqlalchemy.org/en/20/

For pgvector documentation:
- https://github.com/pgvector/pgvector
- https://github.com/pgvector/pgvector-python
