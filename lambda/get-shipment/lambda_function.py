import json
import boto3

dynamodb = boto3.resource('dynamodb')

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
            'body': json.dumps(item)}
