#!/usr/bin/env bash
set -e

echo "Running NCERT ingest..."
python scripts/ingest_ncert.py --dir data --truncate-first

echo "Starting FastAPI..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"