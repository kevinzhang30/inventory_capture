#!/usr/bin/env bash
# Runs the ledger consistency checks against the local Postgres container.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T postgres psql -U inventory -d inventory -v ON_ERROR_STOP=1 < ../loadtest/sql/verify_movements.sql
