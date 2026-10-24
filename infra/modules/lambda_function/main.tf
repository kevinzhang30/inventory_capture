# One function + its own least-privilege role (design §8) + encrypted log group.
variable "name" { type = string }
variable "package_path" { type = string }
variable "handler" { type = string }
variable "memory_mb" {
  type    = number
  default = 512
}
variable "timeout_s" {
  type    = number
  default = 30
}
variable "environment" {
  type    = map(string)
  default = {}
}
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "reserved_concurrency" {
  type    = number
  default = null
}
variable "policy_json" {
  description = "Inline policy for this function's role"
  type        = string
  default     = ""
}
variable "managed_policy_arns" {
  type    = list(string)
  default = []
}
variable "kms_key_arn" { type = string }
variable "log_retention_days" {
  type    = number
  default = 14
}
variable "layers" {
  description = "e.g. the ADOT Python layer for OpenTelemetry → X-Ray (design §9)"
  type        = list(string)
  default     = []
}

data "aws_partition" "current" {}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "managed" {
  for_each = toset(concat([
    "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole",
    "arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess",
  ], var.managed_policy_arns))
  role       = aws_iam_role.this.name
  policy_arn = each.value
}

resource "aws_iam_role_policy" "inline" {
  count  = var.policy_json == "" ? 0 : 1
  name   = "${var.name}-inline"
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

resource "aws_lambda_function" "this" {
  function_name                  = var.name
  role                           = aws_iam_role.this.arn
  filename                       = var.package_path
  source_code_hash               = filebase64sha256(var.package_path)
  handler                        = var.handler
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  memory_size                    = var.memory_mb
  timeout                        = var.timeout_s
  reserved_concurrent_executions = var.reserved_concurrency == null ? -1 : var.reserved_concurrency
  layers                         = var.layers
  kms_key_arn                    = var.kms_key_arn

  environment {
    variables = var.environment
  }

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "Text" # our handlers already emit JSON + EMF lines
    log_group  = aws_cloudwatch_log_group.this.name
  }

  depends_on = [aws_iam_role_policy_attachment.managed, aws_iam_role_policy.inline]
}

output "function_name" { value = aws_lambda_function.this.function_name }
output "arn" { value = aws_lambda_function.this.arn }
output "invoke_arn" { value = aws_lambda_function.this.invoke_arn }
output "role_arn" { value = aws_iam_role.this.arn }
output "role_name" { value = aws_iam_role.this.name }
