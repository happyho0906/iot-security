import json
import boto3
import urllib.request
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    body = json.loads(event.get('body') or '{}')
    shipment_id = body.get('shipmentId')
    alert_type  = body.get('alertType', 'UNKNOWN')
    severity    = body.get('severity', 'HIGH')
    temperature = body.get('temperature')

    if not shipment_id:
        return {'statusCode': 400, 'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'shipmentId required'})}

    now = datetime.now(timezone.utc).isoformat()
    shipments_table = dynamodb.Table('Shipments')

    # Handle lock/unlock — no alert created, just update DynamoDB
    if alert_type == 'LOCK_UPDATE':
        lock_status = body.get('lockStatus', 'LOCKED')
        shipments_table.update_item(
            Key={'shipmentId': shipment_id},
            UpdateExpression='SET lockStatus = :l, lastUpdatedAt = :t',
            ExpressionAttributeValues={':l': lock_status, ':t': now},
        )
        return {'statusCode': 200, 'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'status': 'lock updated', 'lockStatus': lock_status})}

    alert_id = f"ALERT-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    dynamodb.Table('AlertEvents').put_item(Item={
        'alertId':    alert_id,
        'shipmentId': shipment_id,
        'alertType':  alert_type,
        'severity':   severity,
        'message': f"{alert_type} on {shipment_id}" + (f": {temperature}°C" if temperature else ""),
        'resolved':   False,
        'resolvedBy': None,
        'createdAt':  now,
        'resolvedAt': None,
    })

    shipments_table.update_item(
        Key={'shipmentId': shipment_id},
        UpdateExpression='SET riskLevel = :r, #s = :s, lastUpdatedAt = :t',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':r': severity, ':s': 'ALERT', ':t': now},
    )

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if webhook_url:
        msg = {
            'content': (
                f"🚨 **CRITICAL ALERT**\n"
                f"Shipment: **{shipment_id}**\n"
                f"Type: **{alert_type}**\n"
                f"Severity: **{severity}**\n"
                f"Use `/status {shipment_id}` or `/resolve {alert_id}` to respond."
            )
        }
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(msg).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            print(f"Discord webhook error: {exc}")

    return {'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'alertId': alert_id, 'status': 'created'})}
