variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "allowed_security_group_ids" { type = list(string) }
variable "max_data_storage_gb" {
  type    = number
  default = 1
}
variable "max_ecpu_per_second" {
  type    = number
  default = 10000
}

resource "aws_security_group" "this" {
  name        = "${var.name}-valkey"
  description = "ElastiCache Serverless (Valkey)"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "valkey" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  from_port                    = 6379
  to_port                      = 6380
  ip_protocol                  = "tcp"
  description                  = "Valkey from app"
}

resource "aws_elasticache_serverless_cache" "this" {
  name                 = var.name
  engine               = "valkey"
  major_engine_version = "8"
  kms_key_id           = var.kms_key_arn
  security_group_ids   = [aws_security_group.this.id]
  subnet_ids           = var.subnet_ids

  cache_usage_limits {
    data_storage {
      maximum = var.max_data_storage_gb
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = var.max_ecpu_per_second
    }
  }
}

output "endpoint" { value = aws_elasticache_serverless_cache.this.endpoint[0].address }
output "port" { value = aws_elasticache_serverless_cache.this.endpoint[0].port }
output "name" { value = aws_elasticache_serverless_cache.this.name }
output "security_group_id" { value = aws_security_group.this.id }
