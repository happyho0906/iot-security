import json
import boto3
import urllib.request
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
iot_data = boto3.client('iot-data', region_name='us-east-1')

TEMP_HIGH_C = 8.0   # °C cold-chain threshold
GFORCE_HIGH = 2.0   # g  collision threshold


def lambda_handler(event, context):
    thing_name = event.get('thingName', '')
    if not thing_name.startswith('shipment-'):
        print(f'Skipping unknown thing: {thing_name}')
        return

    shipment_id = thing_name[len('shipment-'):]
    now = datetime.now(timezone.utc).isoformat()

    temperature  = event.get('temperature')
    humidity     = event.get('humidity')
    g_force      = event.get('gForce')
    latitude     = event.get('latitude')
    longitude    = event.get('longitude')
    battery      = event.get('batteryLevel')
    online       = event.get('online', True)

    # 1. Write sensor readings to Shipments
    expr_parts = ['lastUpdatedAt = :t', 'deviceStatus = :ds']
    expr_vals  = {':t': now, ':ds': 'ONLINE' if online else 'OFFLINE'}

    if temperature is not None:
        expr_parts.append('temperature = :temp')
        expr_vals[':temp'] = str(round(float(temperature), 2))
    if humidity is not None:
        expr_parts.append('humidity = :hum')
        expr_vals[':hum'] = str(round(float(humidity), 1))
    if g_force is not None:
        expr_parts.append('gForce = :gf')
        expr_vals[':gf'] = str(round(float(g_force), 3))
    if latitude is not None:
        expr_parts.append('latitude = :lat')
        expr_vals[':lat'] = str(latitude)
    if longitude is not None:
        expr_parts.append('longitude = :lon')
        expr_vals[':lon'] = str(longitude)
    if battery is not None:
        expr_parts.append('batteryLevel = :bat')
        expr_vals[':bat'] = int(battery)

    dynamodb.Table('Shipments').update_item(
        Key={'shipmentId': shipment_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeValues=expr_vals,
    )

    # 2. Threshold checks — create AlertEvents on breach
    if temperature is not None and float(temperature) > TEMP_HIGH_C:
        _create_alert(
            shipment_id, 'TEMP_HIGH', 'CRITICAL',
            f'Temperature exceeded {TEMP_HIGH_C}C limit: reading {temperature}C',
            now=now,
        )

    if g_force is not None and float(g_force) > GFORCE_HIGH:
        _create_alert(
            shipment_id, 'COLLISION', 'HIGH',
            f'G-force spike: {g_force}g detected',
            now=now,
        )

    if not online:
        _create_alert(
            shipment_id, 'DEVICE_OFFLINE', 'HIGH',
            f'Device went offline: {thing_name}',
            now=now,
        )


def _create_alert(shipment_id, alert_type, severity, message, now=None):
    if now is None:
        now = datetime.now(timezone.utc).isoformat()

    alert_id = f"ALERT-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    dynamodb.Table('AlertEvents').put_item(Item={
        'alertId':    alert_id,
        'shipmentId': shipment_id,
        'alertType':  alert_type,
        'severity':   severity,
        'message':    message,
        'source':     'iot',
        'resolved':   False,
        'resolvedBy': None,
        'createdAt':  now,
        'resolvedAt': None,
    })

    dynamodb.Table('Shipments').update_item(
        Key={'shipmentId': shipment_id},
        UpdateExpression='SET riskLevel = :r, #s = :s, lastUpdatedAt = :t',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':r': severity, ':s': 'ALERT', ':t': now},
    )

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if webhook_url:
        msg = {'content': (
            f"**IoT Alert — {alert_type}**\n"
            f"Shipment: **{shipment_id}**  Severity: **{severity}**\n"
            f"{message}\n"
            f"Use `/status {shipment_id}` or `/resolve {alert_id}` to respond."
        )}
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(msg).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            print(f'Discord webhook error: {exc}')
