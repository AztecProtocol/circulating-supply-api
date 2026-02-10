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
    # Configure backend in backend.tfvars or via CLI
    # bucket = "your-terraform-state-bucket"
    # key    = "aztec-supply/terraform.tfstate"
    # region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "AztecSupply"
      ManagedBy   = "Terraform"
      Environment = var.environment
    }
  }
}

# For ACM certificates (must be in us-east-1 for CloudFront)
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

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
