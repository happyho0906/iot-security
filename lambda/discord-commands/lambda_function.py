import json
import os
import boto3
from boto3.dynamodb.conditions import Attr
from datetime import datetime, timezone
import nacl.signing
import nacl.exceptions

dynamodb = boto3.resource('dynamodb')

def verify_signature(public_key_hex, signature_hex, timestamp, body):
    try:
        key = nacl.signing.VerifyKey(bytes.fromhex(public_key_hex))
        key.verify((timestamp + body).encode(), bytes.fromhex(signature_hex))
        return True
    except (nacl.exceptions.BadSignatureError, Exception):
        return False

def get_shipment(shipment_id):
    return dynamodb.Table('Shipments').get_item(Key={'shipmentId': shipment_id}).get('Item')

def update_lock(shipment_id, lock_status):
    now = datetime.now(timezone.utc).isoformat()
    dynamodb.Table('Shipments').update_item(
        Key={'shipmentId': shipment_id},
        UpdateExpression='SET lockStatus = :l, lastUpdatedAt = :t',
        ExpressionAttributeValues={':l': lock_status, ':t': now},
    )

def discord_response(content):
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({'type': 4, 'data': {'content': content}}),
    }

def lambda_handler(event, context):
    public_key = os.environ.get('DISCORD_PUBLIC_KEY', '')
    headers    = event.get('headers', {})
    signature  = headers.get('x-signature-ed25519', '')
    timestamp  = headers.get('x-signature-timestamp', '')
    body       = event.get('body', '')

    if not verify_signature(public_key, signature, timestamp, body):
        return {'statusCode': 401, 'body': 'Invalid signature'}

    payload = json.loads(body)
    itype   = payload.get('type')

    # PING
    if itype == 1:
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'type': 1})}

    # APPLICATION_COMMAND
    if itype == 2:
        data     = payload.get('data', {})
        cmd      = data.get('name')
        opts     = {o['name']: o['value'] for o in data.get('options', [])}
        username = payload.get('member', {}).get('user', {}).get('username', 'unknown')
        now      = datetime.now(timezone.utc).isoformat()

        if cmd == 'status':
            sid = opts.get('shipment_id', '')
            s   = get_shipment(sid)
            if not s:
                return discord_response(f"❌ Shipment `{sid}` not found.")
            return discord_response(
                f"📦 **{s['shipmentId']}**\n"
                f"Status: {s.get('status')} | Risk: {s.get('riskLevel')}\n"
                f"Temp: {s.get('temperature')}°C | Humidity: {s.get('humidity')}%\n"
                f"Lock: {s.get('lockStatus')} | Device: {s.get('deviceStatus')}"
            )

        if cmd == 'alerts':
            items = dynamodb.Table('AlertEvents').scan(
                FilterExpression=Attr('resolved').eq(False)
            ).get('Items', [])
            if not items:
                return discord_response("✅ No active alerts.")
            lines = [f"🚨 `{a['alertId']}` | {a['shipmentId']} | {a['alertType']} | {a['severity']}"
                     for a in items[:10]]
            return discord_response("**Active Alerts:**\n" + "\n".join(lines))

        if cmd == 'resolve':
            alert_id = opts.get('alert_id', '')
            alerts   = dynamodb.Table('AlertEvents')
            alert    = alerts.get_item(Key={'alertId': alert_id}).get('Item')
            if not alert:
                return discord_response(f"❌ Alert `{alert_id}` not found.")
            sid = alert['shipmentId']
            alerts.update_item(
                Key={'alertId': alert_id},
                UpdateExpression='SET resolved = :t, resolvedBy = :b, resolvedAt = :a',
                ExpressionAttributeValues={':t': True, ':b': f'discord:{username}', ':a': now},
            )
            remaining = alerts.scan(
                FilterExpression=Attr('shipmentId').eq(sid) & Attr('resolved').eq(False)
            ).get('Items', [])
            if not remaining:
                dynamodb.Table('Shipments').update_item(
                    Key={'shipmentId': sid},
                    UpdateExpression='SET riskLevel = :r, #s = :s, lastUpdatedAt = :t',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':r': 'LOW', ':s': 'IN_TRANSIT', ':t': now},
                )
            return discord_response(f"✅ Alert `{alert_id}` resolved by {username}.")

        if cmd == 'lock':
            sid = opts.get('shipment_id', '')
            update_lock(sid, 'LOCKED')
            return discord_response(f"🔒 Shipment `{sid}` locked.")

        if cmd == 'unlock':
            sid = opts.get('shipment_id', '')
            update_lock(sid, 'UNLOCKED')
            return discord_response(f"🔓 Shipment `{sid}` unlocked.")

        return discord_response(f"Unknown command: {cmd}")

    return {'statusCode': 400, 'body': 'Unhandled type'}
