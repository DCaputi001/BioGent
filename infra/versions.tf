# versions.tf
# Provider and backend configuration for the BioGent AWS infrastructure.
# State lives in S3 so it survives a lost laptop and works from a second
# machine, per the PC-plus-laptop workflow in ARCHITECTURE.md.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # The bucket must already exist -- Terraform cannot create the bucket holding
  # its own state. See infra/README.md for the one-time bootstrap commands.
  #
  # use_lockfile replaces the DynamoDB lock table that older guides describe;
  # it needs Terraform 1.10+ and keeps the lock in S3 beside the state.
  # Backend settings cannot use variables -- Terraform reads this block before
  # variables exist -- so the profile is spelled out here as well as in the
  # provider below. Without it the backend ignores the provider's profile and
  # falls through to the EC2 instance metadata service, which fails on a laptop.
  backend "s3" {
    bucket       = "biogent-tfstate-396913715360"
    key          = "phase5/terraform.tfstate"
    region       = "us-east-1"
    profile      = "biogent-admin"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}
