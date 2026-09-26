// Pure privacy-filter logic: no chrome.* APIs, no DOM. Imported by the extension pages (via
// <script type="module">) and directly by the Node tests in ../tests/.

// A deliberately short starting point covering a few obviously sensitive categories (email,
// banking, health, government). This is NOT a complete list; users are expected to extend it
// from the options page for their own accounts and services.
export const DEFAULT_EXCLUDED_DOMAINS = Object.freeze([
  "mail.google.com",
  "outlook.live.com",
  "accounts.google.com",
  "chase.com",
  "bankofamerica.com",
  "paypal.com",
  "healthcare.gov",
]);

/** Only http/https pages are ever capturable; chrome://, file://, about: and similar are not. */
export function isCapturableScheme(pageUrl) {
  try {
    const { protocol } = new URL(pageUrl);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * True if `pageUrl`'s hostname exactly matches, or is a subdomain of, any entry in
 * `excludedDomains`. Matching is case-insensitive; a leading "*." or "." on an entry is ignored,
 * so "example.com", ".example.com" and "*.example.com" all behave the same. An unparseable URL is
 * treated as excluded (fail closed: never capture a page that cannot be classified).
 */
export function isExcluded(pageUrl, excludedDomains) {
  let hostname;
  try {
    hostname = new URL(pageUrl).hostname.toLowerCase();
  } catch {
    return true;
  }
  return excludedDomains.some((raw) => {
    const pattern = String(raw).trim().toLowerCase().replace(/^\*\.|^\./, "");
    if (!pattern) return false;
    return hostname === pattern || hostname.endsWith(`.${pattern}`);
  });
}

/** The single gate a capture must pass before anything is extracted or sent. */
export function canCapture(pageUrl, excludedDomains) {
  return isCapturableScheme(pageUrl) && !isExcluded(pageUrl, excludedDomains);
}
