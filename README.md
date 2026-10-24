# Inventory Capture

Receiving-dock capture platform: a desktop app scans barcodes and photographs packing slips, an LLM extracts line items, low-confidence results go to a human review queue, and stock levels, search and dashboards stay current within seconds.

- Design: [inventory-capture-design.md](inventory-capture-design.md)
- Integration contracts (env vars, APIs, events, keys): [docs/CONTRACTS.md](docs/CONTRACTS.md)

```
Desktop (PySide6) ──► API Gateway ──► ingest ──► Kafka captures.raw ──► extract ──► Postgres (+ outbox)
                                  └─► core-api ◄── Redis / OpenSearch           │
                                                                                 ▼
             cache-updater / indexer / reorder-checker ◄── Kafka inventory.events ◄── outbox-relay ──► RabbitMQ
                                                                                   review-dispatcher ◄──┘
```

## Quickstart (local)

Requires Docker, Python 3.12+, Node 20.

```bash
make install      # .venv with every Python package (WITH_DESKTOP=1 for the PySide6 app)
make up           # Postgres, Kafka (KRaft), RabbitMQ, Valkey, OpenSearch, S3 mock + all services on :8080
make smoke        # scan → stock visible end to end
make web          # Next.js on http://localhost:3000 (dev identity switcher in the sidebar)
make desktop      # capture app against localhost:8080
make down         # stop and delete volumes
```

`make infra` starts only the data stores, so you can run any service on the host (`make bootstrap` prepares them).
Local auth uses `x-dev-user` / `x-dev-groups` headers; the extractor defaults to the deterministic stub
(`EXTRACTOR=bedrock make up` uses real Bedrock with your AWS credentials).

## Testing, load and resilience

| Command | What it does |
| --- | --- |
| `make test` | Unit tests (no infrastructure) |
| `make lint` / `make typecheck` | ruff + ESLint / mypy + tsc |
| `make test-integration` | DB-backed tests against `make up` |
| `make simulate RATE=2000 STATIONS=50 DURATION=600` | Headless multi-station simulator (scans + synthetic slips) |
| `make latency-probe` | Scan → visible latency percentiles (target p95 < 2 s) |
| `make loadtest-ingest` / `-stock` / `-search` | k6 scripts with the NFR thresholds |
| `make chaos` then `make verify` | SIGKILL random consumers under load, then check for lost or duplicated movements |
| `make rebuild-cache` / `make rebuild-index VERSION=2` | Rebuild Redis / OpenSearch from Postgres (alias swap) |
| `make eval-golden` / `make eval-run EXTRACTOR=bedrock` | Golden-set evaluation report in `eval/reports/` |

## AWS dev environment

```bash
cp infra/envs/dev/backend.hcl.example infra/envs/dev/backend.hcl          # state bucket + lock table
cp infra/envs/dev/terraform.tfvars.example infra/envs/dev/terraform.tfvars
make dev-up       # builds Lambda zips + relay image, applies Terraform, runs migrations/topics/indices
make dev-down     # destroys everything
```

See [infra/README.md](infra/README.md). CI (`.github/workflows/ci.yml`) runs lint, types, unit and integration tests;
`deploy.yml` deploys to dev on merge to `main` via GitHub OIDC.

## Layout

```
apps/web               Next.js 14 (dashboard, search, review workspace, eval dashboard)
apps/desktop           PySide6 capture app (HID wedge + camera barcode input, slip photos, offline outbox)
libs/common            Shared server library (config, db, outbox, Kafka/RabbitMQ/Redis/OpenSearch clients)
libs/capture_client    Desktop/simulator client: SQLite outbox, sync engine, synthetic slips
services/*             Lambdas: ingest, extract, cache_updater, indexer, reorder_checker, core_api,
                       review_dispatcher (+reorder/notify/reaper), eval_nightly, ops; ECS: outbox_relay
db/                    Alembic migrations + seed catalog
infra/                 Terraform modules + envs/dev
local/                 docker-compose stack, API Gateway emulator, smoke/chaos/verify scripts
loadtest/              k6 scripts, simulator, ledger verification SQL
eval/                  Golden set generator + offline harness
```

## Decisions on the design's open questions

- **Web hosting:** Amplify (keeps everything in one cloud and one Terraform state; optional via `enable_amplify`).
- **Local Kafka:** Apache Kafka 3.8 in KRaft mode (same client behaviour as MSK).
- **Desktop input:** both USB HID keyboard-wedge scanners and camera decoding feed the same scan session.
- **Bedrock in dev:** stub extractor locally (free, deterministic, uses ground-truth sidecars); Bedrock in the AWS dev environment.

## Deviations from the design

- `stock:{sku}` keeps a version per location (`_v:{location_id}`) instead of one `_v`, because `stock_level.version`
  is per (SKU, location). Cache-updater only writes keys that a full fill has populated (`_filled`), so a cold key
  never holds a partial set of locations.
- RabbitMQ retries are handled in the consumer: failures are republished to `<queue>.retry` (TTL) and then
  `<queue>.dlq` after five attempts, so one poison message cannot block a batch.
- Added `reorder_request` and `app_setting` tables (reorder audit trail; calibration-driven confidence threshold).
