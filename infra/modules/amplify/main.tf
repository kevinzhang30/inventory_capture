# Next.js SSR hosting (resolves the design's open question: Amplify keeps everything in one cloud).
variable "name" { type = string }
variable "repository" { type = string }
variable "access_token" {
  type      = string
  sensitive = true
}
variable "branch" {
  type    = string
  default = "main"
}
variable "environment" { type = map(string) }

resource "aws_amplify_app" "this" {
  name         = var.name
  repository   = var.repository
  access_token = var.access_token
  platform     = "WEB_COMPUTE"

  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: apps/web
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - env | grep -E '^(API_BASE_URL|AUTH_MODE|COGNITO_|NEXTAUTH_)' >> .env.production
                - npm run build
          artifacts:
            baseDirectory: .next
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
              - .next/cache/**/*
  YAML

  environment_variables = merge(var.environment, { AMPLIFY_MONOREPO_APP_ROOT = "apps/web" })
}

resource "aws_amplify_branch" "this" {
  app_id            = aws_amplify_app.this.id
  branch_name       = var.branch
  framework         = "Next.js - SSR"
  stage             = "DEVELOPMENT"
  enable_auto_build = true
}

output "default_domain" { value = "https://${var.branch}.${aws_amplify_app.this.default_domain}" }
