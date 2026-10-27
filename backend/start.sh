#!/usr/bin/env bash
# Starts the API on http://127.0.0.1:8010 (the frontend proxies /api to it). macOS / Linux counterpart of start.ps1.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-dev.txt
fi
[ -f .env ] || .venv/bin/python scripts/generate_env.py
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
