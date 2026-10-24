# Lambda functions (docs/CONTRACTS.md §12), their least-privilege policies, triggers and the bootstrap run.

locals {
  zip = { for p in ["ingest", "core_api", "extract", "cache_updater", "indexer", "reorder_checker",
    "review_dispatcher", "eval_nightly", "ops"] : p => abspath("${path.module}/${var.lambda_dist_dir}/${p}.zip")
  }

  topic_arn = { for t in ["captures.raw", "inventory.events"] : t => "${module.msk.topic_arn_prefix}/${t}" }
  group_arn = "${module.msk.group_arn_prefix}/*"

  common_env = {
    APP_ENV                = "dev"
    LOG_LEVEL              = "INFO"
    DATABASE_URL           = ""
    DB_SECRET_ARN          = module.aurora.master_secret_arn
    DB_HOST                = module.aurora.endpoint
    DB_PORT                = tostring(module.aurora.port)
    DB_NAME                = module.aurora.database_name
    DB_POOL_MAX            = "2"
    REDIS_URL              = "rediss://${module.cache.endpoint}:${module.cache.port}"
    REDIS_CLUSTER          = "true"
    KAFKA_BOOTSTRAP        = module.msk.bootstrap_brokers_iam
    KAFKA_AUTH             = "iam"
    TOPIC_CAPTURES_RAW     = "captures.raw"
    TOPIC_INVENTORY_EVENTS = "inventory.events"
    RABBITMQ_URL           = ""
    RABBITMQ_SECRET_ARN    = module.mq.secret_arn
    RABBITMQ_HOST          = module.mq.host
    OPENSEARCH_URL         = "https://${module.opensearch.endpoint}"
    OPENSEARCH_AUTH        = "sigv4"
    S3_BUCKET              = module.s3.bucket
    S3_ENDPOINT_URL        = ""
    S3_PUBLIC_ENDPOINT_URL = ""
    EXTRACTOR              = var.extractor
    BEDROCK_MODEL_ID       = var.bedrock_model_id
    PROMPT_VERSION         = var.prompt_version
    AUTH_MODE              = "cognito"
    SNS_TOPIC_ARN          = aws_sns_topic.notify.arn
  }

  layers = var.adot_layer_arn == "" ? [] : [var.adot_layer_arn]
}

# ---------------------------------------------------------------- reusable policy statements

data "aws_iam_policy_document" "db" {
  statement {
    sid       = "DbSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.aurora.master_secret_arn]
  }
  statement {
    sid       = "KmsDb"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [module.kms.key_arn]
  }
}

data "aws_iam_policy_document" "mq" {
  statement {
    sid       = "MqSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [module.mq.secret_arn]
  }
  statement {
    sid       = "KmsMq"
    actions   = ["kms:Decrypt"]
    resources = [module.kms.key_arn]
  }
}

data "aws_iam_policy_document" "mq_esm" {
  statement {
    sid       = "MqEventSource"
    actions   = ["mq:DescribeBroker"]
    resources = [module.mq.broker_arn]
  }
  statement {
    sid       = "EsmNetworking"
    actions   = ["ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "msk_connect" {
  statement {
    sid       = "MskConnect"
    actions   = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"]
    resources = [module.msk.cluster_arn]
  }
}

data "aws_iam_policy_document" "produce_captures" {
  source_policy_documents = [data.aws_iam_policy_document.msk_connect.json]
  statement {
    sid       = "ProduceCaptures"
    actions   = ["kafka-cluster:WriteData", "kafka-cluster:DescribeTopic"]
    resources = [local.topic_arn["captures.raw"]]
  }
}

data "aws_iam_policy_document" "produce_events" {
  source_policy_documents = [data.aws_iam_policy_document.msk_connect.json]
  statement {
    sid       = "ProduceEvents"
    actions   = ["kafka-cluster:WriteData", "kafka-cluster:DescribeTopic"]
    resources = [local.topic_arn["inventory.events"]]
  }
}

data "aws_iam_policy_document" "consume" {
  for_each                = local.topic_arn
  source_policy_documents = [data.aws_iam_policy_document.msk_connect.json]
  statement {
    sid       = "ConsumeTopic"
    actions   = ["kafka-cluster:ReadData", "kafka-cluster:DescribeTopic"]
    resources = [each.value]
  }
  statement {
    sid       = "ConsumerGroups"
    actions   = ["kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup"]
    resources = [local.group_arn]
  }
  statement {
    sid       = "FailedBatches"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.kafka_dlq.arn]
  }
}

data "aws_iam_policy_document" "opensearch" {
  statement {
    sid       = "OpenSearchHttp"
    actions   = ["es:ESHttpGet", "es:ESHttpHead", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"]
    resources = ["${module.opensearch.domain_arn}/*"]
  }
}

data "aws_iam_policy_document" "s3_put" {
  statement {
    sid       = "PresignPut"
    actions   = ["s3:PutObject"]
    resources = ["${module.s3.arn}/captures/*"]
  }
  statement {
    sid       = "KmsS3Put"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [module.kms.key_arn]
  }
}

data "aws_iam_policy_document" "s3_get" {
  statement {
    sid       = "ReadCaptures"
    actions   = ["s3:GetObject"]
    resources = ["${module.s3.arn}/captures/*"]
  }
  statement {
    sid       = "KmsS3Get"
    actions   = ["kms:Decrypt"]
    resources = [module.kms.key_arn]
  }
}

data "aws_iam_policy_document" "bedrock" {
  statement {
    sid     = "InvokeClaude"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:${local.partition}:bedrock:*::foundation-model/anthropic.*",
      "arn:${local.partition}:bedrock:*:${local.account}:inference-profile/*",
    ]
  }
}

data "aws_iam_policy_document" "sns" {
  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notify.arn]
  }
  statement {
    sid       = "KmsSns"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [module.kms.key_arn]
  }
}

