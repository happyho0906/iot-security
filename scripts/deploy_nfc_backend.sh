#!/usr/bin/env bash
#
# Deploys the NFC whitelist backend onto the EXISTING LISA API Gateway:
#   - Creates the `NFCDevices` DynamoDB table (+ status-index GSI)
#   - Creates/updates the 4 NFC Lambda functions
#   - Adds /nfc/devices, /nfc/devices/{tagId}/whitelist, /nfc/check/{tagId}
#     routes to the existing REST API and redeploys the stage
#
# This script is purely additive. It never touches /unlock,
# Sentinel_NFC_Unlock, or Sentinel_Image_Processor (see INTEGRATION.md
# "Do Not Touch"). Re-running it is safe (idempotent where practical).
#
# IMPORTANT — AWS Amplify in this repo only manages FRONTEND HOSTING/CI-CD
# (see amplify.yml: it builds index.html + config.local.js from env vars).
# It does not deploy Lambda/DynamoDB/API Gateway. Those are deployed
# separately, by running this script (or the manual steps in DEPLOY.md)
# once from a machine with the AWS CLI configured for this AWS account.
#
# Prerequisites:
#   - AWS CLI v2, configured (`aws configure` or SSO) with permissions for
#     dynamodb:*, lambda:*, apigateway:*, iam:PassRole, sts:GetCallerIdentity
#   - `zip` available on PATH
#   - Run from the repository root
#
# Required environment variables:
#   AWS_REGION       e.g. us-east-1
#   API_ID           existing REST API ID, e.g. d1rocl5xb9 (see DEPLOY.md)
#   STAGE            existing deployed stage, e.g. unlock
#   LAMBDA_ROLE_ARN  shared Lambda execution role ARN (see ARCHITECTURE.md §6 —
#                    must allow dynamodb:Scan/Query/GetItem/PutItem/UpdateItem
#                    on NFCDevices and NFCDevices/index/*)
#
# Optional:
#   COGNITO_AUTHORIZER_ID  ID of the Cognito authorizer already attached to
#                          this API (used by /shipments etc). If unset, the
#                          three admin NFC routes are created with NO
#                          authorizer (NONE) and you must attach the
#                          authorizer manually afterwards in the API Gateway
#                          console (Resources → method → Method Request).
#
# Example:
#   export AWS_REGION=us-east-1
#   export API_ID=d1rocl5xb9
#   export STAGE=unlock
#   export LAMBDA_ROLE_ARN=arn:aws:iam::123456789012:role/lisa-lambda-role
#   export COGNITO_AUTHORIZER_ID=abc123      # optional
#   bash scripts/deploy_nfc_backend.sh

set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION, e.g. us-east-1}"
: "${API_ID:?Set API_ID to the existing REST API ID (see DEPLOY.md)}"
: "${STAGE:?Set STAGE to the existing deployed stage, e.g. unlock}"
: "${LAMBDA_ROLE_ARN:?Set LAMBDA_ROLE_ARN to the shared Lambda execution role ARN}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

AUTH_ADMIN="NONE"
AUTHORIZER_ARGS=()
if [ -n "${COGNITO_AUTHORIZER_ID:-}" ]; then
  AUTH_ADMIN="COGNITO_USER_POOLS"
  AUTHORIZER_ARGS=(--authorizer-id "$COGNITO_AUTHORIZER_ID")
else
  echo "WARNING: COGNITO_AUTHORIZER_ID not set — admin NFC routes will be"
  echo "         created with NO authorizer. Attach the Cognito authorizer"
  echo "         manually afterwards (API Gateway console → Resources →"
  echo "         method → Method Request → Authorization)."
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
  echo "==> Deploying $name (from $dir)"
  rm -f "$zip"
  (cd "$dir" && zip -q -r "$zip" lambda_function.py)

  if aws lambda get-function --function-name "$name" --region "$AWS_REGION" >/dev/null 2>&1; then
    aws lambda update-function-code \
      --function-name "$name" --zip-file "fileb://$zip" \
      --region "$AWS_REGION" >/dev/null
    aws lambda wait function-updated --function-name "$name" --region "$AWS_REGION"
    echo "    Updated existing function."
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
    echo "    Created new function."
  fi

  aws lambda get-function --function-name "$name" --region "$AWS_REGION" \
    --query 'Configuration.FunctionArn' --output text
}

ARN_REGISTER=$(deploy_lambda lisa-register-nfc-device  lambda/register-nfc-device)
ARN_LIST=$(deploy_lambda     lisa-list-nfc-devices     lambda/list-nfc-devices)
ARN_UPDATE=$(deploy_lambda   lisa-update-nfc-whitelist lambda/update-nfc-whitelist)
ARN_CHECK=$(deploy_lambda    lisa-check-nfc-device     lambda/check-nfc-device)

# ── 3. API Gateway resources ────────────────────────────────────────────────

get_or_create_resource() {
  local parent_id="$1" path_part="$2"
  local existing
  existing=$(aws apigateway get-resources --rest-api-id "$API_ID" --region "$AWS_REGION" \
    --query "items[?parentId=='${parent_id}' && pathPart=='${path_part}'].id | [0]" \
    --output text)
  if [ "$existing" != "None" ] && [ -n "$existing" ]; then
    echo "$existing"
  else
    aws apigateway create-resource --rest-api-id "$API_ID" --region "$AWS_REGION" \
      --parent-id "$parent_id" --path-part "$path_part" \
      --query 'id' --output text
  fi
}

