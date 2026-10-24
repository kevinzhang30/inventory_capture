variable "name" { type = string }
variable "domain_prefix" { type = string }
variable "web_callback_urls" { type = list(string) }
variable "web_logout_urls" { type = list(string) }

data "aws_region" "current" {}

resource "aws_cognito_user_pool" "this" {
  name                     = var.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "INACTIVE"
  mfa_configuration        = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_uppercase = true
    require_symbols   = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_group" "role" {
  for_each     = toset(["operator", "reviewer", "admin"])
  name         = each.key
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Inventory capture ${each.key}"
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.name}-web"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = var.web_callback_urls
  logout_urls                          = var.web_logout_urls
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  id_token_validity                    = 60
  access_token_validity                = 60
  refresh_token_validity               = 30
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
}

# Desktop stations: public client, password auth once, then refresh tokens kept in the OS keyring.
resource "aws_cognito_user_pool_client" "desktop" {
  name                          = "${var.name}-desktop"
  user_pool_id                  = aws_cognito_user_pool.this.id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  refresh_token_validity        = 30
}

output "user_pool_id" { value = aws_cognito_user_pool.this.id }
output "issuer" { value = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.this.id}" }
output "web_client_id" { value = aws_cognito_user_pool_client.web.id }
output "web_client_secret" {
  value     = aws_cognito_user_pool_client.web.client_secret
  sensitive = true
}
output "desktop_client_id" { value = aws_cognito_user_pool_client.desktop.id }
output "hosted_ui_domain" { value = "${var.domain_prefix}.auth.${data.aws_region.current.name}.amazoncognito.com" }
