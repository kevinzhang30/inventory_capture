variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kms_key_arn" { type = string }
variable "allowed_security_group_ids" { type = list(string) }
variable "instance_type" {
  type    = string
  default = "mq.t3.micro"
}

resource "random_password" "mq" {
  length  = 32
  special = false # Amazon MQ forbids , : = and our AMQP URL must stay unescaped-safe
}

resource "aws_security_group" "this" {
  name        = "${var.name}-mq"
  description = "Amazon MQ for RabbitMQ (AMQPS 5671)"
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
  from_port                    = 5671
  to_port                      = 5671
  ip_protocol                  = "tcp"
  description                  = "AMQPS from app"
}

# Lambda's RabbitMQ event-source mapping connects through the broker's own security group.
resource "aws_vpc_security_group_ingress_rule" "self" {
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = aws_security_group.this.id
  from_port                    = 5671
  to_port                      = 5671
  ip_protocol                  = "tcp"
  description                  = "Lambda ESM pollers"
}

resource "aws_mq_broker" "this" {
  broker_name                = var.name
  engine_type                = "RabbitMQ"
  engine_version             = "3.13"
  host_instance_type         = var.instance_type
  deployment_mode            = "SINGLE_INSTANCE"
  publicly_accessible        = false
  auto_minor_version_upgrade = true
  subnet_ids                 = [var.subnet_ids[0]]
  security_groups            = [aws_security_group.this.id]
  apply_immediately          = true

  user {
    username = "inventory"
    password = random_password.mq.result
  }

  logs {
    general = true
  }
}

# Lambda RabbitMQ ESM requires exactly {"username","password"} in the secret.
resource "aws_secretsmanager_secret" "mq" {
  name                    = "${var.name}/rabbitmq"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "mq" {
  secret_id     = aws_secretsmanager_secret.mq.id
  secret_string = jsonencode({ username = "inventory", password = random_password.mq.result })
}

locals {
  amqps = aws_mq_broker.this.instances[0].endpoints[0] # amqps://b-xxxx.mq.<region>.amazonaws.com:5671
}

output "broker_arn" { value = aws_mq_broker.this.arn }
output "broker_name" { value = aws_mq_broker.this.broker_name }
output "host" { value = trimsuffix(trimprefix(local.amqps, "amqps://"), ":5671") }
output "secret_arn" { value = aws_secretsmanager_secret.mq.arn }
output "security_group_id" { value = aws_security_group.this.id }
