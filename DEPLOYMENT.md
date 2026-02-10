# Aztec Circulating Supply API - Deployment Guide

This guide covers deploying the Aztec circulating supply calculator as a production-ready API on AWS.

## Quick Start

```bash
# 1. Configure AWS credentials
export AWS_PROFILE=your-profile  # or use aws configure

# 2. Set up Terraform variables
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

# 3. Deploy everything
cd ..
./scripts/deploy.sh
```

That's it! The API will be available at `https://supply.aztec.network`

## What Gets Deployed

### Infrastructure
- **2 Lambda Functions**
  - Calculator: Runs hourly to compute supply
  - API Handler: Serves HTTP requests

- **S3 Buckets**
  - Data bucket: Stores current and historical supply data
  - Artifacts bucket: Stores Lambda deployment packages

- **API Gateway**
  - HTTP API with custom domain
  - Multiple endpoints (/, /supply, /simple, /raw)
  - CORS enabled

- **Route53**
  - DNS record: `supply.aztec.network`
  - SSL/TLS certificate from ACM

- **EventBridge**
  - Hourly trigger for calculator

- **CloudWatch**
  - Log groups for monitoring
  - 7-day retention

### Validation Features
- ✅ Rejects updates if supply is 0
- ✅ Rejects updates if supply drops >5% (configurable)
- ✅ Stores historical snapshots
- ✅ S3 versioning enabled

## Prerequisites

1. **AWS Account** with permissions for:
   - Lambda, S3, API Gateway, Route53, IAM, CloudWatch, ACM

2. **Route53 Hosted Zone** for `aztec.network`
   - Find zone ID: `aws route53 list-hosted-zones`

3. **Ethereum RPC URL**
   - Get from: Infura, Alchemy, QuickNode, or your own node
   - Free tier: https://www.alchemy.com/

4. **Tools**
   - AWS CLI: https://aws.amazon.com/cli/
   - Terraform >= 1.0: https://www.terraform.io/downloads
   - Python 3.11+
   - jq (optional, for testing)

## Step-by-Step Deployment

### 1. Configure Terraform Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region  = "us-east-1"
environment = "prod"
eth_rpc_url = "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
route53_zone_id = "Z1234567890ABC"  # Your Route53 zone ID
```

⚠️ **Never commit `terraform.tfvars` to git!**

### 2. Build Lambda Layer

The Lambda functions need Python dependencies (`web3`, `eth_abi`):

```bash
./scripts/build-lambda-layer.sh
```

This creates `build/python-deps.zip` (~20MB).

### 3. Deploy with Script (Recommended)

```bash
./scripts/deploy.sh
```

This script will:
1. ✅ Check prerequisites
2. ✅ Build Lambda layer
3. ✅ Create S3 buckets
4. ✅ Upload dependencies
5. ✅ Run Terraform init/plan/apply
6. ✅ Trigger initial calculator run
7. ✅ Display API endpoints

### 3. Deploy Manually (Alternative)

```bash
# Build layer
./scripts/build-lambda-layer.sh

# Upload layer
aws s3 mb s3://aztec-supply-lambda-artifacts-prod
aws s3 cp build/python-deps.zip s3://aztec-supply-lambda-artifacts-prod/layers/python-deps.zip

# Deploy infrastructure
cd terraform
terraform init
terraform plan
terraform apply

# Trigger first run
aws lambda invoke \
  --function-name aztec-supply-calculator \
  --region us-east-1 \
  output.json

cat output.json | jq
```

## API Endpoints

### Full Data (Default)
```bash
curl https://supply.aztec.network/
```

Returns complete supply data with breakdown.

### Simple Format
```bash
curl https://supply.aztec.network/simple
```

Returns just circulating supply and timestamp.

### Raw Text
```bash
curl https://supply.aztec.network/raw
```

Returns only the circulating supply number (for CoinGecko, etc.).

### All Endpoints
```bash
./scripts/test-api.sh
```

## Monitoring

### View Live Logs
```bash
# Calculator logs
aws logs tail /aws/lambda/aztec-supply-calculator --follow

# API logs
aws logs tail /aws/lambda/aztec-supply-api-handler --follow

# API Gateway logs
aws logs tail /aws/apigateway/aztec-supply-api --follow
```

### Check Current Data
```bash
aws s3 cp s3://aztec-supply-data-prod/current.json - | jq
```

### Trigger Manual Update
```bash
aws lambda invoke \
  --function-name aztec-supply-calculator \
  --region us-east-1 \
  output.json

