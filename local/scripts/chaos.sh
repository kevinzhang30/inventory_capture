#!/usr/bin/env bash
# Chaos drill: SIGKILL a random consumer every INTERVAL seconds for DURATION seconds while load runs,
# then restart it. Afterwards run `make verify` (loadtest/sql/verify_movements.sql) — expect zero rows.
set -euo pipefail
cd "$(dirname "$0")/.."
DURATION="${DURATION:-300}"
INTERVAL="${INTERVAL:-20}"
read -r -a TARGETS <<< "${TARGETS:-extract cache-updater indexer reorder-checker outbox-relay review-dispatcher}"
end=$(( $(date +%s) + DURATION ))
while [ "$(date +%s)" -lt "$end" ]; do
  svc=${TARGETS[$((RANDOM % ${#TARGETS[@]}))]}
  echo "$(date -u +%T) killing $svc"
  docker compose --profile app kill -s SIGKILL "$svc" >/dev/null
  sleep "$(( (RANDOM % 5) + 1 ))"
  docker compose --profile app up -d "$svc" >/dev/null
  echo "$(date -u +%T) restarted $svc"
  sleep "$INTERVAL"
done
