# Elhaq (إلحق) — Privacy Policy

_Last updated: [DATE]_

**⚠️ DRAFT — requires legal review and a professional Arabic translation before
it is published. This document describes the app's current behavior; re-verify
each section against the codebase if features change (e.g., when crash reporting
or analytics are added in a later release).**

---

Elhaq (the "إلحق" price-tracking app) is a tool that helps you follow the prices
of products you care about on Egyptian online stores (Amazon Egypt, Noon, Jumia)
and record a price event when one of your tracked products changes. This policy
explains what data we collect, how it is used, and your choices.

## 1. What we collect

- **Account information.** To create an account you provide a **phone number**,
  which we use for login and one-time-password (OTP) verification.
- **Tracked items.** The products you choose to track (identified by the store,
  product/URL, and any associated image reference).
- **Price data.** Current and historical prices for your tracked items, fetched
  from the stores you track.
- **Price alerts.** When a price you track changes (a drop, a return to stock,
  crossing your target), we record that event against your account, so the app
  can show it to you later even if the app was closed when it happened. When you
  open one of those alerts in the app, we record that you have seen it, so unseen
  alerts can be counted. This stays tied to your account: we do not track who
  else might want to know.
- **Device-local settings.** Your theme preference (light/dark), language
  (Arabic/English), and demo-mode setting are stored **only on your device** and
  are not sent to our servers.
- **Secure session token.** Your authentication token is stored in the device's
  secure storage and sent only to our own API for authenticated requests.

## 2. What we do NOT collect

- We do **not** use third-party **advertising SDKs**.
- We do **not** run third-party **analytics** SDKs.
- As of this version we do **not** send **crash reports** to any third party.
  _(If crash reporting is enabled in a future release, this section will be
  updated and users will be notified.)_
- We do **not** request the Android notifications permission and do **not**
  deliver OS push notifications, email or WhatsApp messages to you in this
  version. Price events are shown inside the app; a delivery channel is only
  described here once it actually ships.
- We do not collect precise physical location, contacts, photos, or microphone
  data. The app requests only the `INTERNET` permission.

## 3. How we use your data

- To provide the service: authenticate you, fetch prices for your tracked items,
  and record price-change events for your account so the app can show them to
  you (see §1: an event is stored and displayed in-app in this version).
- To operate and improve the service (e.g., reliability of price fetching).
- We do **not** sell your personal data, and we do **not** share it with third
  parties for advertising.

## 4. How long we keep your data

We keep your account and tracked items while your account is active. When you
delete your account, we delete the associated personal data — including the price
events and alert history recorded for that account, which are removed with it.

## 5. Your choices

- **Access.** You can view your tracked items and account details in the app.
- **Deletion.** You can delete your account; this removes your personal data,
  tracked items, and the price events and alert history tied to the account.
- **Contact.** For privacy questions or a data-deletion request, contact:
  **[SUPPORT EMAIL / ADDRESS — fill in before publishing]**.

## 6. Security

Data in transit is encrypted using HTTPS/TLS. Your authentication token is
stored in the device's secure storage.

## 7. Children's privacy

The service is not directed at children under 13, and we do not knowingly
collect personal information from children.

## 8. Changes to this policy

We may update this policy; the "Last updated" date above reflects the latest
revision. Material changes will be communicated in the app.

---
_AR translation (`privacy-policy.ar.md`) to be produced by a native Arabic
reviewer and kept in sync with this English source._
