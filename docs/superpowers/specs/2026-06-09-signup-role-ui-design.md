# Sign-Up Role Selection & UI Polish Design

**Date:** 2026-06-09
**Status:** Approved

## Problem

The sign-up form has no role selection — all users default to CUSTOMER. The login card header is verbose (long subtitle). Spacing is loose, making the card feel taller than needed.

## Changes

### 1. Header — remove subtitle

Remove the "Logistics Intelligence & Sentinel Assistant" subtitle from the login card header. Keep the `L` mark and "LISA" title. Reduce header padding from `24px` to `16px` top.

### 2. Sign-up — Role dropdown

Add a `Role` `<select>` field at the top of `#form-signup`, before the Email field.

Options (in order):
- `Customer` (value: `CUSTOMER`) — selected by default
- `Driver` (value: `DRIVER`)
- `Admin` (value: `ADMIN`)

The selected value is passed to Cognito's `signUp()` as a `CognitoUserAttribute` with `Name: "custom:role"`.

### 3. Password requirements — condensed hint

Replace the 4-line requirements list with a single hint line below the password input:
`8+ chars · Uppercase · Number · Symbol`

The live `.met` / unmet checklist still updates dynamically but is displayed as inline items on one line instead of stacked rows.

### 4. Spacing — tighter form groups

Reduce `margin-bottom` on `.form-group` from current value to `10px`. Reduce padding inside `.login-card` form area.

## Cognito Prerequisite

The User Pool App Client must allow read/write of the `custom:role` attribute:
- AWS Console → Cognito → User pools → your pool → App clients → your client
- Under "Attribute read and write permissions" → enable `custom:role` for both read and write

Without this, `signUp()` will return an error about the attribute.

## Scope

All changes in `index.html` only. No Lambda or API Gateway changes needed — `custom:role` is already read from the JWT payload in `handleLogin()` at line ~1256.
