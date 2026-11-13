#!/usr/bin/env bash
# Production start: one worker only – the import lock, rate limiters and the data snapshot live in the process.
# Run behind nginx (deploy/nginx.conf); FORWARDED_ALLOW_IPS must list only the proxy that talks to the API.
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m uvicorn app.main:app \
  --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-8010}" \
  --workers 1 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --no-server-header --timeout-keep-alive 15
