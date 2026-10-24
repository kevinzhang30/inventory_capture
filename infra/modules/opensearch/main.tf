variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "allowed_security_group_ids" { type = list(string) }
variable "instance_type" {
  type    = string
  default = "t3.small.search"
}
variable "volume_gb" {
  type    = number
  default = 10
}
variable "create_service_linked_role" {
  description = "Set true in accounts that have never created a VPC OpenSearch domain."
  type        = bool
  default     = false
}

resource "aws_iam_service_linked_role" "opensearch" {
  count            = var.create_service_linked_role ? 1 : 0
  aws_service_name = "opensearchservice.amazonaws.com"
}

resource "aws_security_group" "this" {
  name        = "${var.name}-opensearch"
  description = "OpenSearch domain (HTTPS)"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "HTTPS from app"
}

# ADR-007: a provisioned single node is cheaper than OpenSearch Serverless at dev scale, and Serverless
# does not run the indexer's Painless update scripts.
resource "aws_opensearch_domain" "this" {
  domain_name    = var.name
  engine_version = "OpenSearch_3.5"

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = 1
    zone_awareness_enabled = false
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.volume_gb
  }

  vpc_options {
    subnet_ids         = [var.subnet_ids[0]]
    security_group_ids = [aws_security_group.this.id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_options = {
    "rest.action.multi.allow_explicit_index" = "true"
  }

  depends_on = [aws_iam_service_linked_role.opensearch]
}

output "domain_arn" { value = aws_opensearch_domain.this.arn }
output "domain_name" { value = aws_opensearch_domain.this.domain_name }
output "endpoint" { value = aws_opensearch_domain.this.endpoint }
output "security_group_id" { value = aws_security_group.this.id }
