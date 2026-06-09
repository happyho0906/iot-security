import json
import boto3

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    Called by Raspberry Pi / NFC hardware to verify whether a scanned tag is
    authorised.  This route is intentionally unauthenticated so that embedded
    hardware can call it without Cognito tokens.
    """
    tag_id = (event.get('pathParameters') or {}).get('tagId', '').strip()
    if not tag_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'tagId is required'}),
        }

    resp = dynamodb.Table('NFCWhitelist').get_item(Key={'tagId': tag_id})
    item = resp.get('Item')

    if not item or not item.get('active', False):
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({'allowed': False, 'tagId': tag_id}),
        }

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps({
            'allowed': True,
            'tagId':   tag_id,
            'label':   item.get('label', ''),
            'addedBy': item.get('addedBy', ''),
        }),
    }
