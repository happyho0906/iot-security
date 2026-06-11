#!/usr/bin/env bash
#
# Deploys the NFC whitelist backend onto the EXISTING LISA HTTP API
# (API Gateway v2, e.g. "Sentinel_NFC_API"):
#   - Creates the `NFCDevices` DynamoDB table (+ status-index GSI)
#   - Creates/updates the 4 NFC Lambda functions
#   - Adds POST/GET /nfc/devices, PUT /nfc/devices/{tagId}/whitelist,
#     GET /nfc/check/{tagId} routes to the existing HTTP API
#   - Optionally creates a Cognito JWT authorizer and attaches it to the
#     3 admin-only routes (registration/list/whitelist update)
#
# This script is purely additive. It never touches POST /unlock,
# Sentinel_NFC_Unlock, Sentinel_Image_Processor, or the existing
# /discord/commands route (see INTEGRATION.md "Do Not Touch").
# Re-running it is safe (idempotent: existing integrations/routes/
# authorizer are reused and updated in place).
#
# IMPORTANT — AWS Amplify in this repo only manages FRONTEND HOSTING/CI-CD
# (see amplify.yml: it builds index.html + config.local.js from env vars).
# It does not deploy Lambda/DynamoDB/API Gateway. Those are deployed
# separately, by running this script (or the manual steps in DEPLOY.md)
# once from a machine/CloudShell with the AWS CLI configured for this
# AWS account.
#
# Prerequisites:
#   - AWS CLI v2, configured (e.g. AWS CloudShell already has this)
#   - `zip` available on PATH (preinstalled in CloudShell)
#   - Run from the repository root
#
# Required environment variables:
#   AWS_REGION       e.g. us-east-1
#   API_ID           existing HTTP API ID, e.g. d1rocl5xb9 (Sentinel_NFC_API)
#   LAMBDA_ROLE_ARN  shared Lambda execution role ARN, e.g. LabRole
#                    (must allow dynamodb:Scan/Query/GetItem/PutItem/UpdateItem
#                    on NFCDevices and NFCDevices/index/*)
#
# Optional (enables Cognito auth on the 3 admin routes):
#   COGNITO_USER_POOL_ID   e.g. us-east-1_XXXXXXXXX
#   COGNITO_CLIENT_ID      App client ID used by the dashboard (no secret)
#
#   If either is unset, the 3 admin routes are created with NO authorizer
#   (authorizationType=NONE). In that case requestContext.authorizer will be
#   absent, so the Lambdas' `custom:role == ADMIN` check will always fail
#   (403) — i.e. the admin endpoints simply won't work yet. Set both env
#   vars and re-run this script once the Cognito User Pool is known.
#
# Example (run in AWS CloudShell, region us-east-1):
#   export AWS_REGION=us-east-1
#   export API_ID=d1rocl5xb9
#   export LAMBDA_ROLE_ARN=arn:aws:iam::194686029661:role/LabRole
#   export COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX   # optional
#   export COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx  # optional
#   bash scripts/deploy_nfc_backend.sh

set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION, e.g. us-east-1}"
: "${API_ID:?Set API_ID to the existing HTTP API ID (Sentinel_NFC_API)}"
: "${LAMBDA_ROLE_ARN:?Set LAMBDA_ROLE_ARN to the shared Lambda execution role ARN (e.g. LabRole)}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# ── 0. Cognito JWT authorizer (optional) ────────────────────────────────────

AUTH_TYPE="NONE"
AUTHORIZER_ID=""

if [ -n "${COGNITO_USER_POOL_ID:-}" ] && [ -n "${COGNITO_CLIENT_ID:-}" ]; then
  AUTH_TYPE="JWT"
  ISSUER="https://cognito-idp.${AWS_REGION}.amazonaws.com/${COGNITO_USER_POOL_ID}"

  echo "==> Checking for existing Cognito JWT authorizer..."
  AUTHORIZER_ID=$(aws apigatewayv2 get-authorizers --api-id "$API_ID" --region "$AWS_REGION" \
    --query "Items[?Name=='lisa-cognito-jwt'].AuthorizerId | [0]" --output text)

  if [ "$AUTHORIZER_ID" != "None" ] && [ -n "$AUTHORIZER_ID" ]; then
    echo "    Reusing existing authorizer $AUTHORIZER_ID"
    aws apigatewayv2 update-authorizer --api-id "$API_ID" --authorizer-id "$AUTHORIZER_ID" \
      --jwt-configuration "Audience=${COGNITO_CLIENT_ID},Issuer=${ISSUER}" \
      --region "$AWS_REGION" >/dev/null
  else
    AUTHORIZER_ID=$(aws apigatewayv2 create-authorizer --api-id "$API_ID" --region "$AWS_REGION" \
      --authorizer-type JWT --identity-source '$request.header.Authorization' \
      --name lisa-cognito-jwt \
      --jwt-configuration "Audience=${COGNITO_CLIENT_ID},Issuer=${ISSUER}" \
      --query AuthorizerId --output text)
    echo "    Created authorizer $AUTHORIZER_ID"
  fi
