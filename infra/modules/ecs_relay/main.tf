# outbox-relay on ECS Fargate (single leader via Postgres advisory lock; a second task would wait as follower).
variable "name" { type = string }
variable "image" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "environment" { type = map(string) }
variable "task_policy_json" { type = string }
variable "kms_key_arn" { type = string }
variable "desired_count" {
  type    = number
  default = 1
}

data "aws_region" "current" {}
data "aws_partition" "current" {}

resource "aws_ecr_repository" "this" {
  name                 = var.name
  force_delete         = true
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1, description = "keep last 10",
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 },
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = 14
  kms_key_id        = var.kms_key_arn
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_kms" {
  statement {
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_kms" {
  name   = "ecr-kms"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_kms.json
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.name}-task"
  role   = aws_iam_role.task.id
  policy = var.task_policy_json
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name         = "relay"
    image        = var.image
    essential    = true
    portMappings = [{ containerPort = 8081, protocol = "tcp" }]
    environment  = [for k, v in var.environment : { name = k, value = v }]
    healthCheck = {
      command     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/healthz')"]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = data.aws_region.current.name
        awslogs-stream-prefix = "relay"
      }
    }
  }])
}

resource "aws_ecs_service" "this" {
  name                               = var.name
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.this.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 100 # new task starts as a follower, takes the lock when the old one stops
  deployment_maximum_percent         = 200
  enable_execute_command             = true

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

output "repository_url" { value = aws_ecr_repository.this.repository_url }
output "cluster_name" { value = aws_ecs_cluster.this.name }
output "service_name" { value = aws_ecs_service.this.name }
output "task_role_arn" { value = aws_iam_role.task.arn }
