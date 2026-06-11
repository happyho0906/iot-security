# LISA: Integration & Team Collaboration Guide

This document is for developers integrating other hardware modules, Lambda functions, or services into the LISA platform. 

---

## Current System State

| Component | State | Notes |
|-----------|-------|-------|
| `index.html` frontend | **Working**  demo mode | Runs locally, no AWS needed |
| Lambda functions (6) | **Written, not deployed** | Code in `lambda/*/lambda_function.py` |
| NFC whitelist Lambdas (4) | **Written, not deployed** | `lambda/register-nfc-device`, `list-nfc-devices`, `update-nfc-whitelist`, `check-nfc-device` |
| DynamoDB tables | **Not created** | Schema defined, seed script ready (incl. `NFCDevices`) |
| API Gateway routes | **Not wired** | Endpoint exists, new routes not added |
| Discord webhook alerts | **Working**  browser-to-Discord | Set `DISCORD_WEBHOOK_URL` in `index.html` |
| Discord slash commands | **Not active** | Needs Lambda deployment + Discord setup |
| `Sentinel_NFC_Unlock` Lambda | **Deployed** (not in this repo) | Handles `POST /unlock`  do not touch |
| `Sentinel_Image_Processor` Lambda | **Deployed** (not in this repo) | Camera capture → S3  not yet surfaced in UI |

**The frontend runs in two modes:**
- **Demo mode** (current): all data is in-memory in `index.html`. Works with no AWS at all.
- **Production mode**: uncomment `API_BASE` in `index.html` and replace the `db*` mock functions with `fetch()` calls to API Gateway.

---

## Do Not Touch

These resources are live and used by hardware in the field:

| Resource | Why |
|----------|-----|
| `POST /unlock` API Gateway route | NFC hardware calls this on every tag scan |
| `Sentinel_NFC_Unlock` Lambda | Handles the unlock flow end-to-end |
| `Sentinel_Image_Processor` Lambda | Triggered by the NFC event, writes evidence to S3 |

Adding new routes to the same API Gateway is fine. Redeploying the existing stage is fine. Modifying the above resources is not.

---

## Data Contracts

Everything in LISA flows through two DynamoDB tables. Any module that writes correct records to these tables will automatically appear in the dashboard.

### Table: `Shipments`
Partition key: `shipmentId` (String)

```json
{
  "shipmentId":    "SHIP-001",          // unique ID, string
  "status":        "IN_TRANSIT",        // IN_TRANSIT | ALERT | DELIVERED
  "riskLevel":     "LOW",               // LOW | HIGH | CRITICAL
  "temperature":   4.2,                 // number (Celsius)
  "humidity":      65,                  // number (percent)
  "gForce":        0.1,                 // number
  "lockStatus":    "LOCKED",            // LOCKED | UNLOCKED
  "deviceStatus":  "ONLINE",            // ONLINE | OFFLINE
  "latitude":      "1.3521",            // string (GPS decimal degrees)
  "longitude":     "103.8198",          // string (GPS decimal degrees)
  "lastUpdatedAt": "2025-06-05T07:00:00Z"  // ISO 8601 UTC
}
```

**Rules:**
- `riskLevel` and `status` are updated automatically by `lisa-resolve-alert` when all alerts for a shipment are resolved (set to `LOW` / `IN_TRANSIT`)
- `lisa-trigger-alert` sets `status = ALERT` and `riskLevel = <severity>` when a new alert is created
- Any module can write additional fields to a Shipments record  the dashboard will ignore unknown fields unless you add them to the UI
- `latitude` and `longitude` are strings in DynamoDB to match the seed data format  the Leaflet map parses them with `parseFloat`

### Table: `AlertEvents`
Partition key: `alertId` (String)

```json
{
  "alertId":    "ALERT-1749123456789",  // unique ID  use timestamp millis suffix
  "shipmentId": "SHIP-001",            // must match a Shipments record
  "alertType":  "TEMP_HIGH",           // see alert types below
  "severity":   "CRITICAL",            // LOW | HIGH | CRITICAL
  "message":    "Temperature exceeded 8C limit: reading 11.2C",
  "resolved":   false,                 // boolean
  "resolvedBy": null,                  // null | "username" | "discord:username"
  "createdAt":  "2025-06-05T08:00:00Z",
  "resolvedAt": null                   // null | ISO 8601 UTC
}
```

**Defined alert types** (use these strings for consistent UI display):

