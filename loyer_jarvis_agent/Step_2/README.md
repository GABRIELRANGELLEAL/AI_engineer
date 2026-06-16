# Step 2: eProc Scraper with Playwright

**Goal**: Scrape filings from eProc (Brazilian legal portal), authenticate, extract new documents, and save them to the database.

## Overview

This step implements a Playwright-based web scraper that:
- Authenticates with eProc (username/password or digital certificate)
- Searches for monitored legal cases
- Extracts recent filings from case dockets
- Deduplicates against database
- Saves new filings with structured logging
- Manages session cookies for efficiency

## Architecture

### Components

| Component | File | Purpose |
|-----------|------|---------|
| **Scraper** | `scraper.py` | Core Playwright logic, filing extraction |
| **Auth** | `auth.py` | eProc authentication, session management |
| **Config** | `config.py` | Environment-based configuration |
| **Logging** | `logging_config.py` | Structured JSON logging |
| **CLI** | `scraper_run.py` | Main execution script |
| **Tests** | `test_scraper.py` | Unit tests for components |

### Data Flow

```
eProc Portal
    ↓
Authenticate (username or certificate)
    ↓
Search Case by case_number
    ↓
Extract Docket Entries
    ↓
Filter Out Existing Filings (check database)
    ↓
Save to Database (filings table with status=new)
    ↓
Log Results (structured logging)
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Authentication
AUTH_METHOD=username
EPROC_USERNAME=your_cpf_or_username
EPROC_PASSWORD=your_password

# Database (from Step 1)
DATABASE_URL=postgresql://user:password@localhost:5432/legal_assistant_db
```

### 3. Create Test Cases in Database

Before running the scraper, add test cases:

```python
from database import SessionLocal
from models import User, Case
from sqlalchemy import create_engine

engine = create_engine("your_database_url")
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

# Create lawyer
lawyer = User(name="John Doe", email="john@example.com")
session.add(lawyer)
session.commit()

# Create case
case = Case(
    case_number="0001234-56.2026.8.26.0100",
    court="TJ-SP",
    lawyer_id=lawyer.id,
    active=True
)
session.add(case)
session.commit()
```

## Usage

### Run Full Scraper

```bash
python scraper_run.py
```

Scrapes all active cases and saves new filings.

### Scrape Specific Case

```bash
python scraper_run.py --case-id 123
```

### Dry Run (Test Without Saving)

```bash
python scraper_run.py --dry-run
```

Extracts filings but doesn't save to database. Useful for testing.

## Testing

### Run All Tests

```bash
python test_scraper.py --test all
```

Tests: database connection, filing extraction, database write.

### Test Database Connection

```bash
python test_scraper.py --test database
```

### Test Filing Extraction Logic

```bash
python test_scraper.py --test filings
```

## Implementation Details

### Playwright & Async

- **Why async?** eProc pages load dynamically; async allows parallel case scraping and non-blocking waits.
- **Browser lifecycle**: Start once, reuse context for multiple cases, close after completion.
- **Headless mode**: Configurable via `HEADLESS_MODE` env var (set to `false` for debugging).

### Authentication

**Session Management**:
- Credentials stored in `.env` (never committed)
- After login, browser cookies saved to `~/.playwright_session/session_{lawyer_id}.json`
- Sessions cached for 30 days (configurable via `SESSION_COOKIE_DURATION_DAYS`)
- Re-authenticates if session expires

**Supported Methods**:
- `AUTH_METHOD=username` — Username/password login (implemented)
- `AUTH_METHOD=certificate` — Digital certificate (A1/A3) — placeholder for future

### Filing Extraction

**Selectors** (adaptive):
- Tries multiple selector patterns to handle eProc UI variations
- Falls back gracefully if selectors don't match
- Logs detailed selector errors for debugging

**Deduplication**:
- Queries database for filings with same content in last 5 entries
- Prevents inserting duplicate rows on repeated runs
- Stores filings with `status=new` for later analysis

### Error Handling

