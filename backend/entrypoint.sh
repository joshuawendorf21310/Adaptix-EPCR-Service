#!/bin/sh
set -eu

SERVICE_NAME="${SERVICE_NAME:-epcr-backend}"
APP_MODULE="${APP_MODULE:-epcr_app.main:app}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"

echo "Starting ${SERVICE_NAME}"

if [ -f "/app/alembic.ini" ]; then
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "DATABASE_URL is required because /app/alembic.ini exists"
    exit 1
  fi
fi

python - <<'PY'
import socket
import sys
import time

host = "postgres"
port = 5432
deadline_seconds = 60
started_at = time.time()

while True:
    try:
        with socket.create_connection((host, port), timeout=3):
            print("postgres is reachable")
            break
    except OSError as exc:
        if time.time() - started_at >= deadline_seconds:
            print(f"postgres was not reachable at {host}:{port} after {deadline_seconds} seconds: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"waiting for postgres at {host}:{port}: {exc}")
        time.sleep(2)
PY

if [ -f "/app/alembic.ini" ]; then
  echo "Running Alembic migrations for ${SERVICE_NAME}"
  alembic upgrade head
fi

echo "Starting Uvicorn for ${SERVICE_NAME} with ${APP_MODULE}"
exec uvicorn "${APP_MODULE}" --host "${APP_HOST}" --port "${APP_PORT}"
