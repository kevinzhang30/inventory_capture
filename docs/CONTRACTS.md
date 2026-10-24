# Inventory Capture — Integration Contracts

Every component builds against this file. If code and this file disagree, this file wins (fix the code).
Design rationale lives in `inventory-capture-design.md`.

## 0. Repository layout

```
apps/web                 Next.js 14 App Router (TypeScript)
apps/desktop             PySide6 capture app            (package: inventory_desktop)
libs/common              Shared server-side lib          (package: inventory_common)
libs/capture_client      Shared HTTP/outbox client       (package: capture_client)
services/<name>/<name>/  One Python package per Lambda / task, e.g. services/ingest/ingest/handler.py
services/ops             Bootstrap: Kafka topics, RabbitMQ topology, OpenSearch indices, migrations
db/                      Alembic migrations (db/migrations) + seed data (db/seed)
infra/                   Terraform modules + envs/dev
local/                   docker-compose stack + local API gateway emulator
loadtest/                k6 scripts + headless simulator
eval/                    Golden set + offline harness
```

Python 3.12, pydantic v2, psycopg 3, redis-py 5 (Valkey compatible), confluent-kafka, pika, opensearch-py, boto3.
Each Python package has its own `pyproject.toml` (hatchling). Lambda handler strings are `<package>.handler.handler`
unless stated otherwise. Lint: ruff; types: mypy.

## 1. Environment variables (read via `inventory_common.config.settings`)

| Var | Local default | AWS | Meaning |
| --- | --- | --- | --- |
| `APP_ENV` | `local` | `dev` | |
| `DATABASE_URL` | `postgresql://inventory:inventory@localhost:5432/inventory` | unset | Direct DSN |
| `DB_SECRET_ARN`, `DB_HOST`, `DB_PORT`, `DB_NAME` | unset | set | Secret JSON has `username`, `password` |
| `DB_POOL_MAX` | `5` | `2` | |
| `REDIS_URL` | `redis://localhost:6379/0` | `rediss://<serverless endpoint>:6379` | |
| `REDIS_CLUSTER` | `false` | `true` | Use `RedisCluster` client |
| `KAFKA_BOOTSTRAP` | `localhost:9092` | MSK bootstrap (IAM, 9098) | |
| `KAFKA_AUTH` | `none` | `iam` | `iam` → SASL_SSL + OAUTHBEARER via aws-msk-iam-sasl-signer |
| `TOPIC_CAPTURES_RAW` | `captures.raw` | same | |
| `TOPIC_INVENTORY_EVENTS` | `inventory.events` | same | |
| `RABBITMQ_URL` | `amqp://inventory:inventory@localhost:5672/%2F` | unset | |
| `RABBITMQ_SECRET_ARN`, `RABBITMQ_HOST` | unset | set | `amqps://user:pass@host:5671/%2F` is built from them |
| `RABBITMQ_QUEUE_TYPE` | `quorum` | `quorum` | |
| `OPENSEARCH_URL` | `http://localhost:9200` | `https://<domain endpoint>` | |
| `OPENSEARCH_AUTH` | `none` | `sigv4` | |
| `S3_BUCKET` | `captures` | bucket name | |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | unset | Server-side S3 endpoint (s3mock locally) |
| `S3_PUBLIC_ENDPOINT_URL` | `http://localhost:9000` | unset | Endpoint used when presigning for clients |
| `EXTRACTOR` | `stub` | `bedrock` | |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | configurable (inference profile ID OK) | |
| `PROMPT_VERSION` | `v1` | | |
| `CONFIDENCE_THRESHOLD` | `0.85` | | Fallback; `app_setting.confidence_threshold` overrides |
| `AUDIT_SAMPLE_RATE` | `0.05` | | |
| `AUTH_MODE` | `dev` | `cognito` | See §6 |
| `SNS_TOPIC_ARN` | unset | set | notify channel |
| `OUTBOX_BATCH_SIZE` | `500` | | |
| `OUTBOX_POLL_INTERVAL_MS` | `50` | | |
| `LOG_LEVEL` | `INFO` | | |
| `AWS_REGION` | `us-east-1` | | |

