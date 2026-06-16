# Implementation Notes — Step 1: Database Schema

## Design Decisions Explained

### 1. Why SQLAlchemy + Alembic?

- **SQLAlchemy ORM**: Provides type-safe, Pythonic database interactions. Avoids raw SQL while maintaining full control.
- **Alembic**: Version control for database schema. Essential when working with AI pipelines that may need schema changes as requirements evolve.
- **No ORMs abstraction layer**: Direct Alembic control over migrations ensures pgvector-specific features work correctly.

### 2. Embedding Dimensions (1536)

The 1536-dimension vectors are the standard for:
- OpenAI's `text-embedding-3-small` and older embeddings
- Anthropic's embedding models
- Most major LLM providers

This ensures compatibility across the entire ecosystem without re-embedding when switching providers.

### 3. Vector Index Choice: IVFFlat

| Index Type | Speed | Memory | Best For |
|-----------|-------|--------|----------|
| **IVFFlat** | Medium | Low | Most applications, ~100k+ vectors |
| HNSW | Fast | High | Very large datasets (1M+) |
| Exact | Slow | None | Small datasets or accuracy critical |

**Decision**: IVFFlat with `lists=100` is a good starting point. As the `example_bank` grows:
- **<10k vectors**: Can downgrade to exact search
- **>500k vectors**: May upgrade to HNSW

The migration can be changed without data loss — just different index creation.

### 4. Relationship Design

All relationships are **one-to-many** flowing down the pipeline:

```
User (1) ──┐
           ├─→ Case (1) ──→ Filing (1) ──→ Analysis (1) ──→ Task (1) ──→ Draft (1)
           └─→ other cases
```

**Advantages**:
- Clear data provenance (trace any result back to the original filing)
- Efficient querying (filter by case → get all filings, analyses, tasks)
- Supports the feedback loop (Draft → ExampleBank with source tracking)

**Nullable columns**:
- `google_calendar_event_id`: Filled only after Step 10 (Google Calendar integration)
- `source_draft_id` (ExampleBank): Only for examples generated from lawyer-approved drafts
- `rag_examples_used` (Analysis): Always populated, but structure varies

### 5. Enum Design

Enums are preferred over lookup tables for small, fixed sets:

```python
# Good: Fixed values unlikely to change
FilingStatusEnum = ("new", "analyzed", "confirmed", "discarded")

# Good: Clear domain values
DeadlineTypeEnum = ("request", "follow_up", "review", "filing")

# Good: Only 2 types
ExampleTypeEnum = ("analysis", "document")
```

If these values need to be user-customizable later, they can be refactored to lookup tables with a migration.

### 6. Indexes

**B-tree indexes**:
- Foreign keys (lawyer_id, case_id, etc.) — **Required for joins**
- Status columns — **Frequent filtering** (e.g., `filings WHERE status = 'analyzed'`)
- Date columns — **Range queries** (e.g., `tasks WHERE due_date BETWEEN ? AND ?`)

**Vector index (IVFFlat)**:
- Essential for similarity search performance
- Created with `vector_cosine_ops` (cosine similarity is standard for embeddings)

### 7. Timestamp Strategy

All timestamps use UTC (`datetime.utcnow()`) to avoid timezone issues in a distributed system.

- **created_at**: Immutable, set at row creation
- **filing_date**: Comes from the court system, user-provided

No `updated_at` field because most rows are immutable once created. If audit trails are needed later, that's a separate concern (Event Sourcing pattern).

## Migration Strategy

### Adding a new field

```bash
# Create a new migration
alembic revision --autogenerate -m "Add lawyer_phone to users"

# Review alembic/versions/XXX_add_lawyer_phone.py

# Apply it
alembic upgrade head
```

### Renaming a column

```bash
# Manual migration (SQLAlchemy doesn't auto-detect renames safely)
alembic revision -m "Rename case_number to process_number"

# Edit the file to:
# - op.alter_column('cases', 'case_number', new_column_name='process_number')
# - op.execute("ALTER INDEX ix_cases_case_number RENAME TO ix_cases_process_number")
```

### Adding a table

```bash
# Add the model to models.py
# Generate migration
alembic revision --autogenerate -m "Add notifications table"
# Review and apply
alembic upgrade head
```

## Performance Considerations

### Query Patterns

**High-frequency queries** (should be fast):
1. `Filing.objects.filter(status='analyzed').recent(case_id)` — Dashboard view
2. `Analysis.objects.get(filing_id).rag_examples_used` — Already cached as JSON
3. `ExampleBank.similarity_search(embedding, top_k=5)` — Vector similarity

**Rare/analytical queries**:
- Full-text search on filing content
- Aggregate stats by court/deadline type

