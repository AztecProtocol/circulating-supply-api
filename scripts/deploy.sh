#!/bin/bash
set -e

# Deployment script for Aztec Supply API
# This script automates the deployment process

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
TERRAFORM_DIR="$PROJECT_ROOT/terraform"

echo "🚀 Aztec Supply API Deployment"
echo "================================"
echo ""

# Check prerequisites
echo "✅ Checking prerequisites..."

# Check if terraform is installed
if ! command -v terraform &> /dev/null; then
    echo "❌ Terraform is not installed. Please install it first."
    echo "   Visit: https://www.terraform.io/downloads"
    exit 1
fi

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed. Please install it first."
    echo "   Visit: https://aws.amazon.com/cli/"
    exit 1
fi

# Check if terraform.tfvars exists
if [ ! -f "$TERRAFORM_DIR/terraform.tfvars" ]; then
    echo "❌ terraform.tfvars not found"
    echo "   Copy terraform.tfvars.example to terraform.tfvars and fill in your values:"
    echo "   cd terraform && cp terraform.tfvars.example terraform.tfvars"
    exit 1
fi

echo "   ✓ Terraform installed"
echo "   ✓ AWS CLI installed"
echo "   ✓ terraform.tfvars found"
echo ""

# Step 1: Build Lambda Layer
echo "📦 Step 1: Building Lambda Layer..."
"$SCRIPT_DIR/build-lambda-layer.sh"
echo ""

# Step 2: Create S3 bucket for artifacts (if it doesn't exist)
echo "📦 Step 2: Setting up S3 buckets..."
ENVIRONMENT=$(grep 'environment' "$TERRAFORM_DIR/terraform.tfvars" | cut -d'"' -f2)
REGION=$(grep 'aws_region' "$TERRAFORM_DIR/terraform.tfvars" | cut -d'"' -f2)
ARTIFACTS_BUCKET="aztec-supply-lambda-artifacts-${ENVIRONMENT}"

# Check if bucket exists
if aws s3 ls "s3://$ARTIFACTS_BUCKET" 2>&1 | grep -q 'NoSuchBucket'; then
    echo "   Creating artifacts bucket: $ARTIFACTS_BUCKET"
    aws s3 mb "s3://$ARTIFACTS_BUCKET" --region "$REGION"
else
    echo "   ✓ Artifacts bucket exists: $ARTIFACTS_BUCKET"
fi

# Upload layer
echo "   Uploading Lambda layer..."
aws s3 cp "$PROJECT_ROOT/build/python-deps.zip" "s3://$ARTIFACTS_BUCKET/layers/python-deps.zip"
echo "   ✓ Layer uploaded"
echo ""

# Step 3: Terraform Init
echo "🔧 Step 3: Initializing Terraform..."
cd "$TERRAFORM_DIR"
terraform init
echo ""

# Step 4: Terraform Plan
echo "📋 Step 4: Planning Terraform deployment..."
terraform plan -out=tfplan
echo ""

# Step 5: Confirm deployment
echo "⚠️  Review the plan above carefully."
read -p "   Do you want to proceed with deployment? (yes/no): " CONFIRM
echo ""

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Deployment cancelled."
    rm -f tfplan
    exit 0
fi

# Step 6: Apply
echo "🚀 Step 5: Applying Terraform configuration..."
terraform apply tfplan
rm -f tfplan
echo ""

# Step 7: Get outputs
echo "📊 Deployment complete! Here are your endpoints:"
echo ""
terraform output -json | jq -r '
  .api_routes.value | to_entries[] |
  "   \(.key | ascii_upcase): \(.value)"
'
echo ""

# Step 8: Trigger initial run
FUNCTION_NAME=$(terraform output -raw calculator_lambda_function_name)
echo "🔄 Triggering initial calculator run..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    /tmp/supply-response.json > /dev/null

if [ -f /tmp/supply-response.json ]; then
    echo "   Response:"
    cat /tmp/supply-response.json | jq
    rm /tmp/supply-response.json
fi

echo ""
echo "✅ Deployment successful!"
echo ""
echo "📚 Next steps:"
echo "   - Monitor logs: aws logs tail /aws/lambda/$FUNCTION_NAME --follow"
echo "   - Test API: curl https://supply.aztec.network/"
echo "   - View data: aws s3 cp s3://aztec-supply-data-${ENVIRONMENT}/current.json - | jq"
