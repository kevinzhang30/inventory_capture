"""Headless multi-station simulator (design §12 phase 4).

    python -m simulator.run --api http://localhost:8080 --stations 50 --rate 2000 --duration 600 \
        --doc-ratio 0.02 --site DAL1 --parts 2000 [--duplicate-ratio 0.01]

Each station paces batches (≤ 50) to hit its share of --rate. Document captures render a synthetic slip,
upload it via the presign route, and write the `<s3_key>.truth.json` sidecar straight to S3 (the local S3 mock)
for the stub extractor (docs/CONTRACTS.md §13).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx

from capture_client.ids import new_capture_id
from capture_client.slips import random_truth, render_packing_slip
from simulator.catalog import bin_locations, parts, receiving_location
from simulator.stats import Stats


def auth_headers(mode: str, token: str | None) -> dict[str, str]:
    if mode == "bearer":
        return {"authorization": f"Bearer {token}"}
    return {"x-dev-user": "simulator", "x-dev-groups": "operator"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Simulator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.rng = random.Random(args.seed)
        self.parts = parts(args.parts)
        self.locations = bin_locations(args.site)
        self.headers = auth_headers(args.auth_mode, args.token)
        self.stats = Stats()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.s3 = None
        if args.sidecar_s3_endpoint or args.bucket:
            import boto3

            self.s3 = boto3.client(
                "s3", endpoint_url=args.sidecar_s3_endpoint or None,
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )

    def scan(self, station: str) -> dict[str, Any]:
        p = self.rng.choice(self.parts)
        return {"capture_id": new_capture_id(), "site_id": self.args.site, "station_id": station, "kind": "scan",
                "captured_at": now_iso(),
                "payload": {"sku": p["sku"], "qty": self.rng.randint(1, 20),
                            "location_id": self.rng.choice(self.locations)}}

    async def document(self, client: httpx.AsyncClient, station: str) -> dict[str, Any] | None:
        cid = new_capture_id()
        truth = random_truth(self.rng, self.parts)
        png = await asyncio.get_running_loop().run_in_executor(self.pool, render_packing_slip, truth,
                                                               self.rng.randint(0, 1 << 30))
        r = await client.post("/uploads", json={"capture_id": cid, "content_type": "image/png"}, headers=self.headers)
        if r.status_code != 200:
            self.stats.http_errors[f"uploads:{r.status_code}"] += 1
            return None
        pre = r.json()
        put = await client.put(pre["url"], content=png, headers=pre.get("headers") or {})
        if put.status_code >= 300:
            self.stats.http_errors[f"put:{put.status_code}"] += 1
            return None
        if self.s3 is not None:
            body = json.dumps({k: truth[k] for k in ("supplier", "supplier_name", "po_number", "line_items")})
            await asyncio.get_running_loop().run_in_executor(
                self.pool, lambda: self.s3.put_object(Bucket=self.args.bucket, Key=f"{pre['s3_key']}.truth.json",
                                                      Body=body.encode(), ContentType="application/json"))
        self.stats.documents += 1
        return {"capture_id": cid, "site_id": self.args.site, "station_id": station, "kind": "document",
                "captured_at": now_iso(),
                "payload": {"s3_key": pre["s3_key"], "content_type": "image/png",
                            "location_id": receiving_location(self.args.site)}}

    async def post_batch(self, client: httpx.AsyncClient, batch: list[dict[str, Any]]) -> None:
        started = time.perf_counter()
        try:
            r = await client.post("/captures", json={"captures": batch}, headers=self.headers)
        except httpx.HTTPError as exc:
            self.stats.http_errors[type(exc).__name__] += 1
            return
        self.stats.latencies_ms.append((time.perf_counter() - started) * 1000)
        if r.status_code != 202:
            self.stats.http_errors[str(r.status_code)] += 1
            return
        self.stats.captures_sent += len(batch)
        for res in r.json()["results"]:
            self.stats.statuses[res["status"] if not res.get("error") else f"{res['status']}:{res['error']}"] += 1

    async def station(self, client: httpx.AsyncClient, idx: int, deadline: float) -> None:
        a = self.args
        name = f"{a.site}-SIM-{idx:03d}"
        per_station = a.rate / a.stations
        batch_size = max(1, min(50, round(per_station * a.batch_interval)))
        interval = batch_size / per_station
        next_at = time.monotonic() + self.rng.uniform(0, interval)  # spread station phases
        recent: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))
            next_at += interval
            batch: list[dict[str, Any]] = []
            for _ in range(batch_size):
                if self.rng.random() < a.doc_ratio:
                    doc = await self.document(client, name)
                    if doc:
                        batch.append(doc)
                else:
                    batch.append(self.scan(name))
            if recent and self.rng.random() < a.duplicate_ratio:
                batch = recent  # simulate a client retry of an already-acknowledged batch
            if batch:
                await self.post_batch(client, batch)
                recent = batch

    async def run(self) -> dict[str, Any]:
        limits = httpx.Limits(max_connections=self.args.stations * 2, max_keepalive_connections=self.args.stations)
        async with httpx.AsyncClient(base_url=self.args.api, timeout=30, limits=limits) as client:
            started = time.monotonic()
            deadline = started + self.args.duration
            reporter = asyncio.create_task(self.report(started))
            await asyncio.gather(*(self.station(client, i, deadline) for i in range(self.args.stations)))
            reporter.cancel()
            return self.stats.summary(time.monotonic() - started)

    async def report(self, started: float) -> None:
        while True:
            await asyncio.sleep(10)
            elapsed = time.monotonic() - started
            print(json.dumps({"t": round(elapsed), **self.stats.summary(elapsed)}), flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--stations", type=int, default=10)
    ap.add_argument("--rate", type=float, default=100, help="captures per second, all stations")
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--doc-ratio", type=float, default=0.02)
    ap.add_argument("--duplicate-ratio", type=float, default=0.0)
    ap.add_argument("--batch-interval", type=float, default=0.5, help="target seconds between a station's batches")
    ap.add_argument("--site", default="DAL1")
    ap.add_argument("--parts", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--auth-mode", choices=["dev", "bearer"], default=os.environ.get("SIM_AUTH_MODE", "dev"))
    ap.add_argument("--token", default=os.environ.get("SIM_TOKEN"))
    ap.add_argument("--sidecar-s3-endpoint", default=os.environ.get("SIM_S3_ENDPOINT", "http://localhost:9000"))
    ap.add_argument("--bucket", default=os.environ.get("SIM_BUCKET", "captures"))
    return ap.parse_args(argv)


def main() -> None:
    summary = asyncio.run(Simulator(parse_args()).run())
    print(json.dumps({"final": summary}, indent=2))


if __name__ == "__main__":
    main()