**Indexes are set up for high-frequency queries.** No full-text index yet (not needed for Steps 1-7).

### Volume Estimates

For a solo lawyer (~50 cases, 5 filings/case/month, 3 years):
- **Filings**: ~900 rows
- **Analyses**: ~900 rows
- **Tasks**: ~3,600 rows (4 per analysis avg)
- **Drafts**: ~10,800 rows (3 per task)
- **ExampleBank**: ~1,800 rows (assuming 2 new examples per case)

**Total**: ~17k rows — IVFFlat index is appropriate; no sharding needed.

If scaling to 100s of lawyers: Consider partitioning by lawyer_id or date, but that's a future optimization.

## Security Considerations

### Sensitive Data

**Stored securely**:
- ✓ `google_calendar_token` (JSON) — Should be encrypted at rest (future: add encryption layer)
- ✓ Database URL in `.env` — Never committed to git

**Not stored** (correct):
- ✗ Lawyer passwords (handled by external OAuth / SSO)
- ✗ API keys (passed via environment, not stored)

### SQL Injection

SQLAlchemy ORM prevents SQL injection automatically. Raw SQL (only in migrations) is developer-written and reviewed.

### Row-Level Security

Future consideration: Add PostgreSQL RLS (Row-Level Security) policies to prevent one lawyer from seeing another's cases.

```sql
-- Hypothetical for Step 11
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY cases_by_lawyer ON cases
  USING (lawyer_id = current_user_id());
```

## Testing Approach

The `test_database.py` script:
1. **Creates one record per table** — Ensures schema is correct
2. **Tests relationships** — Verifies foreign keys work
3. **Retrieves with joins** — Tests cascading queries
4. **Stores embeddings** — Verifies pgvector integration

**It does NOT**:
- Test migration rollback (manual check recommended)
- Test performance at scale (separate load test)
- Test concurrent writes (PostgreSQL's default isolation is sufficient)

### Running tests

```bash
# Full test
python test_database.py

# Specific table test (manually in Python REPL)
python
>>> from database import SessionLocal
>>> from models import User
>>> session = SessionLocal()
>>> users = session.query(User).all()
>>> print(len(users))
```

## Scaling Considerations

### Single Lawyer (Current)

- ✓ One database, no sharding needed
- ✓ SQLAlchemy default connection pooling is fine
- ✓ IVFFlat index sufficient

### Multi-Lawyer (Future)

If expanding to 100+ lawyers:

1. **Add `tenant_id` or `workspace_id`** — Allow multi-tenancy
   ```python
   class Case(Base):
       lawyer_id = FK(User)
       workspace_id = FK(Workspace)  # New
   ```

2. **Partition by workspace** — Separate schemas or databases
3. **Add RLS policies** — Enforce data isolation at DB level
4. **Use read replicas** — For analytics queries

Current design is **compatible with all of these** without breaking changes.

## Dependencies Locked

All versions in `requirements.txt` are pinned to ensure reproducibility:
- `sqlalchemy==2.0.23` — Latest stable in 2.0 series
- `alembic==1.13.1` — Compatible with SQLAlchemy 2.0
- `pgvector==0.3.0` — Latest stable
- `psycopg2-binary==2.9.9` — Stable PostgreSQL driver

Update with:
```bash
pip install --upgrade sqlalchemy alembic pgvector psycopg2-binary
pip freeze | grep -E "sqlalchemy|alembic|pgvector|psycopg2" > requirements.txt
```

## Troubleshooting

### Alembic Doesn't Detect Changes

```bash
# Ensure models.py is imported in env.py
# Current setup: Not auto-detecting (manual approach)

# To enable auto-detection:
# In alembic/env.py, change target_metadata = None to:
from models import Base
target_metadata = Base.metadata
```

Currently, migrations are **manual** (safer for pgvector-specific operations).

### Vector Index Slow to Create

IVFFlat index on large datasets can take time:
```bash
# Monitor in another terminal
SELECT current_query, query_start FROM pg_stat_activity WHERE state != 'idle';

# If needed, run in background
CREATE INDEX CONCURRENTLY ix_example_bank_embedding ON example_bank 
USING ivfflat (embedding vector_cosine_ops);
```

## Next Integration Points

- **Step 2 (Scraper)**: Will insert into `filings` table
- **Step 3 (RAG)**: Will populate `example_bank` with embeddings
- **Step 5 (Analysis)**: Will create `analyses` records
- **Step 6 (Tasks)**: Will create `tasks` records
- **Step 7 (Drafts)**: Will create `drafts` records and update `example_bank`

Each step can be developed/tested independently once this schema is in place.
