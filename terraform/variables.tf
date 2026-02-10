variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., prod, staging)"
  type        = string
  default     = "prod"
}

variable "eth_rpc_url" {
  description = "Ethereum RPC URL for the script"
  type        = string
  sensitive   = true
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for aztec.network"
  type        = string
}

variable "update_threshold_percentage" {
  description = "Minimum percentage decrease allowed before rejecting update (0.95 = 5% threshold)"
  type        = number
  default     = 0.95
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300 # 5 minutes
}

variable "lambda_memory" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 512
}
