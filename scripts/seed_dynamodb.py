import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

def seed():
    now = datetime.now(timezone.utc).isoformat()
    shipments = dynamodb.Table('Shipments')
    alerts = dynamodb.Table('AlertEvents')

    for item in [
        {'shipmentId': 'SHIP-001', 'status': 'IN_TRANSIT', 'riskLevel': 'LOW',
         'temperature': '4.2', 'humidity': '65', 'gForce': '0.1',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'latitude': '1.3521', 'longitude': '103.8198', 'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-001', 'batteryLevel': 87,
         'driver': 'driver@lisa.demo', 'customer': 'customer@lisa.demo'},
        {'shipmentId': 'SHIP-002', 'status': 'ALERT', 'riskLevel': 'CRITICAL',
         'temperature': '11.2', 'humidity': '70', 'gForce': '0.3',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'latitude': '1.3000', 'longitude': '103.8500', 'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-002', 'batteryLevel': 62,
         'driver': 'driver@lisa.demo'},
        {'shipmentId': 'SHIP-003', 'status': 'IN_TRANSIT', 'riskLevel': 'LOW',
         'temperature': '3.8', 'humidity': '62', 'gForce': '0.0',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'latitude': '1.3200', 'longitude': '103.7800', 'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-003', 'batteryLevel': 91},
    ]:
        shipments.put_item(Item=item)

    alerts.put_item(Item={
        'alertId': 'ALERT-001',
        'shipmentId': 'SHIP-002',
        'alertType': 'TEMP_HIGH',
        'severity': 'CRITICAL',
        'message': 'Temperature exceeded threshold: 11.2°C (limit: 8°C)',
        'source': 'iot',
        'resolved': False,
        'resolvedBy': None,
        'createdAt': now,
        'resolvedAt': None,
    })

    # Seed Users table (for Cognito role mapping). Shipment assignment is
    # not stored here — it lives on the Shipments table's driver/customer
    # email fields, so query Shipments by those to find a user's shipments.
    users = dynamodb.Table('Users')
    for u in [
        {'userId': 'demo-admin',    'email': 'admin@lisa.demo',    'role': 'ADMIN',    'createdAt': now},
        {'userId': 'demo-driver',   'email': 'driver@lisa.demo',   'role': 'DRIVER',   'createdAt': now},
        {'userId': 'demo-customer', 'email': 'customer@lisa.demo', 'role': 'CUSTOMER', 'createdAt': now},
    ]:
        users.put_item(Item=u)

    # Migration: strip the legacy assignedShipments attribute from any
    # remaining Users rows (put_item above already replaced the demo users
    # wholesale, so this only touches non-demo entries).
    for u in users.scan().get('Items', []):
        if 'assignedShipments' in u:
            users.update_item(
                Key={'userId': u['userId']},
                UpdateExpression='REMOVE assignedShipments',
            )

    # Seed NFCDevices table (known devices + whitelist, single table keyed by tagId)
    nfc = dynamodb.Table('NFCDevices')
    for entry in [
        {'tagId': '04:AB:12:CD:34:EF:00', 'label': 'Driver Device A', 'status': 'WHITELISTED',
         'firstSeenAt': '2025-06-01T10:00:00Z', 'lastSeenAt': '2025-06-05T08:00:00Z',
         'addedBy': 'admin@lisa.demo', 'addedAt': '2025-06-01T10:05:00Z'},
        {'tagId': '04:CD:56:EF:78:01:02', 'label': 'Warehouse Scanner', 'status': 'WHITELISTED',
         'firstSeenAt': '2025-06-02T09:00:00Z', 'lastSeenAt': '2025-06-04T09:00:00Z',
         'addedBy': 'admin@lisa.demo', 'addedAt': '2025-06-02T09:05:00Z'},
        {'tagId': '04:9F:33:11:22:AA:BB', 'label': 'Guest Phone', 'status': 'KNOWN',
         'firstSeenAt': '2025-06-06T11:00:00Z', 'lastSeenAt': '2025-06-06T11:00:00Z'},
    ]:
        nfc.put_item(Item=entry)

    print('Seed complete: 3 shipments, 1 alert, 3 users, 3 NFC devices (2 whitelisted)')

if __name__ == '__main__':
    seed()
