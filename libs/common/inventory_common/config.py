"""Runtime configuration. See docs/CONTRACTS.md §1 for the full table."""

from __future__ import annotations

import json
from functools import lru_cache
from urllib.parse import quote

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    aws_region: str = "us-east-1"
    log_level: str = "INFO"

    database_url: str | None = "postgresql://inventory:inventory@localhost:5432/inventory"
    db_secret_arn: str | None = None
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "inventory"
    db_pool_max: int = 5

    redis_url: str = "redis://localhost:6379/0"
    redis_cluster: bool = False

    kafka_bootstrap: str = "localhost:9092"
    kafka_auth: str = "none"  # none | iam
    topic_captures_raw: str = "captures.raw"
    topic_inventory_events: str = "inventory.events"

    rabbitmq_url: str | None = "amqp://inventory:inventory@localhost:5672/%2F"
    rabbitmq_secret_arn: str | None = None
    rabbitmq_host: str | None = None
    rabbitmq_queue_type: str = "quorum"

    opensearch_url: str = "http://localhost:9200"
    opensearch_auth: str = "none"  # none | sigv4

    s3_bucket: str = "captures"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_public_endpoint_url: str | None = "http://localhost:9000"

    extractor: str = "stub"  # stub | bedrock
    bedrock_model_id: str = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    prompt_version: str = "v1"
    confidence_threshold: float = 0.85
    audit_sample_rate: float = 0.05

    auth_mode: str = "dev"  # dev | cognito
    sns_topic_arn: str | None = None

    outbox_batch_size: int = 500
    outbox_poll_interval_ms: int = 50

    @field_validator(
        "database_url", "db_secret_arn", "db_host", "rabbitmq_url", "rabbitmq_secret_arn", "rabbitmq_host",
        "s3_endpoint_url", "s3_public_endpoint_url", "sns_topic_arn", mode="before",
    )
    @classmethod
    def empty_is_none(cls, v: object) -> object:
        # In AWS the local defaults must be switched off; Terraform sets these to "".
        return None if v == "" else v

    @property
    def is_aws(self) -> bool:
        return self.app_env != "local"


settings = Settings()


@lru_cache(maxsize=8)
def _secret(arn: str) -> dict[str, str]:
    import boto3

    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    return json.loads(client.get_secret_value(SecretId=arn)["SecretString"])


def database_dsn() -> str:
    if settings.db_secret_arn:
        s = _secret(settings.db_secret_arn)
        host = settings.db_host or s.get("host")
        port = settings.db_port or s.get("port", 5432)
        name = settings.db_name or s.get("dbname", "inventory")
        return (
            f"postgresql://{quote(s['username'])}:{quote(s['password'])}@{host}:{port}/{name}"
            "?sslmode=require"
        )
    assert settings.database_url, "DATABASE_URL or DB_SECRET_ARN must be set"
    return settings.database_url


def rabbitmq_url() -> str:
    if settings.rabbitmq_secret_arn:
        s = _secret(settings.rabbitmq_secret_arn)
        host = settings.rabbitmq_host
        return f"amqps://{quote(s['username'])}:{quote(s['password'], safe='')}@{host}:5671/%2F"
    assert settings.rabbitmq_url, "RABBITMQ_URL or RABBITMQ_SECRET_ARN must be set"
    return settings.rabbitmq_url