data "aws_iam_policy_document" "msk_admin" {
  source_policy_documents = [data.aws_iam_policy_document.msk_connect.json]
  statement {
    sid = "ManageTopics"
    actions = ["kafka-cluster:CreateTopic", "kafka-cluster:DescribeTopic", "kafka-cluster:AlterTopic",
    "kafka-cluster:DescribeTopicDynamicConfiguration", "kafka-cluster:AlterTopicDynamicConfiguration"]
    resources = ["${module.msk.topic_arn_prefix}/*"]
  }
}

# Per-function policies, composed from the statements above.
data "aws_iam_policy_document" "fn" {
  for_each = {
    ingest = [data.aws_iam_policy_document.produce_captures.json, data.aws_iam_policy_document.s3_put.json]
    core_api = [data.aws_iam_policy_document.db.json, data.aws_iam_policy_document.opensearch.json,
    data.aws_iam_policy_document.s3_get.json]
    extract = [data.aws_iam_policy_document.consume["captures.raw"].json, data.aws_iam_policy_document.db.json,
    data.aws_iam_policy_document.s3_get.json, data.aws_iam_policy_document.bedrock.json]
    cache_updater   = [data.aws_iam_policy_document.consume["inventory.events"].json]
    indexer         = [data.aws_iam_policy_document.consume["inventory.events"].json, data.aws_iam_policy_document.opensearch.json]
    reorder_checker = [data.aws_iam_policy_document.consume["inventory.events"].json, data.aws_iam_policy_document.mq.json]
    review_dispatcher = [data.aws_iam_policy_document.db.json, data.aws_iam_policy_document.mq.json,
    data.aws_iam_policy_document.mq_esm.json]
    reorder_worker = [data.aws_iam_policy_document.db.json, data.aws_iam_policy_document.mq.json,
    data.aws_iam_policy_document.mq_esm.json]
    notify_worker = [data.aws_iam_policy_document.mq.json, data.aws_iam_policy_document.mq_esm.json,
    data.aws_iam_policy_document.sns.json]
    review_reaper = [data.aws_iam_policy_document.db.json]
    eval_nightly  = [data.aws_iam_policy_document.db.json]
    ops = [data.aws_iam_policy_document.db.json, data.aws_iam_policy_document.mq.json,
    data.aws_iam_policy_document.msk_admin.json, data.aws_iam_policy_document.opensearch.json]
  }
  source_policy_documents = each.value
}

locals {
  msk_managed = ["arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaMSKExecutionRole"]

  functions = {
    ingest = { pkg = "ingest", handler = "ingest.handler.handler", memory = 512, timeout = 15, sg = "ingest",
    managed = [], reserved = null, env = {} }
    core_api = { pkg = "core_api", handler = "core_api.handler.handler", memory = 1024, timeout = 29, sg = "api",
      managed = [], reserved = null,
      env = { COGNITO_ISSUER = module.cognito.issuer, CORS_ORIGINS = join(",", var.cors_allow_origins),
    COGNITO_AUDIENCE = join(",", [module.cognito.web_client_id, module.cognito.desktop_client_id]) } }
    extract = { pkg = "extract", handler = "extract.handler.handler", memory = 1024, timeout = 300,
    sg = "consumers", managed = local.msk_managed, reserved = var.extract_reserved_concurrency, env = { EXTRACT_CONCURRENCY = "4" } }
    cache_updater = { pkg = "cache_updater", handler = "cache_updater.handler.handler", memory = 512, timeout = 60,
    sg = "consumers", managed = local.msk_managed, reserved = null, env = {} }
    indexer = { pkg = "indexer", handler = "indexer.handler.handler", memory = 512, timeout = 120,
    sg = "consumers", managed = local.msk_managed, reserved = null, env = { INDEX_REFRESH_INTERVAL = "1s" } }
    reorder_checker = { pkg = "reorder_checker", handler = "reorder_checker.handler.handler", memory = 256,
    timeout = 60, sg = "consumers", managed = local.msk_managed, reserved = null, env = {} }
    review_dispatcher = { pkg = "review_dispatcher", handler = "review_dispatcher.handler.handler", memory = 256,
    timeout = 60, sg = "consumers", managed = [], reserved = null, env = {} }
    reorder_worker = { pkg = "review_dispatcher", handler = "review_dispatcher.reorder.handler", memory = 256,
    timeout = 60, sg = "consumers", managed = [], reserved = null, env = {} }
    notify_worker = { pkg = "review_dispatcher", handler = "review_dispatcher.notify.handler", memory = 256,
    timeout = 60, sg = "consumers", managed = [], reserved = null, env = {} }
    review_reaper = { pkg = "review_dispatcher", handler = "review_dispatcher.reaper.handler", memory = 256,
    timeout = 60, sg = "consumers", managed = [], reserved = 1, env = {} }
    eval_nightly = { pkg = "eval_nightly", handler = "eval_nightly.handler.handler", memory = 1024, timeout = 900,
    sg = "consumers", managed = [], reserved = 1, env = { AUTO_TUNE_THRESHOLD = "true" } }
    ops = { pkg = "ops", handler = "ops.bootstrap.handler", memory = 1024, timeout = 900, sg = "consumers",
    managed = [], reserved = 1, env = { OPS_MIGRATIONS_DIR = "/var/task/db", BOOTSTRAP_RETRIES = "5" } }
  }
}

