variable "name" { type = string }
variable "ingest_function_name" { type = string }
variable "ingest_invoke_arn" { type = string }
variable "core_function_name" { type = string }
variable "core_invoke_arn" { type = string }
variable "jwt_issuer" { type = string }
variable "jwt_audience" { type = list(string) }
variable "cors_allow_origins" {
  type    = list(string)
  default = ["*"]
}
variable "throttle_burst" {
  type    = number
  default = 5000
}
variable "throttle_rate" {
  type    = number
  default = 3000
}
variable "kms_key_arn" { type = string }

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = var.cors_allow_origins
    allow_methods = ["GET", "POST", "PUT", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    issuer   = var.jwt_issuer
    audience = var.jwt_audience
  }
}

resource "aws_apigatewayv2_integration" "ingest" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.ingest_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 15000
}

resource "aws_apigatewayv2_integration" "core" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.core_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

locals {
  routes = {
    "POST /uploads"  = { target = aws_apigatewayv2_integration.ingest.id, auth = true }
    "POST /captures" = { target = aws_apigatewayv2_integration.ingest.id, auth = true }
    "GET /health"    = { target = aws_apigatewayv2_integration.core.id, auth = false }
    "$default"       = { target = aws_apigatewayv2_integration.core.id, auth = true }
  }
}

resource "aws_apigatewayv2_route" "this" {
  for_each           = local.routes
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = each.key
  target             = "integrations/${each.value.target}"
  authorization_type = each.value.auth ? "JWT" : "NONE"
  authorizer_id      = each.value.auth ? aws_apigatewayv2_authorizer.jwt.id : null
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = 14
  kms_key_id        = var.kms_key_arn
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = var.throttle_burst
    throttling_rate_limit  = var.throttle_rate
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId          = "$context.requestId", ip = "$context.identity.sourceIp", routeKey = "$context.routeKey",
      status             = "$context.status", latency = "$context.responseLatency", sub = "$context.authorizer.claims.sub",
      integrationLatency = "$context.integrationLatency", error = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "ingest" {
  statement_id  = "apigw-ingest"
  action        = "lambda:InvokeFunction"
  function_name = var.ingest_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

resource "aws_lambda_permission" "core" {
  statement_id  = "apigw-core"
  action        = "lambda:InvokeFunction"
  function_name = var.core_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

output "api_id" { value = aws_apigatewayv2_api.this.id }
output "api_url" { value = aws_apigatewayv2_stage.default.invoke_url }
