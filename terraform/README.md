# Aztec Circulating Supply API - Terraform Infrastructure

This Terraform configuration deploys the Aztec circulating supply calculator as a serverless API on AWS.

## Architecture

```
┌─────────────────┐
│  EventBridge    │  ──> Triggers hourly
│   (Cron: 1hr)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│  Calculator     │ ───> │  S3 Bucket   │
│  Lambda         │      │  (Data)      │
│  (circulating-  │      └──────┬───────┘
│   supply.py)    │             │
└─────────────────┘             │
                                ▼
┌─────────────────┐      ┌──────────────┐
│  API Gateway    │ <─── │  API Lambda  │
│  + Custom Domain│      │  (Handler)   │
└────────┬────────┘      └──────────────┘
         │
         ▼
┌─────────────────┐
│   Route53 DNS   │
│ supply.aztec... │
└─────────────────┘
```

## Features

- **Hourly Updates**: Automatically calculates supply every hour via EventBridge
- **Validation**: Rejects updates if supply is 0 or drops >5% (configurable)
- **Multiple Formats**: Full JSON, simple, and raw text endpoints
- **CORS Enabled**: API accessible from any origin
- **Custom Domain**: `supply.aztec.network` with SSL/TLS
- **Monitoring**: CloudWatch Logs for all components
- **Versioning**: S3 versioning and historical snapshots

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **Terraform** >= 1.0
3. **AWS CLI** configured with credentials
4. **Route53 Hosted Zone** for `aztec.network`
5. **Ethereum RPC URL** (e.g., Infura, Alchemy, or custom node)

## Setup

### Step 1: Build Python Dependencies Layer

The Lambda function requires `web3` and `eth_abi` packages. Build a Lambda Layer:

```bash
cd ..
mkdir -p lambda-layer/python
pip install web3 eth-abi -t lambda-layer/python/
cd lambda-layer
zip -r ../python-deps.zip python/
cd ..
```

Upload to S3:
```bash
aws s3 mb s3://aztec-supply-lambda-artifacts-prod  # Create bucket
aws s3 cp python-deps.zip s3://aztec-supply-lambda-artifacts-prod/layers/python-deps.zip
```

### Step 2: Configure Variables

Create `terraform.tfvars`:

```hcl
aws_region     = "us-east-1"
environment    = "prod"
eth_rpc_url    = "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"  # Keep secret!
route53_zone_id = "Z1234567890ABC"  # Your Route53 zone ID for aztec.network

# Optional overrides
update_threshold_percentage = 0.95  # Reject if >5% decrease
lambda_timeout              = 300   # 5 minutes
lambda_memory               = 512   # MB
```

⚠️ **Security**: Keep `terraform.tfvars` out of version control. Add to `.gitignore`.

### Step 3: Initialize Terraform

```bash
cd terraform
terraform init
```

### Step 4: Review Plan

```bash
terraform plan
```

Review the resources to be created:
- 2 Lambda functions (calculator, API)
- 2 S3 buckets (data, artifacts)
- API Gateway with custom domain
- Route53 DNS record
- EventBridge hourly trigger
- IAM roles and policies
- CloudWatch Log Groups

### Step 5: Deploy

```bash
terraform apply
```

Confirm with `yes` when prompted.

### Step 6: Manual First Run (Optional)

Trigger the calculator immediately instead of waiting for the hourly schedule:

```bash
aws lambda invoke \
  --function-name aztec-supply-calculator \
  --region us-east-1 \
  /tmp/response.json

cat /tmp/response.json | jq
```

## API Endpoints

Once deployed, the API will be available at:

### Full Data (Default)
```bash
curl https://supply.aztec.network/
```

Response:
```json
{
  "timestamp": "2026-02-09T12:34:56+00:00",
  "block_number": 21866000,
  "circulating_supply": "123,456,789.00",
  "circulating_supply_wei": "123456789000000000000000000",
  "total_supply": "1,000,000,000.00",
  "locked_supply": "876,543,211.00",
  "percentage_circulating": 12.35,
  "is_rewards_claimable": false,
  "breakdown": { ... }
}
```

### Simple Format
```bash
curl https://supply.aztec.network/simple
```

