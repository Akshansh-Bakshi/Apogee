import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import { DEFAULT_EXCLUDED_DOMAINS, canCapture } from "../src/privacy.mjs";

const source = readFileSync(new URL("../popup.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?\n/gm, "");

async function popupFor(stored) {
  let click;
  let extracted = 0;
  const status = { textContent: "", className: "" };
  const button = { disabled: false, addEventListener: (_type, callback) => { click = callback; } };
  const context = {
    canCapture, DEFAULT_EXCLUDED_DOMAINS,
    document: { getElementById: (id) => id === "status" ? status : button },
    chrome: {
      storage: { local: { get: async () => stored } },
      tabs: {
        query: async () => [{ id: 1, url: "https://mail.google.com/" }],
        sendMessage: async () => { extracted++; return null; },
      },
    },
  };
  vm.runInNewContext(source, context);
  await click();
  return { status: status.textContent, extracted };
}

test("absent exclusions use defaults before extraction", async () => {
  const result = await popupFor({ userId: "user", deviceId: "device" });
  assert.match(result.status, /excluded/);
  assert.equal(result.extracted, 0);
});

test("an explicitly saved empty exclusion list remains an override", async () => {
  const result = await popupFor({ userId: "user", deviceId: "device", excludedDomains: [] });
  assert.equal(result.extracted, 1);
});

test("a saved exclusion list blocks its matching domain", async () => {
  const result = await popupFor({ userId: "user", deviceId: "device", excludedDomains: ["google.com"] });
  assert.match(result.status, /excluded/);
  assert.equal(result.extracted, 0);
});
