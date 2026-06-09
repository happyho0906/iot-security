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

    tag_id = (event.get('pathParameters') or {}).get('tagId', '').strip()
    if not tag_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'tagId is required'}),
        }

    dynamodb.Table('NFCWhitelist').delete_item(Key={'tagId': tag_id})

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps({'tagId': tag_id, 'deleted': True}),
    }
