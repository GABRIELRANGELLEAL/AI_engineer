# Docker Setup Guide

> **💡 NEW:** For full-stack testing with frontend + WSL, see [**WSL + Docker Setup Guide**](WSL_DOCKER_SETUP.md)

This guide focuses on API + PostgreSQL testing only.

## Quick Start

### 1. Start the full stack (API + PostgreSQL)

```bash
cd /mnt/c/Users/Leal/AI_Projects/time_series_analysis_agent
docker compose up --build
```

Wait for both services to be ready:
- `ts-agent-db` — Postgres healthy
- `ts-agent-api` — Uvicorn running on http://0.0.0.0:8000

### 2. Verify the setup

**Health check:**
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

**API docs:**
Open http://127.0.0.1:8000/docs in your browser

**Database tables:**
```powershell
docker exec -it ts-agent-db psql -U app -d analytics -c "\dt"
```

You should see `tasks` and `llm_interactions` tables.

---

## Test the Planner API

### Step A — Create task (first planner turn)

```powershell
$body = @{
  data_source_type = "csv"
  data_source_meta = @{ csv_path = "/app/docs/data.csv" }
  prompt = "Analyze this CSV and propose a step-by-step plan for time series analysis."
} | ConvertTo-Json -Depth 5

$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/tasks `
  -ContentType "application/json" -Body $body

$r | ConvertTo-Json -Depth 5
$taskId = $r.task_id
```

### Step B — Follow-up message

```powershell
$msg = @{ prompt = "Focus on trend and seasonality. Keep at most 5 steps." } | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/tasks/$taskId/messages" `
  -ContentType "application/json" -Body $msg | ConvertTo-Json -Depth 5
```

### Step C — Poll task state

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$taskId" | ConvertTo-Json -Depth 5
```

### Step D — List interactions

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$taskId/interactions" | ConvertTo-Json -Depth 5
```

### Step E — Proceed

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/tasks/$taskId/proceed" | ConvertTo-Json -Depth 5
```

### Step F — Verify messages blocked after proceed

```powershell
# Should return 400
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/tasks/$taskId/messages" `
  -ContentType "application/json" `
  -Body (@{ prompt = "one more question" } | ConvertTo-Json)
```

---

## Container Management

**Stop services:**
```powershell
docker compose down
```

**Stop and remove volumes (fresh DB):**
```powershell
docker compose down -v
```

**View logs:**
```powershell
# Both services
docker compose logs -f

# API only
docker compose logs -f api

# Database only
docker compose logs -f db
```

**Rebuild after code changes:**
```powershell
docker compose up --build
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 5432 or 8000 already in use | Stop other services using those ports |
| `ANTHROPIC_API_KEY not set` | Check `.env` file exists and has valid key |
| Database connection refused | Wait for `db` health check to pass |
| 500 on `/tasks` | Check API logs: `docker compose logs api` |

---

## Environment Variables

The `.env` file is used by the API container:

```env
DATABASE_URL=postgresql://app:app@db:5432/analytics
ANTHROPIC_API_KEY=sk-ant-...
```

**Note:** `db` is the Docker service name, not `localhost`.

---

## Development Mode

The `docker-compose.yml` mounts the current directory to `/app` in the container, so code changes trigger auto-reload.

To disable auto-reload (production-like):
```yaml
command: uvicorn main:app --host 0.0.0.0 --port 8000
```
