#!/usr/bin/env bash
# End-to-end smoke test: POST a scan, then poll GET /stock until it is visible (Phase 1 exit criterion).
set -euo pipefail
API="${API:-http://localhost:8080}"
SKU="${SKU:-SKU-000001}"
LOC="${LOC:-DAL1-A01-01}"
TIMEOUT_S="${TIMEOUT_S:-10}"
H=(-H "content-type: application/json" -H "x-dev-user: smoke" -H "x-dev-groups: operator,reviewer")

on_hand() {
  curl -fsS "${H[@]}" "$API/stock/$SKU" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(next((l['on_hand'] for l in d['locations'] if l['location_id'] == '$LOC'), 0))"
}

before=$(on_hand)
cid=$(python3 -c 'import os, time, uuid
ms = int(time.time() * 1000); r = int.from_bytes(os.urandom(10), "big")
v = (ms << 80) | (0x7 << 76) | ((r >> 64) & 0xFFF) << 64 | (0b10 << 62) | (r & ((1 << 62) - 1))
print(uuid.UUID(int=v))')
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
body="{\"captures\":[{\"capture_id\":\"$cid\",\"site_id\":\"DAL1\",\"station_id\":\"DAL1-SMOKE\",\"kind\":\"scan\",\"captured_at\":\"$now\",\"payload\":{\"sku\":\"$SKU\",\"qty\":3,\"location_id\":\"$LOC\"}}]}"
resp=$(curl -fsS "${H[@]}" -X POST "$API/captures" -d "$body")
echo "ingest: $resp"
echo "$resp" | grep -q '"accepted"' || { echo "capture not accepted"; exit 1; }

start=$(date +%s)
while true; do
  now_val=$(on_hand)
  if [ "$now_val" -ge $((before + 3)) ]; then
    echo "OK: $SKU@$LOC $before -> $now_val in $(( $(date +%s) - start ))s"
    exit 0
  fi
  if [ $(( $(date +%s) - start )) -ge "$TIMEOUT_S" ]; then
    echo "FAIL: stock not visible after ${TIMEOUT_S}s (before=$before now=$now_val)"
    exit 1
  fi
  sleep 0.2
done
