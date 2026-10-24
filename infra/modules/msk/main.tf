variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_security_group_ids" { type = list(string) }

resource "aws_security_group" "this" {
  name        = "${var.name}-msk"
  description = "MSK Serverless (IAM auth, 9098)"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "clients" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  from_port                    = 9098
  to_port                      = 9098
  ip_protocol                  = "tcp"
  description                  = "Kafka IAM from app"
}

# Lambda event-source mappings poll MSK using the cluster's own subnets and security group.
resource "aws_vpc_security_group_ingress_rule" "self" {
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = aws_security_group.this.id
  from_port                    = 9098
  to_port                      = 9098
  ip_protocol                  = "tcp"
  description                  = "Lambda ESM pollers"
}

resource "aws_msk_serverless_cluster" "this" {
  cluster_name = var.name

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.this.id]
  }

  client_authentication {
    sasl {
      iam {
        enabled = true
      }
    }
  }
}

data "aws_msk_bootstrap_brokers" "this" {
  cluster_arn = aws_msk_serverless_cluster.this.arn
}

output "cluster_arn" { value = aws_msk_serverless_cluster.this.arn }
output "cluster_name" { value = aws_msk_serverless_cluster.this.cluster_name }
output "bootstrap_brokers_iam" { value = data.aws_msk_bootstrap_brokers.this.bootstrap_brokers_sasl_iam }
output "security_group_id" { value = aws_security_group.this.id }
# IAM resource prefixes: arn:aws:kafka:<region>:<acct>:topic/<cluster>/<uuid>/<topic> (and group/...)
output "topic_arn_prefix" { value = replace(aws_msk_serverless_cluster.this.arn, ":cluster/", ":topic/") }
output "group_arn_prefix" { value = replace(aws_msk_serverless_cluster.this.arn, ":cluster/", ":group/") }
