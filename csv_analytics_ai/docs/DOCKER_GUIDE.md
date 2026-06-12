# Docker Setup Guide

```bash
cd /mnt/c/Users/Leal/AI_Projects/time_series_analysis_agent

#1ª vez / mudou Dockerfile ou requirements
docker compose up --build

#ts-agent-db + ts-agent-api
docker compose up db api

#ts-agent-frontend
docker compose up frontend
```
Já está rodando e mudou .py do back -> Nada só salvar e testar

Wait for both services to be ready:
- `ts-agent-db` — Postgres healthy
- `ts-agent-api` — Uvicorn running on http://0.0.0.0:8000
- `ts-agent-frontend`- docker compose up frontend

**API docs:**
Open http://127.0.0.1:8000/docs in your browser

All stopped containers:
```bash
docker container prune -f
```
All unused images, networks, and build cache:
```bash
docker system prune -a
```
Everything including volumes (deletes DB data, etc.):

```bash
docker system prune -a --volumes
```