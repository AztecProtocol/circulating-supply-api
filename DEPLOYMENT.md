# Aztec Circulating Supply API - Deployment Guide

## Quick Start

```bash
# 1. Configure AWS credentials
export AWS_PROFILE=foundation

# 2. Set up Terraform variables
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

# 3. Deploy everything
cd ..
./scripts/deploy.sh
```

The API will be available at `https://supply.aztec.network`

## Architecture

```
Route53 (supply.aztec.network)
  -> CloudFront (HTTP->HTTPS redirect, caching)
    -> API Gateway HTTP API (eu-west-2)
      -> Lambda (API handler, reads from S3)

EventBridge (hourly)
  -> Lambda (Calculator, writes to S3)
```

## What Gets Deployed

### Infrastructure
- **2 Lambda Functions**
  - Calculator (512MB, 5min timeout): Runs hourly to compute supply
  - API Handler (256MB, 30s timeout): Serves HTTP requests

- **S3 Buckets**
  - `aztec-supply-data-prod`: Stores current and historical supply data (versioned)
  - `aztec-supply-lambda-artifacts-prod`: Stores Lambda deployment packages

- **CloudFront Distribution**
  - Custom domain: `supply.aztec.network`
  - HTTP to HTTPS redirect
  - 5-minute default TTL cache
  - IPv6 enabled

- **API Gateway HTTP API** (regional, eu-west-2)
  - Routes: `/`, `/all`, `/simple`, `/raw`
  - CORS enabled
  - Throttling: 100 burst, 50 rate limit

- **ACM Certificate** (us-east-1, required by CloudFront)
  - DNS-validated via Route53

- **Route53**
  - A + AAAA records pointing to CloudFront

- **EventBridge**
  - Hourly trigger for calculator Lambda

- **CloudWatch**
  - Log groups with 7-day retention

### Validation
- Rejects updates if supply is 0
- Rejects updates if supply drops >5% (configurable)
- Stores historical snapshots in S3
- S3 versioning enabled for rollback

## Prerequisites

1. **AWS Account** with permissions for:
   Lambda, S3, API Gateway, Route53, IAM, CloudWatch, ACM, CloudFront

2. **Route53 Hosted Zone** for `aztec.network`
   ```bash
   aws route53 list-hosted-zones
   ```

3. **Ethereum RPC URL** (Infura, Alchemy, QuickNode, or own node)

4. **Tools**: AWS CLI, Terraform >= 1.0, Python 3.11+

## Configuration

### Terraform Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region      = "eu-west-2"
environment     = "prod"
eth_rpc_url     = "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
route53_zone_id = "Z1234567890ABC"
```

Never commit `terraform.tfvars` to git.

### Manual Deployment

```bash
# Build Lambda layer
./scripts/build-lambda-layer.sh

# Upload layer to S3
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
  --region eu-west-2 \
  output.json
cat output.json | jq
```

Note: CloudFront distributions take 5-15 minutes to deploy.

## API Endpoints

| Endpoint | Returns | Content-Type |
|----------|---------|--------------|
| `/` | Circulating supply as a number | `application/json` |
| `/all` | Full data dump with breakdown | `application/json` |
| `/simple` | Supply + timestamp | `application/json` |
| `/raw` | Plain text number | `text/plain` |

```bash
# Circulating supply number
curl https://supply.aztec.network/

# Full data
curl https://supply.aztec.network/all

# Simple format
curl https://supply.aztec.network/simple

# Raw text (for CoinGecko, CMC)
curl https://supply.aztec.network/raw
```

## CI/CD

The GitHub Actions workflow (`.github/workflows/deploy.yml`) deploys on push to `main` using GitHub Deployments.

### Required Secrets

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | IAM role ARN for OIDC federation |
| `ETH_RPC_URL` | Ethereum RPC endpoint |
| `ROUTE53_ZONE_ID` | Route53 hosted zone ID |

The workflow uses OIDC (`id-token: write`) for AWS auth. Set up an [IAM OIDC identity provider](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services) for the GitHub Actions trust relationship.

The Terraform state backend bucket (`aztec-foundation-terraform-state`) is hardcoded in `terraform/main.tf`.

## Monitoring

```bash
# Calculator logs
aws logs tail /aws/lambda/aztec-supply-calculator --follow

# API logs
aws logs tail /aws/lambda/aztec-supply-api-handler --follow

# API Gateway logs
aws logs tail /aws/apigateway/aztec-supply-api --follow

# Check current data in S3
aws s3 cp s3://aztec-supply-data-prod/current.json - | jq

# Trigger manual recalculation
aws lambda invoke \
  --function-name aztec-supply-calculator \
  --region eu-west-2 \
  output.json
```

## Tuning

### Update Frequency

Edit `terraform/eventbridge.tf`:
```hcl
schedule_expression = "rate(30 minutes)"  # Every 30 minutes
```

### Validation Threshold

In `terraform.tfvars`:
```hcl
update_threshold_percentage = 0.90  # Allow up to 10% decrease
```

### Lambda Resources

In `terraform.tfvars`:
```hcl
lambda_timeout = 600   # 10 minutes
lambda_memory  = 1024  # 1 GB
```

Run `terraform apply` after any changes.

## Troubleshooting

### ACM Certificate Stuck Pending

DNS validation can take 10-30 minutes. Check:
```bash
aws acm list-certificates --region us-east-1
```

### Lambda Import Errors

Rebuild and re-upload the Lambda layer:
```bash
./scripts/build-lambda-layer.sh aztec-supply-lambda-artifacts-prod
terraform apply
```

### RPC Errors

The script scans from deployment blocks (~21.8M), not genesis. If you still hit rate limits, use a paid RPC plan or reduce update frequency.

### Supply Value is Wrong

Check the calculator logs for errors. Common causes:
- RPC URL is invalid or rate-limited
- Contract addresses changed (update `circulating-supply.py`)

### CloudFront Returns Old Data

CloudFront caches responses for up to 5 minutes (`default_ttl = 300`). To invalidate:
```bash
aws cloudfront create-invalidation \
  --distribution-id DIST_ID \
  --paths "/*"
```

## Backup & Recovery

S3 versioning is enabled. To restore a previous version:

```bash
# List versions
aws s3api list-object-versions \
  --bucket aztec-supply-data-prod \
  --prefix current.json

# Restore
aws s3api copy-object \
  --bucket aztec-supply-data-prod \
  --copy-source "aztec-supply-data-prod/current.json?versionId=VERSION_ID" \
  --key current.json
```

## Cleanup

```bash
cd terraform
terraform destroy
```

Before destroying, backup data:
```bash
aws s3 sync s3://aztec-supply-data-prod ./backup/
```

## Environment Variable

The `ETH_RPC_URL` environment variable is required to run `circulating-supply.py` locally:
```bash
ETH_RPC_URL=https://... python3 circulating-supply.py
```
