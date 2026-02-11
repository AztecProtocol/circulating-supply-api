#!/usr/bin/env python3
"""
AWS Lambda handler for the Aztec Supply API.
Serves the current circulating supply from S3.
"""

import json
import os
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client('s3')
BUCKET_NAME = os.environ['SUPPLY_BUCKET']
CURRENT_FILE = 'current.json'


def lambda_handler(event, context):
    """AWS Lambda handler for API Gateway requests."""

    # CORS headers
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Cache-Control': 'public, max-age=300'  # 5 minute cache
    }

    # Handle OPTIONS request for CORS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': ''
        }

    try:
        # Fetch current supply data from S3
        response = s3.get_object(Bucket=BUCKET_NAME, Key=CURRENT_FILE)
        supply_data = response['Body'].read().decode('utf-8')
        data = json.loads(supply_data)

        # Determine which format to return based on path
        # API Gateway HTTP API v2 uses 'rawPath', v1 uses 'path'
        path = event.get('rawPath') or event.get('path', '/')
        supply = data['circulating_supply_formatted'].replace(',', '')

        # Support different response formats
        # rawPath includes stage prefix for non-$default stages (e.g. /prod/all)
        if path.endswith('/all'):
            # Full data dump
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps(data, indent=2)
            }

        elif path.endswith('/simple'):
            # Simple format - circulating supply + timestamp
            # Build JSON manually to keep supply as an unquoted number
            return {
                'statusCode': 200,
                'headers': headers,
                'body': f'{{"circulating_supply": {supply}, "timestamp": {json.dumps(data["timestamp"])}}}'
            }

        elif path.endswith('/total'):
            # Total supply
            total = data['total_supply_formatted'].replace(',', '')
            return {
                'statusCode': 200,
                'headers': headers,
                'body': total
            }

        elif path.endswith('/raw'):
            # Raw format - just the number (for tools like CoinGecko)
            return {
                'statusCode': 200,
                'headers': {**headers, 'Content-Type': 'text/plain'},
                'body': supply
            }

        else:
            # Default (/) - just the circulating supply
            return {
                'statusCode': 200,
                'headers': headers,
                'body': supply
            }

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return {
                'statusCode': 404,
                'headers': headers,
                'body': json.dumps({
                    'error': 'Supply data not available yet',
                    'message': 'The calculator has not run yet. Please try again later.'
                })
            }
        else:
            print(f"S3 Error: {str(e)}")
            return {
                'statusCode': 500,
                'headers': headers,
                'body': json.dumps({
                    'error': 'Internal server error',
                    'message': str(e)
                })
            }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }
