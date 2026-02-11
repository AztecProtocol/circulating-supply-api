terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  backend "s3" {
    bucket = "aztec-foundation-terraform-state"
    key    = "circulating-supply-api"
    region = "eu-west-2"
  }
}

provider "aws" {
  profile = "foundation"
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "AztecSupply"
      ManagedBy   = "Terraform"
      Environment = var.environment
    }
  }
}

# ACM certificates for CloudFront must be in us-east-1
provider "aws" {
  alias   = "us_east_1"
  profile = "foundation"
  region  = "us-east-1"

  default_tags {
    tags = {
      Project     = "AztecSupply"
      ManagedBy   = "Terraform"
      Environment = var.environment
    }
  }
}

locals {
  function_name = "aztec-supply-calculator"
  api_name      = "aztec-supply-api"
  domain_name   = "supply.aztec.network"
}
