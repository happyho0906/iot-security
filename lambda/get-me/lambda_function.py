import json


def lambda_handler(event, context):
    """
    Returns the authenticated user's identity from the Cognito JWT.
    API Gateway Cognito Authorizer populates requestContext.authorizer.claims.
    """
    claims = (
        (event.get('requestContext') or {})
        .get('authorizer', {})
        .get('claims', {})
    )

    if not claims:
        return {
            'statusCode': 401,
            'headers': {'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': 'Unauthorized'}),
        }

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps({
            'userId': claims.get('sub', ''),
            'email':  claims.get('email', ''),
            'role':   claims.get('custom:role', 'CUSTOMER'),
        }),
    }
