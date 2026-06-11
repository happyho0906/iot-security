import json
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    PUT /nfc/devices/{tagId}/whitelist
    Body: { "whitelisted": true | false }

    Toggles a known device's whitelist membership without removing it from
    "Known Devices":
      - whitelisted=true  -> status becomes WHITELISTED, records who/when
      - whitelisted=false -> status reverts to KNOWN, clears addedBy/addedAt

    Admin-only.
    """
    # HTTP API (v2) + Cognito JWT authorizer puts claims under
    # requestContext.authorizer.jwt.claims (not .authorizer.claims like
    # REST API v1).
    claims = (
        (event.get('requestContext') or {})
        .get('authorizer', {})
        .get('jwt', {})
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

    tag_id = (event.get('pathParameters') or {}).get('tagId', '').strip()
    if not tag_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'tagId is required'}),
        }

    body        = json.loads(event.get('body') or '{}')
    whitelisted = bool(body.get('whitelisted', False))

    table  = dynamodb.Table('NFCDevices')
    exists = table.get_item(Key={'tagId': tag_id}).get('Item')
    if not exists:
        return {
            'statusCode': 404,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Device not found. Scan and register it first.'}),
        }

    if whitelisted:
        now = datetime.now(timezone.utc).isoformat()
        resp = table.update_item(
            Key={'tagId': tag_id},
            UpdateExpression='SET #s = :w, addedBy = :by, addedAt = :at',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':w': 'WHITELISTED', ':by': email, ':at': now},
            ReturnValues='ALL_NEW',
        )
    else:
        resp = table.update_item(
            Key={'tagId': tag_id},
            UpdateExpression='SET #s = :k REMOVE addedBy, addedAt',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':k': 'KNOWN'},
            ReturnValues='ALL_NEW',
        )

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(resp['Attributes']),
    }
