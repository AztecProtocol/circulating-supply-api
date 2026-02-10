# S3 bucket for storing supply data
resource "aws_s3_bucket" "supply_data" {
  bucket = "aztec-supply-data-${var.environment}"
}

resource "aws_s3_bucket_versioning" "supply_data" {
  bucket = aws_s3_bucket.supply_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "supply_data" {
  bucket = aws_s3_bucket.supply_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "supply_data" {
  bucket = aws_s3_bucket.supply_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 bucket for Lambda deployment package
resource "aws_s3_bucket" "lambda_artifacts" {
  bucket = "aztec-supply-lambda-artifacts-${var.environment}"
}

resource "aws_s3_bucket_versioning" "lambda_artifacts" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "lambda_artifacts" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
