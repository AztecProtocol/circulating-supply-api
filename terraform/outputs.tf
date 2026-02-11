output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_stage.supply.invoke_url
}

output "custom_domain_url" {
  description = "Custom domain URL"
  value       = "https://${local.domain_name}"
}

output "calculator_lambda_function_name" {
  description = "Name of the calculator Lambda function"
  value       = aws_lambda_function.calculator.function_name
}

output "api_lambda_function_name" {
  description = "Name of the API Lambda function"
  value       = aws_lambda_function.api.function_name
}

output "supply_data_bucket" {
  description = "S3 bucket for supply data"
  value       = aws_s3_bucket.supply_data.id
}

output "cloudwatch_log_groups" {
  description = "CloudWatch Log Groups"
  value = {
    calculator = aws_cloudwatch_log_group.calculator.name
    api        = aws_cloudwatch_log_group.api.name
    api_gateway = aws_cloudwatch_log_group.api_gateway.name
  }
}

output "api_routes" {
  description = "Available API routes"
  value = {
    default = "https://${local.domain_name}/"
    all     = "https://${local.domain_name}/all"
    simple  = "https://${local.domain_name}/simple"
    raw     = "https://${local.domain_name}/raw"
  }
}
