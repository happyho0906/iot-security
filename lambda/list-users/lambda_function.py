import json
import boto3

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    """
    GET /users?role=DRIVER|CUSTOMER|ADMIN

    Returns Users table entries (userId, email, role), optionally filtered
    by the `role` query string parameter. Used by the dashboard's
    "Add Shipment" form to populate the Driver/Customer dropdowns with
    users that hold the matching role.

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

    items = dynamodb.Table('Users').scan().get('Items', [])

    role_filter = (event.get('queryStringParameters') or {}).get('role', '').upper()
    if role_filter:
        items = [u for u in items if u.get('role', '').upper() == role_filter]

    items.sort(key=lambda u: u.get('email', ''))

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps([
            {'userId': u.get('userId'), 'email': u.get('email'), 'role': u.get('role')}
            for u in items
        ]),
    }
