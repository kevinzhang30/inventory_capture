variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "allowed_security_group_ids" { type = list(string) }
variable "engine_version" {
  type    = string
  default = "18.4"
}
variable "min_capacity" {
  description = "ACUs; 0 enables auto-pause (Aurora PostgreSQL 16.3+)."
  type        = number
  default     = 0
}
variable "max_capacity" {
  type    = number
  default = 4
}
variable "database_name" {
  type    = string
  default = "inventory"
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name        = "${var.name}-aurora"
  description = "Aurora PostgreSQL"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "pg" {
  for_each                     = toset(var.allowed_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Postgres from app"
}

resource "aws_rds_cluster" "this" {
  cluster_identifier            = var.name
  engine                        = "aurora-postgresql"
  engine_mode                   = "provisioned"
  engine_version                = var.engine_version
  allow_major_version_upgrade   = true # lets an existing 16.x cluster move to the 18.x default in place
  database_name                 = var.database_name
  master_username               = "inventory"
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.kms_key_arn
  storage_encrypted             = true
  kms_key_id                    = var.kms_key_arn
  db_subnet_group_name          = aws_db_subnet_group.this.name
  vpc_security_group_ids        = [aws_security_group.this.id]
  skip_final_snapshot           = true
  deletion_protection           = false
  backup_retention_period       = 1
  apply_immediately             = true

  serverlessv2_scaling_configuration {
    min_capacity             = var.min_capacity
    max_capacity             = var.max_capacity
    seconds_until_auto_pause = var.min_capacity == 0 ? 3600 : null
  }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier          = "${var.name}-writer"
  cluster_identifier  = aws_rds_cluster.this.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.this.engine
  engine_version      = aws_rds_cluster.this.engine_version
  publicly_accessible = false
}

output "endpoint" { value = aws_rds_cluster.this.endpoint }
output "port" { value = aws_rds_cluster.this.port }
output "database_name" { value = aws_rds_cluster.this.database_name }
output "master_secret_arn" { value = aws_rds_cluster.this.master_user_secret[0].secret_arn }
output "security_group_id" { value = aws_security_group.this.id }
