# Starts the API on http://127.0.0.1:8010 (the frontend proxies /api to it).
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements.txt }
if (-not (Test-Path .env)) { .\.venv\Scripts\python scripts\generate_env.py }
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
