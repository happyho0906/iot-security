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
         'thingName': 'shipment-SHIP-001', 'batteryLevel': 87},
        {'shipmentId': 'SHIP-002', 'status': 'ALERT', 'riskLevel': 'CRITICAL',
         'temperature': '11.2', 'humidity': '70', 'gForce': '0.3',
         'lockStatus': 'LOCKED', 'deviceStatus': 'ONLINE',
         'latitude': '1.3000', 'longitude': '103.8500', 'lastUpdatedAt': now,
         'thingName': 'shipment-SHIP-002', 'batteryLevel': 62},
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

    # Seed Users table (for Cognito role mapping)
    users = dynamodb.Table('Users')
    for u in [
        {'userId': 'demo-admin',    'email': 'admin@lisa.demo',    'role': 'ADMIN',
         'assignedShipments': [], 'createdAt': now},
        {'userId': 'demo-driver',   'email': 'driver@lisa.demo',   'role': 'DRIVER',
         'assignedShipments': ['SHIP-001', 'SHIP-002'], 'createdAt': now},
        {'userId': 'demo-customer', 'email': 'customer@lisa.demo', 'role': 'CUSTOMER',
         'assignedShipments': ['SHIP-001'], 'createdAt': now},
    ]:
        users.put_item(Item=u)

    print('Seed complete: 3 shipments, 1 alert, 3 users')

if __name__ == '__main__':
    seed()