## 2. HTTP API (API Gateway HTTP API; locally `local/gateway` on :8080)

All bodies are JSON. All routes except `/health` need auth. Errors: `{"error": "<code>", "detail": "..."}`.

### ingest Lambda (`ingest.handler.handler`, raw API GW v2 payload format 2.0)

`POST /uploads` (operator, admin)
→ body `{"capture_id": "<uuidv7>", "content_type": "image/jpeg|image/png|application/pdf"}`
← 200 `{"url": "...", "s3_key": "captures/<site?>/<yyyy>/<mm>/<dd>/<capture_id>.<ext>", "expires_in": 300, "headers": {"Content-Type": "..."}}`

`POST /captures` (operator, admin) — batch of 1..50
→ body `{"captures": [Capture, ...]}`
← 202 `{"results": [{"capture_id": "...", "status": "accepted|duplicate|rejected", "error": null}]}`

```jsonc
// Capture
{
  "capture_id": "0192f...uuidv7",       // client generated
  "site_id": "DAL1",
  "station_id": "DAL1-DOCK-01",
  "operator_id": "op-123",              // overwritten server-side from token `sub` when present
  "kind": "scan" | "document",
  "captured_at": "2026-10-22T18:01:02.123Z",
  "payload": {
    // scan:
    "sku": "SKU-000123", "qty": 5, "location_id": "DAL1-A01-01"
    // document:
    // "s3_key": "captures/...", "content_type": "image/jpeg", "location_id": "DAL1-RECV-01", "po_number": "PO-1234" (optional hint)
  }
}
```

### core-api Lambda (`core_api.handler.handler`, FastAPI + Mangum)

| Method & path | Roles | Response |
| --- | --- | --- |
| `GET /health` | none | `{"status":"ok"}` |
| `GET /me` | any | `{"user_id","email","groups":[...]}` |
| `GET /stock/{sku}` | any | `{"sku","on_hand_total","locations":[{"location_id","on_hand","version"}],"source":"cache|db"}` |
| `GET /parts/{sku}` | any | `Part & {"stock": <GET /stock body>}` |
| `GET /search/parts?q=&category=&supplier=&site=&page=1&size=20` | any | `{"total","items":[PartDoc],"facets":{"category":[{"key","count"}],"supplier":[...],"site":[...]}}` |
| `GET /search/documents?q=&supplier=&from=&to=&page=1&size=20` | any | `{"total","items":[DocumentDoc],"facets":{"supplier":[...]}}` |
| `GET /dashboard/summary` | any | `{"captures_last_hour","pending_reviews","claimed_reviews","low_stock":[{"sku","name","on_hand_total","reorder_point"}],"recent_movements":[{"movement_id","sku","location_id","qty_delta","type","created_at"}]}` |
| `GET /captures/{capture_id}` | any | `{"capture":{...},"extractions":[...],"image_url": "<presigned GET or null>"}` |
| `POST /reviews/next` | reviewer, admin | 200 `ReviewTask` or 204 |
| `GET /reviews/{task_id}` | reviewer, admin | `ReviewTask` |
| `POST /reviews/{task_id}/renew` | reviewer (lease owner) | `{"lease_expires_at"}`; 409 if not owner |
| `POST /reviews/{task_id}/release` | reviewer (lease owner) | `{"status":"ready"}` |
| `POST /reviews/{task_id}/submit` | reviewer (lease owner) | `{"status":"done","movements":[...]}`; 409 lease lost |
| `GET /reviews/stats` | reviewer, admin | `{"ready","claimed","done_today"}` |
| `GET /eval/runs?model_id=&prompt_version=&limit=50` | any | `{"items":[EvalRun]}` |
| `GET /eval/latest` | any | `{"items":[EvalRun]}` latest per (model_id, prompt_version) |
| `PUT /admin/parts/{sku}` | admin | upsert Part, emits `part.upserted` via outbox |
| `PUT /admin/settings/{key}` | admin | upsert app_setting |

