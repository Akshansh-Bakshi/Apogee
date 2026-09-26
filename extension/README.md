# extension/

A minimal Chrome (Manifest V3) extension: manual page capture into Apogee. This is the Day 3
vertical slice — a click-to-capture tool, not an always-on/autonomous capture system.

## What it does

1. You click **Capture this page** in the popup.
2. The popup checks the current tab against the privacy filter (`src/privacy.mjs`): the page must
   be `http`/`https` and its hostname must not match (or be a subdomain of) an excluded domain. If
   either check fails, nothing is extracted and nothing is sent.
3. If the page passes, the popup asks the content script (already passively injected on every
   http(s) page, `src/content-script.js`) to extract the current URL, title, and visible text.
   The content script does nothing on its own; it only responds to that one request.
4. The popup builds the capture payload (`src/payload.mjs`) and sends it to the existing
   `POST /api/v1/capture` — the same endpoint Day 2 built. No separate/duplicate API is used.

## What it captures, and what it never does

Captured (only on a manual click): URL, page title, timestamp, and visible text (hidden and
`aria-hidden` elements, and `<script>`/`<style>`/`<noscript>`/`<template>`/`<iframe>` content, are
excluded from "visible text").

Never captured: cookies, passwords, authentication tokens, form values, typed input, or any
browsing history beyond the one page you chose to capture.

## Privacy filter

- **Excluded domains** are configured on the options page (Settings), one per line. A page is
  excluded if its hostname exactly matches an entry, or is a subdomain of one (a leading `.` or
  `*.` on an entry is ignored, so `example.com`, `.example.com` and `*.example.com` all mean the
  same thing). Matching is case-insensitive. A short, illustrative default list ships in
  `src/privacy.mjs` (`DEFAULT_EXCLUDED_DOMAINS`) covering a few obviously sensitive categories
  (webmail, a couple of banks, PayPal, healthcare.gov); it is **not** complete and you are expected
  to extend it for your own accounts and services.
- **Fails closed.** A URL the filter cannot parse is treated as excluded, and only `http`/`https`
  pages are ever capturable (`chrome://`, `file://`, extension pages, etc. are not).
- **Incognito is not captured.** Chrome does not run extensions in Incognito windows unless you
  explicitly enable "Allow in Incognito" for the extension; this extension does not request that,
  and nothing in it overrides that default.

See `docs/privacy.md` ("Client-side capture") for the full picture, including what the *backend*
additionally validates once a capture reaches it.

## Settings

There is no account system yet (see `docs/architecture.md`, "Authentication and device
registration" under future work). Open the options page and:

1. Create a development user and device with the `psql` commands in `README.md` ("Try it").
2. Paste the resulting user ID and device ID into Settings.
3. Set the API base URL (defaults to `http://127.0.0.1:8000`).
4. Review/extend the excluded-domains list.

These are stored in `chrome.storage.local`, unencrypted, on your machine only.

## Loading it in Chrome

1. `chrome://extensions` → enable **Developer mode**.
2. **Load unpacked** → select this `extension/` directory.
3. Open the extension's options page and configure it (above) before capturing.

## Architecture

```
popup.js  ──(chrome.tabs.sendMessage)──►  src/content-script.js   (extracts url/title/text)
  │
  ├─ src/privacy.mjs   canCapture(url, excludedDomains)   — pure, no chrome.* / DOM
  ├─ src/payload.mjs   buildCapturePayload({...})         — pure, no chrome.* / DOM
  └─ fetch(...)  ──►  POST /api/v1/capture   (existing Day 2 endpoint, unmodified contract)
```

`src/privacy.mjs` and `src/payload.mjs` have no dependency on `chrome.*` or the DOM, so they are
imported directly by the Node tests in `tests/`. `src/content-script.js` and `popup.js`/`options.js`
use browser-only APIs (`document`, `chrome.tabs`, `chrome.storage`) and cannot run under Node; they
have been reviewed and syntax-checked (`node --check`) but not executed. There is no background
service worker: a static content script plus a popup is sufficient for manual, click-triggered
capture, and MV3 does not require one for this.

## Tests

```
node --test tests/privacy.test.mjs tests/payload.test.mjs
```

These genuinely execute (Node's built-in test runner, no dependencies to install) and cover the
privacy filter and payload construction in isolation — including that sensitive fields (cookies,
passwords, form values, ...) passed into `buildCapturePayload` never appear in its output, since it
always builds a fresh object from a fixed, named set of fields.

Manual, browser-only checks (loading the extension, clicking Capture against a real backend,
confirming the popup's excluded/success/error states) have not been performed in this environment,
which has no Chrome to run.

## Known limitations

- Manual capture only; no autonomous/always-on capture.
- `manifest.json`'s `host_permissions` are static (`127.0.0.1:8000`, `localhost:8000`). Changing
  the API base URL in Settings to a different origin also requires updating `manifest.json`, or the
  extension's fetch will be blocked by the browser's cross-origin rules.
- No PII/secret redaction of the captured text — see `docs/privacy.md`.
- No icon is bundled; Chrome shows its default placeholder icon.
