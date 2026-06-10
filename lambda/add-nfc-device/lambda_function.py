import json
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    claims = (
        (event.get('requestContext') or {})
        .get('authorizer', {})
        .get('claims', {})
    )
    role  = claims.get('custom:role', '').upper()
    email = claims.get('email', 'unknown')

    if role != 'ADMIN':
        return {
            'statusCode': 403,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Admin access required'}),
        }

    body   = json.loads(event.get('body') or '{}')
    tag_id = body.get('tagId', '').strip()
    label  = body.get('label', '').strip()

    if not tag_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'tagId is required'}),
        }

    item = {
        'tagId':   tag_id,
        'label':   label or tag_id,
        'addedBy': email,
        'addedAt': datetime.now(timezone.utc).isoformat(),
        'active':  True,
    }

    dynamodb.Table('NFCWhitelist').put_item(Item=item)

    return {
        'statusCode': 201,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(item),
    }
