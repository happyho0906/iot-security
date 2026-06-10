import json
import boto3

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    GET /nfc/devices

    Returns every device LISA has ever seen, each tagged with `status`:
      - "KNOWN"       -> appears in "Known Devices" only
      - "WHITELISTED" -> appears in "Known Devices" (badge) and "Whitelist"

    The frontend splits this single list into the two panels client-side.
    Admin-only.
    """
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

    items = dynamodb.Table('NFCDevices').scan().get('Items', [])
    items.sort(key=lambda x: x.get('lastSeenAt', ''), reverse=True)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(items),
    }
