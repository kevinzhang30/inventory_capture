# Infrastructure (Terraform)

`envs/dev` composes the modules in `modules/` into one AWS dev environment (region `us-east-1` by default).

| Module | Resources |
| --- | --- |
| `network` | VPC, 2 AZs, single NAT (toggle), S3 gateway + interface endpoints (Bedrock, Secrets Manager, STS, Logs, SQS, SNS, Lambda) |
| `kms` | One CMK for S3, Aurora, Secrets, ElastiCache, OpenSearch, logs, SNS, ECR |
| `s3_captures` | Capture image bucket (SSE-KMS, TLS-only, CORS, IA after 30 days) |
| `aurora` | Aurora PostgreSQL 18 Serverless v2 (min 0 ACU auto-pause), RDS-managed master secret |
| `elasticache` | ElastiCache Serverless (Valkey 8) |
| `msk` | MSK Serverless with IAM auth; outputs topic/group ARN prefixes for IAM policies |
| `amazonmq` | Amazon MQ RabbitMQ 3.13 single instance; `{username,password}` secret for the Lambda ESM |
| `opensearch` | Single-node provisioned OpenSearch 3.5 in the VPC (ADR-007) |
| `cognito` | User pool, `operator`/`reviewer`/`admin` groups, Hosted UI, web + desktop clients |
| `lambda_function` | One function + its own role, log group, X-Ray, optional ADOT layer |
| `api` | HTTP API with Cognito JWT authorizer, throttling, access logs |
| `ecs_relay` | ECR + Fargate service for the outbox relay |
| `observability` | Dashboard, alarms (DLQs, consumer lag, errors, relay lag, OpenSearch rejections, Bedrock tokens), budget |
| `amplify` | Optional Next.js SSR hosting |
| `github_oidc` | Optional GitHub Actions deploy role |

## Deploy

```bash
make dev-up    # = build-lambdas, init, apply ECR, build+push relay image, full apply
make dev-down  # destroy
```

The first apply creates only the ECR repository (`-target=module.ecs_relay.aws_ecr_repository.this`) so the
relay image can be pushed before the ECS service references it.

After the data stores exist, Terraform invokes the `ops` Lambda (`aws_lambda_invocation.bootstrap`) to run
Alembic migrations, create the Kafka topics, declare the RabbitMQ topology, create the OpenSearch indices and
(optionally) seed the catalog. The event-source mappings depend on that step. It re-runs whenever the ops package
changes.

## Operations

- **Replay drill:** bump `consumer_group_generation`. Each MSK consumer gets a new group starting at
  `TRIM_HORIZON`, which rebuilds Redis and OpenSearch from Kafka retention.
- **Failed Kafka batches** go to the `*-kafka-consumer-dlq` SQS queue (`python -m ops.redrive kafka-dlq`).
- **RabbitMQ DLQs:** `python -m ops.redrive rabbit --queue review.dispatch`.
- **Bedrock quota:** `extract_reserved_concurrency` caps concurrent extractions; Kafka absorbs bursts.
- **Users:** create users in the Cognito pool and add them to groups (`aws cognito-idp admin-add-user-to-group`).
- **First VPC OpenSearch domain in the account:** set `opensearch_create_service_linked_role = true`.
