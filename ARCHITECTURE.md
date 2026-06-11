# LISA — System Architecture

## Architecture Diagram

```text
┌──────────────────────────────────────────────────────────────┐
│  Browser  (index.html)                                       │
│                                                              │
│  Login ──► Cognito User Pool ──► JWT                         │
│  Dashboard / Alerts / Map / Detail                           │
│  Discord embed ────────────────────────► Discord Webhook     │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTPS + Cognito JWT
                         ▼
┌────────────────────────────────────────────────────┐
│  API Gateway  (HTTP API, us-east-1, d1rocl5xb9)    │
│  Cognito JWT Authorizer on all routes except:      │
│    POST /unlock          (NFC hardware — no auth)  │
│    POST /discord/commands  (Ed25519 by Discord)    │
└──────────┬─────────────────────────────────────────┘
           │
    ┌──────┴──────────────────────────────────┐
    │  Lambda Functions                       │
    │  lisa-list-shipments   GET /shipments   │
    │  lisa-get-shipment     GET /shipments/{id}│
    │  lisa-list-alerts      GET /alerts      │
    │  lisa-trigger-alert    POST /demo/trigger│──► Discord Webhook
    │  lisa-resolve-alert    POST /alerts/... │
    │  lisa-discord-commands POST /discord/.. │
    │  lisa-get-me           GET /me          │
    │  lisa-shadow-processor (IoT Rule)       │
    │  lisa-register-nfc-device  POST /nfc/devices            │
    │  lisa-list-nfc-devices     GET  /nfc/devices            │
    │  lisa-update-nfc-whitelist PUT  /nfc/devices/{tagId}/...│
    │  lisa-check-nfc-device     GET  /nfc/check/{tagId}      │──► (no auth, for hardware)
    └──────────────────┬──────────────────────┘
                       │
         ┌─────────────┴──────────────┐
         │  DynamoDB                  │
         │  Shipments                 │
         │  AlertEvents               │
         │  DiscordUsers              │
         │  Users                     │
         │  NFCDevices                │
         └────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Raspberry Pi  (one per shipment)                            │
│  DHT22 · MPU-6050 · GPS · NFC                                │
│                                                              │
│  pi/sensor_agent.py ──MQTT──► IoT Core                       │
│    $aws/things/shipment-SHIP-001/shadow/update               │
│           │                                                  │
│     Device Shadow  (state persists offline)                  │
│           │                                                  │
│     IoT Rule → lisa-shadow-processor                         │
│       • Updates Shipments (temp/humidity/gForce/GPS/battery) │
│       • Threshold breach → AlertEvents + Discord             │
│                                                              │
│  Shadow desired.lockStatus ◄── lisa-trigger-alert (LOCK_UPDATE)│
│  Pi delta callback → GPIO relay                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Existing — DO NOT MODIFY                                    │
│  POST /unlock → Sentinel_NFC_Unlock → Sentinel_Image_Processor│
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Future Extensions  (paths reserved, Lambdas not yet built)  │
│  POST /ai/query             → lisa-ai-agent  (Bedrock LLM)  │
│  GET  /shipments/{id}/route → lisa-route-optimizer           │
│  GET  /alerts/{id}/evidence → lisa-image-evidence            │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. Cognito Integration

### User Pool Setup

```bash
POOL=us-east-1_XXXXXXX

# Create users with custom:role attribute
aws cognito-idp admin-create-user \
  --user-pool-id $POOL \
  --username admin@lisa.demo \
  --user-attributes Name=email,Value=admin@lisa.demo \
                    Name=email_verified,Value=true \
                    Name=custom:role,Value=ADMIN \
  --temporary-password "Lisa@2025!"
