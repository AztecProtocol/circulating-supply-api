# API Gateway HTTP API
resource "aws_apigatewayv2_api" "supply" {
  name          = local.api_name
  protocol_type = "HTTP"
  description   = "Aztec Circulating Supply API"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 300
  }
}

# API Gateway Stage
resource "aws_apigatewayv2_stage" "supply" {
  api_id      = aws_apigatewayv2_api.supply.id
  name        = var.environment
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }
}

# CloudWatch Log Group for API Gateway
resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.api_name}"
  retention_in_days = 7
}

# Lambda Integration
resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id           = aws_apigatewayv2_api.supply.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.api.invoke_arn

  payload_format_version = "2.0"
}

# Routes
resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.supply.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_route" "supply" {
  api_id    = aws_apigatewayv2_api.supply.id
  route_key = "GET /supply"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_route" "simple" {
  api_id    = aws_apigatewayv2_api.supply.id
  route_key = "GET /simple"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_route" "raw" {
  api_id    = aws_apigatewayv2_api.supply.id
  route_key = "GET /raw"
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

# Custom Domain - ACM Certificate
resource "aws_acm_certificate" "supply" {
  provider          = aws.us_east_1 # Must be in us-east-1 for API Gateway
  domain_name       = local.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Certificate Validation Record
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.supply.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = var.route53_zone_id
}

# Certificate Validation
resource "aws_acm_certificate_validation" "supply" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.supply.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# API Gateway Custom Domain
resource "aws_apigatewayv2_domain_name" "supply" {
  domain_name = local.domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.supply.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

# API Mapping
resource "aws_apigatewayv2_api_mapping" "supply" {
  api_id      = aws_apigatewayv2_api.supply.id
  domain_name = aws_apigatewayv2_domain_name.supply.id
  stage       = aws_apigatewayv2_stage.supply.id
}
