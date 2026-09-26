import { DEFAULT_EXCLUDED_DOMAINS } from "./src/privacy.mjs";

const fields = {
  apiBaseUrl: document.getElementById("apiBaseUrl"),
  userId: document.getElementById("userId"),
  deviceId: document.getElementById("deviceId"),
  excludedDomains: document.getElementById("excludedDomains"),
};
const statusEl = document.getElementById("status");

async function load() {
  const stored = await chrome.storage.local.get(["apiBaseUrl", "userId", "deviceId", "excludedDomains"]);
  fields.apiBaseUrl.value = stored.apiBaseUrl || "http://127.0.0.1:8000";
  fields.userId.value = stored.userId || "";
  fields.deviceId.value = stored.deviceId || "";
  fields.excludedDomains.value = (stored.excludedDomains || DEFAULT_EXCLUDED_DOMAINS).join("\n");
}

document.getElementById("save").addEventListener("click", async () => {
  const excludedDomains = fields.excludedDomains.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  await chrome.storage.local.set({
    apiBaseUrl: fields.apiBaseUrl.value.trim() || "http://127.0.0.1:8000",
    userId: fields.userId.value.trim(),
    deviceId: fields.deviceId.value.trim(),
    excludedDomains,
  });
  statusEl.textContent = "Saved.";
  setTimeout(() => (statusEl.textContent = ""), 2000);
});

load();
