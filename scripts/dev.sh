#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Install backend dependencies first; see README.md." >&2
  exit 1
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "Run npm --prefix frontend ci first." >&2
  exit 1
fi
.venv/bin/uvicorn cheaper_air.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend/src &
backend_pid=$!
cleanup() { kill "$backend_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
npm --prefix frontend run dev -- --port 5173 --strictPort
