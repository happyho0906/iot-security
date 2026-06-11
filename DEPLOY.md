# LISA Deployment Guide

## Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.x with boto3 installed (`pip install boto3`)

---

## Note: AWS Amplify only deploys the frontend

This repo is connected to **AWS Amplify Hosting** (see `amplify.yml`). On every
push to a connected branch, Amplify builds and deploys `index.html` +
`config.local.js` (generated from the `COGNITO_USER_POOL_ID`,
`COGNITO_CLIENT_ID`, `DISCORD_WEBHOOK_URL` environment variables set in the
Amplify Console). **Amplify does not create or manage DynamoDB tables, Lambda
functions, or API Gateway routes** — those are separate AWS resources, deployed
once via the steps below (or the script in Step 2b), independent of any git
push/Amplify build.

---

## Note: the existing API (`d1rocl5xb9` / `Sentinel_NFC_API`) is an HTTP API (v2)

This matters because it's a different product from a REST API (v1) and uses a
different console/CLI:

- **No "Deploy API" step.** The `$default` stage has auto-deploy enabled —
  routes go live as soon as they're created/updated.
- **No per-resource CORS.** CORS is one config block at the API level
  (`aws apigatewayv2 update-api --cors-configuration ...`), not an `OPTIONS`
  method per resource.
- **URLs have no stage prefix.** Base URL is just
  `https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com` — e.g.
  `POST /unlock` is reachable at
  `https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/unlock`, and the new
  NFC routes will be at `.../nfc/devices`, `.../nfc/check/{tagId}`, etc.
  (**no** `/unlock` or `/prod` segment in front of `/nfc/...`).
- **Cognito authorization uses a JWT authorizer** (`--authorizer-type JWT`),
  not the REST API `COGNITO_USER_POOLS` authorizer type. Claims land at
  `event.requestContext.authorizer.jwt.claims` in the Lambda event (the 3
  admin NFC Lambdas already expect this shape).
- **Lambda execution role**: in this AWS Academy account, both
  `lisa-discord-commands` and `Sentinel_NFC_Unlock` run as `LabRole`
  (`arn:aws:iam::194686029661:role/LabRole`). Reuse this role for the 4 new
  NFC Lambdas too.

`scripts/deploy_nfc_backend.sh` (Step 2b) already accounts for all of this.

---

## Step 1: DynamoDB Tables

Create these tables in AWS Console → DynamoDB → Create table:

| Table Name | Partition Key | Type | Billing |
|-----------|---------------|------|---------|
| Shipments | shipmentId | String | On-demand |
| AlertEvents | alertId | String | On-demand |
| DiscordUsers | discordUserId | String | On-demand |
| NFCDevices | tagId | String | On-demand |

For `NFCDevices`, optionally add a Global Secondary Index:

- Index name: `status-index`
- Partition key: `status` (String)

(The bundled Lambdas use `Scan` and work fine without the GSI; add it later if
the table grows large and you want `Query`-based lookups.)

After creating tables, seed initial data:
```bash
python scripts/seed_dynamodb.py
```

---

## Step 2: Lambda Functions

Create 6 Lambda functions in AWS Console → Lambda → Create function.
All use **Runtime: Python 3.12**.

| Function Name | File | Handler |
|--------------|------|---------|
| lisa-list-shipments | lambda/list-shipments/lambda_function.py | lambda_function.lambda_handler |
| lisa-get-shipment | lambda/get-shipment/lambda_function.py | lambda_function.lambda_handler |
| lisa-list-alerts | lambda/list-alerts/lambda_function.py | lambda_function.lambda_handler |
| lisa-trigger-alert | lambda/trigger-alert/lambda_function.py | lambda_function.lambda_handler |
| lisa-resolve-alert | lambda/resolve-alert/lambda_function.py | lambda_function.lambda_handler |
| lisa-discord-commands | (zip bundle — see below) | lambda_function.lambda_handler |

