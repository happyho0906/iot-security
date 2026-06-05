# LISA — AWS Architecture & Integration Plan

## 1. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  BROWSER  (index.html — single file, no build step)                     │
│                                                                         │
│   Login ──► Amazon Cognito User Pool ──► JWT token                      │
│                                                ▼                        │
│   Dashboard / Alerts / Map / Detail           API calls with            │
│   (demo mode: _db in-memory)                  Authorization header      │
│                                                                         │
│   Discord embed ──────────────────────────────────────► Discord Webhook │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTPS + Cognito JWT
                                ▼
┌───────────────────────────────────────────────────────┐
│  Amazon API Gateway  (REST, us-east-1, d1rocl5xb9)   │
│                                                       │
│  Cognito Authorizer on all routes except:             │
│    POST /unlock  (NFC hardware — no auth, existing)   │
│    POST /discord/commands  (Ed25519 signed by Discord) │
└───────────┬───────────────────────────────────────────┘
            │
     ┌──────┴──────────────────────────────────────┐
     │                Lambda Functions              │
     │                                             │
     │  lisa-list-shipments    GET  /shipments      │
     │  lisa-get-shipment      GET  /shipments/{id} │
     │  lisa-list-alerts       GET  /alerts         │
     │  lisa-trigger-alert     POST /demo/trigger   │──► Discord Webhook
     │  lisa-resolve-alert     POST /alerts/.../    │
     │  lisa-discord-commands  POST /discord/cmds   │
     │  lisa-get-me            GET  /me             │  ← new
     │  lisa-shadow-processor  (IoT Rule trigger)   │  ← new
     └──────────────────────┬──────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              │        DynamoDB             │
              │  Shipments                  │
              │  AlertEvents                │
              │  DiscordUsers               │
              │  Users  ← new               │
              └─────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Raspberry Pi  (one per shipment)                                       │
│                                                                         │
│  Sensors: DHT22 (temp/humidity) · MPU-6050 (G-force) · GPS · NFC       │
│                                                                         │
│  Python agent ──MQTT──► AWS IoT Core                                    │
│     $aws/things/shipment-SHIP-001/shadow/update                         │
│           │                                                             │
│           ▼                                                             │
│     Device Shadow  (reported state persists offline)                    │
│           │                                                             │
│     IoT Rule: $aws/things/+/shadow/update/accepted                      │
│           │                                                             │
│           ▼                                                             │
│     lisa-shadow-processor Lambda                                        │
│       • Updates Shipments (temp, humidity, gForce, lat, lon, battery)  │
│       • Checks thresholds → creates AlertEvents + Discord alert         │
│       • Sets deviceStatus = ONLINE / OFFLINE                            │
│                                                                         │
│  Shadow desired.lockStatus ◄── lisa-trigger-alert (LOCK_UPDATE)        │
│  Pi listens for shadow delta → actuates physical lock                   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Discord                                                                │
│   Slash commands ──► API Gateway /discord/commands                      │
│                      ──► lisa-discord-commands Lambda                   │
│                          (Ed25519 signature verification)               │
│   Webhook embeds ◄── Browser fetch() on alert trigger                  │
│   Webhook text  ◄── lisa-trigger-alert Lambda on IoT alert             │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Existing — DO NOT MODIFY                                               │
│   POST /unlock ──► Sentinel_NFC_Unlock ──► Sentinel_Image_Processor     │
│   (NFC hardware is hardcoded to this endpoint and stage name)           │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Future Extensions  (API paths reserved; Lambdas not yet created)       │
│                                                                         │
│  POST /ai/query          → lisa-ai-agent         (Bedrock Claude)       │
│  GET  /shipments/{id}/anomalies → lisa-anomaly-detector                 │
│  GET  /shipments/{id}/route     → lisa-route-optimizer                  │
│  GET  /alerts/{id}/evidence     → lisa-image-evidence (S3 presigned)   │
│  POST /cold-chain/alert  → lisa-cold-chain-monitor                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Cognito Integration Plan

### Goal

Replace `DEMO_ACCOUNTS` + `sessionStorage` with Amazon Cognito, changing only the three auth functions (`handleLogin`, `handleLogout`, `checkSession`). All render functions and role-gated UI are untouched.

**Demo stability first:** If `COGNITO_USER_POOL_ID` is not set in `window.LISA_CONFIG`, the system falls back to `DEMO_ACCOUNTS` automatically. Demo mode always works.

### 2.1 Cognito User Pool Setup (AWS Console)

