"""S3 helpers. Locally targets an S3 mock; presigned URLs use the public endpoint so desktop/web can reach them."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from inventory_common.config import settings

ALLOWED_CONTENT_TYPES = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}


@lru_cache(maxsize=2)
def _client(public: bool) -> Any:
    endpoint = settings.s3_public_endpoint_url if public else settings.s3_endpoint_url
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=endpoint,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path" if endpoint else "auto"}),
    )


def s3() -> Any:
    return _client(False)


def presign_put(key: str, content_type: str, expires_in: int = 300) -> str:
    return _client(True).generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def presign_get(key: str, expires_in: int = 900) -> str:
    return _client(True).generate_presigned_url(
        "get_object", Params={"Bucket": settings.s3_bucket, "Key": key}, ExpiresIn=expires_in
    )


def get_bytes(key: str) -> bytes:
    return s3().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
