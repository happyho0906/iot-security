import json
import boto3
from boto3.dynamodb.conditions import Attr
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    alert_id    = (event.get('pathParameters') or {}).get('alertId')
    body        = json.loads(event.get('body') or '{}')
    resolved_by = body.get('resolvedBy', 'unknown')

    if not alert_id:
        return {'statusCode': 400, 'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'alertId required'})}

    now = datetime.now(timezone.utc).isoformat()
    alerts_table = dynamodb.Table('AlertEvents')

    resp = alerts_table.get_item(Key={'alertId': alert_id})
    alert = resp.get('Item')
    if not alert:
        return {'statusCode': 404, 'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'Alert not found'})}

    shipment_id = alert['shipmentId']

    alerts_table.update_item(
        Key={'alertId': alert_id},
        UpdateExpression='SET resolved = :t, resolvedBy = :b, resolvedAt = :a',
        ExpressionAttributeValues={':t': True, ':b': resolved_by, ':a': now},
    )

    remaining = alerts_table.scan(
        FilterExpression=Attr('shipmentId').eq(shipment_id) & Attr('resolved').eq(False)
    ).get('Items', [])

    if not remaining:
        dynamodb.Table('Shipments').update_item(
            Key={'shipmentId': shipment_id},
            UpdateExpression='SET riskLevel = :r, #s = :s, lastUpdatedAt = :t',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':r': 'LOW', ':s': 'IN_TRANSIT', ':t': now},
        )

    return {'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'alertId': alert_id, 'resolved': True})}
