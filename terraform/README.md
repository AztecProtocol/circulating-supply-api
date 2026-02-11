# Aztec Circulating Supply API - Terraform Infrastructure

Terraform configuration for deploying the Aztec circulating supply calculator as a serverless API on AWS.

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
                          │  (512MB, 5min)  │      └──────┬───────┘
                          └─────────────────┘             │
                                                          ▼
┌─────────────────┐      ┌─────────────────┐      ┌──────────────┐
│   Route53 DNS   │ ───> │   CloudFront    │ ───> │  API Gateway │
│ supply.aztec... │      │  (HTTP→HTTPS)   │      │  HTTP API    │
└─────────────────┘      └─────────────────┘      └──────┬───────┘
                                                          │
                                                   ┌──────┴───────┐
                                                   │  API Lambda  │
                                                   │  (256MB)     │
                                                   └──────────────┘
```

## Resources Created

- **2 Lambda Functions**: Calculator (hourly, 512MB, 5min timeout) and API handler (256MB, 30s timeout)
- **2 S3 Buckets**: Supply data (versioned) and Lambda artifacts
- **CloudFront Distribution**: Custom domain, HTTP→HTTPS redirect, 5min cache, IPv6
- **API Gateway HTTP API**: Regional (eu-west-2), routes: `/`, `/all`, `/simple`, `/raw`
- **ACM Certificate**: DNS-validated, in us-east-1 (CloudFront requirement)
- **Route53**: A + AAAA records pointing to CloudFront
- **EventBridge**: Hourly calculator trigger
- **CloudWatch**: Log groups with 7-day retention
- **IAM**: Least-privilege roles for both Lambdas

## Prerequisites

1. AWS account with permissions for Lambda, S3, API Gateway, Route53, IAM, CloudWatch, ACM, CloudFront
2. Terraform >= 1.0
3. AWS CLI configured (`aws configure --profile foundation`)
4. Route53 hosted zone for `aztec.network`
5. Ethereum RPC URL

## Setup

### 1. Build Lambda Layer

```bash
cd ..
./scripts/build-lambda-layer.sh
```

Upload to S3:
```bash
aws s3 mb s3://aztec-supply-lambda-artifacts-prod
aws s3 cp build/python-deps.zip s3://aztec-supply-lambda-artifacts-prod/layers/python-deps.zip
```

### 2. Configure Variables

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region      = "eu-west-2"
environment     = "prod"
eth_rpc_url     = "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
route53_zone_id = "Z1234567890ABC"

# Optional
update_threshold_percentage = 0.95  # Reject if >5% decrease
lambda_timeout              = 300   # 5 minutes
lambda_memory               = 512   # MB
```

Never commit `terraform.tfvars` to version control.

### 3. Deploy

```bash
terraform init
terraform plan
terraform apply
```

CloudFront distributions take 5-15 minutes to deploy.

### 4. Trigger First Run

```bash
aws lambda invoke \
  --function-name aztec-supply-calculator \
  --region eu-west-2 \
  output.json

cat output.json | jq
```

## API Endpoints

| Endpoint | Response | Content-Type |
|----------|----------|--------------|
| `GET /` | Circulating supply as a number | `application/json` |
| `GET /all` | Full data dump with breakdown | `application/json` |
| `GET /simple` | Supply number + timestamp | `application/json` |
| `GET /raw` | Plain text number | `text/plain` |

```bash
curl https://supply.aztec.network/
# 1342003144.11

curl https://supply.aztec.network/all
# { "timestamp": "...", "circulating_supply": "...", "breakdown": { ... } }

curl https://supply.aztec.network/raw
# 1342003144.11
```

## File Structure

```
terraform/
  main.tf                 # Providers (eu-west-2 + us-east-1 for ACM), locals
  variables.tf            # Input variables
  api.tf                  # API Gateway, CloudFront, ACM certificate
  lambda.tf               # Lambda functions and layer
  s3.tf                   # S3 buckets
  iam.tf                  # IAM roles and policies
  eventbridge.tf          # Hourly schedule trigger
  route53.tf              # DNS records (A + AAAA -> CloudFront)
  outputs.tf              # Exported values
  terraform.tfvars.example
```

## CI/CD

Deployments are automated via `.github/workflows/deploy.yml` on push to `main`.

Required GitHub secrets:

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | IAM role ARN for OIDC federation |
| `ETH_RPC_URL` | Ethereum RPC endpoint |
| `ROUTE53_ZONE_ID` | Route53 hosted zone ID |

State is stored in `s3://aztec-foundation-terraform-state/circulating-supply-api`.

## Validation

The calculator validates before updating S3:

1. Rejects if circulating supply is 0
2. Rejects if supply drops >5% from current value (configurable)
3. Always accepts the initial data point

Failed validations are logged but don't update the API — the previous value persists.

## Monitoring

```bash
# Calculator logs
aws logs tail /aws/lambda/aztec-supply-calculator --follow

# API logs
aws logs tail /aws/lambda/aztec-supply-api-handler --follow

# Current data
aws s3 cp s3://aztec-supply-data-prod/current.json - | jq

# Manual recalculation
aws lambda invoke --function-name aztec-supply-calculator --region eu-west-2 output.json
```

## Troubleshooting

**ACM certificate stuck pending**: DNS validation takes 10-30 minutes. Check with `aws acm list-certificates --region us-east-1`.

**Lambda timeout**: Increase `lambda_timeout` in `terraform.tfvars` and `terraform apply`.

**RPC errors**: The script scans from deployment blocks (~21.8M), not genesis. Use a paid RPC provider if rate-limited.

**CloudFront serving stale data**: Cache TTL is 5 minutes. Force invalidation:
```bash
aws cloudfront create-invalidation --distribution-id DIST_ID --paths "/*"
```

**Lambda import errors**: Rebuild the layer: `./scripts/build-lambda-layer.sh aztec-supply-lambda-artifacts-prod && terraform apply`.

## Cleanup

```bash
terraform destroy
```

Backup data first: `aws s3 sync s3://aztec-supply-data-prod ./backup/`
