# Amplify Deployment Design

**Date:** 2026-06-09
**Status:** Approved

## Problem

`config.local.js` is gitignored and contains all runtime config (`COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `DISCORD_WEBHOOK_URL`). AWS Amplify clones the repo and serves the artifacts — it never has `config.local.js`, so the app deploys broken (Cognito disabled, Discord notifications fail).

## Approach

Generate `config.local.js` at Amplify build time from Amplify environment variables. Since `index.html` already loads `config.local.js` via `<script src="config.local.js" onerror="window.LISA_CONFIG = {}">`, no HTML changes are needed — the generated file slots in transparently.

## Changes

### New file: `amplify.yml` (repo root)

```yaml
version: 1
frontend:
  phases:
    build:
      commands:
        - |
          printf 'window.LISA_CONFIG = {\n  COGNITO_USER_POOL_ID: "%s",\n  COGNITO_CLIENT_ID: "%s",\n  DISCORD_WEBHOOK_URL: "%s",\n};\n' \
          "$COGNITO_USER_POOL_ID" "$COGNITO_CLIENT_ID" "$DISCORD_WEBHOOK_URL" \
          > config.local.js
  artifacts:
    baseDirectory: .
    files:
      - index.html
      - config.local.js
  cache:
    paths: []
```

### No changes to `index.html`

The existing `onerror="window.LISA_CONFIG = {}"` fallback already handles local dev (file not found). On Amplify, the generated file is always present.

### Amplify Console — Environment Variables

Set under App settings → Environment variables:

| Key | Source |
|-----|--------|
| `COGNITO_USER_POOL_ID` | AWS Cognito → User pools → Pool ID |
| `COGNITO_CLIENT_ID` | AWS Cognito → App clients → Client ID |
| `DISCORD_WEBHOOK_URL` | Discord channel → Integrations → Webhooks |

## Deployment Flow

```
git push origin master
       ↓
Amplify webhook triggers
       ↓
Build phase: generates config.local.js from env vars
       ↓
Artifacts (index.html + config.local.js) deployed to CloudFront
       ↓
App loads with live Cognito + Discord config
```

## Out of Scope

- Moving Discord webhook call server-side (currently called client-side at index.html:1520) — tracked separately
- Wiring up `API_BASE` for live Lambda calls (currently commented out at index.html:752)