echo "==> Creating API Gateway resource tree under /nfc..."
ROOT_ID=$(aws apigateway get-resources --rest-api-id "$API_ID" --region "$AWS_REGION" \
  --query "items[?path=='/'].id | [0]" --output text)

NFC_ID=$(get_or_create_resource "$ROOT_ID" "nfc")
DEVICES_ID=$(get_or_create_resource "$NFC_ID" "devices")
DEVICE_ID=$(get_or_create_resource "$DEVICES_ID" "{tagId}")
WHITELIST_ID=$(get_or_create_resource "$DEVICE_ID" "whitelist")
CHECK_ID=$(get_or_create_resource "$NFC_ID" "check")
CHECK_TAG_ID=$(get_or_create_resource "$CHECK_ID" "{tagId}")

# ── 4. Methods + Lambda proxy integrations ──────────────────────────────────

add_method() {
  local resource_id="$1" http_method="$2" lambda_arn="$3" lambda_name="$4" auth="$5"
  local authorizer_args=()
  if [ "$auth" = "COGNITO_USER_POOLS" ]; then
    authorizer_args=("${AUTHORIZER_ARGS[@]}")
  fi

  echo "==> $http_method on resource $resource_id -> $lambda_name (auth=$auth)"

  aws apigateway put-method \
    --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method "$http_method" --authorization-type "$auth" \
    "${authorizer_args[@]}" \
    --region "$AWS_REGION" >/dev/null 2>&1 || \
  aws apigateway update-method \
    --rest-api-id "$API_ID" --resource-id "$resource_id" --http-method "$http_method" \
    --patch-operations "op=replace,path=/authorizationType,value=$auth" \
    --region "$AWS_REGION" >/dev/null

  aws apigateway put-integration \
    --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method "$http_method" --type AWS_PROXY --integration-http-method POST \
    --uri "arn:aws:apigateway:${AWS_REGION}:lambda:path/2015-03-31/functions/${lambda_arn}/invocations" \
    --region "$AWS_REGION" >/dev/null

  aws lambda add-permission \
    --function-name "$lambda_name" \
    --statement-id "apigw-$(echo "${resource_id}-${http_method}" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9-')" \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*/${http_method}/*" \
    --region "$AWS_REGION" >/dev/null 2>&1 || true
}

enable_cors() {
  local resource_id="$1" methods="$2"  # e.g. "GET,POST"

  aws apigateway put-method --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method OPTIONS --authorization-type NONE \
    --region "$AWS_REGION" >/dev/null 2>&1 || true

  aws apigateway put-integration --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method OPTIONS --type MOCK \
    --request-templates '{"application/json":"{\"statusCode\": 200}"}' \
    --region "$AWS_REGION" >/dev/null

  aws apigateway put-method-response --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method OPTIONS --status-code 200 \
    --response-parameters '{
      "method.response.header.Access-Control-Allow-Headers": false,
      "method.response.header.Access-Control-Allow-Methods": false,
      "method.response.header.Access-Control-Allow-Origin": false
    }' \
    --region "$AWS_REGION" >/dev/null 2>&1 || true

  aws apigateway put-integration-response --rest-api-id "$API_ID" --resource-id "$resource_id" \
    --http-method OPTIONS --status-code 200 \
    --response-parameters "{
      \"method.response.header.Access-Control-Allow-Headers\": \"'Content-Type,Authorization'\",
      \"method.response.header.Access-Control-Allow-Methods\": \"'${methods},OPTIONS'\",
      \"method.response.header.Access-Control-Allow-Origin\": \"'*'\"
    }" \
    --region "$AWS_REGION" >/dev/null
}

add_method "$DEVICES_ID"   POST "$ARN_REGISTER" lisa-register-nfc-device  "$AUTH_ADMIN"
add_method "$DEVICES_ID"   GET  "$ARN_LIST"     lisa-list-nfc-devices     "$AUTH_ADMIN"
add_method "$WHITELIST_ID" PUT  "$ARN_UPDATE"   lisa-update-nfc-whitelist "$AUTH_ADMIN"
add_method "$CHECK_TAG_ID" GET  "$ARN_CHECK"    lisa-check-nfc-device     "NONE"

enable_cors "$DEVICES_ID"   "GET,POST"
enable_cors "$WHITELIST_ID" "PUT"
enable_cors "$CHECK_TAG_ID" "GET"

# ── 5. Deploy stage ──────────────────────────────────────────────────────────

echo "==> Deploying API stage '$STAGE'..."
aws apigateway create-deployment --rest-api-id "$API_ID" --stage-name "$STAGE" \
  --description "Add NFC whitelist routes (lisa-*-nfc-* lambdas)" \
  --region "$AWS_REGION" >/dev/null

BASE="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com/${STAGE}"
cat <<EOF

Done. New routes are live at:
  POST $BASE/nfc/devices
  GET  $BASE/nfc/devices
  PUT  $BASE/nfc/devices/{tagId}/whitelist
  GET  $BASE/nfc/check/{tagId}        (no auth)

Smoke test (no-auth route):
  curl "$BASE/nfc/check/04:AB:12:CD:34:EF:00"

Admin routes need a Cognito ID token:
  curl -H "Authorization: Bearer \$TOKEN" "$BASE/nfc/devices"

Don't forget:
  python scripts/seed_dynamodb.py   # seeds NFCDevices with demo data
EOF
