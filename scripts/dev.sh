#!/usr/bin/env bash
# Brings up a local dev environment: Postgres, migrations, seed data, and the API server.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d
until docker compose exec -T postgres pg_isready -U miya -d miya >/dev/null 2>&1; do
  sleep 1
done

uv run alembic upgrade head
uv run seed
uv run uvicorn miya_server.main:app --reload