### NFC whitelist Lambda functions

Create these 4 additional functions, also **Runtime: Python 3.12**:

| Function Name | File | Handler |
|--------------|------|---------|
| lisa-register-nfc-device | lambda/register-nfc-device/lambda_function.py | lambda_function.lambda_handler |
| lisa-list-nfc-devices | lambda/list-nfc-devices/lambda_function.py | lambda_function.lambda_handler |
| lisa-update-nfc-whitelist | lambda/update-nfc-whitelist/lambda_function.py | lambda_function.lambda_handler |
| lisa-check-nfc-device | lambda/check-nfc-device/lambda_function.py | lambda_function.lambda_handler |

### Step 2b (alternative): scripted deploy of the NFC backend

Instead of clicking through the console for the `NFCDevices` table, the 4 NFC
Lambdas, and their HTTP API routes (Steps 1, 2, and 3 for the NFC pieces),
you can run `scripts/deploy_nfc_backend.sh` from **AWS CloudShell** (preinstalled
AWS CLI/zip/Python — no local setup needed). It is idempotent — safe to re-run
after editing a Lambda's code.

```bash
export AWS_REGION=us-east-1
export API_ID=d1rocl5xb9        # existing HTTP API "Sentinel_NFC_API"
export LAMBDA_ROLE_ARN=arn:aws:iam::194686029661:role/LabRole

# Optional — enables Cognito JWT auth on the 3 admin routes. Omit both to
# deploy with auth=NONE on those routes (they'll 403 until you set these
# and re-run).
export COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
export COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx

bash scripts/deploy_nfc_backend.sh
python3 scripts/seed_dynamodb.py
```

