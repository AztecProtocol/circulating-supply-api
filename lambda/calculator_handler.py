#!/usr/bin/env python3
"""
AWS Lambda handler for calculating Aztec circulating supply.
Runs hourly and validates results before updating.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

# Add the parent directory to path to import circulating-supply script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the main calculation logic
# We'll need to refactor circulating-supply.py slightly to be importable
from supply_calculator import calculate_supply

s3 = boto3.client('s3')
BUCKET_NAME = os.environ['SUPPLY_BUCKET']
CURRENT_FILE = 'current.json'
UPDATE_THRESHOLD = float(os.environ.get('UPDATE_THRESHOLD', '0.95'))


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder for Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def get_current_supply():
    """Fetch current supply data from S3."""
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=CURRENT_FILE)
        data = json.loads(response['Body'].read().decode('utf-8'))
        return data
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            print("No existing supply data found, this is the first run")
            return None
        raise


def validate_update(current_data, new_data):
    """
    Validate that the new data is reasonable before updating.

    Returns: (bool, str) - (should_update, reason)
    """
    new_supply = float(new_data['circulating_supply_wei'])

    # Check if new supply is zero
    if new_supply == 0:
        return False, "New circulating supply is zero"

    # If no current data, allow the update
    if current_data is None:
        return True, "Initial data point"

    current_supply = float(current_data['circulating_supply_wei'])

    # Check if new supply is significantly lower than current
    if new_supply < current_supply * UPDATE_THRESHOLD:
        decrease_pct = ((current_supply - new_supply) / current_supply) * 100
        return False, f"Supply decreased by {decrease_pct:.2f}% (threshold: {(1-UPDATE_THRESHOLD)*100:.2f}%)"

    return True, "Validation passed"


def save_supply_data(data, is_update=True):
    """Save supply data to S3."""
    timestamp = datetime.now(timezone.utc).isoformat()

    # Save as current.json
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=CURRENT_FILE,
        Body=json.dumps(data, cls=DecimalEncoder, indent=2),
        ContentType='application/json',
        CacheControl='max-age=3600'  # 1 hour cache
    )

    # Save historical snapshot if this is an update
    if is_update:
        history_key = f"history/{data['timestamp'].replace(':', '-')}.json"
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=history_key,
            Body=json.dumps(data, cls=DecimalEncoder, indent=2),
            ContentType='application/json'
        )

    print(f"Saved supply data: {data['circulating_supply_formatted']} AZTEC")


def lambda_handler(event, context):
    """AWS Lambda handler function."""
    start_time = time.time()

    try:
        print("Starting circulating supply calculation...")

        # Calculate new supply data
        new_data = calculate_supply()

        if not new_data:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to calculate supply'})
            }

        # Get current data for validation
        current_data = get_current_supply()

        # Validate the update
        should_update, reason = validate_update(current_data, new_data)

        if not should_update:
            print(f"❌ Update rejected: {reason}")
            print(f"   Current: {current_data.get('circulating_supply_formatted', 'N/A')} AZTEC")
            print(f"   New:     {new_data['circulating_supply_formatted']} AZTEC")

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'updated': False,
                    'reason': reason,
                    'current_supply': current_data.get('circulating_supply_formatted') if current_data else None,
                    'calculated_supply': new_data['circulating_supply_formatted']
                }, cls=DecimalEncoder)
            }

        # Update is valid, save the data
        print(f"✓ Update approved: {reason}")
        save_supply_data(new_data, is_update=(current_data is not None))

        elapsed = time.time() - start_time

        return {
            'statusCode': 200,
            'body': json.dumps({
                'updated': True,
                'reason': reason,
                'supply': new_data,
                'execution_time_seconds': round(elapsed, 2)
            }, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'type': type(e).__name__
            })
        }