1. **Cognito → Create user pool**
   - Sign-in identifier: Email
   - Password policy: Cognito defaults
   - MFA: Off
   - Self-registration: On (for team onboarding) or Off (admin-only creation)
   - App type: **Public client** — no client secret
   - App client name: `lisa-web-client`
   - OAuth flows: **Implicit grant** (required for CDN library)
   - Scopes: `openid email profile`
   - Callback URL: `http://localhost:8080` (add production URL later)

2. **Add custom attribute:** `custom:role` (String, mutable)
   - Values: `ADMIN` | `DRIVER` | `CUSTOMER`

3. **Create demo users** (AWS CLI — run once):
   ```bash
   POOL=us-east-1_XXXXXXX   # your pool ID

   aws cognito-idp admin-create-user \
     --user-pool-id $POOL \
     --username admin@lisa.demo \
     --user-attributes Name=email,Value=admin@lisa.demo \
                       Name=email_verified,Value=true \
                       Name=custom:role,Value=ADMIN \
     --temporary-password "Lisa@2025!"

   aws cognito-idp admin-create-user \
     --user-pool-id $POOL \
     --username driver@lisa.demo \
     --user-attributes Name=email,Value=driver@lisa.demo \
                       Name=email_verified,Value=true \
                       Name=custom:role,Value=DRIVER \
     --temporary-password "Lisa@2025!"

   aws cognito-idp admin-create-user \
     --user-pool-id $POOL \
     --username customer@lisa.demo \
     --user-attributes Name=email,Value=customer@lisa.demo \
                       Name=email_verified,Value=true \
                       Name=custom:role,Value=CUSTOMER \
     --temporary-password "Lisa@2025!"
   ```

4. **Note credentials** — add to `config.local.js` (gitignored):
   ```javascript
   window.LISA_CONFIG = {
     DISCORD_WEBHOOK_URL: "...",
     COGNITO_USER_POOL_ID: "us-east-1_XXXXXXX",
     COGNITO_CLIENT_ID:    "XXXXXXXXXXXXXXXXXXXXXXXXX",
   };
   ```

### 2.2 Frontend Changes

**Only these sections of `index.html` change:**

**Add to `<head>` (after config.local.js loader):**
```html
<script src="https://cdn.jsdelivr.net/npm/amazon-cognito-identity-js/dist/amazon-cognito-identity.min.js"></script>
```

**Replace the three auth functions (~lines 1020–1078):**
```javascript
// ── AUTH ─────────────────────────────────────────────────────────────────
const _cognitoConfig = {
  userPoolId: (window.LISA_CONFIG || {}).COGNITO_USER_POOL_ID || "",
  clientId:   (window.LISA_CONFIG || {}).COGNITO_CLIENT_ID    || "",
};
const _useCognito = !!(_cognitoConfig.userPoolId && _cognitoConfig.clientId);
let _cognitoUser = null;
let _cognitoUserPool = _useCognito
  ? new AmazonCognitoIdentity.CognitoUserPool({
      UserPoolId: _cognitoConfig.userPoolId,
      ClientId:   _cognitoConfig.clientId,
    })
  : null;

function showApp(email, role) {
  _currentRole = role;
  document.getElementById("page-login").style.display    = "none";
  document.getElementById("app-shell").style.display     = "block";
  document.getElementById("nav-user-label").textContent  = email;
  sessionStorage.setItem("lisa_email", email);
  sessionStorage.setItem("lisa_role",  role);
  const badge = document.getElementById("nav-role-badge");
  badge.textContent   = role;
  badge.style.color   = role === "ADMIN" ? "var(--blue)"
                      : role === "DRIVER" ? "var(--green)"
                      : "var(--muted)";
  initApp();
}

function checkSession() {
  // 1. Try Cognito session
  if (_useCognito) {
    const user = _cognitoUserPool.getCurrentUser();
    if (user) {
      user.getSession((err, session) => {
        if (!err && session && session.isValid()) {
          _cognitoUser = user;
          const payload = JSON.parse(atob(session.getIdToken().getJwtToken().split(".")[1]));
          showApp(payload.email, payload["custom:role"] || "CUSTOMER");
          return;
        }
        showLogin();
      });
      return;
    }
  }
  // 2. Fall back to demo session
  const email = sessionStorage.getItem("lisa_email");
  const role  = sessionStorage.getItem("lisa_role");
  if (email && role && DEMO_ACCOUNTS[email]) { showApp(email, role); return; }
  showLogin();
}

function handleLogin() {
  const email    = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const errEl    = document.getElementById("login-error");
  errEl.style.display = "none";

  // Cognito path
  if (_useCognito) {
    const details  = new AmazonCognitoIdentity.AuthenticationDetails({ Username: email, Password: password });
    const cogUser  = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: _cognitoUserPool });
    _cognitoUser = cogUser;
    cogUser.authenticateUser(details, {
      onSuccess(session) {
        const payload = JSON.parse(atob(session.getIdToken().getJwtToken().split(".")[1]));
        showApp(payload.email, payload["custom:role"] || "CUSTOMER");
      },
      onFailure(err) {
        errEl.textContent = err.message || "Login failed";
        errEl.style.display = "block";
      },
      newPasswordRequired() {
        // Show new-password section — handled by existing HTML element
        document.getElementById("new-password-section").style.display = "flex";
      },
    });
    return;
  }

  // Demo path (fallback)
  const account = DEMO_ACCOUNTS[email];
  if (!account || account.password !== password) {
    errEl.textContent = "Invalid email or password.";
    errEl.style.display = "block";
    return;
  }
  showApp(email, account.role);
}

function handleNewPassword() {
  const newPw = document.getElementById("new-password").value;
  _cognitoUser.completeNewPasswordChallenge(newPw, {}, {
    onSuccess(session) {
      const payload = JSON.parse(atob(session.getIdToken().getJwtToken().split(".")[1]));
      showApp(payload.email, payload["custom:role"] || "CUSTOMER");
    },
    onFailure(err) {
      document.getElementById("login-error").textContent = err.message;
      document.getElementById("login-error").style.display = "block";
    },
  });
}

function handleLogout() {
  if (_cognitoUser) { _cognitoUser.signOut(); _cognitoUser = null; }
  _currentRole = null;
  sessionStorage.clear();
  showLogin();
}
```