| `alertType` | Meaning |
|-------------|---------|
| `TEMP_HIGH` | Temperature above threshold |
| `TEMP_LOW` | Temperature below threshold |
| `COLLISION` | G-force impact detected |
| `LOCK_TAMPER` | Lock opened without authorization |
| `HUMIDITY_HIGH` | Humidity out of range |
| `DEVICE_OFFLINE` | Sensor lost connectivity |
| `LOCK_UPDATE` | Special type  updates `lockStatus` only, no alert record created |

You can add new types freely  the dashboard will display any string in the `alertType` field. Add it to this table when you do.

### Table: `NFCDevices`
Partition key: `tagId` (String)

```json
{
  "tagId":       "04:AB:12:CD:34:EF:00",
  "label":       "Driver Device A",
  "status":      "WHITELISTED",          // KNOWN | WHITELISTED
  "firstSeenAt": "2025-06-01T10:00:00Z",
  "lastSeenAt":  "2025-06-05T08:00:00Z",
  "addedBy":     "admin@lisa.demo",       // only present when status = WHITELISTED
  "addedAt":     "2025-06-01T10:05:00Z"   // only present when status = WHITELISTED
}
```

**Rules:**
- One row per physical NFC tag  there is no separate whitelist table
- `lisa-register-nfc-device` (`POST /nfc/devices`) creates the row on first scan (`status = KNOWN`) or refreshes `lastSeenAt`/`label` on repeat scans
- `lisa-update-nfc-whitelist` (`PUT /nfc/devices/{tagId}/whitelist`) flips `status` between `KNOWN` and `WHITELISTED` and sets/clears `addedBy`/`addedAt`
- `lisa-check-nfc-device` (`GET /nfc/check/{tagId}`, unauthenticated) returns `{allowed: true}` only when `status = WHITELISTED`  this is the route hardware/`Sentinel_NFC_Unlock` should call before unlocking
- All four NFC routes (except `check`) require `custom:role = ADMIN`; the dashboard only shows the "NFC Whitelist" nav item to admins, but the Lambdas enforce it independently

---

## How to Trigger an Alert from Any Module

### Option A  Call the API Gateway (recommended for external services)

```bash
curl -X POST https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/demo/trigger-alert \
  -H "Content-Type: application/json" \
  -d '{
    "shipmentId": "SHIP-001",
    "alertType":  "TEMP_HIGH",
    "severity":   "CRITICAL",
    "temperature": 12.5
  }'
```

Response:
```json
{ "alertId": "ALERT-1749123456789", "status": "created" }
```

Side effects (handled automatically by `lisa-trigger-alert` Lambda):
1. Writes a record to `AlertEvents`
2. Updates `Shipments.riskLevel` and `Shipments.status = ALERT`
3. Posts a Discord embed to the webhook channel (if `DISCORD_WEBHOOK_URL` env var is set on the Lambda)

### Option B  Write directly to DynamoDB (for Lambda-to-Lambda or IoT Core rules)

```python
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
now = datetime.now(timezone.utc).isoformat()
alert_id = f"ALERT-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

dynamodb.Table('AlertEvents').put_item(Item={
    'alertId':    alert_id,
    'shipmentId': 'SHIP-001',
    'alertType':  'COLLISION',
    'severity':   'HIGH',
    'message':    'G-force spike: 2.4g detected',
    'resolved':   False,
    'resolvedBy': None,
    'createdAt':  now,
    'resolvedAt': None,
})

dynamodb.Table('Shipments').update_item(
    Key={'shipmentId': 'SHIP-001'},
    UpdateExpression='SET riskLevel = :r, #s = :s, lastUpdatedAt = :t',
    ExpressionAttributeNames={'#s': 'status'},
    ExpressionAttributeValues={':r': 'HIGH', ':s': 'ALERT', ':t': now},
)
```

Note: Option B bypasses the Discord notification. Call the API Gateway instead if you want the Discord alert.

### Option C  Update sensor readings without creating an alert

Use DynamoDB `update_item` directly to push new sensor readings:

```python
dynamodb.Table('Shipments').update_item(
    Key={'shipmentId': 'SHIP-001'},
    UpdateExpression='SET temperature = :t, humidity = :h, gForce = :g, '
                     'latitude = :lat, longitude = :lon, lastUpdatedAt = :ts',
    ExpressionAttributeValues={
        ':t':   4.8,
        ':h':   67,
        ':g':   0.1,
        ':lat': '1.3521',
        ':lon': '103.8198',
        ':ts':  now,
    },
)
```

The dashboard will show updated values on next load / refresh.

---

## Module Integration Points

### NFC Unlock Module (`Sentinel_NFC_Unlock`)

**Current state:** Deployed, handles `POST /unlock`. Result is not yet surfaced in the dashboard.

