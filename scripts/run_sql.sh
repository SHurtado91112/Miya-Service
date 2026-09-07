#!/usr/bin/env bash
set -euo pipefail

# Query the local Postgres DB. With no args, opens an interactive psql shell.
# With args, runs them as a one-off SQL command, e.g.:
#   ./scripts/run_sql.sh "SELECT count(*) FROM media_items;"

if [ "$#" -eq 0 ]; then
  exec docker compose exec postgres psql -U miya -d miya
else
  exec docker compose exec postgres psql -U miya -d miya -c "$*"
fi
