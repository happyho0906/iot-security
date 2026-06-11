import json
import boto3

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    DELETE /shipments/{id}

    Permanently removes a shipment from the Shipments table. The dashboard
    shows a confirmation dialog before calling this, and the backend
    enforces admin independently.

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

    shipment_id = (event.get('pathParameters') or {}).get('id', '').strip()
    if not shipment_id:
        return {
            'statusCode': 400,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'shipmentId required'}),
        }

    table = dynamodb.Table('Shipments')
    if not table.get_item(Key={'shipmentId': shipment_id}).get('Item'):
        return {
            'statusCode': 404,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Not found'}),
        }

    table.delete_item(Key={'shipmentId': shipment_id})

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps({'deleted': shipment_id}),
    }
