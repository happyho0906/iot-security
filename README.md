# LISA: Logistics Intelligence & Sentinel Assistant

Cold-chain logistics monitoring platform. Tracks shipments, sensor readings, and alerts in real time. Runs fully in the browser in demo mode; connects to AWS (DynamoDB + Lambda + API Gateway + IoT Core) for production.

---

## Quick Start

```bash
python3 -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080). No AWS credentials required.

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@lisa.demo | admin123 |
| Driver | driver@lisa.demo | driver123 |
| Customer | customer@lisa.demo | customer123 |

---

## Project Structure

```
iot-security/
├── index.html                         # Frontend  single file, no build step
├── config.local.js                    # Local secrets (gitignored)
├── lambda/
│   ├── list-shipments/                # GET /shipments
│   ├── get-shipment/                  # GET /shipments/{id}
│   ├── list-alerts/                   # GET /alerts
│   ├── trigger-alert/                 # POST /demo/trigger-alert (+ LOCK_UPDATE)
│   ├── resolve-alert/                 # POST /alerts/{alertId}/resolve
│   ├── discord-commands/              # POST /discord/commands (Ed25519 verified)
│   ├── get-me/                        # GET /me  Cognito identity
│   ├── shadow-processor/              # IoT Rule trigger  shadow → DynamoDB
│   ├── register-nfc-device/           # POST /nfc/devices (admin)
│   ├── list-nfc-devices/              # GET /nfc/devices (admin)
│   ├── update-nfc-whitelist/          # PUT /nfc/devices/{tagId}/whitelist (admin)
│   └── check-nfc-device/              # GET /nfc/check/{tagId} (no auth, hardware)
├── pi/
│   └── sensor_agent.py                # Raspberry Pi MQTT shadow agent
├── scripts/
│   ├── seed_dynamodb.py               # Seeds 3 shipments, 1 alert, 3 users, 3 NFC devices
│   └── register_discord_commands.py   # Registers Discord slash commands
├── ARCHITECTURE.md                    # System design and migration plan
├── INTEGRATION.md                     # Module integration reference
└── DEPLOY.md                          # AWS deployment steps
```

---

## Configuration

Create `config.local.js` (gitignored):

```javascript
window.LISA_CONFIG = {
  DISCORD_WEBHOOK_URL:  "...",
  COGNITO_USER_POOL_ID: "us-east-1_...",   // Phase 2
  COGNITO_CLIENT_ID:    "...",              // Phase 2
};
```

---

## Discord Notifications

1. Discord → channel → Integrations → Webhooks → copy URL
2. Add to `config.local.js` as `DISCORD_WEBHOOK_URL`
3. Reload  Discord panel turns green, "Send Test Notification" appears

Slash commands (`/status`, `/alerts`, `/resolve`, `/lock`, `/unlock`) require the AWS backend. See [DEPLOY.md](DEPLOY.md).

---

## API Reference

| Method | Path | Lambda | Notes |
|--------|------|--------|-------|
| GET | `/shipments` | lisa-list-shipments | |
| GET | `/shipments/{id}` | lisa-get-shipment | |
| GET | `/alerts` | lisa-list-alerts | ?resolved=true/false |
| POST | `/demo/trigger-alert` | lisa-trigger-alert | also handles `LOCK_UPDATE` |
| POST | `/alerts/{alertId}/resolve` | lisa-resolve-alert | |
| POST | `/discord/commands` | lisa-discord-commands | Ed25519 verified |
| GET | `/me` | lisa-get-me | Cognito JWT identity |
| POST | `/nfc/devices` | lisa-register-nfc-device | Admin only — register/touch a device |
| GET | `/nfc/devices` | lisa-list-nfc-devices | Admin only — known devices + whitelist |
| PUT | `/nfc/devices/{tagId}/whitelist` | lisa-update-nfc-whitelist | Admin only — `{whitelisted: bool}` |
| GET | `/nfc/check/{tagId}` | lisa-check-nfc-device | No auth — for hardware/`Sentinel_NFC_Unlock` |
| POST | `/unlock` | Sentinel_NFC_Unlock | **Existing  do not modify** |

---

## AWS Deployment

See [DEPLOY.md](DEPLOY.md) for step-by-step instructions.

**Phase 1  Backend:** Deploy 6 Lambda functions, API Gateway routes, seed DynamoDB  
**Phase 2  Auth:** Cognito User Pool, update `config.local.js`, switch frontend auth  
**Phase 3  Live API:** Uncomment `API_BASE` in `index.html`, replace `db*` mocks with `fetch()`  
**Phase 4  IoT Core:** Deploy `shadow-processor` Lambda, run `pi/sensor_agent.py` on each device

### Switching to live API (Phase 3)

In `index.html`, uncomment `API_BASE` and replace `db*` functions:

```javascript
const API_BASE = 'https://d1rocl5xb9.execute-api.us-east-1.amazonaws.com/unlock';

async function dbShipments() {
  return fetch(API_BASE + '/shipments').then(r => r.json());
}
async function dbAlerts() {
  return fetch(API_BASE + '/alerts').then(r => r.json());
}
// Full patterns in ARCHITECTURE.md §6
```

---

## DynamoDB Schema

**Shipments** (PK: `shipmentId`): `status`, `riskLevel`, `temperature`, `humidity`, `gForce`, `lockStatus`, `deviceStatus`, `latitude`, `longitude`, `batteryLevel`, `thingName`, `lastUpdatedAt`

**AlertEvents** (PK: `alertId`): `shipmentId`, `alertType`, `severity`, `message`, `source`, `resolved`, `resolvedBy`, `createdAt`, `resolvedAt`

**NFCDevices** (PK: `tagId`): `label`, `status` (`KNOWN`/`WHITELISTED`), `firstSeenAt`, `lastSeenAt`, `addedBy`, `addedAt`

**Users** (PK: `userId`): `email`, `role`, `assignedShipments`  Cognito role mapping

---

## Architecture

```
Browser ──► Cognito ──► API Gateway ──► Lambda ──► DynamoDB
Raspberry Pi ──► IoT Core (Device Shadow) ──► shadow-processor ──► DynamoDB
Discord slash commands ──► API Gateway ──► lisa-discord-commands
```

Full diagram and migration plan: [ARCHITECTURE.md](ARCHITECTURE.md)
