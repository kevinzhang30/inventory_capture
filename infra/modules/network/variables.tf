variable "name" { type = string }
variable "cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "az_count" {
  type    = number
  default = 2
}
variable "enable_nat" {
  description = "Single NAT gateway (dev). Needed for ECR pulls, Cognito JWKS and Lambda ESM control traffic."
  type        = bool
  default     = true
}
variable "interface_endpoints" {
  description = "Interface VPC endpoints to reduce NAT dependence (design §8)."
  type        = list(string)
  default     = ["bedrock-runtime", "secretsmanager", "sts", "logs", "sqs", "sns", "lambda"]
}
