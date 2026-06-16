# Quick Start — 5 Minutes to Running Database

## Option A: Using Docker (Recommended)

**Fastest way to get PostgreSQL + pgvector running.**

### 1. Start Database

```bash
cd Step_1
docker-compose up -d
```

Wait for health check to pass:
```bash
docker ps  # Should show postgres container healthy
```

### 2. Update .env

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env`:
```
DATABASE_URL=postgresql://legaluser:securepassword@localhost:5432/legal_assistant_db
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply Migrations

```bash
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl with dialect postgresql
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, initial schema
```

### 5. Test

```bash
python test_database.py
```

Expected:
```
Testing User creation...
✓ User created: John Doe (ID: 1)
...
✓ ALL TESTS PASSED!
```

**Done!** Your database is ready for Step 2.

---

## Option B: Using Existing PostgreSQL

**If you already have PostgreSQL + pgvector installed.**

### 1. Create Database

```bash
psql -U postgres
CREATE DATABASE legal_assistant_db;
\c legal_assistant_db
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

### 2. Update .env

```bash
cp .env.example .env
```

Edit with your credentials:
```
DATABASE_URL=postgresql://your_user:your_password@localhost:5432/legal_assistant_db
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply Migrations

```bash
alembic upgrade head
```

### 5. Test

```bash
python test_database.py
```

---

## Verify Everything Works

```bash
# Connect directly to database
psql -U legaluser -d legal_assistant_db -h localhost

# List tables
\dt

# Check pgvector
\dx vector

# Count rows (after test_database.py)
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM example_bank;

# Exit
\q
```

---

## Common Issues & Fixes

### "pg_isready: could not translate host name"

**Fix**: Ensure PostgreSQL is running
```bash
# If using Docker
docker-compose up -d

# If using local PostgreSQL
sudo service postgresql start  # Linux
brew services start postgresql  # macOS
```

### "FATAL: database \"legal_assistant_db\" does not exist"

**Fix**: Create the database first (Option B Step 1)

### "CreateExtensionError: pgvector extension not found"

**Fix**: pgvector not installed in your PostgreSQL
```bash
# Ubuntu/Debian
sudo apt-get install postgresql-14-pgvector

# macOS
brew install pgvector

# Then create extension
psql -d legal_assistant_db -c "CREATE EXTENSION vector;"
```

### "ModuleNotFoundError: No module named 'sqlalchemy'"

**Fix**: Install dependencies
```bash
pip install -r requirements.txt
```

### "SQLAlchemy error: (psycopg2.OperationalError) ... refused"

**Fix**: Wrong database URL in `.env`
```bash
# Test connection
python -c "from database import engine; print(engine.execute('SELECT 1'))"

# If fails, check .env
cat .env
```

---

## Next Steps

Once `test_database.py` passes:

1. ✓ Schema is ready
2. → Go to **Step 2**: Implement eProc scraper
3. → Step 2 will insert test data into `filings` table

---

## Cleanup (If Starting Over)

### Drop Everything and Restart

```bash
# Using Docker
docker-compose down -v  # -v removes volume/data
docker-compose up -d
alembic upgrade head
python test_database.py

# Using local PostgreSQL
psql -U postgres -c "DROP DATABASE IF EXISTS legal_assistant_db;"
psql -U postgres -c "CREATE DATABASE legal_assistant_db;"
psql -U postgres -d legal_assistant_db -c "CREATE EXTENSION vector;"
alembic upgrade head
python test_database.py
```

---

## Useful Commands

```bash
# Check Alembic status
alembic current
alembic history

# View current database structure
\d  # (in psql)

# Count records in each table
SELECT 'users' as table_name, COUNT(*) as count FROM users
UNION ALL SELECT 'cases', COUNT(*) FROM cases
UNION ALL SELECT 'filings', COUNT(*) FROM filings;

# Rollback (dangerous!)
alembic downgrade base  # Goes to empty schema
```

---

**That's it!** You now have a working database schema with vector support. Ready to scrape filings in Step 2.