module "fn" {
  source   = "../../modules/lambda_function"
  for_each = local.functions

  name                 = "${var.name}-${replace(each.key, "_", "-")}"
  package_path         = local.zip[each.value.pkg]
  handler              = each.value.handler
  memory_mb            = each.value.memory
  timeout_s            = each.value.timeout
  environment          = merge(local.common_env, each.value.env)
  subnet_ids           = module.network.private_subnet_ids
  security_group_ids   = [local.sg[each.value.sg]]
  reserved_concurrency = each.value.reserved
  policy_json          = data.aws_iam_policy_document.fn[each.key].json
  managed_policy_arns  = each.value.managed
  kms_key_arn          = module.kms.key_arn
  layers               = local.layers
}

resource "aws_opensearch_domain_policy" "this" {
  domain_name = module.opensearch.domain_name
  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = [for k in ["core_api", "indexer", "ops"] : module.fn[k].role_arn] }
      Action    = ["es:ESHttpGet", "es:ESHttpHead", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"]
      Resource  = "${module.opensearch.domain_arn}/*"
    }]
  })
}

# ---------------------------------------------------------------- bootstrap: migrations, topics, topology, indices

resource "aws_lambda_invocation" "bootstrap" {
  function_name = module.fn["ops"].function_name
  input         = jsonencode({ actions = concat(["migrate", "topics", "rabbitmq", "indices"], var.seed_catalog ? ["seed"] : []) })
  triggers = {
    code = filebase64sha256(local.zip["ops"])
  }
  depends_on = [aws_opensearch_domain_policy.this, module.aurora, module.mq, module.msk]
}

# ---------------------------------------------------------------- event-source mappings

locals {
  msk_consumers = {
    extract         = { topic = "captures.raw", group = "extract", batch = 100, window = 1 }
    cache_updater   = { topic = "inventory.events", group = "cache-updater", batch = 500, window = 0 }
    indexer         = { topic = "inventory.events", group = "indexer", batch = 500, window = 1 }
    reorder_checker = { topic = "inventory.events", group = "reorder-checker", batch = 500, window = 1 }
  }
  mq_consumers = {
    review_dispatcher = "review.dispatch"
    reorder_worker    = "reorder.request"
    notify_worker     = "notify"
  }
}

resource "aws_lambda_event_source_mapping" "msk" {
  for_each                           = local.msk_consumers
  event_source_arn                   = module.msk.cluster_arn
  function_name                      = module.fn[each.key].arn
  topics                             = [each.value.topic]
  starting_position                  = "TRIM_HORIZON"
  batch_size                         = each.value.batch
  maximum_batching_window_in_seconds = each.value.window

  amazon_managed_kafka_event_source_config {
    consumer_group_id = "${each.value.group}-g${var.consumer_group_generation}"
  }

  dynamic "destination_config" {
    for_each = var.enable_kafka_failure_destination ? [1] : []
    content {
      on_failure {
        destination_arn = aws_sqs_queue.kafka_dlq.arn
      }
    }
  }

  depends_on = [aws_lambda_invocation.bootstrap] # topics must exist
}

resource "aws_lambda_event_source_mapping" "mq" {
  for_each         = local.mq_consumers
  event_source_arn = module.mq.broker_arn
  function_name    = module.fn[each.key].arn
  queues           = [each.value]
  batch_size       = 10

  source_access_configuration {
    type = "BASIC_AUTH"
    uri  = module.mq.secret_arn
  }
  source_access_configuration {
    type = "VIRTUAL_HOST"
    uri  = "/"
  }

  depends_on = [aws_lambda_invocation.bootstrap] # queues must exist
}

# ---------------------------------------------------------------- schedules

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [module.fn["review_reaper"].arn, module.fn["eval_nightly"].arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "jobs" {
  for_each = {
    review_reaper = "rate(1 minute)"
    eval_nightly  = "cron(0 7 * * ? *)"
  }
  name                = "${var.name}-${replace(each.key, "_", "-")}"
  schedule_expression = each.value
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = module.fn[each.key].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({})
  }
}
