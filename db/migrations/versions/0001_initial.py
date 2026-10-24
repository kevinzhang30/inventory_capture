"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UP = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE site (
  site_id     text PRIMARY KEY,
  name        text NOT NULL,
  timezone    text NOT NULL DEFAULT 'UTC'
);

CREATE TABLE location (
  location_id text PRIMARY KEY,
  site_id     text NOT NULL REFERENCES site(site_id),
  bin_code    text NOT NULL,
  kind        text NOT NULL DEFAULT 'bin' CHECK (kind IN ('bin', 'receiving', 'staging')),
  UNIQUE (site_id, bin_code)
);

CREATE TABLE supplier (
  supplier_id text PRIMARY KEY,
  name        text NOT NULL
);

CREATE TABLE part (
  sku           text PRIMARY KEY,
  part_number   text NOT NULL,
  name          text NOT NULL,
  category      text NOT NULL,
  supplier_id   text REFERENCES supplier(supplier_id),
  uom           text NOT NULL DEFAULT 'ea',
  reorder_point integer NOT NULL DEFAULT 0 CHECK (reorder_point >= 0),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX part_part_number_trgm ON part USING gin (part_number gin_trgm_ops);

CREATE TABLE capture (
  capture_id  uuid PRIMARY KEY,
  site_id     text NOT NULL,
  station_id  text NOT NULL,
  operator_id text,
  kind        text NOT NULL CHECK (kind IN ('scan', 'document')),
  s3_key      text,
  payload     jsonb NOT NULL,
  captured_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  status      text NOT NULL DEFAULT 'received'
              CHECK (status IN ('received', 'applied', 'pending_review', 'reviewed', 'failed', 'rejected')),
  error       text
);
CREATE INDEX capture_received_at ON capture (received_at DESC);
CREATE INDEX capture_status ON capture (status) WHERE status IN ('pending_review', 'failed');

CREATE TABLE extraction (
  extraction_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  capture_id     uuid NOT NULL REFERENCES capture(capture_id),
  model_id       text NOT NULL,
  prompt_version text NOT NULL,
  output         jsonb,
  min_confidence numeric(5,4),
  latency_ms     integer,
  input_tokens   integer,
  output_tokens  integer,
  error          text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (capture_id, model_id, prompt_version)
);

CREATE TABLE review_task (
  task_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  extraction_id    uuid NOT NULL UNIQUE REFERENCES extraction(extraction_id),
  reason           text NOT NULL
                   CHECK (reason IN ('low_confidence', 'audit_sample', 'unknown_sku', 'extraction_error')),
  priority         smallint NOT NULL DEFAULT 5,
  status           text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready', 'claimed', 'done')),
  claimed_by       text,
  claimed_at       timestamptz,
  lease_expires_at timestamptz,
  completed_at     timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX review_task_status ON review_task (status, priority, created_at);
CREATE INDEX review_task_lease ON review_task (lease_expires_at) WHERE status = 'claimed';

CREATE TABLE ground_truth (
  extraction_id uuid PRIMARY KEY REFERENCES extraction(extraction_id),
  task_id       uuid REFERENCES review_task(task_id),
  corrected     jsonb NOT NULL,
  reviewer_id   text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stock_movement (
  movement_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sku               text NOT NULL REFERENCES part(sku),
  location_id       text NOT NULL REFERENCES location(location_id),
  qty_delta         integer NOT NULL,
  type              text NOT NULL CHECK (type IN ('receipt', 'adjustment', 'correction', 'issue')),
  source_capture_id uuid,
  idempotency_key   text NOT NULL UNIQUE,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stock_movement_sku ON stock_movement (sku, created_at DESC);
CREATE INDEX stock_movement_created ON stock_movement (created_at DESC);

CREATE TABLE stock_level (
  sku         text NOT NULL REFERENCES part(sku),
  location_id text NOT NULL REFERENCES location(location_id),
  on_hand     integer NOT NULL DEFAULT 0,
  version     bigint NOT NULL DEFAULT 0,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (sku, location_id)
);

CREATE TABLE outbox (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  destination    text NOT NULL CHECK (destination IN ('kafka', 'rabbitmq')),
  topic_or_queue text NOT NULL,
  msg_key        text,
  payload        jsonb NOT NULL,
  headers        jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at     timestamptz NOT NULL DEFAULT now(),
  sent_at        timestamptz,
  attempts       integer NOT NULL DEFAULT 0,
  last_error     text
);
CREATE INDEX outbox_unsent ON outbox (id) WHERE sent_at IS NULL;

CREATE TABLE reorder_request (
  request_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  command_id    text NOT NULL UNIQUE,
  sku           text NOT NULL REFERENCES part(sku),
  location_id   text,
  on_hand_total integer NOT NULL,
  reorder_point integer NOT NULL,
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'notified', 'closed')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_run (
  run_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind           text NOT NULL DEFAULT 'nightly' CHECK (kind IN ('nightly', 'golden')),
  model_id       text NOT NULL,
  prompt_version text NOT NULL,
  sample_size    integer NOT NULL DEFAULT 0,
  metrics        jsonb NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_run_model ON eval_run (model_id, prompt_version, created_at DESC);

CREATE TABLE app_setting (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
"""

DOWN = """
DROP TABLE IF EXISTS app_setting, eval_run, reorder_request, outbox, stock_level, stock_movement,
  ground_truth, review_task, extraction, capture, part, supplier, location, site CASCADE;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
