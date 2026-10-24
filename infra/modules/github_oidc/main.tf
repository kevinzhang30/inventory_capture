# GitHub Actions → AWS via OIDC (design §11: deploy to dev on merge).
variable "name" { type = string }
variable "github_repo" {
  description = "owner/repo"
  type        = string
}
variable "branch" {
  type    = string
  default = "main"
}
variable "policy_arns" {
  description = "Dev deploys create every resource type in this stack, so this defaults to broad access."
  type        = list(string)
  default     = ["arn:aws:iam::aws:policy/AdministratorAccess"]
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f2df264fcd"]
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.branch}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

resource "aws_iam_role_policy_attachment" "deploy" {
  for_each   = toset(var.policy_arns)
  role       = aws_iam_role.deploy.name
  policy_arn = each.value
}

output "role_arn" { value = aws_iam_role.deploy.arn }