**Add "new password" section to the login card HTML** (after the Sign In button):
```html
<div id="new-password-section" style="display:none; flex-direction:column; gap:10px; margin-top:12px;">
  <div style="color:var(--amber); font-size:12px; font-weight:600;">New password required on first login</div>
  <input id="new-password" type="password" placeholder="Set new password"
    class="login-input" />
  <button onclick="handleNewPassword()" class="btn btn-primary btn-full">Set Password</button>
</div>
```

**Add Cognito JWT to API calls** (in production mode — when API_BASE is set):
```javascript
async function getAuthHeader() {
  if (!_useCognito || !_cognitoUser) return {};
  return new Promise((resolve) => {
    _cognitoUser.getSession((err, session) => {
      if (err || !session) { resolve({}); return; }
      resolve({ Authorization: session.getIdToken().getJwtToken() });
    });
  });
}
```
Then all `fetch()` calls in production mode use:
```javascript
const headers = { "Content-Type": "application/json", ...(await getAuthHeader()) };
```

### 2.3 API Gateway Cognito Authorizer

After deploying Cognito:

1. API Gateway → Authorizers → Create new authorizer
   - Type: Cognito
   - User Pool: `lisa-users`
   - Token source: `Authorization` header
   - Name: `lisa-cognito-auth`

2. Apply to all routes **except**:
   - `POST /unlock` — NFC hardware (no auth)
   - `POST /discord/commands` — Ed25519 signed by Discord, not Cognito

3. `lisa-get-me` Lambda reads identity from the request context:
   ```python
   def lambda_handler(event, context):
       claims = event['requestContext']['authorizer']['claims']
       return {
           'statusCode': 200,
           'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
           'body': json.dumps({
               'email': claims['email'],
               'role':  claims.get('custom:role', 'CUSTOMER'),
               'sub':   claims['sub'],
           }),
       }
   ```

### 2.4 What Does NOT Change

- Login card HTML (same structure, same CSS classes)
- `_currentRole` variable and all role-gated UI checks (`_currentRole === "ADMIN"`)
- All `renderDashboard`, `renderAlerts`, `renderDetail`, `renderMap` functions
- `DEMO_ACCOUNTS` constant (kept as fallback — demo mode still works without Cognito config)
- All `db*` mock functions

---

## 3. IoT Core Device Shadow Integration Plan

### 3.1 Concept

Each Raspberry Pi is an **IoT Thing** named `shipment-SHIP-001` (matching the shipmentId with prefix). The Pi reports sensor readings to its Device Shadow every 30 seconds. A Lambda triggered by an IoT Rule processes the update, writes to DynamoDB, and fires alerts on threshold breach.

The shadow also carries the lock command in the `desired` state — the Pi listens for the delta and physically actuates the lock.

### 3.2 AWS IoT Setup (Console)

