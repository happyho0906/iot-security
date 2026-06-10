# Sign-Up Role Selection & UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a role dropdown (Customer/Driver/Admin) to sign-up, tighten the login card header, and condense the password requirements to one line.

**Architecture:** All changes are in `index.html` only — CSS edits, HTML additions/removals, and one JS change to `handleSignUp()` to pass `custom:role` to Cognito.

**Tech Stack:** Vanilla JS, existing CSS variables, Amazon Cognito Identity JS SDK (`CognitoUserAttribute`).

---

### Task 1: Header & spacing polish

**Files:**
- Modify: `index.html:72` — `.login-card` padding
- Modify: `index.html:113` — `.login-header` margin-bottom
- Modify: `index.html:115-126` — `.login-mark` size
- Modify: `index.html:127-131` — `.login-title` font-size
- Modify: `index.html:776-778` — remove `.login-sub` element

- [ ] **Step 1: Tighten `.login-card` padding**

At line 72, replace:
```css
        padding: 36px 40px;
```
With:
```css
        padding: 24px 28px;
```

- [ ] **Step 2: Tighten `.login-header` margin-bottom**

At line 113, replace:
```css
        margin-bottom: 28px;
```
With:
```css
        margin-bottom: 16px;
```

- [ ] **Step 3: Shrink `.login-mark`**

Replace the entire `.login-mark` rule (lines 115-126):
```css
      .login-mark {
        width: 46px;
        height: 46px;
        border-radius: 10px;
        background: var(--blue);
        color: #fff;
        font-size: 20px;
        font-weight: 800;
        display: grid;
        place-items: center;
        margin: 0 auto 14px;
      }
```
With:
```css
      .login-mark {
        width: 38px;
        height: 38px;
        border-radius: 8px;
        background: var(--blue);
        color: #fff;
        font-size: 16px;
        font-weight: 800;
        display: grid;
        place-items: center;
        margin: 0 auto 8px;
      }
```

- [ ] **Step 4: Shrink `.login-title`**

At line 128, replace:
```css
        font-size: 20px;
```
With:
```css
        font-size: 16px;
```

- [ ] **Step 5: Remove the subtitle element**

Remove these lines (776-778):
```html
          <div class="login-sub">
            Logistics Intelligence &amp; Sentinel Assistant
          </div>
```

- [ ] **Step 6: Verify HTML is well-formed**

```bash
python3 -c "
from html.parser import HTMLParser
class V(HTMLParser): pass
V().feed(open('/Users/kaixin/Desktop/iot-security/index.html').read())
print('OK')
"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git -C /Users/kaixin/Desktop/iot-security add index.html
git -C /Users/kaixin/Desktop/iot-security commit -m "feat: tighten login card header and spacing"
```

---

### Task 2: Condense password requirements to one line

**Files:**
- Modify: `index.html:739-743` — `.pw-requirements` / `.pw-req` CSS
- Modify: `index.html:866-871` — `#pw-requirements` HTML text

- [ ] **Step 1: Replace password requirements CSS**

Replace lines 739-743:
```css
      .pw-requirements { margin: 6px 0 12px; display: flex; flex-direction: column; gap: 3px; }
      .pw-req { font-size: 11px; color: var(--muted); padding-left: 14px; position: relative; }
      .pw-req::before { content: '·'; position: absolute; left: 0; }
      .pw-req.met { color: var(--green); }
      .pw-req.met::before { content: '✓'; }
```
With:
```css
      .pw-requirements { margin: 4px 0 10px; display: flex; flex-wrap: wrap; gap: 6px; }
      .pw-req { font-size: 10px; color: var(--muted); padding: 2px 7px; border-radius: 20px; border: 1px solid var(--border); }
      .pw-req.met { color: var(--green); border-color: var(--green); background: var(--green-soft); }
```

- [ ] **Step 2: Shorten the requirement labels in HTML**

Replace the `#pw-requirements` div (lines 866-871):
```html
          <div class="pw-requirements" id="pw-requirements">
            <div class="pw-req" id="req-length">At least 8 characters</div>
            <div class="pw-req" id="req-upper">At least 1 uppercase letter</div>
            <div class="pw-req" id="req-number">At least 1 number</div>
            <div class="pw-req" id="req-symbol">At least 1 symbol character</div>
          </div>
```
With:
```html
          <div class="pw-requirements" id="pw-requirements">
            <div class="pw-req" id="req-length">8+ chars</div>
            <div class="pw-req" id="req-upper">Uppercase</div>
            <div class="pw-req" id="req-number">Number</div>
            <div class="pw-req" id="req-symbol">Symbol</div>
          </div>
```

- [ ] **Step 3: Verify HTML is well-formed**

```bash
python3 -c "
from html.parser import HTMLParser
class V(HTMLParser): pass
V().feed(open('/Users/kaixin/Desktop/iot-security/index.html').read())
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git -C /Users/kaixin/Desktop/iot-security add index.html
git -C /Users/kaixin/Desktop/iot-security commit -m "feat: condense password requirements to pill badges on one line"
```

---

### Task 3: Role dropdown + Cognito attribute

**Files:**
- Modify: `index.html:845` — add role select before email in `#form-signup`
- Modify: `index.html:1335-1336` — add `custom:role` to Cognito `attrList`

- [ ] **Step 1: Add role dropdown HTML**

Inside `#form-signup` (line 845), insert this block immediately after `<div id="form-signup" style="display:none;">`:

```html
          <div class="form-group">
            <label class="form-label">Role</label>
            <select id="signup-role" class="form-input">
              <option value="CUSTOMER">Customer</option>
              <option value="DRIVER">Driver</option>
              <option value="ADMIN">Admin</option>
            </select>
          </div>
```

- [ ] **Step 2: Add `custom:role` to Cognito attrList in `handleSignUp()`**

Find the `attrList` assignment (around line 1335). Replace:
```js
        const attrList = [
          new AmazonCognitoIdentity.CognitoUserAttribute({ Name: "email", Value: email }),
        ];
```
With:
```js
        const role = document.getElementById("signup-role").value;
        const attrList = [
          new AmazonCognitoIdentity.CognitoUserAttribute({ Name: "email",       Value: email }),
          new AmazonCognitoIdentity.CognitoUserAttribute({ Name: "custom:role", Value: role  }),
        ];
```

- [ ] **Step 3: Verify HTML is well-formed**

```bash
python3 -c "
from html.parser import HTMLParser
class V(HTMLParser): pass
V().feed(open('/Users/kaixin/Desktop/iot-security/index.html').read())
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git -C /Users/kaixin/Desktop/iot-security add index.html
git -C /Users/kaixin/Desktop/iot-security commit -m "feat: add role dropdown to sign-up, pass custom:role to Cognito"
```

---

### Manual Step: Enable custom:role in Cognito App Client

> No code changes — one-time AWS Console setup required before testing sign-up.

- [ ] Go to AWS Console → Cognito → User pools → `us-east-1_F3yuU3Vhq`
- [ ] App clients → your client (`4lck88f893ohf06fo18qudnbp4`)
- [ ] Scroll to **Attribute read and write permissions**
- [ ] Find `custom:role` — enable both **Read** and **Write**
- [ ] Save changes

Without this, Cognito will reject the `custom:role` attribute during sign-up with an `InvalidParameterException`.
