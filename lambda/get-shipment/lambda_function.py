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
    shipment_id = (event.get('pathParameters') or {}).get('id')
    if not shipment_id:
        return {'statusCode': 400, 'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'shipmentId required'})}

    item = dynamodb.Table('Shipments').get_item(Key={'shipmentId': shipment_id}).get('Item')
    if not item:
        return {'statusCode': 404, 'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Not found'})}

    return {'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(item, default=_from_dynamo)}
