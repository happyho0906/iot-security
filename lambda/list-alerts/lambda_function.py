import json
import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    table = dynamodb.Table('AlertEvents')
    params = event.get('queryStringParameters') or {}
    resolved_param = params.get('resolved', 'all').lower()

    if resolved_param == 'false':
        resp = table.scan(FilterExpression=Attr('resolved').eq(False))
    elif resolved_param == 'true':
        resp = table.scan(FilterExpression=Attr('resolved').eq(True))
    else:
        resp = table.scan()

    return {'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps(resp.get('Items', []))}
