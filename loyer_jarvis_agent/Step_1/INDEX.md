# Step 1 File Index & Navigation Guide

A guide to all files in Step 1 and how to use them.

---

## 📋 Documentation (Start Here)

Read these first to understand what's in this step:

| File | Purpose | Time | Priority |
|------|---------|------|----------|
| **QUICKSTART.md** | Get database running in 5 minutes | 5 min | 🔴 START |
| **README.md** | Complete reference (setup, models, testing) | 20 min | 🟡 THEN |
| **COMPLETION_REPORT.md** | What was built, checklist, test results | 10 min | 🟡 THEN |
| **IMPLEMENTATION_NOTES.md** | Design decisions explained in depth | 30 min | 🟢 OPTIONAL |
| **INDEX.md** | This file — navigation guide | 5 min | 🟢 OPTIONAL |

### Quick Decision Tree

```
Q: "How do I get this running?"
A: Read QUICKSTART.md

Q: "How do I use the database?"
A: Read README.md → Models Reference section

Q: "Why was it designed this way?"
A: Read IMPLEMENTATION_NOTES.md

Q: "Is everything done?"
A: Read COMPLETION_REPORT.md → Verification Checklist
```

---

## 🗄️ Core Code Files

The actual implementation:

| File | Lines | Purpose | How to Use |
|------|-------|---------|-----------|
| **models.py** | 160 | SQLAlchemy ORM models for all 7 tables | Import: `from models import User, Case, Filing, ...` |
| **database.py** | 30 | Database connection & session management | Import: `from database import SessionLocal, get_db` |
| **test_database.py** | 200 | End-to-end test script | Run: `python test_database.py` |

### Understanding the Code Flow

```python
# 1. Define models (models.py)
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    # ...

# 2. Connect to database (database.py)
from database import SessionLocal
session = SessionLocal()

# 3. Use models (anywhere)
user = User(name="John Doe", email="john@example.com")
session.add(user)
session.commit()

# 4. Query back
retrieved = session.query(User).filter_by(name="John Doe").first()
print(retrieved.email)  # john@example.com
```

---

## 🔄 Database Migration Files

Version control for your schema:

| File | Purpose |
|------|---------|
| **alembic.ini** | Alembic configuration (database URL, logging, etc.) |
| **alembic/env.py** | Migration environment (sets up SQLAlchemy connection) |
| **alembic/versions/__init__.py** | Makes versions a package |
| **alembic/versions/001_initial_schema.py** | Initial migration (creates all tables + pgvector setup) |

### Migration Workflow

```bash
# Apply migrations
alembic upgrade head

# Check status
alembic current      # Current revision
alembic history      # All revisions

# Rollback (if needed)
alembic downgrade base  # To empty schema
alembic downgrade 001   # To specific revision
```

---

## 🐳 Docker & Environment

Get PostgreSQL running locally:

| File | Purpose | Usage |
|------|---------|-------|
| **docker-compose.yml** | One-command PostgreSQL + pgvector setup | `docker-compose up -d` |
| **init_db.sql** | Database initialization script | Auto-run by Docker |
| **.env.example** | Connection string template | `cp .env.example .env` |
| **.env** | Your actual connection string | Not in Git, created locally |

### Docker Commands

```bash
# Start database
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs postgres

# Connect to database
docker exec -it legal_assistant_db psql -U legaluser -d legal_assistant_db

# Stop database
docker-compose down

# Clean everything and restart
docker-compose down -v
docker-compose up -d
```

---

## 📦 Configuration Files

Python packaging & dependencies:

| File | Purpose | Edit When |
|------|---------|-----------|
| **requirements.txt** | Pinned dependency versions | Adding new library |
| **pyproject.toml** | Python package metadata | Changing project info |
| **.gitignore** | Files to exclude from Git | Adding new pattern (DB, logs, env vars) |
| **__init__.py** | Package marker | Leave as-is |

### Installing Dependencies

```bash
# Install all
pip install -r requirements.txt

# Install with dev tools (testing, linting)
pip install -e ".[dev]"

# Update a library
pip install --upgrade sqlalchemy
pip freeze | grep sqlalchemy > requirements.txt
```

---

## 📊 What Each Table Does

Quick reference for database schema:

### Core Tables (The Pipeline)

```
Filing (raw court document)
    ↓
Analysis (AI decides: action needed?)
    ↓
Task (what needs to be done)
    ↓
Draft (generated document)
```

| Table | Row Count (3 yr) | Purpose |
|-------|-----------------|---------|
| **users** | 1 | Lawyer profile + Google Calendar token |
| **cases** | 50 | Legal cases under monitoring |
| **filings** | 900 | Court documents/publications (5 per case/month) |
| **analyses** | 900 | AI analysis (1 per filing) |
| **tasks** | 3,600 | Actions extracted (4 per analysis avg) |
| **drafts** | 10,800 | Document versions (3 per task) |
| **example_bank** | 1,800 | Past examples for RAG similarity search |

---

