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
    """
    GET /accidents

    Returns every AccidentEvents row. The dashboard's Map page draws each
    accident as a warning marker alongside the shipment markers. Any
    signed-in user may read (the route's JWT authorizer enforces sign-in).
    """
    items = dynamodb.Table('AccidentEvents').scan().get('Items', [])
    items.sort(key=lambda a: a.get('accidentId', ''))
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
        'body': json.dumps(items, default=_from_dynamo),
    }