```jsonc
// ReviewTask
{
  "task_id","extraction_id","capture_id","reason","priority","status","claimed_by","lease_expires_at",
  "image_url": "...",
  "capture": {"site_id","station_id","captured_at","payload":{...}},
  "extraction": {"model_id","prompt_version","min_confidence","output": ExtractionOutput}
}
// submit body
{"supplier": "SUP-01", "po_number": "PO-1", "line_items": [{"line_no":1,"sku":"SKU-000123","qty":5,"location_id":"DAL1-RECV-01"}], "notes": ""}
```

## 3. Extraction output (stored in `extraction.output`)

```jsonc
{
  "supplier":  {"value": "SUP-01" | null, "confidence": 0.0-1.0},
  "po_number": {"value": "PO-1234" | null, "confidence": 0.93},
  "line_items": [
    {"line_no": 1,
     "sku":         {"value": "SKU-000123" | null, "confidence": 0.9},
     "part_number": {"value": "PN-88-123" | null, "confidence": 0.9},
     "qty":         {"value": 5, "confidence": 0.97},
     "description": "Hex bolt M8"}
  ],
  "raw_text": "full transcription"
}
```
`min_confidence` = min over all field confidences (supplier, po_number, every line item's sku/qty).
Ground truth (`ground_truth.corrected`) = the submit body without `notes`.

## 4. Kafka (MSK Serverless; values are UTF-8 JSON; keys UTF-8 strings)

`captures.raw` key = `capture_id`, value = Capture + `{"received_at": iso, "trace_id": str}`.

`inventory.events` — every value has `type`, `event_id` (uuid), `occurred_at`:
```jsonc
// key = sku
{"type":"stock.changed","event_id","occurred_at","sku","location_id","on_hand","version","on_hand_total",
 "reorder_point","qty_delta","movement_id","movement_type","source_capture_id","captured_at"}
// key = sku
{"type":"part.upserted","event_id","occurred_at","sku","part_number","name","category","supplier_id","supplier_name","uom","reorder_point"}
// key = capture_id
{"type":"document.extracted","event_id","occurred_at","capture_id","extraction_id","site_id","supplier","po_number",
 "raw_text","line_items":[{"line_no","sku","part_number","qty","description"}],"status":"auto_applied|pending_review|reviewed","captured_at"}
```
`version` is per (sku, location_id). Consumers MUST compare versions per location.

## 5. RabbitMQ (Amazon MQ). Exchange topology is declared by `inventory_common.rabbit.declare_topology()`

- direct exchange `commands` → quorum queues `review.dispatch`, `reorder.request`, `notify` (routing key = queue name)
- direct exchange `commands.retry` → `<queue>.retry` (x-message-ttl 15000, dead-letters back to `commands` with routing key `<queue>`)
- direct exchange `commands.dlq` → `<queue>.dlq`
- Consumers use `inventory_common.lambda_events.rmq_consume()`: header `x-attempt` counts retries; after 5 attempts → DLQ.

```jsonc
// review.dispatch
{"command_id","extraction_id","capture_id","reason":"low_confidence|audit_sample|unknown_sku|extraction_error","priority":0-9,"min_confidence"}
// reorder.request
{"command_id","sku","on_hand_total","reorder_point","location_id","requested_at"}
// notify
{"command_id","channel":"log|sns","subject","message"}
```
Priority: lower = more urgent. low_confidence → `round(min_confidence*9)`, unknown_sku/extraction_error → 0, audit_sample → 9.

## 6. Auth

Cognito groups: `operator`, `reviewer`, `admin` (admin implies all).
`inventory_common.auth.principal_from_event(event)` returns `Principal(user_id, email, groups)`.
- `AUTH_MODE=cognito`: claims from `event.requestContext.authorizer.jwt.claims` (`sub`, `email`, `cognito:groups` which HTTP API delivers as `"[a b]"` string or list).
- `AUTH_MODE=dev`: headers `x-dev-user` (default `dev-user`) and `x-dev-groups` (comma list, default `operator,reviewer,admin`).
The local gateway forwards headers untouched. Web and desktop send `Authorization: Bearer <id token>` in AWS and the dev headers locally.

## 7. Redis keys (see `inventory_common.keys`)

| Key | Type | TTL |
| --- | --- | --- |
| `idem:capture:{capture_id}` | string | 24 h |
| `stock:{sku}` | hash: `{location_id}` → on_hand, `_v:{location_id}` → version, `_filled`=1 after a full fill; write only via `redis_client.write_stock(fill=...)` | 10 min |
| `lock:fill:{sku}` | string | 2 s |
| `review:ready` | zset, score = `priority * 1e10 + created_epoch_s` (ZPOPMIN) | none |
| `review:lease:{task_id}` | string reviewer_id | 300 s, renewable |
| `reorder:sent:{sku}:{yyyymmdd}` | string | 24 h |
| `rl:{station_id}:{epoch_s}` | counter | 2 s (limit 200/s per station) |
| `setting:{key}` | string cache of app_setting | 60 s |

## 8. OpenSearch

Index `parts_v1` alias `parts`, doc id = sku:
`{sku, part_number (text + edge_ngram subfield `part_number.ngram` + keyword `part_number.raw`), name, category, supplier_id, supplier_name, uom, reorder_point, on_hand_total, sites[], locations:[{location_id, site_id, on_hand, version}] (nested), updated_at}`.
Index `documents_v1` alias `documents`, doc id = capture_id:
`{capture_id, extraction_id, site_id, supplier, po_number, raw_text, line_items(nested), status, captured_at}`.
Mappings live in `services/indexer/indexer/mappings.py`; `services/ops` creates them. OpenSearch 3.5 in AWS and locally.

## 9. Eval metrics (`eval_run.metrics`)

```jsonc
{"n_extractions": 120, "n_line_items": 410,
 "fields": {"supplier": {"accuracy"}, "po_number": {"accuracy"},
            "sku": {"precision","recall","f1"}, "qty": {"accuracy"}},
 "line_item_exact_match": 0.81, "document_exact_match": 0.62,
 "calibration": [{"bin_lo":0.0,"bin_hi":0.1,"count":3,"mean_confidence":0.05,"accuracy":0.33}],
 "ece": 0.04, "recommended_threshold": 0.88, "target_precision": 0.98}
```
`eval_run.kind` ∈ `nightly|golden`.

## 10. Lambda event shapes (decoded by `inventory_common.lambda_events`)

- MSK / Kafka: `{"eventSource":"aws:kafka","records":{"<topic>-<partition>":[{"topic","partition","offset","timestamp","key":b64,"value":b64,"headers":[{"k":[bytes]}]}]}}`
- RabbitMQ: `{"eventSource":"aws:rmq","rmqMessagesByQueue":{"<queue>::/":[{"basicProperties":{"headers":{...}},"redelivered":false,"data":b64}]}}`
  (string header values arrive as `{"bytes":[...]}` or byte arrays)
- Locally, `python -m inventory_common.local.kafka_runner` and `python -m inventory_common.local.rmq_runner`
  build the same shapes from real brokers and call the handler.

## 11. Local ports (docker-compose)

Postgres 5432 · Kafka 9092 · RabbitMQ 5672 / UI 15672 · Valkey 6379 · OpenSearch 9200 / Dashboards 5601 ·
S3 mock (adobe/s3mock) 9000 · local gateway 8080 · web 3000.

## 12. Deployables (Terraform and docker-compose both use exactly these)

| Name | Package dir | Entry point | Trigger | Talks to |
| --- | --- | --- | --- | --- |
| `ingest` | services/ingest | `ingest.handler.handler` | API GW `POST /uploads`, `POST /captures` | Redis, MSK produce `captures.raw`, S3 presign |
| `core_api` | services/core_api | `core_api.handler.handler` | API GW `$default` (+ `GET /health` unauthenticated) | PG, Redis, OpenSearch, S3 |
| `extract` | services/extract | `extract.handler.handler` | MSK `captures.raw`, group `extract`, batch 100 | PG, Redis, S3, Bedrock |
| `cache_updater` | services/cache_updater | `cache_updater.handler.handler` | MSK `inventory.events`, group `cache-updater`, batch 500 | Redis |
| `indexer` | services/indexer | `indexer.handler.handler` | MSK `inventory.events`, group `indexer`, batch 500 | OpenSearch |
| `reorder_checker` | services/reorder_checker | `reorder_checker.handler.handler` | MSK `inventory.events`, group `reorder-checker` | Redis, RabbitMQ publish |
| `review_dispatcher` | services/review_dispatcher | `review_dispatcher.handler.handler` | MQ queue `review.dispatch` | PG, Redis, RabbitMQ (retry publish) |
| `reorder_worker` | services/review_dispatcher | `review_dispatcher.reorder.handler` | MQ queue `reorder.request` | PG (outbox → notify) |
| `notify_worker` | services/review_dispatcher | `review_dispatcher.notify.handler` | MQ queue `notify` | SNS |
| `review_reaper` | services/review_dispatcher | `review_dispatcher.reaper.handler` | EventBridge Scheduler `rate(1 minute)` | PG, Redis |
| `eval_nightly` | services/eval_nightly | `eval_nightly.handler.handler` | EventBridge Scheduler `cron(0 7 * * ? *)` | PG |
| `ops` | services/ops (+ db/) | `ops.bootstrap.handler` | Terraform `aws_lambda_invocation` after deploy; event `{"actions": ["migrate","topics","rabbitmq","indices","seed"]}` | PG, MSK admin, RabbitMQ, OpenSearch |
| `outbox_relay` | services/outbox_relay | container, `python -m outbox_relay.main` (Dockerfile in package dir) | ECS Fargate service, 1 task | PG, MSK produce `inventory.events`, RabbitMQ |

Lambdas: Python 3.12, arm64, in private subnets. Zips are built by `scripts/build_lambdas.sh` into
`dist/lambda/<name>.zip` (one zip per package dir; the review_dispatcher zip serves four functions).
The same entry points run locally via `inventory_common.local.*_runner` (§10) or, for HTTP, via `local/gateway`.
Local equivalents of scheduled jobs: `python -m review_dispatcher.reaper --loop`, `python -m eval_nightly.handler`.
Local bootstrap: `python -m ops.bootstrap migrate topics rabbitmq indices seed`.
Rebuild drills: `python -m ops.rebuild cache|index` (see services/ops) — in AWS, rebuild uses a new ESM consumer
group via Terraform variable `consumer_group_generation`.

## 13. Synthetic packing slips (shared by simulator, stub extractor and golden set)

- `capture_client.slips.render_packing_slip(truth: dict, seed: int | None = None) -> bytes` returns a PNG.
  `truth` has the ground-truth shape: `{"supplier": "SUP-ACME", "supplier_name": "Acme Fasteners", "po_number": "PO-123456",
  "line_items": [{"line_no": 1, "sku": "SKU-000123", "part_number": "ACME-12-00123", "qty": 5, "description": "Hex bolt M8"}]}`.
- The simulator uploads `<s3_key>.truth.json` next to each synthetic image. The stub extractor reads that sidecar if
  present and returns it with simulated noise (and lower confidence on corrupted fields); without it, it fabricates
  plausible items from the catalog. Real Bedrock never sees the sidecar.
- `eval/golden/` holds `<name>.png` + `<name>.truth.json` pairs.
