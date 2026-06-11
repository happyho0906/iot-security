#!/usr/bin/env bash
#
# Deploys the "Add Shipment" admin feature onto the EXISTING LISA HTTP API
# (API Gateway v2, e.g. "Sentinel_NFC_API"):
#   - Creates the `Shipments` and `Users` DynamoDB tables if they don't
#     already exist (PK shipmentId / userId respectively)
#   - Creates/updates the `lisa-list-users` and `lisa-create-shipment`
#     Lambda functions
#   - Adds GET /users and POST /shipments routes to the existing HTTP API,
#     both protected by the shared Cognito JWT authorizer (admin-only)
#
# This script is purely additive. It never touches POST /unlock,
# Sentinel_NFC_Unlock, Sentinel_Image_Processor, /discord/commands, or the
# /nfc/* routes (see INTEGRATION.md "Do Not Touch").
# Re-running it is safe (idempotent: existing tables/integrations/routes/
# authorizer are reused and updated in place).
#
# Prerequisites:
#   - AWS CLI v2, configured (e.g. AWS CloudShell already has this)
#   - `zip` available on PATH (preinstalled in CloudShell)
#   - Run from the repository root
#   - The Cognito JWT authorizer `lisa-cognito-jwt` already exists (created
#     by scripts/deploy_nfc_backend.sh)
#
# Required environment variables:
#   AWS_REGION       e.g. us-east-1
#   API_ID           existing HTTP API ID, e.g. d1rocl5xb9 (Sentinel_NFC_API)
#   LAMBDA_ROLE_ARN  shared Lambda execution role ARN, e.g. LabRole
#                    (must allow dynamodb:Scan/Query/GetItem/PutItem on
#                    Shipments and Users)
#
# Example (run in AWS CloudShell, region us-east-1):
#   export AWS_REGION=us-east-1
#   export API_ID=d1rocl5xb9
#   export LAMBDA_ROLE_ARN=arn:aws:iam::194686029661:role/LabRole
#   bash scripts/deploy_shipments_backend.sh

set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION, e.g. us-east-1}"
: "${API_ID:?Set API_ID to the existing HTTP API ID (Sentinel_NFC_API)}"
: "${LAMBDA_ROLE_ARN:?Set LAMBDA_ROLE_ARN to the shared Lambda execution role ARN (e.g. LabRole)}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# ── 0. Cognito JWT authorizer (reuse existing) ──────────────────────────────

echo "==> Looking up existing Cognito JWT authorizer 'lisa-cognito-jwt'..."
AUTHORIZER_ID=$(aws apigatewayv2 get-authorizers --api-id "$API_ID" --region "$AWS_REGION" \
  --query "Items[?Name=='lisa-cognito-jwt'].AuthorizerId | [0]" --output text)

if [ "$AUTHORIZER_ID" = "None" ] || [ -z "$AUTHORIZER_ID" ]; then
  echo "ERROR: authorizer 'lisa-cognito-jwt' not found on API $API_ID."
  echo "       Run scripts/deploy_nfc_backend.sh with COGNITO_USER_POOL_ID and"
  echo "       COGNITO_CLIENT_ID set first to create it."
  exit 1
fi
echo "    Found authorizer $AUTHORIZER_ID"

# ── 1. DynamoDB tables ───────────────────────────────────────────────────────

create_table_if_missing() {
  local table="$1" key="$2"
  echo "==> Checking $table table..."
  if aws dynamodb describe-table --table-name "$table" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "    $table already exists, skipping create."
  else
    aws dynamodb create-table \
      --table-name "$table" \
      --attribute-definitions AttributeName="$key",AttributeType=S \
      --key-schema AttributeName="$key",KeyType=HASH \
      --billing-mode PAY_PER_REQUEST \
      --region "$AWS_REGION" >/dev/null
    echo "    Waiting for table to become active..."
    aws dynamodb wait table-exists --table-name "$table" --region "$AWS_REGION"
    echo "    Created $table."
  fi
}

create_table_if_missing Shipments shipmentId
create_table_if_missing Users userId

# ── 2. Lambda functions ─────────────────────────────────────────────────────

deploy_lambda() {
  local name="$1" dir="$2"
  local zip="/tmp/${name}.zip"
  # NOTE: this function's stdout is captured via $(...) to get the
  # FunctionArn, so all progress messages MUST go to stderr (>&2) —
  # otherwise they get appended to the captured ARN and corrupt it.
  echo "==> Deploying $name (from $dir)" >&2
  rm -f "$zip"
  (cd "$dir" && zip -q -r "$zip" lambda_function.py)

  if aws lambda get-function --function-name "$name" --region "$AWS_REGION" >/dev/null 2>&1; then
    aws lambda update-function-code \
      --function-name "$name" --zip-file "fileb://$zip" \
      --region "$AWS_REGION" >/dev/null
    aws lambda wait function-updated --function-name "$name" --region "$AWS_REGION"
    echo "    Updated existing function." >&2
  else
    aws lambda create-function \
      --function-name "$name" \
      --runtime python3.12 \
      --role "$LAMBDA_ROLE_ARN" \
      --handler lambda_function.lambda_handler \
      --timeout 10 \
      --zip-file "fileb://$zip" \
      --region "$AWS_REGION" >/dev/null
    aws lambda wait function-active --function-name "$name" --region "$AWS_REGION"
    echo "    Created new function." >&2
  fi

  aws lambda get-function --function-name "$name" --region "$AWS_REGION" \
    --query 'Configuration.FunctionArn' --output text
}

ARN_LIST_USERS=$(deploy_lambda lisa-list-users     lambda/list-users)
ARN_CREATE_SHIP=$(deploy_lambda lisa-create-shipment lambda/create-shipment)

# ── 3. HTTP API integrations + routes ───────────────────────────────────────

get_or_create_integration() {
  local lambda_arn="$1"
  local existing
  existing=$(aws apigatewayv2 get-integrations --api-id "$API_ID" --region "$AWS_REGION" \
    --query "Items[?IntegrationUri=='${lambda_arn}'].IntegrationId | [0]" --output text)
  if [ "$existing" != "None" ] && [ -n "$existing" ]; then
    echo "$existing"
  else
    aws apigatewayv2 create-integration --api-id "$API_ID" --region "$AWS_REGION" \
      --integration-type AWS_PROXY --integration-method POST \
      --integration-uri "$lambda_arn" --payload-format-version 2.0 \
      --query IntegrationId --output text
  fi
}

get_or_create_route() {
  local route_key="$1" integration_id="$2"
  local target="integrations/${integration_id}"

  local existing
  existing=$(aws apigatewayv2 get-routes --api-id "$API_ID" --region "$AWS_REGION" \
    --query "Items[?RouteKey=='${route_key}'].RouteId | [0]" --output text)

  echo "==> $route_key -> $target (auth=JWT)"
  if [ "$existing" != "None" ] && [ -n "$existing" ]; then
    aws apigatewayv2 update-route --api-id "$API_ID" --route-id "$existing" \
      --target "$target" --authorization-type JWT --authorizer-id "$AUTHORIZER_ID" \
      --region "$AWS_REGION" >/dev/null
  else
    aws apigatewayv2 create-route --api-id "$API_ID" --route-key "$route_key" \
      --target "$target" --authorization-type JWT --authorizer-id "$AUTHORIZER_ID" \
      --region "$AWS_REGION" >/dev/null
  fi
}

add_permission() {
  local lambda_name="$1"
  aws lambda add-permission \
    --function-name "$lambda_name" \
    --statement-id "apigw-invoke" \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*/*" \
    --region "$AWS_REGION" >/dev/null 2>&1 || true
}

INT_LIST_USERS=$(get_or_create_integration "$ARN_LIST_USERS")
INT_CREATE_SHIP=$(get_or_create_integration "$ARN_CREATE_SHIP")

get_or_create_route "GET /users"      "$INT_LIST_USERS"
get_or_create_route "POST /shipments" "$INT_CREATE_SHIP"

add_permission lisa-list-users
add_permission lisa-create-shipment

# ── 4. Done ──────────────────────────────────────────────────────────────────
# $default stage has auto-deploy enabled, so routes are live immediately.

BASE="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"
cat <<EOF

Done. New routes are live at:
  GET  $BASE/users?role=DRIVER|CUSTOMER|ADMIN  (admin only)
  POST $BASE/shipments                          (admin only)

Smoke test (needs an admin Cognito ID token):
  curl -H "Authorization: Bearer \$TOKEN" "$BASE/users?role=DRIVER"
  curl -H "Authorization: Bearer \$TOKEN" -H "Content-Type: application/json" \\
       -X POST "$BASE/shipments" \\
       -d '{"shipmentId":"SHIP-004","status":"IN_TRANSIT","riskLevel":"LOW","driver":"driver@lisa.demo","customer":"customer@lisa.demo"}'

Don't forget:
  python3 scripts/seed_dynamodb.py   # seeds Shipments/Users with demo data
EOF
