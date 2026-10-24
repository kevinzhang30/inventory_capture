# outbox-relay (ECS), public API, web hosting, CI identity, observability.

data "aws_iam_policy_document" "relay" {
  source_policy_documents = [
    data.aws_iam_policy_document.db.json,
    data.aws_iam_policy_document.mq.json,
    data.aws_iam_policy_document.produce_events.json,
  ]
}

module "ecs_relay" {
  source             = "../../modules/ecs_relay"
  name               = "${var.name}-outbox-relay"
  image              = var.relay_image
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [local.sg.relay]
  task_policy_json   = data.aws_iam_policy_document.relay.json
  kms_key_arn        = module.kms.key_arn
  environment = merge(local.common_env, {
    AWS_REGION        = var.region
    DB_POOL_MAX       = "1"
    OUTBOX_BATCH_SIZE = "500"
  })
  depends_on = [aws_lambda_invocation.bootstrap]
}

module "api" {
  source               = "../../modules/api"
  name                 = var.name
  ingest_function_name = module.fn["ingest"].function_name
  ingest_invoke_arn    = module.fn["ingest"].invoke_arn
  core_function_name   = module.fn["core_api"].function_name
  core_invoke_arn      = module.fn["core_api"].invoke_arn
  jwt_issuer           = module.cognito.issuer
  jwt_audience         = [module.cognito.web_client_id, module.cognito.desktop_client_id]
  cors_allow_origins   = var.cors_allow_origins
  kms_key_arn          = module.kms.key_arn
}

module "amplify" {
  count        = var.enable_amplify ? 1 : 0
  source       = "../../modules/amplify"
  name         = "${var.name}-web"
  repository   = var.amplify_repository
  access_token = var.amplify_access_token
  environment = {
    API_BASE_URL          = module.api.api_url
    AUTH_MODE             = "cognito"
    COGNITO_CLIENT_ID     = module.cognito.web_client_id
    COGNITO_CLIENT_SECRET = module.cognito.web_client_secret
    COGNITO_ISSUER        = module.cognito.issuer
  }
}

module "github_oidc" {
  count       = var.create_github_oidc ? 1 : 0
  source      = "../../modules/github_oidc"
  name        = var.name
  github_repo = var.github_repo
}

module "observability" {
  source                 = "../../modules/observability"
  name                   = var.name
  kms_key_arn            = module.kms.key_arn
  alert_email            = var.alert_email
  lambda_function_names  = [for k, f in module.fn : f.function_name]
  msk_cluster_name       = module.msk.cluster_name
  consumer_groups        = { for k, c in local.msk_consumers : "${c.group}-g${var.consumer_group_generation}" => c.topic }
  mq_broker_name         = module.mq.broker_name
  mq_queues              = values(local.mq_consumers)
  opensearch_domain_name = module.opensearch.domain_name
  cache_name             = module.cache.name
  bedrock_model_id       = var.bedrock_model_id
  kafka_dlq_name         = aws_sqs_queue.kafka_dlq.name
  daily_token_budget     = var.daily_token_budget
  monthly_budget_usd     = var.monthly_budget_usd
}
