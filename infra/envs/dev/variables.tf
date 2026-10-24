variable "region" {
  type    = string
  default = "us-east-1"
}
variable "name" {
  type    = string
  default = "invcap-dev"
}
variable "alert_email" {
  type    = string
  default = ""
}
variable "enable_nat" {
  type    = bool
  default = true
}
variable "lambda_dist_dir" {
  description = "Where scripts/build_lambdas.sh writes the zips"
  type        = string
  default     = "../../../dist/lambda"
}
variable "relay_image" {
  description = "outbox-relay image URI (pushed by scripts/build_relay_image.sh)"
  type        = string
}
variable "extractor" {
  type    = string
  default = "bedrock"
  validation {
    condition     = contains(["bedrock", "stub"], var.extractor)
    error_message = "extractor must be bedrock or stub"
  }
}
variable "bedrock_model_id" {
  description = "Foundation model ID or cross-region inference profile ID"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}
variable "prompt_version" {
  type    = string
  default = "v1"
}
variable "extract_reserved_concurrency" {
  description = "Caps concurrent Bedrock calls (protects the quota; Kafka absorbs bursts)"
  type        = number
  default     = 5
}
variable "consumer_group_generation" {
  description = "Bump to replay Kafka from the start into fresh consumer groups (cache/index rebuild drill)"
  type        = number
  default     = 1
}
variable "enable_kafka_failure_destination" {
  type    = bool
  default = true
}
variable "seed_catalog" {
  type    = bool
  default = true
}
variable "adot_layer_arn" {
  description = "Optional AWS Distro for OpenTelemetry Python layer (arm64) for tracing to X-Ray"
  type        = string
  default     = ""
}
variable "opensearch_create_service_linked_role" {
  type    = bool
  default = false
}
variable "web_callback_urls" {
  type    = list(string)
  default = ["http://localhost:3000/api/auth/callback/cognito"]
}
variable "cors_allow_origins" {
  type    = list(string)
  default = ["http://localhost:3000"]
}
variable "monthly_budget_usd" {
  type    = number
  default = 150
}
variable "daily_token_budget" {
  type    = number
  default = 2000000
}
variable "enable_amplify" {
  type    = bool
  default = false
}
variable "amplify_repository" {
  type    = string
  default = ""
}
variable "amplify_access_token" {
  type      = string
  default   = ""
  sensitive = true
}
variable "create_github_oidc" {
  type    = bool
  default = false
}
variable "github_repo" {
  type    = string
  default = ""
}