else
  echo "WARNING: COGNITO_USER_POOL_ID / COGNITO_CLIENT_ID not set."
  echo "         The 3 admin NFC routes will be created with NO authorizer."
  echo "         requestContext.authorizer will be absent, so the Lambdas'"
  echo "         ADMIN check will always return 403 until you set both env"
  echo "         vars and re-run this script."
fi

# ── 1. DynamoDB table ───────────────────────────────────────────────────────

echo "==> Checking NFCDevices table..."
if aws dynamodb describe-table --table-name NFCDevices --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "    NFCDevices already exists, skipping create."
else
  aws dynamodb create-table \
    --table-name NFCDevices \
    --attribute-definitions \
        AttributeName=tagId,AttributeType=S \
        AttributeName=status,AttributeType=S \
    --key-schema AttributeName=tagId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[{
      "IndexName": "status-index",
      "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
      "Projection": {"ProjectionType": "ALL"}
    }]' \
    --region "$AWS_REGION" >/dev/null
  echo "    Waiting for table to become active..."
  aws dynamodb wait table-exists --table-name NFCDevices --region "$AWS_REGION"
  echo "    Created NFCDevices."
fi

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

ARN_REGISTER=$(deploy_lambda lisa-register-nfc-device  lambda/register-nfc-device)
ARN_LIST=$(deploy_lambda     lisa-list-nfc-devices     lambda/list-nfc-devices)
ARN_UPDATE=$(deploy_lambda   lisa-update-nfc-whitelist lambda/update-nfc-whitelist)
ARN_CHECK=$(deploy_lambda    lisa-check-nfc-device     lambda/check-nfc-device)

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
  local route_key="$1" integration_id="$2" auth="$3"
  local target="integrations/${integration_id}"
  local auth_args=(--authorization-type "$auth")
  if [ "$auth" = "JWT" ]; then
    auth_args+=(--authorizer-id "$AUTHORIZER_ID")
  fi

  local existing
  existing=$(aws apigatewayv2 get-routes --api-id "$API_ID" --region "$AWS_REGION" \
    --query "Items[?RouteKey=='${route_key}'].RouteId | [0]" --output text)

  echo "==> $route_key -> $target (auth=$auth)"
  if [ "$existing" != "None" ] && [ -n "$existing" ]; then
    aws apigatewayv2 update-route --api-id "$API_ID" --route-id "$existing" \
      --target "$target" "${auth_args[@]}" --region "$AWS_REGION" >/dev/null
  else
    aws apigatewayv2 create-route --api-id "$API_ID" --route-key "$route_key" \
      --target "$target" "${auth_args[@]}" --region "$AWS_REGION" >/dev/null
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

INT_REGISTER=$(get_or_create_integration "$ARN_REGISTER")
INT_LIST=$(get_or_create_integration "$ARN_LIST")
INT_UPDATE=$(get_or_create_integration "$ARN_UPDATE")
INT_CHECK=$(get_or_create_integration "$ARN_CHECK")

get_or_create_route "POST /nfc/devices"                     "$INT_REGISTER" "$AUTH_TYPE"
get_or_create_route "GET /nfc/devices"                      "$INT_LIST"     "$AUTH_TYPE"
get_or_create_route "PUT /nfc/devices/{tagId}/whitelist"    "$INT_UPDATE"   "$AUTH_TYPE"
get_or_create_route "GET /nfc/check/{tagId}"                "$INT_CHECK"    "NONE"

add_permission lisa-register-nfc-device
add_permission lisa-list-nfc-devices
add_permission lisa-update-nfc-whitelist
add_permission lisa-check-nfc-device

# ── 4. CORS (API-level, HTTP API style) ─────────────────────────────────────

echo "==> Updating API-level CORS configuration..."
EXISTING_ORIGINS=$(aws apigatewayv2 get-api --api-id "$API_ID" --region "$AWS_REGION" \
  --query 'CorsConfiguration.AllowOrigins' --output json)

aws apigatewayv2 update-api --api-id "$API_ID" --region "$AWS_REGION" \
  --cors-configuration "{
    \"AllowOrigins\": ${EXISTING_ORIGINS:-[\"*\"]},
    \"AllowMethods\": [\"GET\",\"POST\",\"PUT\",\"OPTIONS\"],
    \"AllowHeaders\": [\"content-type\",\"authorization\"],
    \"AllowCredentials\": false,
    \"MaxAge\": 0
  }" >/dev/null

# ── 5. Done ──────────────────────────────────────────────────────────────────
# $default stage has auto-deploy enabled, so routes are live immediately.

BASE="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"
cat <<EOF

Done. New routes are live at:
  POST $BASE/nfc/devices
  GET  $BASE/nfc/devices
  PUT  $BASE/nfc/devices/{tagId}/whitelist
  GET  $BASE/nfc/check/{tagId}        (no auth)

Smoke test (no-auth route):
  curl "$BASE/nfc/check/04:AB:12:CD:34:EF:00"

Admin routes need a Cognito ID token (auth=$AUTH_TYPE):
  curl -H "Authorization: Bearer \$TOKEN" "$BASE/nfc/devices"

Don't forget:
  python3 scripts/seed_dynamodb.py   # seeds NFCDevices with demo data
EOF