1. **IoT Core → Manage → Things → Create thing**
   - Name: `shipment-SHIP-001` (repeat for each Pi)
   - Create a certificate (download `.pem`, `.key`, root CA)
   - Attach policy `lisa-iot-policy`:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Action": ["iot:Connect"],
           "Resource": "arn:aws:iot:us-east-1:*:client/shipment-*"
         },
         {
           "Effect": "Allow",
           "Action": ["iot:Publish", "iot:Subscribe", "iot:Receive"],
           "Resource": [
             "arn:aws:iot:us-east-1:*:topic/$aws/things/shipment-*/shadow/*",
             "arn:aws:iot:us-east-1:*:topicfilter/$aws/things/shipment-*/shadow/*"
           ]
         }
       ]
     }
     ```

2. **IoT Core → Message routing → Rules → Create rule**
   - Name: `lisa_shadow_update`
   - SQL:
     ```sql
     SELECT topic(3) as thingName,
            state.reported.temperature  as temperature,
            state.reported.humidity     as humidity,
            state.reported.gForce       as gForce,
            state.reported.latitude     as latitude,
            state.reported.longitude    as longitude,
            state.reported.batteryLevel as batteryLevel,
            state.reported.online       as online,
            timestamp() as eventTime
     FROM '$aws/things/+/shadow/update/accepted'
     WHERE state.reported IS NOT NULL
     ```
   - Action: Lambda → `lisa-shadow-processor`

### 3.3 New Lambda: `lisa-shadow-processor`

**File:** `lambda/shadow-processor/lambda_function.py`

```python
import json, boto3, urllib.request, os
from datetime import datetime, timezone

dynamodb  = boto3.resource('dynamodb', region_name='us-east-1')
iot_data  = boto3.client('iot-data', region_name='us-east-1')

TEMP_HIGH_C  = 8.0    # °C — cold chain threshold
GFORCE_HIGH  = 2.0    # g  — collision threshold

def lambda_handler(event, context):
    thing_name   = event.get('thingName', '')
    # thingName format: "shipment-SHIP-001" → shipmentId = "SHIP-001"
    if not thing_name.startswith('shipment-'):
        return
    shipment_id  = thing_name[len('shipment-'):]

    temperature  = event.get('temperature')
    humidity     = event.get('humidity')
    g_force      = event.get('gForce')
    latitude     = event.get('latitude')
    longitude    = event.get('longitude')
    battery      = event.get('batteryLevel')
    online       = event.get('online', True)
    now          = datetime.now(timezone.utc).isoformat()

    # 1. Update Shipments with latest sensor readings
    expr_parts   = []
    expr_vals    = {':t': now, ':ds': 'ONLINE' if online else 'OFFLINE'}
    expr_parts   = ['lastUpdatedAt = :t', 'deviceStatus = :ds']

    if temperature  is not None: expr_parts.append('temperature = :temp');  expr_vals[':temp']  = str(round(float(temperature), 2))
    if humidity     is not None: expr_parts.append('humidity = :hum');      expr_vals[':hum']   = str(round(float(humidity), 1))
    if g_force      is not None: expr_parts.append('gForce = :gf');         expr_vals[':gf']    = str(round(float(g_force), 3))
    if latitude     is not None: expr_parts.append('latitude = :lat');      expr_vals[':lat']   = str(latitude)
    if longitude    is not None: expr_parts.append('longitude = :lon');     expr_vals[':lon']   = str(longitude)
    if battery      is not None: expr_parts.append('batteryLevel = :bat');  expr_vals[':bat']   = int(battery)

    dynamodb.Table('Shipments').update_item(
        Key={'shipmentId': shipment_id},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeValues=expr_vals,
    )

    # 2. Threshold checks → create alert if breached
    if temperature is not None and float(temperature) > TEMP_HIGH_C:
        _create_alert(shipment_id, 'TEMP_HIGH', 'CRITICAL',
                      f'Temperature exceeded {TEMP_HIGH_C}C limit: reading {temperature}C',
                      source='iot', now=now)

    if g_force is not None and float(g_force) > GFORCE_HIGH:
        _create_alert(shipment_id, 'COLLISION', 'HIGH',
                      f'G-force spike: {g_force}g detected',
                      source='iot', now=now)

    if not online:
        _create_alert(shipment_id, 'DEVICE_OFFLINE', 'HIGH',
                      f'Device went offline: {thing_name}',
                      source='iot', now=now)