cat output.json | jq
```

### View CloudWatch Metrics
```bash
# Open in browser
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=aztec-supply-calculator \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum
```

## Configuration

### Change Update Frequency

Edit `terraform/eventbridge.tf`:

```hcl
schedule_expression = "rate(30 minutes)"  # Every 30 minutes
# OR
schedule_expression = "cron(0 * * * ? *)"  # Top of every hour
```

Then run `terraform apply`.

### Adjust Validation Threshold

In `terraform.tfvars`:

```hcl
update_threshold_percentage = 0.90  # Allow up to 10% decrease
```

Then run `terraform apply`.

### Increase Lambda Timeout

If calculator times out, increase timeout in `terraform.tfvars`:

```hcl
lambda_timeout = 600  # 10 minutes
lambda_memory  = 1024 # 1 GB
```

Then run `terraform apply`.

## Troubleshooting

### "No Such Bucket" Error

The S3 buckets are created by Terraform. If you see this error during first deployment, it's normal - Terraform will create them.

### ACM Certificate Stuck Pending

DNS validation can take 10-30 minutes. Check status:

```bash
aws acm list-certificates --region us-east-1
```

### Lambda Import Errors

Rebuild and re-upload the Lambda layer:

```bash
./scripts/build-lambda-layer.sh aztec-supply-lambda-artifacts-prod
terraform apply
```

### RPC Rate Limiting

The script is optimized to start scanning from deployment blocks (~21.8M), not genesis. If you still hit rate limits:

1. Use a paid RPC plan
2. Reduce update frequency
3. Use your own Ethereum node

### Supply Value is 0 or Wrong

Check the calculator logs:

```bash
aws logs tail /aws/lambda/aztec-supply-calculator --follow
```

Common causes:
- RPC URL is invalid
- Network connectivity issues
- Contract addresses changed (update `circulating-supply.py`)

## Cost Estimate

Monthly AWS costs (approximate):

| Service | Usage | Cost |
|---------|-------|------|
| Lambda (Calculator) | 744 runs/month @ 300s | $1-2 |
| Lambda (API) | 10K requests/month | $0.20 |
| S3 Storage | 1 GB | $0.02 |
| S3 Requests | 10K GET | $0.004 |
| API Gateway | 10K requests | $0.01 |
| Route53 | 1 record | $0.50 |
| Data Transfer | ~1 GB out | $0.09 |
| **Total** | | **~$2-4/month** |

Costs scale with API traffic. 1M API requests/month ≈ $30/month.

## Security

✅ **Implemented**:
- S3 encryption at rest (AES-256)
- HTTPS/TLS 1.2+ for all endpoints
- IAM least privilege roles
- S3 public access blocked
- VPC not needed (public Lambda)
- CloudWatch Logs encryption
- Secrets in environment variables (encrypted at rest)

❌ **Not Implemented** (optional enhancements):
- VPC for Lambda functions
- WAF for API Gateway
- DDoS protection (CloudFront)
- Secrets Manager for RPC URL
- Multi-region deployment

## Backup & Recovery

### Backup Strategy
- **S3 Versioning**: Enabled on data bucket
- **Historical Snapshots**: Saved in `history/` folder
- **Terraform State**: Store in S3 with versioning

### Recovery Procedure

If data is corrupted:

```bash
# List versions
aws s3api list-object-versions \
  --bucket aztec-supply-data-prod \
  --prefix current.json

# Restore previous version
aws s3api copy-object \
  --bucket aztec-supply-data-prod \
  --copy-source "aztec-supply-data-prod/current.json?versionId=VERSION_ID" \
  --key current.json
```

## Updating the Script

To update the calculator logic:

1. Modify `circulating-supply.py`
2. Run `terraform apply`
3. Verify: `aws lambda invoke --function-name aztec-supply-calculator output.json`

Terraform detects file changes and redeploys automatically.

## Cleanup

To destroy all resources:

```bash
cd terraform
terraform destroy
```

⚠️ **Warning**: This deletes everything including historical data!

Before destroying:
1. Backup S3 data: `aws s3 sync s3://aztec-supply-data-prod ./backup/`
2. Export Terraform state: `terraform state pull > backup/terraform.tfstate`

## Production Checklist

Before going to production:

- [ ] Configure Terraform backend (S3 + DynamoDB)
- [ ] Use paid RPC provider with high rate limits
- [ ] Set up CloudWatch alarms for errors
- [ ] Configure SNS notifications
- [ ] Enable API Gateway access logging
- [ ] Consider adding WAF for DDoS protection
- [ ] Set up Route53 health checks
- [ ] Document runbooks for common issues
- [ ] Test failover scenarios
- [ ] Set up backup/restore procedures

## Support

- **Terraform Docs**: https://registry.terraform.io/providers/hashicorp/aws/latest/docs
- **AWS Lambda**: https://docs.aws.amazon.com/lambda/
- **API Gateway**: https://docs.aws.amazon.com/apigateway/
- **web3.py**: https://web3py.readthedocs.io/

For issues with the calculator script, check CloudWatch Logs first.

## License

Same as main project.
