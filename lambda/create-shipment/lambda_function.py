import json
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    POST /shipments

    Body: {
      "shipmentId": "SHIP-004",
      "status":     "IN_TRANSIT",   (optional, default IN_TRANSIT)
      "riskLevel":  "LOW",          (optional, default LOW)
      "driver":     "driver@lisa.demo",     (optional, must be a Users
                                              entry with role DRIVER)
      "customer":   "customer@lisa.demo"    (optional, must be a Users
                                              entry with role CUSTOMER)
    }

    Creates a new Shipments row with sensible defaults for the telemetry
    fields (temperature, humidity, gForce, lock/device status, location)
    so it renders correctly on the dashboard before any IoT data arrives.

    Admin-only.
    """
    # HTTP API (v2) + Cognito JWT authorizer puts claims under
    # requestContext.authorizer.jwt.claims (not .authorizer.claims like
    # REST API v1).
    claims = (
        (event.get('requestContext') or {})
        .get('authorizer', {})
        .get('jwt', {})
        .get('claims', {})
    )
    role = claims.get('custom:role', '').upper()

    if role != 'ADMIN':
        return {
            'statusCode': 403,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Admin access required'}),
        }

    body        = json.loads(event.get('body') or '{}')
    shipment_id = (body.get('shipmentId') or '').strip()
    status      = (body.get('status') or 'IN_TRANSIT').strip()
    risk_level  = (body.get('riskLevel') or 'LOW').strip()
    driver      = (body.get('driver') or '').strip()
    customer    = (body.get('customer') or '').strip()

    if not shipment_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'shipmentId is required'}),
        }

    shipments_table = dynamodb.Table('Shipments')
    if shipments_table.get_item(Key={'shipmentId': shipment_id}).get('Item'):
        return {
            'statusCode': 409,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'A shipment with this ID already exists.'}),
        }

    if driver or customer:
        users = dynamodb.Table('Users').scan().get('Items', [])
        if driver and not any(
            u.get('email') == driver and u.get('role', '').upper() == 'DRIVER' for u in users
        ):
            return {
                'statusCode': 400,
                'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'driver must be an existing user with role DRIVER'}),
            }
        if customer and not any(
            u.get('email') == customer and u.get('role', '').upper() == 'CUSTOMER' for u in users
        ):
            return {
                'statusCode': 400,
                'headers': {'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'error': 'customer must be an existing user with role CUSTOMER'}),
            }

    item = {
        'shipmentId':    shipment_id,
        'status':        status,
        'riskLevel':     risk_level,
        'temperature':   '4.0',
        'humidity':      '60',
        'gForce':        '0.0',
        'lockStatus':    'LOCKED',
        'deviceStatus':  'ONLINE',
        'latitude':      '1.3521',
        'longitude':     '103.8198',
        'lastUpdatedAt': datetime.now(timezone.utc).isoformat(),
        'thingName':     'shipment-' + shipment_id,
        'batteryLevel':  100,
    }
    if driver:
        item['driver'] = driver
    if customer:
        item['customer'] = customer

    shipments_table.put_item(Item=item)

    return {
        'statusCode': 201,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(item),
    }