**To integrate:**
1. After a successful unlock, `Sentinel_NFC_Unlock` should write `lockStatus = UNLOCKED` to `Shipments`:
   ```python
   dynamodb.Table('Shipments').update_item(
       Key={'shipmentId': shipment_id},
       UpdateExpression='SET lockStatus = :l, lastUpdatedAt = :t',
       ExpressionAttributeValues={':l': 'UNLOCKED', ':t': now},
   )
   ```
2. The dashboard Shipment Detail page reads `lockStatus` directly  no frontend change needed.
3. If you want the dashboard Lock/Unlock buttons to call `POST /unlock` instead of the demo trigger, update `doSetLock()` in `index.html`:
   ```javascript
   async function doSetLock(sid, status) {
     if (status === 'UNLOCKED') {
       // Call real NFC endpoint
       await fetch('https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/unlock', {
         method: 'POST',
         headers: { 'Content-Type': 'application/json' },
         body: JSON.stringify({ action: 'unlock', shipmentId: sid }),
       });
     } else {
       await dbSetLock(sid, status);
     }
     renderDetail(sid); renderDashboard();
   }
   ```

### NFC Whitelist Module (new)

**Current state:** 4 Lambdas written (`lambda/register-nfc-device`, `lambda/list-nfc-devices`,
`lambda/update-nfc-whitelist`, `lambda/check-nfc-device`), `NFCDevices` table not yet created.

**To integrate with `Sentinel_NFC_Unlock` (optional, without modifying it):**

`GET /nfc/check/{tagId}` is unauthenticated, like `/unlock`, and is safe to call
from hardware or from `Sentinel_NFC_Unlock` itself before proceeding with an
unlock:

```python
import urllib.request, json

def is_tag_whitelisted(tag_id):
    # HTTP API on $default — no stage prefix in the URL
    url = f"https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/nfc/check/{tag_id}"
    with urllib.request.urlopen(url, timeout=2) as r:
        return json.load(r).get('allowed', False)
```

This is purely additive  `/unlock` itself is untouched, and `Sentinel_NFC_Unlock`
can choose to call `/nfc/check/{tagId}` first and short-circuit if `allowed` is
`false`. If you'd rather not modify `Sentinel_NFC_Unlock` at all, the whitelist
still works as a standalone admin tool (Known Devices / Whitelist management UI).

### Image Processor Module (`Sentinel_Image_Processor`)

**Current state:** Deployed, writes evidence images to S3. Not yet shown in the UI.

**To integrate:** Add an `images` attribute to the `AlertEvents` record containing S3 URLs:
```python
# In Sentinel_Image_Processor, after uploading to S3:
dynamodb.Table('AlertEvents').update_item(
    Key={'alertId': alert_id},
    UpdateExpression='SET images = list_append(if_not_exists(images, :empty), :img)',
    ExpressionAttributeValues={
        ':img':   ['https://your-bucket.s3.amazonaws.com/evidence/SHIP-001/img.jpg'],
        ':empty': [],
    },
)
```

Then in `renderDetail()` in `index.html`, read `latestAlert.images` and render `<img>` tags. The data shape is already designed for this  just needs the UI section added.

### Real IoT Sensor Integration

**Replace demo triggers with real sensor data:**

1. Set up an **IoT Core rule** that matches your sensor MQTT topic:
   ```sql
   SELECT * FROM 'shipment/+/sensors'
   ```
2. Rule action: invoke a Lambda that writes to DynamoDB (Option B or C above)
3. For threshold breaches (temp > 8°C), call the API Gateway trigger endpoint (Option A) so Discord gets notified

**Suggested Lambda for IoT Core → LISA:**
```python
def lambda_handler(event, context):
    shipment_id = event['shipmentId']        # from MQTT payload
    temperature = float(event['temperature'])
    humidity    = float(event['humidity'])
    g_force     = float(event['gForce'])

    # Always update sensor readings
    update_sensor_readings(shipment_id, temperature, humidity, g_force)

    # Trigger alert if threshold breached
    if temperature > 8.0:
        create_alert(shipment_id, 'TEMP_HIGH', 'CRITICAL', temperature)
    elif g_force > 2.0:
        create_alert(shipment_id, 'COLLISION', 'HIGH')
```

### GPS Tracker Integration

The Leaflet map reads `latitude` and `longitude` from each Shipments record. To show live GPS:

1. Send location updates from your GPS device to a Lambda (via IoT Core, HTTP, or SQS)
2. Lambda writes to DynamoDB:
   ```python
   dynamodb.Table('Shipments').update_item(
       Key={'shipmentId': shipment_id},
       UpdateExpression='SET latitude = :lat, longitude = :lon, lastUpdatedAt = :t',
       ExpressionAttributeValues={':lat': str(lat), ':lon': str(lon), ':t': now},
   )
   ```
