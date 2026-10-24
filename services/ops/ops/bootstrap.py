"""Idempotent environment bootstrap: DB migrations, Kafka topics, RabbitMQ topology, OpenSearch indices, seed.

Lambda:  handler({"actions": ["migrate", "topics", "rabbitmq", "indices", "seed"]})  (invoked by Terraform)
CLI:     python -m ops.bootstrap bucket migrate topics rabbitmq indices seed
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from inventory_common.config import settings
from inventory_common.log import get_logger

log = get_logger("ops.bootstrap")

TOPICS = {
    # name: (partitions, retention_ms)
    "captures.raw": (12, 7 * 24 * 3600 * 1000),
    "inventory.events": (12, 30 * 24 * 3600 * 1000),
}
ALL_ACTIONS = ("bucket", "migrate", "topics", "rabbitmq", "indices", "seed")


def db_dir() -> Path:
    if env := os.environ.get("OPS_MIGRATIONS_DIR"):
        return Path(env)
    for candidate in (Path(__file__).resolve().parents[3] / "db", Path("/var/task/db")):
        if (candidate / "alembic.ini").exists():
            return candidate
    raise FileNotFoundError("db/ with alembic.ini not found; set OPS_MIGRATIONS_DIR")


def migrate() -> str:
    from alembic import command
    from alembic.config import Config

    d = db_dir()
    cfg = Config(str(d / "alembic.ini"))
    cfg.set_main_option("script_location", str(d / "migrations"))
    command.upgrade(cfg, "head")
    return "ok"


def topics() -> dict[str, str]:
    from confluent_kafka.admin import AdminClient, NewTopic

    from inventory_common.kafka import base_config

    admin = AdminClient(base_config())
    existing = set(admin.list_topics(timeout=20).topics)
    out = {}
    new = []
    for name, (parts, retention) in TOPICS.items():
        if name in existing:
            out[name] = "exists"
            continue
        # MSK Serverless picks its own replication factor; -1 means "broker default" on both.
        new.append(NewTopic(name, num_partitions=parts, replication_factor=-1,
                            config={"retention.ms": str(retention)}))
    for name, fut in admin.create_topics(new).items() if new else []:
        try:
            fut.result(30)
            out[name] = "created"
        except Exception as exc:  # noqa: BLE001
            if "TOPIC_ALREADY_EXISTS" in str(exc):
                out[name] = "exists"
            else:
                raise
    return out


def rabbitmq() -> str:
    from inventory_common import rabbit

    rabbit.declare_topology()
    return "ok"


def indices() -> list[str]:
    from indexer.mappings import ensure_indices
    from inventory_common.search import get_opensearch

    return ensure_indices(get_opensearch())


def bucket() -> str:
    """Local only: create the capture bucket on the S3 mock (Terraform owns the real bucket in AWS)."""
    if not settings.s3_endpoint_url:
        return "skipped (managed by terraform)"
    from botocore.exceptions import ClientError

    from inventory_common.s3 import s3

    try:
        s3().head_bucket(Bucket=settings.s3_bucket)
        return "exists"
    except ClientError:
        s3().create_bucket(Bucket=settings.s3_bucket)
        return "created"


def seed(parts: int = 2000) -> str:
    sys.path.insert(0, str(db_dir()))
    from seed import seed as seed_mod  # db/seed/seed.py

    argv = sys.argv
    try:
        sys.argv = ["seed", "--parts", str(parts)]
        seed_mod.main()
    finally:
        sys.argv = argv
    return "ok"


ACTIONS = {
    "bucket": bucket, "migrate": migrate, "topics": topics, "rabbitmq": rabbitmq, "indices": indices, "seed": seed,
}


def run(actions: list[str], retries: int = 1) -> dict[str, Any]:
    unknown = [a for a in actions if a not in ACTIONS]
    if unknown:
        raise ValueError(f"unknown actions {unknown}; valid: {ALL_ACTIONS}")
    results: dict[str, Any] = {}
    for action in [a for a in ALL_ACTIONS if a in actions]:  # dependency order
        for attempt in range(1, retries + 1):
            try:
                results[action] = ACTIONS[action]()
                log.info("bootstrap action done", extra={"action": action, "result": results[action]})
                break
            except Exception:
                if attempt == retries:
                    raise
                log.warning("bootstrap action failed; retrying", extra={"action": action}, exc_info=True)
                time.sleep(min(2 * attempt, 10))
    return results


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    actions = event.get("actions") or ["migrate", "topics", "rabbitmq", "indices"]
    return {"env": settings.app_env, "results": run(actions, retries=3)}


if __name__ == "__main__":
    print(run(sys.argv[1:] or list(ALL_ACTIONS), retries=int(os.environ.get("BOOTSTRAP_RETRIES", "30"))))
