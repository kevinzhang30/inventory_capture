# Dashboards, alarms and budgets (design §9, §10).
variable "name" { type = string }
variable "kms_key_arn" { type = string }
variable "alert_email" {
  type    = string
  default = ""
}
variable "lambda_function_names" { type = list(string) }
variable "msk_cluster_name" { type = string }
variable "consumer_groups" {
  description = "{ group_id = topic }"
  type        = map(string)
}
variable "mq_broker_name" { type = string }
variable "mq_queues" { type = list(string) }
variable "opensearch_domain_name" { type = string }
variable "cache_name" { type = string }
variable "bedrock_model_id" { type = string }
variable "kafka_dlq_name" { type = string }
variable "consumer_lag_threshold" {
  type    = number
  default = 10000
}
variable "daily_token_budget" {
  type    = number
  default = 2000000
}
variable "monthly_budget_usd" {
  type    = number
  default = 150
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  region = data.aws_region.current.name
  ns     = "InventoryCapture"
}

resource "aws_sns_topic" "alarms" {
  name              = "${var.name}-alarms"
  kms_master_key_id = var.kms_key_arn
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = var.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title   = "Scan → visible latency (ms)", region = local.region, stat = "p95", period = 60,
          metrics = [[local.ns, "ScanToVisibleLatencyMax"], [local.ns, "ScanToVisibleLatencyAvg", { stat = "Average" }]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title = "MSK consumer lag (max offset lag)", region = local.region, stat = "Maximum", period = 60,
          metrics = [for g, t in var.consumer_groups :
          ["AWS/Kafka", "MaxOffsetLag", "Cluster Name", var.msk_cluster_name, "Consumer Group", g, "Topic", t]]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          title = "RabbitMQ queue depth", region = local.region, stat = "Maximum", period = 60,
          metrics = [for q in concat(var.mq_queues, [for q in var.mq_queues : "${q}.dlq"]) :
          ["AWS/AmazonMQ", "MessageCount", "Broker", var.mq_broker_name, "VirtualHost", "/", "Queue", q]]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6,
        properties = {
          title = "Lambda errors / throttles", region = local.region, stat = "Sum", period = 60,
          metrics = concat(
            [for f in var.lambda_function_names : ["AWS/Lambda", "Errors", "FunctionName", f]],
            [for f in var.lambda_function_names : ["AWS/Lambda", "Throttles", "FunctionName", f]]
          )
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 12, height = 6,
        properties = {
          title   = "Lambda duration p99 (ms)", region = local.region, stat = "p99", period = 60,
          metrics = [for f in var.lambda_function_names : ["AWS/Lambda", "Duration", "FunctionName", f]]
        }
      },
      {
        type = "metric", x = 12, y = 12, width = 12, height = 6,
        properties = {
          title = "Bedrock", region = local.region, period = 300,
          metrics = [
            ["AWS/Bedrock", "InvocationLatency", "ModelId", var.bedrock_model_id, { stat = "p95" }],
            ["AWS/Bedrock", "InvocationThrottles", "ModelId", var.bedrock_model_id, { stat = "Sum" }],
            ["AWS/Bedrock", "InputTokenCount", "ModelId", var.bedrock_model_id, { stat = "Sum" }],
            ["AWS/Bedrock", "OutputTokenCount", "ModelId", var.bedrock_model_id, { stat = "Sum" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 18, width = 12, height = 6,
        properties = {
          title = "Cache hit rate / outbox relay lag", region = local.region, period = 60,
          metrics = [
            ["AWS/ElastiCache", "CacheHitRate", "clusterId", var.cache_name, { stat = "Average" }],
            [local.ns, "OutboxRelayLag", { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 18, width = 12, height = 6,
        properties = {
          title = "OpenSearch indexing", region = local.region, period = 60,
          metrics = [
            ["AWS/ES", "IndexingLatency", "DomainName", var.opensearch_domain_name, "ClientId",
            data.aws_caller_identity.current.account_id, { stat = "Average" }],
            ["AWS/ES", "ThreadpoolWriteRejected", "DomainName", var.opensearch_domain_name, "ClientId",
            data.aws_caller_identity.current.account_id, { stat = "Sum" }],
            [local.ns, "IndexBulkRejected", { stat = "Sum" }],
          ]
        }
      },
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each            = toset(var.mq_queues)
  alarm_name          = "${var.name}-${each.key}-dlq"
  alarm_description   = "Messages dead-lettered on ${each.key} — inspect and redrive with `python -m ops.redrive rabbit`"
  namespace           = "AWS/AmazonMQ"
  metric_name         = "MessageCount"
  dimensions          = { Broker = var.mq_broker_name, VirtualHost = "/", Queue = "${each.key}.dlq" }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "kafka_dlq" {
  alarm_name          = "${var.name}-kafka-failed-batches"
  alarm_description   = "Kafka consumer batches sent to the on-failure SQS destination"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.kafka_dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "consumer_lag" {
  for_each            = var.consumer_groups
  alarm_name          = "${var.name}-lag-${each.key}"
  alarm_description   = "Consumer lag is the primary health signal (design §7)"
  namespace           = "AWS/Kafka"
  metric_name         = "MaxOffsetLag"
  dimensions          = { "Cluster Name" = var.msk_cluster_name, "Consumer Group" = each.key, Topic = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = var.consumer_lag_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = toset(var.lambda_function_names)
  alarm_name          = "${var.name}-errors-${each.key}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.key }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "relay_lag" {
  alarm_name          = "${var.name}-outbox-relay-lag"
  alarm_description   = "Oldest unsent outbox row older than 30 s (relay down or brokers unreachable)"
  namespace           = local.ns
  metric_name         = "OutboxRelayLag"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 30000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching" # no metric means the relay is not running
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "opensearch_rejections" {
  alarm_name          = "${var.name}-opensearch-write-rejected"
  namespace           = "AWS/ES"
  metric_name         = "ThreadpoolWriteRejected"
  dimensions          = { DomainName = var.opensearch_domain_name, ClientId = data.aws_caller_identity.current.account_id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "bedrock_tokens" {
  alarm_name          = "${var.name}-bedrock-daily-tokens"
  alarm_description   = "Bedrock token spend over the daily budget (design §10)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.daily_token_budget
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]

  metric_query {
    id          = "total"
    expression  = "tin + tout"
    label       = "Tokens per day"
    return_data = true
  }
  metric_query {
    id = "tin"
    metric {
      namespace   = "AWS/Bedrock"
      metric_name = "InputTokenCount"
      dimensions  = { ModelId = var.bedrock_model_id }
      period      = 86400
      stat        = "Sum"
    }
  }
  metric_query {
    id = "tout"
    metric {
      namespace   = "AWS/Bedrock"
      metric_name = "OutputTokenCount"
      dimensions  = { ModelId = var.bedrock_model_id }
      period      = 86400
      stat        = "Sum"
    }
  }
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.alert_email == "" ? [] : [80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value == 100 ? "FORECASTED" : "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

output "alarm_topic_arn" { value = aws_sns_topic.alarms.arn }
output "dashboard_url" {
  value = "https://${local.region}.console.aws.amazon.com/cloudwatch/home?region=${local.region}#dashboards:name=${aws_cloudwatch_dashboard.this.dashboard_name}"
}
