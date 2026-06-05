# LISA — Logistics Intelligence & Sentinel Assistant

A self-contained logistics monitoring platform with real-time shipment tracking, alert management, Discord bot integration, and a role-based web dashboard. Runs entirely in the browser in demo mode with no backend required. Designed to connect to AWS (DynamoDB + Lambda + API Gateway) when deployed.

---

## Quick Start (Demo Mode — no AWS needed)

```bash
git clone https://github.com/happyho0906/iot-security.git
cd iot-security
python3 -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080) and sign in with one of the built-in demo accounts:

| Role | Email | Password | Access |
|------|-------|----------|--------|
| Admin | admin@lisa.demo | admin123 | Full — trigger alerts, resolve, lock/unlock |
| Driver | driver@lisa.demo | driver123 | View only |
| Customer | customer@lisa.demo | customer123 | View only |

No AWS credentials, no API keys, no dependencies to install.

---

## What It Does

**Dashboard** — live stat cards (active shipments, alerts, critical count, offline devices), recent alerts panel, Discord status panel, full shipment table with status badges.

**Alert Center** — filterable table of all alerts (active / resolved / all) with one-click resolve for admins.

**Shipment Detail** — per-shipment view with all sensor fields (temperature, humidity, G-force, lock, device status, GPS coordinates) and admin controls: trigger temperature alert, trigger collision alert, resolve active alert, lock/unlock cargo.

**Map** — per-shipment "Open in Google Maps" links and a "View All" multi-waypoint directions link. No API key required.

**Discord notifications** — when an alert is triggered, the dashboard sends a structured Discord embed directly from the browser via webhook (Discord webhooks support CORS). Set `DISCORD_WEBHOOK_URL` in the config block at the top of `index.html`.

---

## Project Structure

```
iot-security/
├── index.html                        # Entire frontend — single file, no build step
│
├── lambda/
│   ├── list-shipments/               # GET /shipments
│   ├── get-shipment/                 # GET /shipments/{id}
│   ├── list-alerts/                  # GET /alerts
│   ├── trigger-alert/                # POST /demo/trigger-alert (also handles LOCK_UPDATE)
│   ├── resolve-alert/                # POST /alerts/{alertId}/resolve
│   └── discord-commands/             # POST /discord/commands — Ed25519 verified slash commands
│       ├── lambda_function.py
│       ├── requirements.txt          # PyNaCl==1.5.0
│       └── discord-commands.zip      # Pre-built deployment bundle (ready to upload)
│
├── scripts/
│   ├── seed_dynamodb.py              # Seeds DynamoDB with 3 shipments + 1 alert
│   └── register_discord_commands.py  # Registers /status /alerts /resolve /lock /unlock with Discord
│
├── DEPLOY.md                         # Step-by-step AWS Console deployment guide
└── webhook.py                        # Standalone webhook test utility
```

---

## Enabling Discord Notifications

1. In Discord: open your server → channel settings → **Integrations → Webhooks → New Webhook** → copy URL.
2. Open `index.html`, find the config block near the top of `<body>`:

```javascript
const DISCORD_WEBHOOK_URL = "";  // ← paste your webhook URL here
```

3. Reload the page. The Discord panel turns green and a "Send Test Notification" button appears.

When any alert is triggered from the dashboard, an embed is posted to your channel with fields: Severity, Type, Shipment, Temperature, Location, and suggested slash commands (`/status`, `/alerts`, `/resolve`).

---

## Connecting to AWS Backend

The frontend is ready to switch from mock data to real API calls. All mock functions (`dbShipments`, `dbAlerts`, etc.) can be replaced by `fetch()` calls to the API Gateway.

### Step 1 — Deploy the backend

Follow [DEPLOY.md](DEPLOY.md) for the full step-by-step guide. Summary:

1. Create DynamoDB tables: `Shipments`, `AlertEvents`, `DiscordUsers`
2. Seed initial data: `python scripts/seed_dynamodb.py`
3. Deploy 6 Lambda functions (Python 3.12) — paste each file from `lambda/*/lambda_function.py`
4. Upload `lambda/discord-commands/discord-commands.zip` for the bot (includes PyNaCl)
5. Add API Gateway routes to the existing API (`d1rocl5xb9`)
6. Deploy the API stage

### Step 2 — Point the frontend at your API

In `index.html`, uncomment and fill in:

```javascript
const API_BASE = 'https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/prod';
```

### Step 3 — Replace mock functions with real fetch calls

Swap the mock `db*` functions in `index.html` with these patterns:

```javascript
// List shipments
async function dbShipments() {
  return fetch(API_BASE + '/shipments').then(r => r.json());
}

// Get single shipment
async function dbShipment(id) {
  return fetch(API_BASE + '/shipments/' + id).then(r => r.json());
}

// List alerts
async function dbAlerts() {
  return fetch(API_BASE + '/alerts').then(r => r.json());
}

// Trigger alert
async function dbTriggerAlert(shipmentId, alertType, severity, temperature) {
  const res = await fetch(API_BASE + '/demo/trigger-alert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ shipmentId, alertType, severity, temperature }),
  });
  const data = await res.json();
  return data.alertId;
}

// Resolve alert
async function dbResolveAlert(alertId, resolvedBy) {
  await fetch(API_BASE + '/alerts/' + alertId + '/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resolvedBy }),
  });
}

// Lock / unlock
async function dbSetLock(shipmentId, lockStatus) {
  await fetch(API_BASE + '/demo/trigger-alert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ shipmentId, alertType: 'LOCK_UPDATE', lockStatus }),
  });
}
```

Make `renderDashboard`, `renderAlerts`, `renderDetail` async and `await` these calls. The render functions are already structured to accept the same data shape that the Lambda functions return.

### Step 4 — Add real auth (optional)

The frontend currently uses hardcoded demo accounts in `DEMO_ACCOUNTS`. To switch to Cognito:

1. Create a Cognito User Pool (see DEPLOY.md Step 4)
2. Add the Cognito CDN to `<head>`:
   ```html
   <script src="https://cdn.jsdelivr.net/npm/amazon-cognito-identity-js/dist/amazon-cognito-identity.min.js"></script>
   ```
3. Replace `handleLogin()` with Cognito's `authenticateUser()` flow (skeleton in DEPLOY.md)

---

## Discord Bot Slash Commands

The `lisa-discord-commands` Lambda handles these slash commands:

| Command | Description |
|---------|-------------|
| `/status <shipment_id>` | Shows live status for a shipment (from DynamoDB) |
| `/alerts` | Lists all unresolved active alerts |
| `/resolve <alert_id>` | Marks an alert resolved, updates shipment risk level |
| `/lock <shipment_id>` | Locks cargo |
| `/unlock <shipment_id>` | Unlocks cargo |

To activate slash commands:

```bash
# Register commands with Discord API
DISCORD_APPLICATION_ID=<id> DISCORD_BOT_TOKEN=<token> \
  python scripts/register_discord_commands.py
```

Then set the Interactions Endpoint URL in Discord Developer Portal → your app → General Information:

```
https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/{stage}/discord/commands
```

Discord verifies the endpoint immediately via an Ed25519 PING — the Lambda handles this automatically.

> **Note:** Slash commands require the AWS backend (Lambda + API Gateway) to be deployed. The demo-mode frontend does not expose a bot endpoint.

---

## API Reference

| Method | Path | Lambda | Description |
|--------|------|--------|-------------|
| GET | `/shipments` | lisa-list-shipments | All shipments |
| GET | `/shipments/{id}` | lisa-get-shipment | Single shipment |
| GET | `/alerts` | lisa-list-alerts | All alerts (filter: `?resolved=true/false`) |
| POST | `/demo/trigger-alert` | lisa-trigger-alert | Create alert or update lock status |
| POST | `/alerts/{alertId}/resolve` | lisa-resolve-alert | Resolve an alert |
| POST | `/discord/commands` | lisa-discord-commands | Discord interaction endpoint |
| POST | `/unlock` | Sentinel_NFC_Unlock | **Existing** — do not modify |

### DynamoDB Schema

**Shipments** (PK: `shipmentId`)
```
shipmentId, status, riskLevel, temperature, humidity, gForce,
lockStatus, deviceStatus, latitude, longitude, lastUpdatedAt
```

**AlertEvents** (PK: `alertId`)
```
alertId, shipmentId, alertType, severity, message,
resolved, resolvedBy, createdAt, resolvedAt
```

---

## Extending the Platform

### Adding a new shipment field

1. Add the field to `scripts/seed_dynamodb.py` and re-run it
2. Add it to the `fields` array in `renderDetail()` in `index.html`
3. Add a column to the shipment table in `renderDashboard()` if needed
4. No Lambda changes needed — `list-shipments` and `get-shipment` return all DynamoDB attributes automatically

### Adding a new alert type

1. Add a trigger button in `renderDetail()` calling `dbTriggerAlert(sid, 'YOUR_TYPE', 'HIGH')`
2. The `trigger-alert` Lambda and `dbTriggerAlert()` mock both accept any `alertType` string
3. To display it specially in Discord, update the `postDiscordAlert()` payload fields in `index.html`

### Adding a new page / route

1. Add a `<div id="page-yourpage" class="page-section">` block inside `#app-shell`
2. Add a `<span class="nav-link" onclick="navigate('yourpage')">` to the topbar nav
3. Add a `if (page === 'yourpage') renderYourPage();` branch in `navigate()` in `index.html`

---

## To-Do / Next Steps

### Required for production

- [ ] **Deploy Lambda functions** — upload each `lambda_function.py` to AWS Console (Python 3.12). Upload `discord-commands.zip` for the bot. See DEPLOY.md.
- [ ] **Wire API Gateway routes** — add GET /shipments, GET /alerts, POST /demo/trigger-alert, POST /alerts/{id}/resolve, POST /discord/commands to the existing API (`d1rocl5xb9`). Deploy the stage.
- [ ] **Discord bot activation** — set `DISCORD_PUBLIC_KEY` on `lisa-discord-commands` Lambda, run `register_discord_commands.py`, set Interactions Endpoint URL in Discord Developer Portal.
- [ ] **Switch frontend to live API** — uncomment `API_BASE` in `index.html` and replace `db*` mock functions with `fetch()` calls (patterns in the section above).

### Improves robustness

- [ ] **Cognito auth** — replace hardcoded `DEMO_ACCOUNTS` with a Cognito User Pool. Skeleton config is in DEPLOY.md Step 4.
- [ ] **API Gateway authorizer** — attach a Cognito JWT authorizer to all routes so unauthenticated calls are rejected at the gateway layer before reaching Lambda.
- [ ] **Live polling** — add a `setInterval` (30 s) re-fetch of `/shipments` and `/alerts` so the dashboard updates without manual refresh. Remove the interval when the user navigates away.
- [ ] **Re-seed after testing** — after trigger/resolve tests, run `python scripts/seed_dynamodb.py` to restore baseline data.

### Future integrations

- [ ] **Real IoT sensor data** — replace the demo trigger path with an IoT Core rule that writes sensor readings (temperature, humidity, G-force) to DynamoDB and auto-triggers alerts on threshold breach.
- [ ] **NFC unlock** — the existing `Sentinel_NFC_Unlock` Lambda already handles `POST /unlock`. Surface its lock/unlock response back in the dashboard's shipment detail lock status display.
- [ ] **Image evidence** — `Sentinel_Image_Processor` Lambda (deployed, not in this repo) captures images to S3. Add an "Evidence" tab in Shipment Detail that lists S3 image URLs associated with a shipment's alert events.
- [ ] **GPS real-time tracking** — replace static lat/long in DynamoDB with a live stream from a GPS tracker (IoT Core MQTT → Lambda → DynamoDB update). The Map page already reads `latitude`/`longitude` from each shipment object — no page changes needed.
- [ ] **Multi-shipment Discord threads** — post each shipment's alerts into a dedicated Discord thread to keep channels organized.
- [ ] **CloudWatch metrics** — add Lambda invocation counts, alert creation rate, and DynamoDB RCU/WCU as CloudWatch metrics for operational monitoring.

---

## Architecture

```
Browser (index.html)
  │  demo mode:   in-memory mock data (_db object)
  │  production:  fetch() → API Gateway → Lambda → DynamoDB
  │
  ├── GET  /shipments            → lisa-list-shipments   → DynamoDB Shipments
  ├── GET  /shipments/{id}       → lisa-get-shipment     → DynamoDB Shipments
  ├── GET  /alerts               → lisa-list-alerts      → DynamoDB AlertEvents
  ├── POST /demo/trigger-alert   → lisa-trigger-alert    → DynamoDB AlertEvents + Shipments
  │                                                      → Discord webhook (env var)
  ├── POST /alerts/{id}/resolve  → lisa-resolve-alert    → DynamoDB AlertEvents + Shipments
  └── POST /discord/commands     → lisa-discord-commands → DynamoDB Shipments + AlertEvents
                                   (Ed25519 verified)

Discord webhook (browser fetch — no proxy needed, Discord sets Access-Control-Allow-Origin: *)
  └── Sends embed on alert trigger: Severity / Type / Shipment / Temp / Location / Suggested commands

Existing (do not modify):
  POST /unlock → Sentinel_NFC_Unlock     (NFC hardware unlock)
              → Sentinel_Image_Processor (camera capture → S3)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS — single file, no framework, no build step |
| Auth (demo) | Hardcoded accounts in `DEMO_ACCOUNTS`, `sessionStorage` for session |
| Auth (production-ready) | Amazon Cognito User Pool + `amazon-cognito-identity-js` CDN |
| Backend | AWS Lambda (Python 3.12) + API Gateway REST (us-east-1) |
| Database | DynamoDB On-Demand — Shipments, AlertEvents, DiscordUsers |
| Discord alerts | Webhook embed via browser `fetch()` |
| Discord commands | Lambda with Ed25519 signature verification (PyNaCl) |
| Map | Google Maps URL links — no API key required |