```

Repeat for `driver@lisa.demo` (DRIVER) and `customer@lisa.demo` (CUSTOMER).

User Pool settings: Email sign-in · Public client · Implicit grant · Scopes: openid, email, profile

### Frontend Changes (index.html)

Add to `<head>`:

```html
<script src="https://cdn.jsdelivr.net/npm/amazon-cognito-identity-js/dist/amazon-cognito-identity.min.js"></script>
```

Add to `config.local.js`:

```javascript
window.LISA_CONFIG = {
  DISCORD_WEBHOOK_URL:  "...",
  COGNITO_USER_POOL_ID: "us-east-1_XXXXXXX",
  COGNITO_CLIENT_ID:    "XXXXXXXXXXXXXXXXXXXXXXXXX",
};
```

**Only these functions change** — all render functions and role checks are untouched:

- `checkSession()` — try Cognito session first, fall back to `DEMO_ACCOUNTS`
- `handleLogin()` — route to Cognito or demo based on config
- `handleLogout()` — call `cognitoUser.signOut()`

Demo mode continues to work when `COGNITO_USER_POOL_ID` is not set.

### API Gateway Authorizer

`d1rocl5xb9` is an **HTTP API (v2)**, so the authorizer is a **JWT authorizer**
(not the REST API "Cognito User Pool" type):

- Type: JWT
- Identity source: `$request.header.Authorization` (clients send
  `Authorization: Bearer <Cognito ID token>`)
- Issuer: `https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>`
- Audience: the App Client ID
- Apply to all routes except `POST /unlock`, `POST /discord/commands`, and
  `GET /nfc/check/{tagId}`

In the Lambda event, claims land at
`event.requestContext.authorizer.jwt.claims` (note the extra `.jwt` level
compared to REST API's `event.requestContext.authorizer.claims`).

---

## 2. IoT Core Device Shadow

### IoT Rule (AWS Console)

Name: `lisa_shadow_update`

SQL:

```sql
SELECT topic(3) as thingName,
       state.reported.temperature  as temperature,
       state.reported.humidity     as humidity,
       state.reported.gForce       as gForce,
       state.reported.latitude     as latitude,
       state.reported.longitude    as longitude,
       state.reported.batteryLevel as batteryLevel,
       state.reported.online       as online
