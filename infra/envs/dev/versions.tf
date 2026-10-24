terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {} # see backend.hcl.example; `terraform init -backend=false` for validation
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "inventory-capture"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}