Find `COGNITO_USER_POOL_ID` / `COGNITO_CLIENT_ID` (the User Pool and App
Client used by the dashboard's login) via:

```bash
aws cognito-idp list-user-pools --max-results 20 \
  --query 'UserPools[*].{id:Id,name:Name}' --output table

aws cognito-idp list-user-pool-clients --user-pool-id <pool-id> \
  --query 'UserPoolClients[*].{id:ClientId,name:ClientName}' --output table
```

If `LAMBDA_ROLE_ARN` (`LabRole`) doesn't already have access to `NFCDevices`,
attach the IAM policy from ARCHITECTURE.md §6 (includes `NFCDevices` and
`NFCDevices/index/*`) — AWS Academy `LabRole` usually already has broad
DynamoDB access, so this is normally unnecessary.

### Step 2c (alternative): scripted deploy of the "Add Shipment" admin feature

Run `scripts/deploy_shipments_backend.sh` from AWS CloudShell, after Step 2b
(it reuses the `lisa-cognito-jwt` authorizer created there). It is idempotent
and additionally creates the `Shipments` and `Users` tables if they don't
already exist:

```bash
export AWS_REGION=us-east-1
export API_ID=d1rocl5xb9        # existing HTTP API "Sentinel_NFC_API"
export LAMBDA_ROLE_ARN=arn:aws:iam::194686029661:role/LabRole

bash scripts/deploy_shipments_backend.sh
python3 scripts/seed_dynamodb.py
```

This deploys `lisa-list-users` (`GET /users?role=...`) and
`lisa-create-shipment` (`POST /shipments`), both admin-only via the JWT
authorizer. The dashboard's "Add Shipment" modal uses these to populate the
Driver/Customer dropdowns from the `Users` table and to persist new shipments
to the `Shipments` table.

### discord-commands bundle (requires PyNaCl)

```bash
cd lambda/discord-commands
pip install PyNaCl==1.5.0 -t ./package
cp lambda_function.py ./package/
cd package && zip -r ../discord-commands.zip . && cd ..
```

Upload `lambda/discord-commands/discord-commands.zip` via the Lambda console.

### IAM Permissions (attach to each Lambda's execution role)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:Scan",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:*:table/Shipments",
        "arn:aws:dynamodb:us-east-1:*:table/AlertEvents",
        "arn:aws:dynamodb:us-east-1:*:table/Users",
        "arn:aws:dynamodb:us-east-1:*:table/NFCDevices",
        "arn:aws:dynamodb:us-east-1:*:table/NFCDevices/index/*"
      ]
    }
  ]
}
```

### Environment Variables

Set on the respective Lambda functions:

**lisa-trigger-alert:**
- `DISCORD_WEBHOOK_URL` = (from Discord channel → Settings → Integrations → Webhooks)
- `SHIPMENTS_TABLE` = `Shipments`
- `ALERTS_TABLE` = `AlertEvents`

**lisa-discord-commands:**
- `DISCORD_PUBLIC_KEY` = (from Discord Developer Portal → Application → General Information)

---

## Step 3: API Gateway Routes

Open the existing **HTTP API** `Sentinel_NFC_API` (API ID: `d1rocl5xb9`) in
AWS Console → API Gateway. (This is an **HTTP API**, not a REST API — the
console UI is the simpler "Routes" / "Integrations" list, and there's no
"Resources" tree or "Deploy API" button.)

Add these routes — do NOT modify the existing `POST /unlock` or
`POST /discord/commands` routes:

| Method | Route | Lambda Integration |
|--------|--------------|-------------------|
| GET | /shipments | lisa-list-shipments |
| GET | /shipments/{id} | lisa-get-shipment |
| GET | /alerts | lisa-list-alerts |
| POST | /demo/trigger-alert | lisa-trigger-alert |
| POST | /alerts/{alertId}/resolve | lisa-resolve-alert |
| POST | /nfc/devices | lisa-register-nfc-device |
| GET | /nfc/devices | lisa-list-nfc-devices |
| PUT | /nfc/devices/{tagId}/whitelist | lisa-update-nfc-whitelist |
| GET | /nfc/check/{tagId} | lisa-check-nfc-device |

For each route: **Routes → Create**, enter the method + path, then attach an
integration of type **Lambda function** (proxy), payload format **2.0**,
pointing at the Lambda above.

**No per-route CORS / no "Deploy API" step.** HTTP APIs configure CORS once at
the API level (**Develop → CORS**) and the `$default` stage auto-deploys new
routes immediately. Make sure the CORS config includes:
- Allow methods: `GET, POST, PUT, OPTIONS`
- Allow headers: `content-type, authorization`
- Allow origins: keep the existing entries (`*`, `http://localhost:5500`)

**Authorization** (Routes → select route → Attach authorizer):
- `POST /nfc/devices`, `GET /nfc/devices`, `PUT /nfc/devices/{tagId}/whitelist`
  → attach a **JWT authorizer** backed by the Cognito User Pool used for login
  (Issuer = `https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>`,
  Audience = the App Client ID). These Lambdas additionally check
  `custom:role = ADMIN` themselves via
  `event.requestContext.authorizer.jwt.claims`.
- `GET /nfc/check/{tagId}` → leave authorization as **NONE**, same as
  `/unlock`, so hardware can call it without a token.

Your base URL has **no stage prefix**:
`https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com`
(e.g. the unlock endpoint is `.../unlock`, the new check endpoint is
`.../nfc/check/{tagId}`).

Update `API_BASE` in `index.html` to `https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com`
(no trailing `/unlock` or stage name).

> `scripts/deploy_nfc_backend.sh` (Step 2b) does all of the above for the 4 NFC
> routes automatically, including the CORS update and JWT authorizer setup.

---

## Step 4: Cognito User Pool

1. AWS Console → Cognito → Create user pool:
   - Sign-in: **Email**
   - MFA: **None**
   - App type: **Public client** (no client secret)
   - OAuth flows: **Implicit grant**
   - Scopes: `openid`, `email`, `profile`
   - Callback URL: your hosting URL + `http://localhost:8080` (for testing)

2. Create Cognito domain: `lisa-auth.auth.us-east-1.amazoncognito.com`

