variable "name" { type = string }
variable "kms_key_arn" { type = string }
variable "cors_allowed_origins" {
  type    = list(string)
  default = ["*"]
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "this" {
  bucket        = "${var.name}-captures-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # dev: `make dev-down` must remove everything
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_cors_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  cors_rule {
    allowed_methods = ["PUT", "GET"]
    allowed_origins = var.cors_allowed_origins
    allowed_headers = ["content-type"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    id     = "infrequent-access"
    status = "Enabled"
    filter {
      prefix = "captures/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket     = aws_s3_bucket.this.id
  policy     = data.aws_iam_policy_document.tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.this]
}

output "bucket" { value = aws_s3_bucket.this.bucket }
output "arn" { value = aws_s3_bucket.this.arn }
