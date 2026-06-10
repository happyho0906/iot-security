import json
import boto3

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    claims = (
        (event.get('requestContext') or {})
        .get('authorizer', {})
        .get('claims', {})
    )
    role = claims.get('custom:role', '').upper()

    if role != 'ADMIN':
        return {
            'statusCode': 403,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Admin access required'}),
        }

    items = dynamodb.Table('NFCWhitelist').scan().get('Items', [])
    items.sort(key=lambda x: x.get('addedAt', ''), reverse=True)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(items),
    }
