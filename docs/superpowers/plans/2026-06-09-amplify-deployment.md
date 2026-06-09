# Amplify Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `amplify.yml` so AWS Amplify generates `config.local.js` from environment variables at build time, enabling Cognito auth and Discord notifications in production.

**Architecture:** A single `amplify.yml` at repo root runs a `printf` command during the Amplify build phase to write `config.local.js` with values injected from Amplify Console environment variables. No changes to `index.html` — it already loads `config.local.js` with an `onerror` fallback for local dev.

**Tech Stack:** AWS Amplify Hosting, bash `printf`, existing `window.LISA_CONFIG` pattern in `index.html`.

---

### Task 1: Create `amplify.yml`

**Files:**
- Create: `amplify.yml`

- [ ] **Step 1: Verify the printf command produces correct output**

Run this locally to confirm the command works before committing:

```bash
COGNITO_USER_POOL_ID="us-east-1_TEST123" \
COGNITO_CLIENT_ID="abc123clientid" \
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test" \
printf 'window.LISA_CONFIG = {\n  COGNITO_USER_POOL_ID: "%s",\n  COGNITO_CLIENT_ID: "%s",\n  DISCORD_WEBHOOK_URL: "%s",\n};\n' \
  "$COGNITO_USER_POOL_ID" "$COGNITO_CLIENT_ID" "$DISCORD_WEBHOOK_URL"
```

Expected output:
```js
window.LISA_CONFIG = {
  COGNITO_USER_POOL_ID: "us-east-1_TEST123",
  COGNITO_CLIENT_ID: "abc123clientid",
  DISCORD_WEBHOOK_URL: "https://discord.com/api/webhooks/test",
};
```

- [ ] **Step 2: Create `amplify.yml`**

Create `amplify.yml` at repo root with this exact content:

```yaml
version: 1
frontend:
  phases:
    build:
      commands:
        - >
          printf 'window.LISA_CONFIG = {\n  COGNITO_USER_POOL_ID: "%s",\n  COGNITO_CLIENT_ID: "%s",\n  DISCORD_WEBHOOK_URL: "%s",\n};\n'
          "$COGNITO_USER_POOL_ID" "$COGNITO_CLIENT_ID" "$DISCORD_WEBHOOK_URL"
          > config.local.js
  artifacts:
    baseDirectory: .
    files:
      - index.html
      - config.local.js
  cache:
    paths: []
```

- [ ] **Step 3: Verify the file parses as valid YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('amplify.yml'))" && echo "VALID"
```

Expected: `VALID`

- [ ] **Step 4: Commit**

```bash
git add amplify.yml
git commit -m "feat: add amplify.yml to inject config from env vars at build time"
```

---

### Task 2: Set Environment Variables in Amplify Console

> This task is manual — no code changes.

- [ ] **Step 1: Open Amplify Console**

Go to AWS Console → Amplify → your app → **App settings → Environment variables**.

- [ ] **Step 2: Add the three variables**

| Variable | Value source |
|----------|-------------|
| `COGNITO_USER_POOL_ID` | AWS Console → Cognito → User pools → your pool → Pool ID (format: `us-east-1_XXXXXXX`) |
| `COGNITO_CLIENT_ID` | AWS Console → Cognito → User pools → your pool → App clients → Client ID |
| `DISCORD_WEBHOOK_URL` | Discord → channel Settings → Integrations → Webhooks → Copy Webhook URL |

Click **Save**.

- [ ] **Step 3: Trigger a redeploy**

In Amplify Console → your app → select the `master` branch → click **Redeploy this version** (or push any commit to trigger a fresh build).

- [ ] **Step 4: Verify the build log**

In Amplify Console → the new build → **Build logs** → expand the build phase. You should see the `printf` command execute without error and `config.local.js` appear in the artifact list.

- [ ] **Step 5: Verify the deployed app**

Open the Amplify-hosted URL. The login page should load. Open browser DevTools → Console and run:

```js
window.LISA_CONFIG
```

Expected: an object with `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, and `DISCORD_WEBHOOK_URL` populated (not empty strings).

Then attempt sign-in with a valid Cognito user — the login flow should complete without "Cognito not configured" errors.