3. Note your **User Pool ID** and **App Client ID** — update `COGNITO_CONFIG` in `index.html`.

4. Create a demo admin user:
   ```bash
   aws cognito-idp admin-create-user \
     --user-pool-id us-east-1_XXXXXXX \
     --username admin@lisa-demo.com \
     --user-attributes Name=email,Value=admin@lisa-demo.com Name=email_verified,Value=true \
     --temporary-password "Lisa@2025!"
   ```

---

## Step 5: Discord Bot Setup

1. Go to https://discord.com/developers/applications → New Application → name it **LISA**
2. Copy **Application ID** and **Public Key** from General Information
3. Under Bot → Add Bot → copy **Bot Token**
4. Set Lambda env vars (from Step 2):
   - `lisa-discord-commands`: `DISCORD_PUBLIC_KEY`
   - `lisa-trigger-alert`: `DISCORD_WEBHOOK_URL` (channel Settings → Integrations → Webhooks)
5. Register slash commands:
   ```bash
   DISCORD_APPLICATION_ID=<id> DISCORD_BOT_TOKEN=<token> python scripts/register_discord_commands.py
   ```
6. In Discord Developer Portal → your app → General Information:
   **Interactions Endpoint URL** = `https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/discord/commands`
   (no stage prefix — this is an HTTP API on `$default`. Discord verifies
   immediately via PING — Ed25519 must work)
7. Add bot to server: OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: Send Messages → copy URL → open in browser

---

## Step 6: Test Everything

```bash
# HTTP API on $default — no stage prefix in the URL
BASE=https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com

# Verify endpoints
curl $BASE/shipments
curl "$BASE/alerts?resolved=false"
curl -X POST $BASE/demo/trigger-alert \
  -H 'Content-Type: application/json' \
  -d '{"shipmentId":"SHIP-001","alertType":"TEMP_HIGH","severity":"CRITICAL","temperature":"12.5"}'

# NFC whitelist (requires a Cognito ADMIN access token in $TOKEN for the /nfc/devices* routes)
curl -H "Authorization: Bearer $TOKEN" $BASE/nfc/devices
curl -X POST $BASE/nfc/devices \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tagId":"04:11:22:33:44:55:66","label":"Test Tag"}'
curl -X PUT "$BASE/nfc/devices/04:11:22:33:44:55:66/whitelist" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"whitelisted": true}'

# /nfc/check is unauthenticated, like /unlock
curl "$BASE/nfc/check/04:11:22:33:44:55:66"

# Serve frontend locally
python3 -m http.server 8080
# Open http://localhost:8080 → login with admin@lisa-demo.com
```

---

## Verification Checklist

- [ ] `GET /shipments` returns 3 shipments
- [ ] `GET /alerts?resolved=false` returns 1 unresolved alert
- [ ] `POST /demo/trigger-alert` creates alert + Discord notification
- [ ] `POST /alerts/{id}/resolve` resolves alert, updates shipment
- [ ] Login page appears at http://localhost:8080
- [ ] Dashboard loads with correct counts after login
- [ ] Shipment Detail page loads for SHIP-001
- [ ] Trigger Temp Alert button creates alert
- [ ] Resolve button from Alert Center works
- [ ] Lock/Unlock updates DynamoDB
- [ ] Map placeholder page loads
- [ ] Discord `/status SHIP-001` returns live data
- [ ] Existing `POST /unlock` endpoint still works
- [ ] `GET /nfc/devices` (admin token) returns the seeded NFC devices
- [ ] `POST /nfc/devices` registers a new tag with `status = KNOWN`
- [ ] `PUT /nfc/devices/{tagId}/whitelist` toggles `status` to `WHITELISTED` and back to `KNOWN`
- [ ] `GET /nfc/check/{tagId}` (no auth) returns `allowed: true` only for whitelisted tags
- [ ] Non-admin users get `403` from all `/nfc/devices*` routes
