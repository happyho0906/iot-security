import json
import boto3

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    GET /nfc/check/{tagId}

    Called by Raspberry Pi / NFC hardware to verify whether a scanned tag is
    on the whitelist before unlocking. This route is intentionally
    unauthenticated so embedded hardware can call it without Cognito tokens
    (same pattern as POST /unlock).
    """
    tag_id = (event.get('pathParameters') or {}).get('tagId', '').strip()
    if not tag_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'tagId is required'}),
        }

    item = dynamodb.Table('NFCDevices').get_item(Key={'tagId': tag_id}).get('Item')
    allowed = bool(item) and item.get('status') == 'WHITELISTED'

    body = {'allowed': allowed, 'tagId': tag_id}
    if item:
        body['label'] = item.get('label', '')

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body),
    }