| Error | Behavior |
|-------|----------|
| Page timeout | Retry up to 3 times, log error |
| Selector not found | Skip that field, continue extraction |
| Auth failure | Fail fast, don't process other cases |
| Database error | Log, rollback transaction, continue |

### Logging

Structured JSON logging to both file and console:

```json
{
  "timestamp": "2026-06-12T10:30:00.000000",
  "level": "INFO",
  "logger": "eproc_scraper",
  "message": "Found 3 new filings",
  "case_number": "0001234-56.2026.8.26.0100",
  "filing_count": 3
}
```

**Log Levels**:
- `INFO` — Successful actions (authenticated, filings saved)
- `WARNING` — Timeouts, retries
- `ERROR` — Authentication failure, DB errors, unhandled exceptions
- `DEBUG` — Selector mismatches, row parsing

## Customization

### Change eProc Portal

Edit `EPROC_BASE_URL` in `.env` or `config.py`:

```bash
EPROC_BASE_URL=https://eproc.tjmg.jus.br  # For Minas Gerais
```

Then adapt selectors in `scraper.py` → `_search_and_extract_filings()` to match new portal's HTML.

### Adjust Timeout/Retries

```bash
EPROC_TIMEOUT_MS=60000        # 60 seconds
EPROC_RETRY_ATTEMPTS=5        # Retry 5 times
```

### Change Log Level

```bash
LOG_LEVEL=DEBUG               # Verbose logging
LOG_FILE=/var/log/scraper.log # Custom log path
```

## Integration with Step 1

The scraper imports models from Step 1:

```python
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case, Filing, FilingStatusEnum
```

**Requires**: Step 1 database already running with `cases` table populated.

## Integration with Celery (Step 8)

This scraper will be wrapped as a Celery task:

```python
@celery_app.task
def task_periodic_scraping():
    asyncio.run(main())
```

Then scheduled via Celery Beat to run hourly/daily.

## Troubleshooting

### "AuthenticationError: Could not find username field"

**Causes**:
- eProc UI changed (layout selector mismatch)
- Site requires CAPTCHA
- Username/password incorrect

**Fix**:
- Run with `HEADLESS_MODE=false` to see browser
- Update selectors in `auth.py`
- Test credentials manually

### "TimeoutError: Waiting for selector timed out"

**Causes**:
- Network slow
- Portal under load
- JavaScript not loading

**Fix**:
- Increase `EPROC_TIMEOUT_MS`
- Check network connectivity
- Try during off-peak hours

### "No active cases found"

**Cause**: No cases in database or all marked inactive

**Fix**:
```python
from models import Case
session.query(Case).update({Case.active: True})
session.commit()
```

### "ModuleNotFoundError: No module named 'models'"

**Cause**: Step 1 not set up or path incorrect

**Fix**: Ensure Step 1 exists in parent directory and has `models.py`

## Performance Characteristics

| Operation | Time |
|-----------|------|
| Authentication | 5-10 seconds (first run) |
| Authentication (cached) | <1 second |
| Case search & extract | 3-5 seconds per case |
| Database save | <100ms per filing |
| Full scrape (5 cases) | ~30 seconds |

## Future Enhancements

- [ ] Implement certificate-based auth (A1/A3)
- [ ] Add proxy/VPN support for geo-restricted portals
- [ ] Implement parallel case scraping
- [ ] Add screenshot on error for debugging
- [ ] Support for other portals (PJe, Jusbrasil)

## Integration Points

**Uses from Step 1**:
- `Case` model — filter active cases
- `Filing` model — store extracted filings
- `FilingStatusEnum` — mark status as `new`
- Database connection — deduplication & saving

**Used by Step 5** (Filing Analysis):
- Reads filings with `status=new`
- Updates status to `analyzed`
- Creates analysis records

## Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| scraper.py | 350 | Core Playwright logic |
| auth.py | 200 | Authentication + session |
| config.py | 30 | Configuration from env |
| logging_config.py | 80 | Structured logging |
| scraper_run.py | 130 | CLI entry point |
| test_scraper.py | 240 | Test suite |

---

**Status**: ✓ Ready to run against test eProc instance or staging environment

Next step: Step 3 (RAG Example Bank Indexing)
