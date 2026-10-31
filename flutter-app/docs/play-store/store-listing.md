# Elhaq (إلحق) — Play Store Listing & Data-Safety

**⚠️ DRAFT. English copy is canonical; Arabic copy is a working translation that
must be reviewed by a native Arabic speaker before submission. Screenshots must be
rendered from the current visual pass.**

**Release gate (plans/p2 truth rule):** the marker this file used to carry (spelled in one word below, never written out here — the gate greps for it, so the gate text cannot contain it) must appear nowhere in `flutter-app/docs` at submission, and no copy may promise a delivery channel the shipped deployment does not have. The app itself uses no OS push notification and no email; whether a WhatsApp deal alert reaches you is a server configuration (`MOCK_WHATSAPP` plus Meta credentials) and belongs in `privacy-policy.md`, so listing copy states only what is always true: the alert is visible in-app.

---

## 1. App name & brand

- **Title:** Elhaq (إلحق)
- **Tagline idea:** Track prices. Get the deal. / تابع الأسعار واحصل على الصفقة.

## 2. Short description (80 chars max)

**EN:**
> Track prices on Amazon EG, Noon & Jumia; every drop stays visible in-app.

**AR (machine-composed: this file's own Arabic opening sentence, reused as the short line; NOT native-reviewed):**
> إلحق يتابع المنتجات التي تهتم بها على أمازون مصر ونون وجوميا.

## 3. Full description

**EN:**
> Elhaq (إلحق) keeps an eye on the products you care about across Amazon Egypt,
> Noon, and Jumia — so you stop refreshing the page hoping for a discount.
>
> **Track what matters.** Add any product and Elhaq follows its price and
> stock for you.
>
> **Every drop stays visible.** When a tracked price falls, the change is recorded
> against your account and appears in the app's alert history — tap it to open
> the product at the merchant. Nothing about this needs a notifications permission:
> what you see, you see in-app.
>
> **Arabic-first.** A fully Arabic experience with right-to-left layout, plus
> English. Prices are formatted for your locale.
>
> **Yours to control.** Light or dark theme, demo mode to explore before you sign
> up, and your data stays yours.

**AR (machine-composed from Arabic this app already ships — `app_ar.arb` vocabulary and this file's own Arabic sentences; NOT native-reviewed):**

> إلحق يتابع المنتجات التي تهتم بها على أمازون مصر ونون وجوميا — لتتوقف عن
> تحديث الصفحة وأنت تنتظر الخصم.
>
> **تابع ما يهمك.** أضف أي منتج وسيتابع إلحق سعره ومتوفرته عنك.
>
> **تنبيهات عند الانخفاض.** عندما ينخفض السعر عن مستواك، يُعلمك إلحق — بدون
> إزعاج، فقط الصفقات التي تهمك.
>
> **العربية أولًا.** تجربة عربية كاملة مع اتجاه من اليمين إلى اليسار، بالإضافة
> إلى الإنجليزية. الأسعار مُنسّقة حسب لغتك.
>
> **بين يديك.** ثيم فاتح أو داكن، وضع تجريبي لتجربة التطبيق قبل التسجيل، وبياناتك
> تبقى ملكك.

## 4. Data-safety form (must match `privacy-policy.md`)

| Question | Answer |
|----------|--------|
| Do you collect any user data? | **Yes** — phone number (account/OTP), tracked items, price data for those items, and price-change events recorded against the account (see `privacy-policy.md` §1). |
| Is any data collected that could identify an individual? | **Yes** — the phone number identifies the account holder. |
| Is any data collected from children < 13? | **No.** |
| Is any data used for advertising? | **No.** No ad SDKs are present. |
| Is any data shared with third parties for advertising? | **No.** |
| Do you provide a way to delete data? | **Yes** — deleting the account removes the associated personal data. |
| Is the data transmitted over an encrypted connection (HTTPS)? | **Yes.** |
| Do you provide a privacy policy? | **Yes** — see `privacy-policy.md` (hosted URL entered in Play console). |

## 5. Content rating

- Target: **Everyone / E**. The app contains no violence, no inappropriate
  content, and no in-app purchases that require a higher rating. (Re-confirm
  against the final feature set at submission time.)

## 6. Screenshots (6, from the current visual pass)

1. Splash / brand
2. Dashboard — tracked items list
3. A tracker card showing a live price
4. A deal / price-drop alert card (shown in-app)
5. Create-tracker flow
6. Settings (theme + demo mode) — include one **dark-mode** and one **Arabic/RTL**
   screen to demonstrate both.

## 7. Feature highlights (Play "What's new" per release)

- v1.0: Initial release — price tracking across Amazon EG, Noon & Jumia; price
  drops recorded and shown to you in-app (no OS push or email in this version);
  Arabic-first with RTL; light/dark theme; demo mode.

---
_Submit the hosted privacy-policy URL and the data-safety answers above in the
Play Console. Keep this file in sync with `privacy-policy.md` and the app's
actual behavior._