3. The map page re-plots markers on every `navigate('map')` call  add a 30-second poll in the frontend if you want live updates without navigation.

**Note:** `latitude` and `longitude` are stored as strings in DynamoDB (matching the seed data). Leaflet reads them as `parseFloat(s.latitude)`  keep this format.

---

## Adding a New Lambda Endpoint

1. Create `lambda/your-feature/lambda_function.py` following the existing pattern:
   ```python
   import json, boto3
   dynamodb = boto3.resource('dynamodb')

   def lambda_handler(event, context):
       # your logic
       return {
           'statusCode': 200,
           'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
           'body': json.dumps({'result': '...'}),
       }
   ```
2. Deploy to AWS Console → Lambda (Python 3.12, same IAM role)
3. Add a route in API Gateway → Resources → your resource → method → integration → Lambda
4. Enable CORS on the new resource
5. Deploy the API stage
6. Call it from `index.html` by adding a `fetch()` call to the relevant `render*` or action function

---

## Adding a New Dashboard Page

1. Add the HTML section inside `#app-shell` in `index.html`:
   ```html
   <div id="page-yourpage" class="page-section">
     <div class="page-content">
       <!-- content -->
     </div>
   </div>
   ```
2. Add a nav link in the topbar:
   ```html
   <span class="nav-link" onclick="navigate('yourpage')">Your Page</span>
   ```
3. Add a render call in `navigate()`:
   ```javascript
   if (page === 'yourpage') renderYourPage();
   ```
4. Write `renderYourPage()` in the app script block. Use `dbShipments()` / `dbAlerts()` for data in demo mode, or `fetch(API_BASE + '/your-endpoint')` for production.

---

## Adding a New Sensor Field to the Dashboard

If your module writes a new field to DynamoDB (e.g., `batteryLevel`):

1. Update the seed script to include it:
   ```python
   {'shipmentId': 'SHIP-001', ..., 'batteryLevel': 87}
   ```
2. Add it to `renderDetail()` in `index.html`:
   ```javascript
   const fields = [
     ...
     ['Battery', s.batteryLevel + ' %'],   // add this line
   ];
   ```
3. Optionally add it to the mock data `_db.shipments` array so demo mode shows it
4. No Lambda changes  `list-shipments` and `get-shipment` return all attributes

---

## IAM Permissions Reference

All LISA Lambdas share a single execution role. Required policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
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
      "arn:aws:dynamodb:us-east-1:*:table/DiscordUsers"
    ]
  }]
}
```

Any new Lambda that needs to read/write these tables must use this role or have equivalent permissions attached.

---

## Environment Variables

| Lambda | Variable | Value |
|--------|----------|-------|
| `lisa-trigger-alert` | `DISCORD_WEBHOOK_URL` | Discord channel webhook URL |
| `lisa-discord-commands` | `DISCORD_PUBLIC_KEY` | From Discord Developer Portal |

The `DISCORD_WEBHOOK_URL` in `index.html` (frontend) is separate from the one on the Lambda. Both can be set independently  the frontend sends embeds from the browser, the Lambda sends plain text from the server side.

---

## API Gateway

`d1rocl5xb9` (`Sentinel_NFC_API`) is an **HTTP API (v2)** on the `$default`
stage, which has **no stage prefix** in the URL and **auto-deploys** new
routes immediately:

Base URL: `https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com`

`/unlock` is a **route path**, not a stage  it's reachable at
`.../unlock` (NFC hardware is hardcoded to this exact path, do not rename it).

When adding new routes, just create the route + integration on this same API
 there's no separate "deploy stage" step. The frontend `API_BASE` constant
points to this base URL (no trailing path).

---

## Quick Checklist for New Module Integration

Before calling LISA "integrated", verify:

- [ ] Your module writes valid `shipmentId` values that exist in the `Shipments` table
- [ ] Alert records include all required fields (`alertId`, `shipmentId`, `alertType`, `severity`, `message`, `resolved`, `resolvedBy`, `createdAt`, `resolvedAt`)
- [ ] `resolved` is a **boolean** (`false`), not a string (`"false"`)  DynamoDB filter expressions are type-sensitive
- [ ] `severity` is one of `LOW`, `HIGH`, `CRITICAL`  the dashboard badge colors depend on exact case
- [ ] `lastUpdatedAt` is ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`)  the frontend parses it with `new Date()`
- [ ] Your Lambda has CORS headers on all responses: `'Access-Control-Allow-Origin': '*'`
- [ ] New routes are covered by the API-level CORS config (HTTP API  Develop → CORS), not a per-resource setting
- [ ] The existing `POST /unlock` route is untouched
