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
        path = event.get('path', '/')
        query_params = event.get('queryStringParameters') or {}

        # Support different response formats
        if query_params.get('format') == 'simple' or path == '/simple':
            # Simple format - just the circulating supply number
            simple_response = {
                'circulating_supply': data['circulating_supply_formatted'],
                'timestamp': data['timestamp']
            }
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps(simple_response, indent=2)
            }

        elif query_params.get('format') == 'raw' or path == '/raw':
            # Raw format - just the number (for tools like CoinGecko)
            return {
                'statusCode': 200,
                'headers': {**headers, 'Content-Type': 'text/plain'},
                'body': data['circulating_supply_formatted']
            }

        else:
            # Full format (default)
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps(data, indent=2)
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
