# IAM role for calculator Lambda function
resource "aws_iam_role" "calculator_lambda" {
  name = "${local.function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "calculator_lambda_basic" {
  role       = aws_iam_role.calculator_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# S3 access policy for calculator Lambda
resource "aws_iam_role_policy" "calculator_lambda_s3" {
  name = "${local.function_name}-s3-policy"
  role = aws_iam_role.calculator_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.supply_data.arn,
          "${aws_s3_bucket.supply_data.arn}/*"
        ]
      }
    ]
  })
}

# IAM role for API Lambda function
resource "aws_iam_role" "api_lambda" {
  name = "${local.api_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Basic Lambda execution policy for API
resource "aws_iam_role_policy_attachment" "api_lambda_basic" {
  role       = aws_iam_role.api_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# S3 read-only access for API Lambda
resource "aws_iam_role_policy" "api_lambda_s3" {
  name = "${local.api_name}-s3-policy"
  role = aws_iam_role.api_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${aws_s3_bucket.supply_data.arn}/*"
        ]
      }
    ]
  })
}