Response:
```json
{
  "circulating_supply": "123,456,789.00",
  "timestamp": "2026-02-09T12:34:56+00:00"
}
```

### Raw Text (e.g., for CoinGecko)
```bash
curl https://supply.aztec.network/raw
```

Response:
```
123456789.00
```

## Monitoring

### View Calculator Logs
```bash
aws logs tail /aws/lambda/aztec-supply-calculator --follow
```

### View API Logs
```bash
aws logs tail /aws/lambda/aztec-supply-api-handler --follow
```

### Check S3 Data
```bash
aws s3 ls s3://aztec-supply-data-prod/ --recursive
aws s3 cp s3://aztec-supply-data-prod/current.json - | jq
```

### Manual Trigger
```bash
aws lambda invoke \
  --function-name aztec-supply-calculator \
  --region us-east-1 \
  output.json

cat output.json | jq
```

## Validation Logic

The calculator validates updates before saving:

1. **Zero Check**: Rejects if circulating supply is 0
2. **Decrease Threshold**: Rejects if supply drops more than 5% (configurable via `update_threshold_percentage`)
3. **First Run**: Always accepts the initial data point

When validation fails, the calculator logs the rejection but doesn't update the API data. The previous value remains available.

## Cost Estimate

Monthly costs (approximate):

- Lambda (Calculator): $1-2/month (744 invocations @ 300s, 512MB)
- Lambda (API): $0-1/month (depends on traffic)
- S3 Storage: $0.10/month (~1GB)
- API Gateway: $1/month per million requests
- Route53: $0.50/month per hosted zone record
- Data Transfer: Varies with traffic

**Total: ~$3-5/month** for low-moderate traffic

## Security

- All S3 buckets have encryption enabled
- Lambda functions use principle of least privilege IAM roles
- API uses HTTPS with TLS 1.2+
- CORS configured for public access
- CloudWatch Logs retention set to 7 days
- RPC URL stored as encrypted environment variable

## Troubleshooting

### Certificate Validation Stuck

DNS propagation for ACM validation can take 10-30 minutes. Check:
```bash
aws acm describe-certificate --certificate-arn <ARN> | jq .Certificate.Status
```

### Lambda Timeout

If calculator times out, increase `lambda_timeout` in `terraform.tfvars`:
```hcl
lambda_timeout = 600  # 10 minutes
```

### RPC Rate Limiting

If you see RPC errors, the script now uses deployment blocks to minimize requests. Ensure your RPC provider allows sufficient requests per hour.

### Import Error in Lambda

If Lambda fails with import errors:
1. Verify the python-deps layer was uploaded correctly
2. Check the layer ARN in the Lambda function configuration
3. Rebuild the layer with correct directory structure

## Updating

To update the calculator script:

1. Modify `circulating-supply.py` locally
2. Run `terraform apply` to redeploy
3. Changes take effect on next scheduled run (or trigger manually)

## Cleanup

To destroy all resources:

```bash
terraform destroy
```

⚠️ This will delete:
- All Lambda functions
- S3 buckets (if empty)
- API Gateway
- Route53 records
- CloudWatch Logs

## Advanced Configuration

### Change Schedule

Edit `terraform/eventbridge.tf`:
```hcl
schedule_expression = "rate(30 minutes)"  # Run every 30 minutes
# OR
schedule_expression = "cron(0 * * * ? *)"  # Run at the top of every hour
```

### Add Alerting

Add SNS topic for failed runs:
```hcl
resource "aws_sns_topic" "calculator_alerts" {
  name = "aztec-supply-calculator-alerts"
}

resource "aws_cloudwatch_metric_alarm" "calculator_errors" {
  alarm_name          = "aztec-supply-calculator-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 3600
  statistic           = "Sum"
  threshold           = 0
  alarm_actions       = [aws_sns_topic.calculator_alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.calculator.function_name
  }
}
```

## Support

For issues:
1. Check CloudWatch Logs
2. Verify RPC URL is valid and has sufficient quota
3. Ensure Route53 hosted zone exists
4. Check IAM permissions

## License

Same license as the main circulating-supply.py script.
