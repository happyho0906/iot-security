import json
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')


def _from_dynamo(o):
    """json.dumps default= hook: DynamoDB numbers come back as Decimal."""
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f'Unserializable type: {type(o)}')


def lambda_handler(event, context):
    table = dynamodb.Table('Shipments')
    items = table.scan().get('Items', [])
    items.sort(key=lambda s: s.get('shipmentId', ''))
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(items, default=_from_dynamo),
    }