## 🧪 Testing

How to verify everything works:

```bash
# Full test
python test_database.py

# Specific checks
psql -d legal_assistant_db -c "SELECT COUNT(*) FROM users;"
psql -d legal_assistant_db -c "\dt"  # List all tables
psql -d legal_assistant_db -c "SELECT * FROM pg_stat_indexes;"  # Check indexes
```

### Test Output

The test script:
1. Creates 1 user, 1 case, 1 filing, 1 analysis, 1 task, 1 draft, 1 example
2. Retrieves each and verifies relationships work
3. Checks embedding dimension is 1536
4. Prints statistics

**Expected**: All `✓` checkmarks, no errors.

---

## 🚀 Getting Started Paths

### Path 1: Fastest Setup (5 minutes)

```bash
cd Step_1
docker-compose up -d
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
python test_database.py
```

→ See `QUICKSTART.md` for details

### Path 2: Using Existing PostgreSQL

```bash
# Ensure PostgreSQL + pgvector installed
createdb legal_assistant_db
psql -d legal_assistant_db -c "CREATE EXTENSION vector;"

# Then:
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
python test_database.py
```

→ See `README.md` → Prerequisites section

### Path 3: Understanding the Design

```bash
# Read in order:
1. README.md (Models Reference section)
2. models.py (look at the code)
3. IMPLEMENTATION_NOTES.md (design decisions)
```

→ See `IMPLEMENTATION_NOTES.md` for deep dive

---

## 🔍 Common Tasks

### "I want to add a new column to users"

```bash
# 1. Edit models.py
class User(Base):
    phone = Column(String(20), nullable=True)  # Add this

# 2. Create migration
alembic revision --autogenerate -m "Add phone to users"

# 3. Review alembic/versions/XXX_add_phone_to_users.py
# 4. Apply it
alembic upgrade head

# 5. Test
python test_database.py
```

### "I want to check if the database is running"

```bash
psql -U legaluser -d legal_assistant_db -h localhost -c "SELECT COUNT(*) FROM users;"
```

### "I want to reset the database"

```bash
alembic downgrade base      # Remove all tables
alembic upgrade head        # Re-create everything
```

### "I want to query the database directly"

```python
from database import SessionLocal
from models import Case, Filing

session = SessionLocal()
cases = session.query(Case).filter(Case.active == True).all()
print(f"Found {len(cases)} active cases")

# With relationships
for case in cases:
    print(f"Case: {case.case_number}")
    for filing in case.filings:
        print(f"  - Filing: {filing.status}")
```

---

## 📞 When You're Stuck

| Problem | Solution |
|---------|----------|
| "How do I run this?" | Read `QUICKSTART.md` |
| "How do I use the database?" | Read `README.md` |
| "Why was it designed this way?" | Read `IMPLEMENTATION_NOTES.md` |
| "Database won't connect" | Check `.env`, see `README.md` → Common Issues |
| "pgvector extension missing" | See `README.md` → Prerequisites |
| "Test fails" | Check `COMPLETION_REPORT.md` → Test Results for expected output |
| "Migration fails" | Check `alembic.ini` and `.env` |

---

## 📈 Next Steps

After Step 1 is working:

**Step 2**: Build the eProc Scraper
- Will insert into `filings` table
- Uses same database connection
- Entry point: `from models import Case, Filing; session = SessionLocal()`

**Step 3**: Populate RAG Example Bank
- Will insert embeddings into `example_bank` table
- Uses LangChain for chunking + embeddings
- Entry point: `example = ExampleBank(...); session.add(example)`

---

## 📚 File Sizes

| File | Lines | Type | Role |
|------|-------|------|------|
| models.py | 160 | Code | Define schema |
| database.py | 30 | Code | Connect to DB |
| test_database.py | 200 | Code | Verify it works |
| alembic/env.py | 40 | Code | Migration setup |
| 001_initial_schema.py | 150 | SQL | Create tables |
| README.md | 400+ | Docs | Full reference |
| QUICKSTART.md | 150+ | Docs | Fast setup |
| IMPLEMENTATION_NOTES.md | 400+ | Docs | Deep dive |
| COMPLETION_REPORT.md | 300+ | Docs | What was built |

**Total**: ~1,600 lines of well-documented code + setup

---

## 🎯 Success Criteria (All Met ✓)

- [x] `alembic upgrade head` creates all tables
- [x] `python test_database.py` passes without errors
- [x] Can insert and retrieve data
- [x] Embeddings store 1536-dimensional vectors
- [x] Relationships work (joining tables)
- [x] Documentation is complete
- [x] Docker Compose setup works

---

## 📞 Support

- **Setup help**: `QUICKSTART.md`
- **Reference**: `README.md`
- **Troubleshooting**: `README.md` → Common Issues section
- **Design questions**: `IMPLEMENTATION_NOTES.md`
- **What's done**: `COMPLETION_REPORT.md`

---

**Ready to start?** → Open `QUICKSTART.md` and follow the 5-minute setup.
