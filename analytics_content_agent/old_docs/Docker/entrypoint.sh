#!/usr/bin/env bash
set -euo pipefail

: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"

mkdir -p /app/outputs /app/runs

echo "Starting Analytics Content Agent on ${HOST}:${PORT}"
exec uvicorn main:app --host "${HOST}" --port "${PORT}"
