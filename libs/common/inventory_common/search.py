"""OpenSearch client (SigV4 against Amazon OpenSearch Service when OPENSEARCH_AUTH=sigv4)."""

from __future__ import annotations

from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from inventory_common.config import settings

PARTS_ALIAS = "parts"
DOCUMENTS_ALIAS = "documents"

_client: OpenSearch | None = None


def get_opensearch() -> OpenSearch:
    global _client
    if _client is None:
        kwargs: dict = {"hosts": [settings.opensearch_url], "timeout": 10, "max_retries": 2,
                        "retry_on_timeout": True}
        if settings.opensearch_auth == "sigv4":
            import boto3

            creds = boto3.Session().get_credentials()
            kwargs.update(
                http_auth=AWSV4SignerAuth(creds, settings.aws_region, "es"),
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                pool_maxsize=20,
            )
        _client = OpenSearch(**kwargs)
    return _client
