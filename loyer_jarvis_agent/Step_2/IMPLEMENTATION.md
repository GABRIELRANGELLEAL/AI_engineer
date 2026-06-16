# Implementation Architecture — Step 2 Deep Dive

## Code Organization & Design Decisions

### Async/Await Pattern

**Why async?**
eProc portal pages load dynamically (JavaScript). Blocking I/O would waste time waiting for network.

```python
# Async allows this pattern:
async def scrape_case(case):
    filings = await self.get_new_filings(case)     # Network wait (non-blocking)
    count = await self.save_filings(case.id, filings)  # DB write (non-blocking)
```

**Browser lifecycle**:
```python
await scraper.start_browser()  # Once at startup
# ... use scraper for multiple cases ...
await scraper.stop_browser()   # Once at shutdown
```

Reusing browser context across cases is 10x faster than creating new browser per case.

### Scraper Class Design

**`EprocScraper`** — Main class encapsulating:
- Browser/context lifecycle
- Authentication (delegates to `AuthenticationManager`)
- Case navigation + filing extraction
- Database integration
- Error handling + retry logic

**Key methods**:

| Method | Purpose | Async |
|--------|---------|-------|
| `start_browser()` | Launch Chromium, create context | Yes |
| `stop_browser()` | Cleanup | Yes |
| `get_new_filings(case)` | Navigate, extract, filter | Yes |
| `_search_and_extract_filings(page, case_number)` | Portal interaction | Yes |
| `_extract_docket_entries(page)` | Parse HTML/DOM | Yes |
| `_filter_existing_filings(case_id, filings)` | Database dedup | Yes |
| `save_filings(case_id, filings)` | Insert to DB | No (sync) |
| `scrape_case(case)` | Full pipeline with retries | Yes |

**Why `save_filings` is sync**:
SQLAlchemy ORM is synchronous. Could be async with `sqlalchemy.ext.asyncio`, but simpler to block briefly for DB.

### Selector Strategy (Robustness)

eProc layouts vary. Solution: **Try multiple selectors**.

```python
login_selectors = [
    'a[href*="login"]',
    'button:has-text("Entrar")',
    'button:has-text("Login")',
]

for selector in login_selectors:
    try:
        await page.click(selector, timeout=5000)
        break
    except:
        continue
```

**Advantages**:
- Gracefully handles UI variations
- Adapts to different tribunal portals
- No hard failure on selector mismatch

**Downside**:
- Slower (tries multiple selectors)
- Could be optimized with better selector detection

### RawFiling Data Class

```python
@dataclass
class RawFiling:
    date: datetime
    content: str
    filing_type: Optional[str] = None
```

Simple intermediate format between Playwright extraction and database model.

**Why not use `Filing` model directly?**
- Model expects `filing_date` not `date`
- Model expects `case_id` (extracted here, not in scraper)
- Keeps extraction logic decoupled from ORM

### Authentication Design

**Session Manager** — Persistent cookies:

```python
SessionManager.save_session(context, lawyer_id)
# Saves to: ~/.playwright_session/session_{lawyer_id}.json

SessionManager.load_session(context, lawyer_id)
# Loads cookies, reusing session (no re-login needed)

SessionManager.is_session_valid(lawyer_id)
# Checks file age: valid for 30 days, then expires
```

**Why this approach?**
- Avoids repeated logins (fast)
- Sessions expire gracefully
- Per-lawyer session isolation

**Authenticators** — Strategy pattern:

```python
class AuthenticatorUsername:
    async def authenticate(page) -> bool: ...

class AuthenticatorCertificate:
    async def authenticate(page) -> bool: ...

# In AuthenticationManager:
if AUTH_METHOD == "certificate":
    success = await self.certificate_auth.authenticate(page)
else:
    success = await self.username_auth.authenticate(page)
```

Allows easy addition of new auth methods without changing core scraper.

### Deduplication Logic

```python
async def _filter_existing_filings(case_id, filings):
    existing = session.query(Filing)\
        .filter_by(case_id=case_id)\
        .order_by(Filing.filing_date.desc())\
        .limit(5).all()  # Only check last 5

    existing_contents = {f.raw_content for f in existing}
    return [f for f in filings if f.content not in existing_contents]
```

**Why check only last 5?**
- eProc typically has 1-3 new filings per scrape
- Avoids expensive full-table scan
- Assumption: new filings come at end of docket

**Why string comparison?**
- Simple, works
- Could use hash if content is huge

### Error Handling Strategy

**Timeouts** → Retry:
```python
for attempt in range(EPROC_RETRY_ATTEMPTS):
    try:
        filings = await self.get_new_filings(case)
        return filings
    except PlaywrightTimeoutError:
        if attempt == EPROC_RETRY_ATTEMPTS - 1:
            raise
```

**Selector mismatches** → Skip field, continue:
```python
for selector in selectors:
    try:
        content = await page.query_selector(selector)
        break
    except:
        continue

if not content:
    logger.error("Could not find field")
    content = ""  # Empty is better than crash
```

**Database errors** → Rollback & log:
```python
try:
    session.add(filing)
    session.commit()
except Exception as e:
    session.rollback()
    logger.error(f"DB error: {e}")
```

