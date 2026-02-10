# Data source to create deployment package
data "archive_file" "calculator_lambda" {
  type        = "zip"
  output_path = "${path.module}/.terraform/calculator_lambda.zip"

  source {
    content  = file("${path.module}/../lambda/calculator_handler.py")
    filename = "calculator_handler.py"
  }

  source {
    content  = file("${path.module}/../lambda/supply_calculator.py")
    filename = "supply_calculator.py"
  }

  source {
    content  = file("${path.module}/../circulating-supply.py")
    filename = "circulating_supply.py"
  }
}

# Upload calculator Lambda package to S3
resource "aws_s3_object" "calculator_lambda" {
  bucket = aws_s3_bucket.lambda_artifacts.id
  key    = "calculator/${data.archive_file.calculator_lambda.output_md5}.zip"
  source = data.archive_file.calculator_lambda.output_path
  etag   = data.archive_file.calculator_lambda.output_md5
}

# Lambda Layer for dependencies (web3, eth_abi)
# Note: You'll need to build this layer separately - see README
resource "aws_lambda_layer_version" "python_dependencies" {
  layer_name          = "aztec-supply-python-deps"
  description         = "Python dependencies: web3, eth_abi"
  s3_bucket           = aws_s3_bucket.lambda_artifacts.id
  s3_key              = "layers/python-deps.zip" # Upload this manually first
  compatible_runtimes = ["python3.11"]

  lifecycle {
    ignore_changes = [s3_key] # Don't recreate if layer already exists
  }
}

# Calculator Lambda Function
resource "aws_lambda_function" "calculator" {
  function_name = local.function_name
  role          = aws_iam_role.calculator_lambda.arn
  handler       = "calculator_handler.lambda_handler"
  runtime       = "python3.11"

  s3_bucket = aws_s3_bucket.lambda_artifacts.id
  s3_key    = aws_s3_object.calculator_lambda.key

  source_code_hash = data.archive_file.calculator_lambda.output_base64sha256

  timeout     = var.lambda_timeout
  memory_size = var.lambda_memory

  layers = [aws_lambda_layer_version.python_dependencies.arn]

  environment {
    variables = {
      SUPPLY_BUCKET     = aws_s3_bucket.supply_data.id
      ETH_RPC_URL       = var.eth_rpc_url
      UPDATE_THRESHOLD  = var.update_threshold_percentage
      PYTHONUNBUFFERED  = "1"
    }
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy_attachment.calculator_lambda_basic,
    aws_iam_role_policy.calculator_lambda_s3
  ]
}

# CloudWatch Log Group for Calculator Lambda
resource "aws_cloudwatch_log_group" "calculator" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 7
}

# Data source for API Lambda package
data "archive_file" "api_lambda" {
  type        = "zip"
  output_path = "${path.module}/.terraform/api_lambda.zip"

  source {
    content  = file("${path.module}/../lambda/api_handler.py")
    filename = "api_handler.py"
  }
}

# Upload API Lambda package to S3
resource "aws_s3_object" "api_lambda" {
  bucket = aws_s3_bucket.lambda_artifacts.id
  key    = "api/${data.archive_file.api_lambda.output_md5}.zip"
  source = data.archive_file.api_lambda.output_path
  etag   = data.archive_file.api_lambda.output_md5
}

# API Lambda Function
resource "aws_lambda_function" "api" {
  function_name = "${local.api_name}-handler"
  role          = aws_iam_role.api_lambda.arn
  handler       = "api_handler.lambda_handler"
  runtime       = "python3.11"

  s3_bucket = aws_s3_bucket.lambda_artifacts.id
  s3_key    = aws_s3_object.api_lambda.key

  source_code_hash = data.archive_file.api_lambda.output_base64sha256

  timeout     = 30
  memory_size = 256

  environment {
    variables = {
      SUPPLY_BUCKET = aws_s3_bucket.supply_data.id
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.api_lambda_basic,
    aws_iam_role_policy.api_lambda_s3
  ]
}

# CloudWatch Log Group for API Lambda
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.api_name}-handler"
  retention_in_days = 7
}

# Lambda permission for API Gateway to invoke API Lambda
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.supply.execution_arn}/*/*"
}