def _create_alert(shipment_id, alert_type, severity, message, source='iot', now=None):
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    alert_id = f"ALERT-{int(datetime.now(timezone.utc).timestamp() * 1000)}"

    dynamodb.Table('AlertEvents').put_item(Item={
        'alertId':    alert_id,
        'shipmentId': shipment_id,
        'alertType':  alert_type,
        'severity':   severity,
        'message':    message,
        'source':     source,
        'resolved':   False,
        'resolvedBy': None,
        'createdAt':  now,
        'resolvedAt': None,
    })

    dynamodb.Table('Shipments').update_item(
        Key={'shipmentId': shipment_id},
        UpdateExpression='SET riskLevel = :r, #s = :s, lastUpdatedAt = :t',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':r': severity, ':s': 'ALERT', ':t': now},
    )

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
    if webhook_url:
        msg = {'content': (
            f"**IoT Alert — {alert_type}**\n"
            f"Shipment: **{shipment_id}**  Severity: **{severity}**\n"
            f"{message}\n"
            f"Use `/status {shipment_id}` or `/resolve {alert_id}` to respond."
        )}
        req = urllib.request.Request(webhook_url,
            data=json.dumps(msg).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        try: urllib.request.urlopen(req, timeout=5)
        except Exception as e: print(f"Discord error: {e}")
```

**IAM for `lisa-shadow-processor`:**
```json
{
  "Action": [
    "dynamodb:UpdateItem",
    "dynamodb:PutItem",
    "iot:UpdateThingShadow"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:*:table/Shipments",
    "arn:aws:dynamodb:us-east-1:*:table/AlertEvents",
    "arn:aws:iot:us-east-1:*:thing/shipment-*"
  ]
}
```

**Environment variable:** `DISCORD_WEBHOOK_URL`

### 3.4 Lock Actuation via Shadow

**When dashboard triggers Lock/Unlock**, `lisa-trigger-alert` (LOCK_UPDATE path) must also push to the shadow's `desired` state. Add to the LOCK_UPDATE branch in `lambda/trigger-alert/lambda_function.py`:

```python
# After updating DynamoDB, push desired lock state to shadow
iot_data = boto3.client('iot-data', region_name='us-east-1')
thing_name = f'shipment-{shipment_id}'
shadow_payload = json.dumps({
    'state': {'desired': {'lockStatus': lock_status}}
})
try:
    iot_data.update_thing_shadow(
        thingName=thing_name,
        payload=shadow_payload.encode()
    )
except Exception as e:
    print(f'Shadow update error: {e}')  # non-fatal — DynamoDB already updated
```

### 3.5 Raspberry Pi Client Script

**File:** `pi/sensor_agent.py` (new file — runs on Pi)

```python
import json, time, math
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient

# ── Config ──────────────────────────────────────────────────────────────
THING_NAME   = "shipment-SHIP-001"   # change per device
ENDPOINT     = "xxxxx.iot.us-east-1.amazonaws.com"
CERT_PATH    = "certs/device.pem.crt"
KEY_PATH     = "certs/private.pem.key"
CA_PATH      = "certs/root-CA.crt"
INTERVAL_S   = 30

# ── Shadow client setup ──────────────────────────────────────────────────
shadow_client = AWSIoTMQTTShadowClient(THING_NAME)
shadow_client.configureEndpoint(ENDPOINT, 8883)
shadow_client.configureCredentials(CA_PATH, KEY_PATH, CERT_PATH)
shadow_client.connect()
device_shadow = shadow_client.createShadowHandlerWithName(THING_NAME, True)

def read_sensors():
    """Replace with real sensor reads: DHT22, MPU-6050, GPS."""
    import random
    return {
        "temperature":  round(4.0 + random.uniform(-0.5, 8.5), 2),
        "humidity":     round(65 + random.uniform(-5, 5), 1),
        "gForce":       round(abs(random.gauss(0.1, 0.05)), 3),
        "latitude":     1.3521 + random.uniform(-0.01, 0.01),
        "longitude":    103.8198 + random.uniform(-0.01, 0.01),
        "batteryLevel": 87,
        "online":       True,
    }

def on_shadow_delta(payload, responseStatus, token):
    """Handle lock commands from the dashboard."""
    delta = json.loads(payload).get("state", {})
    if "lockStatus" in delta:
        desired = delta["lockStatus"]
        print(f"Lock command received: {desired}")
        # TODO: actuate physical lock via GPIO
        # After actuating, confirm in reported state:
        device_shadow.shadowUpdate(
            json.dumps({"state": {"reported": {"lockStatus": desired}}}),
            None, 5
        )

device_shadow.shadowRegisterDeltaCallback(on_shadow_delta)

while True:
    readings = read_sensors()
    payload  = json.dumps({"state": {"reported": readings}})
    device_shadow.shadowUpdate(payload, None, 5)
    print(f"Shadow updated: {readings}")
    time.sleep(INTERVAL_S)
```

**Pi dependencies:**
```
AWSIoTPythonSDK
Adafruit-DHT        # for DHT22
smbus2              # for MPU-6050 I²C
gpsd-py3            # for GPS
```

---

## 4. DynamoDB Schema Updates

### Table: `Shipments`  (PK: `shipmentId`)

| Field | Type | Status | Notes |
|-------|------|--------|-------|
| `shipmentId` | S | Existing | Primary key |
| `status` | S | Existing | IN_TRANSIT \| ALERT \| DELIVERED |
| `riskLevel` | S | Existing | LOW \| HIGH \| CRITICAL |
| `temperature` | S | Existing | Stored as String (matches seed format) |
| `humidity` | S | Existing | Stored as String |
| `gForce` | S | Existing | Stored as String |
| `lockStatus` | S | Existing | LOCKED \| UNLOCKED |
| `deviceStatus` | S | Existing | ONLINE \| OFFLINE |
| `latitude` | S | Existing | String — Leaflet parses with parseFloat |
| `longitude` | S | Existing | String |
| `lastUpdatedAt` | S | Existing | ISO 8601 UTC |
| `thingName` | S | **New** | IoT Thing name, e.g. `shipment-SHIP-001` |
| `batteryLevel` | N | **New** | 0–100 percent, written by shadow-processor |
| `shadowVersion` | N | **New** | IoT shadow version — for deduplication |
| `assignedTo` | S | **New** | Cognito sub of assigned driver (nullable) |
| `customerId` | S | **New** | Customer identifier for role-based filtering |

### Table: `AlertEvents`  (PK: `alertId`)

| Field | Type | Status | Notes |
|-------|------|--------|-------|
| `alertId` | S | Existing | |
| `shipmentId` | S | Existing | |
| `alertType` | S | Existing | TEMP_HIGH \| COLLISION \| LOCK_TAMPER \| … |
| `severity` | S | Existing | LOW \| HIGH \| CRITICAL |
| `message` | S | Existing | |
| `resolved` | BOOL | Existing | |
| `resolvedBy` | S | Existing | username or `discord:username` |
| `createdAt` | S | Existing | |
| `resolvedAt` | S | Existing | |
| `source` | S | **New** | `manual` \| `iot` \| `discord` \| `api` |
| `acknowledgedBy` | S | **New** | Optional: acknowledge before resolve |
| `images` | L | **New** | List of S3 URLs from Sentinel_Image_Processor |

### Table: `Users`  (NEW — PK: `userId`)

| Field | Type | Notes |
|-------|------|-------|
| `userId` | S | Cognito sub (UUID) |
| `email` | S | From Cognito |
| `role` | S | ADMIN \| DRIVER \| CUSTOMER |
| `assignedShipments` | L | List of shipmentId Strings (for driver/customer) |
| `createdAt` | S | ISO 8601 UTC |

> The `DiscordUsers` table (existing) is unchanged.

### Seed script update

Add to `scripts/seed_dynamodb.py` — call after existing seed logic:
```python
users = dynamodb.Table('Users')
for u in [
    {'userId': 'demo-admin',    'email': 'admin@lisa.demo',    'role': 'ADMIN',    'assignedShipments': [], 'createdAt': now},
    {'userId': 'demo-driver',   'email': 'driver@lisa.demo',   'role': 'DRIVER',   'assignedShipments': ['SHIP-001', 'SHIP-002'], 'createdAt': now},
    {'userId': 'demo-customer', 'email': 'customer@lisa.demo', 'role': 'CUSTOMER', 'assignedShipments': ['SHIP-001'], 'createdAt': now},
]:
    users.put_item(Item=u)

# Add new fields to existing shipments
for sid, thing in [('SHIP-001','shipment-SHIP-001'), ('SHIP-002','shipment-SHIP-002'), ('SHIP-003','shipment-SHIP-003')]:
    dynamodb.Table('Shipments').update_item(
        Key={'shipmentId': sid},
        UpdateExpression='SET thingName = :t, batteryLevel = :b',
        ExpressionAttributeValues={':t': thing, ':b': 87},
    )
```

---

## 5. API Routes

### Complete Route Table

| Method | Path | Lambda | Auth | Status |
|--------|------|--------|------|--------|
| POST | `/unlock` | Sentinel_NFC_Unlock | None | **Existing — do not touch** |
| GET | `/shipments` | lisa-list-shipments | Cognito | Deploy |
| GET | `/shipments/{id}` | lisa-get-shipment | Cognito | Deploy |
| GET | `/alerts` | lisa-list-alerts | Cognito | Deploy |
| POST | `/demo/trigger-alert` | lisa-trigger-alert | Cognito | Deploy |
| POST | `/alerts/{alertId}/resolve` | lisa-resolve-alert | Cognito | Deploy |
| POST | `/discord/commands` | lisa-discord-commands | Ed25519 (no Cognito) | Deploy |
| GET | `/me` | lisa-get-me | Cognito | **New** |
| — | IoT Rule trigger | lisa-shadow-processor | IoT (not API GW) | **New** |

### Reserved for Future Extensions (create resource paths now, no Lambda yet)

| Method | Path | Future Lambda | Notes |
|--------|------|---------------|-------|
| POST | `/ai/query` | lisa-ai-agent | Bedrock Claude — natural language queries |
| GET | `/shipments/{id}/anomalies` | lisa-anomaly-detector | SageMaker or rule-based |
| GET | `/shipments/{id}/route` | lisa-route-optimizer | Google Maps Directions or OSRM |
| GET | `/alerts/{alertId}/evidence` | lisa-image-evidence | S3 presigned URLs from Sentinel_Image_Processor |
| POST | `/cold-chain/configure` | lisa-cold-chain-monitor | Per-shipment threshold config |

**How to reserve paths:** Create the resource in API Gateway now with a `POST /ai/query` mock integration returning `{"status":"not_implemented","message":"Coming soon"}`. This lets you wire Lambdas later without touching CORS or redeploying routes.

### `lisa-list-shipments` — role-based filtering update

When Cognito is active, filter by role using the JWT claim:
```python
claims = (event.get('requestContext') or {}).get('authorizer', {}).get('claims', {})
role   = claims.get('custom:role', 'ADMIN')
sub    = claims.get('sub', '')

if role == 'ADMIN':
    items = table.scan().get('Items', [])
else:
    # Driver/customer: return only their assigned shipments
    user_item = dynamodb.Table('Users').get_item(Key={'userId': sub}).get('Item')
    assigned  = (user_item or {}).get('assignedShipments', [])
    items = [dynamodb.Table('Shipments').get_item(Key={'shipmentId': s}).get('Item')
             for s in assigned if s]
    items = [i for i in items if i]
```

---

## 6. Migration Plan: Demo → AWS Production

### Phase 0 — Current state (done)
- `index.html` runs in demo mode (no AWS needed) ✓
- `config.local.js` holds secrets locally ✓
- Git history scrubbed of webhook URL ✓
- 6 Lambda files written ✓

---

### Phase 1 — Backend infrastructure  (~2 hours)

**Goal:** API endpoints live and returning real data.

1. Create DynamoDB tables: `Shipments`, `AlertEvents`, `DiscordUsers`, `Users`
2. Run `python scripts/seed_dynamodb.py`
3. Deploy 6 existing Lambda functions (Python 3.12, same IAM role)
4. Upload `lambda/discord-commands/discord-commands.zip` (pre-built, 924 KB)
5. Add API Gateway routes (see Section 5), enable CORS on each, deploy stage
6. Verify:
   ```bash
   BASE=https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/unlock
   curl $BASE/shipments         # → 3 items
   curl "$BASE/alerts?resolved=false"  # → 1 item
   ```

**Frontend still runs in demo mode** — no change to `index.html` yet.

---

### Phase 2 — Cognito auth  (~1.5 hours)

**Goal:** Real login replacing DEMO_ACCOUNTS, with demo fallback preserved.

1. Create Cognito User Pool (Section 2.1)
2. Add demo users via CLI (Section 2.1 step 3)
3. Add `COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_ID` to `config.local.js`
4. Apply frontend auth changes (Section 2.2) — only 3 functions + `<script>` tag
5. Add Cognito Authorizer to API Gateway (Section 2.3)
6. Deploy new `lisa-get-me` Lambda

**Verify:**
- Login with `admin@lisa.demo` / `Lisa@2025!` → prompted for new password → dashboard loads
- DEMO_ACCOUNTS still works if Cognito config is absent

---

### Phase 3 — Production API mode  (~30 minutes)

**Goal:** Dashboard fetches live data from DynamoDB instead of `_db`.

In `index.html`:

1. Uncomment and set `API_BASE`:
   ```javascript
   const API_BASE = 'https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/unlock';
   ```

2. Replace `db*` functions with `fetch()` calls:
   ```javascript
   async function dbShipments() {
     const h = await getAuthHeader();
     return fetch(API_BASE + '/shipments', { headers: h }).then(r => r.json());
   }
   async function dbShipment(id) {
     const h = await getAuthHeader();
     return fetch(API_BASE + '/shipments/' + id, { headers: h }).then(r => r.json());
   }
   async function dbAlerts() {
     const h = await getAuthHeader();
     return fetch(API_BASE + '/alerts', { headers: h }).then(r => r.json());
   }
   async function dbResolveAlert(alertId, resolvedBy) {
     const h = await getAuthHeader();
     await fetch(API_BASE + '/alerts/' + alertId + '/resolve', {
       method: 'POST', headers: { 'Content-Type': 'application/json', ...h },
       body: JSON.stringify({ resolvedBy }),
     });
   }
   async function dbTriggerAlert(shipmentId, alertType, severity, temperature) {
     const h = await getAuthHeader();
     const res = await fetch(API_BASE + '/demo/trigger-alert', {
       method: 'POST', headers: { 'Content-Type': 'application/json', ...h },
       body: JSON.stringify({ shipmentId, alertType, severity, temperature }),
     });
     const data = await res.json();
     return data.alertId;
   }
   async function dbSetLock(shipmentId, lockStatus) {
     const h = await getAuthHeader();
     await fetch(API_BASE + '/demo/trigger-alert', {
       method: 'POST', headers: { 'Content-Type': 'application/json', ...h },
       body: JSON.stringify({ shipmentId, alertType: 'LOCK_UPDATE', lockStatus }),
     });
   }
   ```

3. Make render functions `async` and add `await`:
   - `renderDashboard`, `renderAlerts`, `renderDetail`, `renderMap` each need `await` before `dbShipments()` etc.

4. Re-seed DynamoDB after testing: `python scripts/seed_dynamodb.py`

---

### Phase 4 — IoT Core  (~2 hours per Pi)

**Goal:** Live sensor data from Raspberry Pi updates the dashboard without manual triggers.

1. Create IoT Things (one per Pi, Section 3.2)
2. Download certificates → copy to Pi `certs/` folder
3. Create IoT Rule `lisa_shadow_update` (Section 3.2 step 2)
4. Deploy `lisa-shadow-processor` Lambda (Section 3.3)
5. Update `lisa-trigger-alert` to push lock state to shadow (Section 3.4)
6. Install Pi dependencies and run `pi/sensor_agent.py` (Section 3.5)
7. Add `thingName` to each Shipments record in DynamoDB (seed script update, Section 4)

**Verify:**
- Pi script runs → DynamoDB Shipments updates every 30 seconds
- Dashboard shows live temperature from Pi
- Simulate temp > 8°C in Pi script → alert appears in LISA within 60 seconds
- Dashboard Lock button → Pi console logs lock command within 5 seconds

---

### Phase 5 — Future extensions (when ready)

The following require no architecture changes — just new Lambdas + API Gateway routes:

| Extension | Trigger | Lambda input | DynamoDB write |
|-----------|---------|-------------|----------------|
| AI Agent | POST /ai/query | User's natural-language question + shipment context | None (reads only) |
| Anomaly Detection | IoT Rule or scheduled | Shadow readings + history | AlertEvents |
| Route Optimization | GET /shipments/{id}/route | Shipment origin/dest + current lat/lon | None (computes on demand) |
| Image Evidence | S3 event from Sentinel_Image_Processor | S3 key, alertId | AlertEvents.images list |
| Cold-Chain Monitor | IoT Rule | Shadow temperature over time | AlertEvents |

---

## Summary Checklist

### Required for AWS compliance
- [ ] Cognito User Pool created with `custom:role` attribute
- [ ] Demo users seeded (admin / driver / customer)
- [ ] `amazon-cognito-identity-js` CDN added to `index.html`
- [ ] `handleLogin`, `handleLogout`, `checkSession` replaced (demo fallback retained)
- [ ] Cognito Authorizer on API Gateway (except /unlock and /discord/commands)
- [ ] `lisa-get-me` Lambda deployed
- [ ] IoT Things created for each Pi
- [ ] `lisa-shadow-processor` Lambda deployed and wired to IoT Rule
- [ ] Pi `sensor_agent.py` running on each device
- [ ] `lisa-trigger-alert` LOCK_UPDATE pushes to Device Shadow
- [ ] All 6 original Lambdas deployed (Phase 1)
- [ ] Frontend switched to `API_BASE` production mode (Phase 3)

### Existing resources — unchanged
- [ ] `POST /unlock` API Gateway route (NFC hardware)
- [ ] `Sentinel_NFC_Unlock` Lambda
- [ ] `Sentinel_Image_Processor` Lambda
- [ ] Discord webhook URL in `config.local.js` only (never committed)
