# Cognito Sign-Up UX Design

**Date:** 2026-06-09
**Status:** Approved

## Problem

The sign-up form gives no feedback on password requirements until submission fails with a Cognito error. Users who don't receive a confirmation email have no way to re-request it.

## Changes

### 1. Live password requirements checklist

A 4-item checklist rendered directly below `#signup-password`, updated on every `input` event. Each rule shows a filled checkmark (green) when met, a dot (muted) when not.

Rules:
- At least 8 characters
- At least 1 uppercase letter
- At least 1 number
- At least 1 symbol character (`[^A-Za-z0-9]`)

The checklist is visible as soon as the Sign Up tab is active. It does not animate in/out — always present.

### 2. Frontend validation in `handleSignUp()`

A `_validatePassword(pw)` helper returns `null` on pass or an error string on failure. `handleSignUp()` calls it before the Cognito API call and shows the error inline if it fails.

Validation order:
1. Length ≥ 8
2. Uppercase present
3. Number present
4. Symbol present

### 3. Resend confirmation code

A "Resend code" link added inside `#verify-section`, below the Verify button. Calls `_cognitoUser.resendConfirmationCode()`. Shows success/error inline using existing `_showOk` / `_showErr` helpers.

30-second cooldown: after clicking, the link is disabled and shows "Resend in 30s…" countdown. Re-enables after the timer expires.

## Implementation Scope

All changes in `index.html` only:
- HTML: add `.pw-requirements` div after `#signup-password`; add resend link in `#verify-section`
- CSS: `.pw-req` and `.pw-req.met` styles (≤ 6 lines)
- JS: `_validatePassword(pw)` helper; `input` listener on `#signup-password`; `handleResendCode()` function; update `handleSignUp()` validation block

No new files. No changes to Cognito configuration.
