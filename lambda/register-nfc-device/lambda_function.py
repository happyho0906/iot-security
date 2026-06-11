import json
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    POST /nfc/devices

    Called by the dashboard whenever the Web NFC reader on an Android/Chrome
    device picks up a tag.

    - If the tag is new: creates a "known device" entry (status=KNOWN). The
      dashboard shows the registration modal first so `label` is normally
      provided on this call.
    - If the tag already exists: refreshes `lastSeenAt` (and `label`, if a
      non-empty one is supplied), without touching its whitelist status.

    Admin-only (the NFC Whitelist page is only shown to ADMIN users, but the
    backend enforces it independently).
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

    body   = json.loads(event.get('body') or '{}')
    tag_id = body.get('tagId', '').strip()
    label  = body.get('label', '').strip()

    if not tag_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'tagId is required'}),
        }

    now   = datetime.now(timezone.utc).isoformat()
    table = dynamodb.Table('NFCDevices')

    existing = table.get_item(Key={'tagId': tag_id}).get('Item')

    if existing:
        update_expr = 'SET lastSeenAt = :now'
        expr_values = {':now': now}
        if label:
            update_expr += ', label = :label'
            expr_values[':label'] = label

        resp = table.update_item(
            Key={'tagId': tag_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ReturnValues='ALL_NEW',
        )
        item = resp['Attributes']
        status_code = 200
    else:
        item = {
            'tagId':       tag_id,
            'label':       label or tag_id,
            'status':      'KNOWN',
            'firstSeenAt': now,
            'lastSeenAt':  now,
        }
        table.put_item(Item=item)
        status_code = 201

    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(item),
    }
