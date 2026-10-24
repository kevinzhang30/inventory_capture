"""Scan → stock-visible latency probe (NFR: p95 < 2 s).

    python -m simulator.latency_probe --api http://localhost:8080 --samples 100 --interval 1

Each sample: read GET /stock/{sku} (warms the cache), POST a +1 scan, then poll GET /stock/{sku} until
the location's on_hand reflects the delta.
"""

from __future__ import annotations

import argparse
import json
import random
import time

import httpx

from capture_client.ids import new_capture_id
from simulator.catalog import bin_locations
from simulator.run import auth_headers, now_iso
from simulator.stats import percentile


def on_hand(client: httpx.Client, sku: str, location_id: str, headers: dict[str, str]) -> int:
    r = client.get(f"/stock/{sku}", headers=headers)
    r.raise_for_status()
    return next((loc["on_hand"] for loc in r.json()["locations"] if loc["location_id"] == location_id), 0)


def probe(client: httpx.Client, sku: str, location_id: str, site: str, headers: dict[str, str],
          timeout_s: float, poll_s: float) -> float | None:
    before = on_hand(client, sku, location_id, headers)
    capture = {"capture_id": new_capture_id(), "site_id": site, "station_id": f"{site}-PROBE", "kind": "scan",
               "captured_at": now_iso(), "payload": {"sku": sku, "qty": 1, "location_id": location_id}}
    started = time.perf_counter()
    r = client.post("/captures", json={"captures": [capture]}, headers=headers)
    r.raise_for_status()
    if r.json()["results"][0]["status"] != "accepted":
        return None
    while time.perf_counter() - started < timeout_s:
        if on_hand(client, sku, location_id, headers) >= before + 1:
            return (time.perf_counter() - started) * 1000
        time.sleep(poll_s)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--samples", type=int, default=50)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--site", default="DAL1")
    ap.add_argument("--parts", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--poll", type=float, default=0.05)
    ap.add_argument("--auth-mode", choices=["dev", "bearer"], default="dev")
    ap.add_argument("--token")
    args = ap.parse_args()
    headers = auth_headers(args.auth_mode, args.token)
    rng = random.Random()
    locations = bin_locations(args.site)
    latencies, timeouts = [], 0
    with httpx.Client(base_url=args.api, timeout=10) as client:
        for i in range(args.samples):
            sku = f"SKU-{rng.randint(1, args.parts):06d}"
            ms = probe(client, sku, rng.choice(locations), args.site, headers, args.timeout, args.poll)
            if ms is None:
                timeouts += 1
            else:
                latencies.append(ms)
            print(json.dumps({"sample": i + 1, "sku": sku, "ms": round(ms, 1) if ms else None}), flush=True)
            time.sleep(args.interval)
    print(json.dumps({"scan_to_visible_ms": {f"p{p}": round(percentile(latencies, p), 1) for p in (50, 95, 99)},
                      "samples": len(latencies), "timeouts": timeouts,
                      "nfr_p95_lt_2000ms": percentile(latencies, 95) < 2000 if latencies else False}, indent=2))


if __name__ == "__main__":
    main()
