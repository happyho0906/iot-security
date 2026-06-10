# Cognito Sign-Up UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live password requirements checklist, full frontend validation, and a resend confirmation code action to the sign-up flow.

**Architecture:** All changes are in `index.html` only — CSS styles added before `</style>` (line 739), HTML nodes inserted into the existing sign-up form, JS helpers added to the existing script block and wired into the existing DOMContentLoaded listener.

**Tech Stack:** Vanilla JS, existing CSS variables (`--green`, `--muted`, `--blue`), Amazon Cognito Identity JS SDK (`resendConfirmationCode`).

---

### Task 1: Password requirements checklist (CSS + HTML + JS)

**Files:**
- Modify: `index.html:739` — add CSS before `</style>`
- Modify: `index.html:860` — add checklist HTML after password input
- Modify: `index.html:1277` — add `_validatePassword()` helper and live input listener
- Modify: `index.html:1289-1291` — replace length-only check with `_validatePassword()`
- Modify: `index.html:1364-1372` — add `input` listener inside DOMContentLoaded

- [ ] **Step 1: Add CSS for the checklist**

Insert these lines immediately before line 739 (`    </style>`):

```css
      .pw-requirements { margin: 6px 0 12px; display: flex; flex-direction: column; gap: 3px; }
      .pw-req { font-size: 11px; color: var(--muted); padding-left: 14px; position: relative; }
      .pw-req::before { content: '·'; position: absolute; left: 0; }
      .pw-req.met { color: var(--green); }
      .pw-req.met::before { content: '✓'; }
```

- [ ] **Step 2: Add checklist HTML after the password input**

The password input `<div class="form-group">` ends at line 860 with `</div>`. Insert this block immediately after it (between line 860 and the Confirm Password group):

```html
          <div class="pw-requirements" id="pw-requirements">
            <div class="pw-req" id="req-length">At least 8 characters</div>
            <div class="pw-req" id="req-upper">At least 1 uppercase letter</div>
            <div class="pw-req" id="req-number">At least 1 number</div>
            <div class="pw-req" id="req-symbol">At least 1 symbol character</div>
          </div>
```

- [ ] **Step 3: Add `_validatePassword()` helper**

Insert this function immediately before the `// ── Sign Up` comment at line 1277:

```js
      function _validatePassword(pw) {
        if (pw.length < 8)             return "Password must be at least 8 characters.";
        if (!/[A-Z]/.test(pw))         return "Password must contain at least 1 uppercase letter.";
        if (!/[0-9]/.test(pw))         return "Password must contain at least 1 number.";
        if (!/[^A-Za-z0-9]/.test(pw))  return "Password must contain at least 1 symbol character.";
        return null;
      }
```

- [ ] **Step 4: Replace the length-only check in `handleSignUp()`**

At lines 1289-1291, replace:

```js
        if (!email || !password) { _showErr("Email and password are required."); return; }
        if (password !== confirm) { _showErr("Passwords do not match.");          return; }
        if (password.length < 8) { _showErr("Password must be at least 8 characters."); return; }
```

With:

```js
        if (!email || !password) { _showErr("Email and password are required."); return; }
        if (password !== confirm) { _showErr("Passwords do not match.");          return; }
        const _pwErr = _validatePassword(password);
        if (_pwErr) { _showErr(_pwErr); return; }
```

- [ ] **Step 5: Wire up the live input listener in DOMContentLoaded**

Inside the `DOMContentLoaded` callback (currently lines 1361-1373), add this listener after the existing `signup-confirm` keydown binding:

```js
        document.getElementById("signup-password").addEventListener("input", function () {
          const pw = this.value;
          document.getElementById("req-length").classList.toggle("met", pw.length >= 8);
          document.getElementById("req-upper").classList.toggle("met", /[A-Z]/.test(pw));
          document.getElementById("req-number").classList.toggle("met", /[0-9]/.test(pw));
          document.getElementById("req-symbol").classList.toggle("met", /[^A-Za-z0-9]/.test(pw));
        });
```

- [ ] **Step 6: Verify in browser**

With `python3 -m http.server 8080 --directory /Users/kaixin/Desktop/iot-security` running:

1. Open `http://localhost:8080` → click **Sign Up** tab
2. Type `abc` in the password field → all 4 rules should show as unmet (muted dots)
3. Type `Abc1!xyz` → all 4 rules should show as met (green checkmarks)
4. Clear the field and click **Create Account** → should show inline error, not call Cognito

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "feat: live password requirements checklist and full frontend validation"
```

---

### Task 2: Resend confirmation code

**Files:**
- Modify: `index.html:893` — add resend link after the Verify button
- Modify: `index.html:1277` — add `handleResendCode()` function (before Sign Up section)

- [ ] **Step 1: Add resend link HTML in the verify section**

The `#verify-section` Verify button ends at line 893 (`</button>`). Insert this block immediately after it, before the closing `</div>` of `#verify-section` (line 894):

```html
            <div style="margin-top:10px; text-align:center; font-size:13px; color:var(--muted);">
              Didn't receive it?
              <button id="btn-resend" onclick="handleResendCode()"
                style="background:none;border:none;color:var(--blue);cursor:pointer;font-size:13px;padding:0;text-decoration:underline;">
                Resend code
              </button>
            </div>
```

- [ ] **Step 2: Add `handleResendCode()` function**

Insert this function immediately before `_validatePassword` (added in Task 1, before the `// ── Sign Up` comment):

```js
      function handleResendCode() {
        if (!_cognitoUser) { _showErr("No account to resend to. Please sign up again."); return; }
        const btn = document.getElementById("btn-resend");
        btn.disabled = true;
        _cognitoUser.resendConfirmationCode((err) => {
          if (err) { _showErr(err.message || "Failed to resend code."); btn.disabled = false; return; }
          _showOk("Verification code resent. Check your email.");
          let secs = 30;
          btn.textContent = "Resend in " + secs + "s…";
          const t = setInterval(() => {
            secs--;
            if (secs <= 0) {
              clearInterval(t);
              btn.disabled = false;
              btn.textContent = "Resend code";
            } else {
              btn.textContent = "Resend in " + secs + "s…";
            }
          }, 1000);
        });
      }
```

- [ ] **Step 3: Verify in browser**

1. Start sign-up with a real email → after submitting, the verify section appears
2. The "Didn't receive it? Resend code" text appears below the Verify button
3. Click **Resend code** → button changes to "Resend in 30s…" countdown
4. After 30 seconds, button re-enables as "Resend code"
5. A success toast/message appears: "Verification code resent. Check your email."

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: add resend confirmation code with 30s cooldown"
```