### Logging Architecture

**Structured logging** — JSON to file:

```json
{
  "timestamp": "2026-06-12T10:30:00Z",
  "level": "INFO",
  "case_number": "0001234-56...",
  "filing_count": 3,
  "message": "Found 3 new filings"
}
```

**Why JSON?**
- Machine parseable (analytics, alerts)
- Can be ingested by ELK/Splunk
- Structured fields for filtering

**LogContext** — Auto-attach case_number:

```python
with LogContext(case.case_number):
    await scraper.get_new_filings(case)
    # All logs in this block auto-include case_number
```

Cleaner than passing `logger` + context everywhere.

### Database Integration

**Import path**:
```python
sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))
from models import Case, Filing
```

**Why relative import?**
- Makes Step 2 independent (can be in different repo)
- Avoids hardcoded absolute paths
- Works from any working directory

**Session management**:
```python
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# In each method:
session = SessionLocal()
try:
    # Use session
finally:
    session.close()  # Always close
```

**Why close in finally?**
Prevents connection pool exhaustion.

### Configuration & Secrets

**Sensitive data** — Environment only:
- Database URL
- Credentials
- Paths

**Never in code**:
```python
# ✗ DON'T
EPROC_PASSWORD = "secretpassword123"

# ✓ DO
EPROC_PASSWORD = os.getenv("EPROC_PASSWORD")
```

**.env.example** — Template without secrets:
```bash
EPROC_PASSWORD=your_password_here  # Placeholder
```

Developers copy to `.env` and fill in their values.

## Performance Considerations

### Async Performance

**Bottleneck**:
- Network (waiting for pages) — mitigated by async
- JavaScript execution (10-30 seconds per case)

**Not parallelized** (yet):
- Currently scrapes cases sequentially
- Playwright supports concurrent page contexts
- Future: `asyncio.gather()` to scrape 5 cases in parallel

### Database Performance

**Single INSERT per filing**:
```python
session.add(Filing(...))
session.commit()  # Expensive: flush + commit
```

**Better for bulk** (if needed):
```python
session.add_all([Filing(...), Filing(...)])
session.commit()  # One flush
```

Currently fine (1-5 filings per case).

### Cookie Caching

**Impact**:
- First scrape: ~15 seconds (login)
- Subsequent: ~5 seconds (reuse session)

**Cache duration**: 30 days (tunable)

## Testing Strategy

**Components tested**:
1. Database connection — Can connect?
2. Database write — Can insert records?
3. Filing extraction — RawFiling creation works?
4. Authentication — (Requires credentials, optional)

**Not tested** (integration):
- Full end-to-end against real eProc (environment-dependent)
- Playwright selectors (will fail if eProc UI changes)

**Manual testing**:
```bash
python scraper_run.py --dry-run
# Shows filings found but doesn't save
```

## Integration with Celery (Step 8)

Future Celery wrapper:

```python
from celery import shared_task

@shared_task
def task_periodic_scraping():
    asyncio.run(main(case_id=None))
    # Runs hourly via Celery Beat

@celery_app.task
def task_analyze_filing(filing_id):
    # Called after filing saved
    filing = session.query(Filing).get(filing_id)
    analyze_filing(filing)
```

Scraper creates filings, Celery orchestrates downstream tasks.

## Known Limitations

1. **Selector brittleness** — UI changes break scraper
   - Solution: Implement selector detection / ML
   
2. **No parallel scraping** — One case at a time
   - Solution: `asyncio.gather()` for 5-10 concurrent cases
   
3. **No certificate auth** — Only username/password
   - Solution: Add pyOpenSSL, implement cert loading
   
4. **No CAPTCHA handling** — Will fail on CAPTCHA
   - Solution: Use anti-CAPTCHA service or manual intervention
   
5. **No session refresh** — Full re-login after 30 days
   - Solution: Implement refresh token flow if available

## Extension Points

### Add New Portal

```python
class PJeScraper(EprocScraper):
    async def _search_and_extract_filings(self, page, case_number):
        # PJe-specific selectors
        ...

scraper = PJeScraper()
```

### Add New Auth Method

```python
class AuthenticatorOAuth(Authenticator):
    async def authenticate(self, page) -> bool:
        # OAuth flow
        ...

# In config:
if AUTH_METHOD == "oauth":
    self.oauth_auth = AuthenticatorOAuth()
```

### Add Proxy Support

```python
context = await browser.new_context(
    proxy={
        "server": os.getenv("PROXY_URL"),
        "username": os.getenv("PROXY_USER"),
        "password": os.getenv("PROXY_PASS"),
    }
)
```

## Summary

**Step 2 design priorities**:
1. **Robustness** — Retry + fallback selectors
2. **Efficiency** — Session caching, async
3. **Maintainability** — Clear separation (scraper, auth, logging)
4. **Extensibility** — Strategy pattern for auth methods
5. **Observability** — Structured logging per case

**Key trade-offs**:
- Synchronous DB writes for simplicity (could be async)
- Sequential case scraping for clarity (could parallelize)
- Multiple selector attempts for robustness (slower)

All are tunable without architecture changes.
