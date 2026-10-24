data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account   = data.aws_caller_identity.current.account_id
  partition = data.aws_partition.current.partition
}

module "kms" {
  source = "../../modules/kms"
  name   = var.name
}

module "network" {
  source     = "../../modules/network"
  name       = var.name
  enable_nat = var.enable_nat
}

module "s3" {
  source               = "../../modules/s3_captures"
  name                 = var.name
  kms_key_arn          = module.kms.key_arn
  cors_allowed_origins = var.cors_allow_origins # desktop uploads are not browser requests and need no CORS
}

# ---------------------------------------------------------------- security groups per service family
locals {
  sg_families = {
    ingest    = "ingest Lambda (Redis, MSK)"
    api       = "core-api Lambda (Postgres, Redis, OpenSearch)"
    consumers = "event/command consumer Lambdas"
    relay     = "outbox-relay ECS task"
  }
}

resource "aws_security_group" "app" {
  for_each    = local.sg_families
  name        = "${var.name}-${each.key}"
  description = each.value
  vpc_id      = module.network.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  sg = { for k, v in aws_security_group.app : k => v.id }
}

# ---------------------------------------------------------------- data stores
module "aurora" {
  source                     = "../../modules/aurora"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  kms_key_arn                = module.kms.key_arn
  allowed_security_group_ids = [local.sg.api, local.sg.consumers, local.sg.relay]
}

module "cache" {
  source                     = "../../modules/elasticache"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  kms_key_arn                = module.kms.key_arn
  allowed_security_group_ids = [local.sg.ingest, local.sg.api, local.sg.consumers]
}

module "msk" {
  source                     = "../../modules/msk"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  allowed_security_group_ids = [local.sg.ingest, local.sg.consumers, local.sg.relay]
}

module "mq" {
  source                     = "../../modules/amazonmq"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  kms_key_arn                = module.kms.key_arn
  allowed_security_group_ids = [local.sg.consumers, local.sg.relay]
}

module "opensearch" {
  source                     = "../../modules/opensearch"
  name                       = var.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  kms_key_arn                = module.kms.key_arn
  allowed_security_group_ids = [local.sg.api, local.sg.consumers]
  create_service_linked_role = var.opensearch_create_service_linked_role
}

module "cognito" {
  source            = "../../modules/cognito"
  name              = var.name
  domain_prefix     = "${var.name}-${local.account}"
  web_callback_urls = var.web_callback_urls
  web_logout_urls   = [for u in var.web_callback_urls : regex("^https?://[^/]+", u)]
}

resource "aws_sqs_queue" "kafka_dlq" {
  name                      = "${var.name}-kafka-consumer-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sns_topic" "notify" {
  name              = "${var.name}-notify"
  kms_master_key_id = module.kms.key_arn
}
