import random

import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

# Approximate straight stretches of major roads in Hsinchu City, Taiwan,
# as ((lat, lng), (lat, lng)) endpoint pairs. Shipments are placed at a
# random point interpolated along a random segment, so they land on (or
# very near) an actual road instead of inside a building/river.
HSINCHU_ROAD_SEGMENTS = [
    ((24.8016, 120.9706), (24.8081, 120.9663)),  # Zhonghua Rd (中華路), from the train station heading north
    ((24.8060, 120.9680), (24.8130, 120.9610)),  # Dongda Rd (東大路) heading northwest
    ((24.7990, 120.9830), (24.7961, 120.9967)),  # Guangfu Rd (光復路) toward NTHU / Science Park
    ((24.8040, 120.9870), (24.8050, 120.9990)),  # Gongdao 5th Rd (公道五路) heading east
    ((24.7950, 120.9740), (24.7906, 120.9800)),  # Shipin Rd (食品路) heading southeast
    ((24.8086, 120.9700), (24.8040, 120.9720)),  # Minzu Rd (民族路) back toward the station
]


def random_road_point():
    """Random (lat, lng) on a random Hsinchu road segment, as strings
    (matching the Shipments table's string-typed coordinate fields)."""
    (lat1, lng1), (lat2, lng2) = random.choice(HSINCHU_ROAD_SEGMENTS)
    t = random.random()
    lat = lat1 + (lat2 - lat1) * t
    lng = lng1 + (lng2 - lng1) * t
    return f'{lat:.6f}', f'{lng:.6f}'


def seed():
    now = datetime.now(timezone.utc).isoformat()
    shipments = dynamodb.Table('Shipments')
    alerts = dynamodb.Table('AlertEvents')

    for item in [
        {'shipmentId': 'SHIP-001', 'status': 'IN_TRANSIT', 'riskLevel': 'LOW',
         'temperature': '4.2', 'humidity': '65', 'gForce': '0.1',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-001', 'batteryLevel': 87,
         'driver': 'driver@lisa.demo', 'customer': 'customer@lisa.demo'},
        {'shipmentId': 'SHIP-002', 'status': 'ALERT', 'riskLevel': 'CRITICAL',
         'temperature': '11.2', 'humidity': '70', 'gForce': '0.3',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-002', 'batteryLevel': 62,
         'driver': 'driver@lisa.demo'},
        {'shipmentId': 'SHIP-003', 'status': 'IN_TRANSIT', 'riskLevel': 'LOW',
         'temperature': '3.8', 'humidity': '62', 'gForce': '0.0',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-003', 'batteryLevel': 91},
    ]:
        item['latitude'], item['longitude'] = random_road_point()
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

    # Seed AccidentEvents: 3 demo road accidents randomly placed on Hsinchu
    # City roads. The dashboard's Map page draws these as warning markers
    # alongside the shipment markers.
    accidents = dynamodb.Table('AccidentEvents')
    for i, (acc_type, severity) in enumerate([
        ('COLLISION',          'HIGH'),
        ('ROAD_BLOCKED',       'MEDIUM'),
        ('VEHICLE_BREAKDOWN',  'LOW'),
    ], start=1):
        lat, lng = random_road_point()
        accidents.put_item(Item={
            'accidentId': f'ACC-{i:03d}',
            'type': acc_type,
            'severity': severity,
            'description': acc_type.replace('_', ' ').title() + ' reported on a Hsinchu City road',
            'latitude': lat,
            'longitude': lng,
            'reportedAt': now,
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

    print('Seed complete: 3 shipments, 1 alert, 3 accidents, 3 users, 3 NFC devices (2 whitelisted)')

if __name__ == '__main__':
    seed()