FROM '$aws/things/+/shadow/update/accepted'
WHERE state.reported IS NOT NULL
```

Action: Lambda → `lisa-shadow-processor`

### IoT Policy

Attach to each Thing certificate:

```json
{
  "Effect": "Allow",
  "Action": ["iot:Connect", "iot:Publish", "iot:Subscribe", "iot:Receive"],
  "Resource": [
    "arn:aws:iot:us-east-1:*:client/shipment-*",
    "arn:aws:iot:us-east-1:*:topic/$aws/things/shipment-*/shadow/*",
    "arn:aws:iot:us-east-1:*:topicfilter/$aws/things/shipment-*/shadow/*"
  ]
}
```

### Shadow Document

Pi reports every 30 seconds:

```json
{
  "state": {
    "reported": {
      "temperature": 4.2,
      "humidity": 65,
      "gForce": 0.1,
      "latitude": 1.3521,
      "longitude": 103.8198,
      "batteryLevel": 87,
      "online": true
    }
  }
}
```

Dashboard lock command sets `desired.lockStatus` → Pi delta callback → GPIO relay.

See `lambda/shadow-processor/lambda_function.py` and `pi/sensor_agent.py`.

---

## 3. DynamoDB Schema

### Shipments (PK: shipmentId)

| Field | Type | Notes |
|-------|------|-------|
| shipmentId | S | Primary key |
| status | S | IN_TRANSIT / ALERT / DELIVERED |
| riskLevel | S | LOW / HIGH / CRITICAL |
| temperature | S | String — matches seed format |
| humidity | S | String |
| gForce | S | String |
| lockStatus | S | LOCKED / UNLOCKED |
| deviceStatus | S | ONLINE / OFFLINE |
| latitude | S | parseFloat in frontend |
| longitude | S | parseFloat in frontend |
| lastUpdatedAt | S | ISO 8601 UTC |
| thingName | S | IoT Thing, e.g. `shipment-SHIP-001` |
| batteryLevel | N | 0–100, written by shadow-processor |
| driver | S | Email of the assigned Users entry with role DRIVER (optional) |
| customer | S | Email of the assigned Users entry with role CUSTOMER (optional) |

### AlertEvents (PK: alertId)

| Field | Type | Notes |
|-------|------|-------|
| alertId | S | ALERT-{timestamp_ms} |
| shipmentId | S | |
| alertType | S | TEMP_HIGH / COLLISION / LOCK_TAMPER / HUMIDITY_HIGH / DEVICE_OFFLINE |
| severity | S | LOW / HIGH / CRITICAL |
| message | S | |
| source | S | manual / iot / discord / api |
| resolved | BOOL | |
| resolvedBy | S | username or `discord:username` |
| createdAt | S | ISO 8601 UTC |
| resolvedAt | S | |

### AccidentEvents (PK: accidentId) — new

Road accidents shown as warning markers on the dashboard's Map page,
alongside the shipment markers. Seeded with 3 demo events randomly placed
on Hsinchu City roads (`scripts/seed_dynamodb.py`).

| Field | Type | Notes |
|-------|------|-------|
| accidentId | S | e.g. `ACC-001` |
| type | S | COLLISION / ROAD_BLOCKED / VEHICLE_BREAKDOWN / ... |
| severity | S | LOW / MEDIUM / HIGH |
| description | S | |
| latitude | S | parseFloat in frontend |
| longitude | S | parseFloat in frontend |
| reportedAt | S | ISO 8601 UTC |

### Users (PK: userId) — new

| Field | Type | Notes |
|-------|------|-------|
| userId | S | Cognito sub |
| email | S | |
| role | S | ADMIN / DRIVER / CUSTOMER |
| createdAt | S | ISO 8601 UTC |

Shipment assignment is not stored on Users — it lives on the Shipments
table's `driver` / `customer` email fields. To find a user's shipments,
query Shipments by those fields (e.g. the dashboard's driver view filters
shipments where `driver` equals the logged-in email).

### NFCDevices (PK: tagId) — new

A single table holds every NFC tag LISA has ever seen. `status` decides whether
it shows up only in "Known Devices" or also in the "Whitelist" panel — there is
no separate whitelist table, so a device can never be "whitelisted but not
known" or vice versa.

| Field | Type | Notes |
|-------|------|-------|
| tagId | S | Primary key — NFC serial number, e.g. `04:AB:12:CD:34:EF:00` |
| label | S | Friendly name entered in the registration modal |
| status | S | `KNOWN` \| `WHITELISTED` |
| firstSeenAt | S | ISO 8601 UTC — set once, on first scan |
| lastSeenAt | S | ISO 8601 UTC — updated on every scan |
| addedBy | S | Admin email; only present when `status = WHITELISTED` |
| addedAt | S | ISO 8601 UTC; only present when `status = WHITELISTED` |

Optional GSI `status-index` (PK: `status`) lets `lisa-list-nfc-devices` and
future queries use `Query` instead of `Scan` once the table grows.

---

## 4. API Routes

| Method | Path | Lambda | Auth | Status |
|--------|------|--------|------|--------|
| POST | `/unlock` | Sentinel_NFC_Unlock | None | Existing — do not touch |
| GET | `/shipments` | lisa-list-shipments | Cognito | Deploy |
| GET | `/shipments/{id}` | lisa-get-shipment | Cognito | Deploy |
| GET | `/alerts` | lisa-list-alerts | Cognito | Deploy |
| POST | `/demo/trigger-alert` | lisa-trigger-alert | Cognito | Deploy |
| POST | `/alerts/{alertId}/resolve` | lisa-resolve-alert | Cognito | Deploy |
| POST | `/discord/commands` | lisa-discord-commands | Ed25519 | Deploy |
| GET | `/me` | lisa-get-me | Cognito | New |
| — | IoT Rule trigger | lisa-shadow-processor | IoT | New |
| POST | `/nfc/devices` | lisa-register-nfc-device | Cognito (ADMIN) | New |
| GET | `/nfc/devices` | lisa-list-nfc-devices | Cognito (ADMIN) | New |
| PUT | `/nfc/devices/{tagId}/whitelist` | lisa-update-nfc-whitelist | Cognito (ADMIN) | New |
| GET | `/nfc/check/{tagId}` | lisa-check-nfc-device | None (hardware) | New |
| GET | `/users` | lisa-list-users | Cognito (ADMIN) | New |
| POST | `/shipments` | lisa-create-shipment | Cognito (ADMIN) | New |
| DELETE | `/shipments/{id}` | lisa-delete-shipment | Cognito (ADMIN) | New |
| GET | `/accidents` | lisa-list-accidents | Cognito | New |

Future paths to reserve now (mock integration, no Lambda yet):

| Method | Path | Future Lambda |
|--------|------|---------------|
| POST | `/ai/query` | lisa-ai-agent |
| GET | `/shipments/{id}/route` | lisa-route-optimizer |
| GET | `/alerts/{id}/evidence` | lisa-image-evidence |

---

## 5. Migration Plan

### Phase 1 — Backend (~2 hours)

1. Create DynamoDB tables: `Shipments`, `AlertEvents`, `DiscordUsers`, `Users`, `NFCDevices` (PK `tagId`, optional GSI `status-index` on `status`)
2. `python scripts/seed_dynamodb.py`
3. Deploy 6 Lambda functions (Python 3.12) — paste from `lambda/*/lambda_function.py`
4. Upload `lambda/discord-commands/discord-commands.zip` (pre-built, 924 KB)
5. Deploy the 4 NFC Lambda functions (`register-nfc-device`, `list-nfc-devices`, `update-nfc-whitelist`, `check-nfc-device`)
6. Add HTTP API routes + Lambda proxy integrations (payload format 2.0), update the API-level CORS config; `$default` stage auto-deploys (`/nfc/check/{tagId}` gets **no** authorizer, same as `/unlock`; the other 3 NFC routes get the JWT authorizer)

Verify:
```bash
BASE=https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com
curl $BASE/shipments          # 3 items
curl "$BASE/alerts?resolved=false"  # 1 item
```

### Phase 2 — Cognito Auth (~1.5 hours)

1. Create Cognito User Pool (settings in §1)
2. Seed demo users via CLI
3. Add `COGNITO_USER_POOL_ID` + `COGNITO_CLIENT_ID` to `config.local.js`
4. Add Cognito CDN `<script>` to `index.html`
5. Replace `checkSession`, `handleLogin`, `handleLogout` (see §1)
6. Add Cognito Authorizer to API Gateway
7. Deploy `lisa-get-me` Lambda

### Phase 3 — Live API (~30 min)

In `index.html`, uncomment `API_BASE` and replace `db*` mock functions with `fetch()` calls:

```javascript
const API_BASE = 'https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/unlock';

async function dbShipments() {
  return fetch(API_BASE + '/shipments').then(r => r.json());
}
async function dbAlerts() {
  return fetch(API_BASE + '/alerts').then(r => r.json());
}
async function dbResolveAlert(alertId, resolvedBy) {
  await fetch(API_BASE + '/alerts/' + alertId + '/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resolvedBy }),
  });
}
async function dbTriggerAlert(shipmentId, alertType, severity, temperature) {
  const res = await fetch(API_BASE + '/demo/trigger-alert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ shipmentId, alertType, severity, temperature }),
  });
  return (await res.json()).alertId;
}
async function dbSetLock(shipmentId, lockStatus) {
  await fetch(API_BASE + '/demo/trigger-alert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ shipmentId, alertType: 'LOCK_UPDATE', lockStatus }),
  });
}
```

Make `renderDashboard`, `renderAlerts`, `renderDetail`, `renderMap` async and `await` these calls.

### Phase 4 — IoT Core (~2 hours per device)

1. Create IoT Things (`shipment-SHIP-001`, etc.)
2. Download certificates → copy to Pi `certs/`
3. Create IoT Rule `lisa_shadow_update` (SQL in §2)
4. Deploy `lambda/shadow-processor/lambda_function.py`
5. Add `iot:UpdateThingShadow` to `lisa-trigger-alert` IAM role
6. Run `pi/sensor_agent.py` on each Pi

---

## 6. IAM Permissions

All Lambda functions share one execution role. Minimum required:

```json
{
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "dynamodb:Scan",
      "dynamodb:Query",
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
  }]
}
```

`lisa-shadow-processor` and `lisa-trigger-alert` additionally need:
```json
{ "Effect": "Allow", "Action": "iot:UpdateThingShadow",
  "Resource": "arn:aws:iot:us-east-1:*:thing/shipment-*" }
```

`lisa-check-nfc-device` runs unauthenticated (like `Sentinel_NFC_Unlock`) but
still uses the same shared execution role — it only needs `dynamodb:GetItem`
on `NFCDevices`, which the policy above already covers.
