import { buildCapturePayload } from "./src/payload.mjs";
import { canCapture } from "./src/privacy.mjs";

const statusEl = document.getElementById("status");
const buttonEl = document.getElementById("capture");

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = kind || "";
}

async function getConfig() {
  const stored = await chrome.storage.local.get(["apiBaseUrl", "userId", "deviceId", "excludedDomains"]);
  return {
    apiBaseUrl: stored.apiBaseUrl || "http://127.0.0.1:8000",
    userId: stored.userId || "",
    deviceId: stored.deviceId || "",
    excludedDomains: stored.excludedDomains || [],
  };
}

buttonEl.addEventListener("click", async () => {
  buttonEl.disabled = true;
  setStatus("Capturing…");
  try {
    const config = await getConfig();
    if (!config.userId || !config.deviceId) {
      setStatus("Set your user ID and device ID in Settings first.", "error");
      return;
    }

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) {
      setStatus("No active tab.", "error");
      return;
    }
    // The gate: an excluded or non-http(s) page is never extracted, let alone sent.
    if (!canCapture(tab.url, config.excludedDomains)) {
      setStatus("This page is excluded from capture.", "error");
      return;
    }

    const extracted = await chrome.tabs.sendMessage(tab.id, { type: "APOGEE_EXTRACT" });
    if (!extracted) {
      setStatus("Could not read this page (try reloading it).", "error");
      return;
    }

    const payload = buildCapturePayload({
      userId: config.userId,
      deviceId: config.deviceId,
      url: extracted.url,
      title: extracted.title,
      text: extracted.text,
      occurredAt: new Date().toISOString(),
    });

    const response = await fetch(`${config.apiBaseUrl}/api/v1/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      const result = await response.json();
      setStatus(result.page_created ? "Captured — new page." : "Captured — existing page updated.", "ok");
    } else {
      const errorBody = await response.json().catch(() => null);
      setStatus(`Capture failed (${response.status}): ${errorBody?.error?.message || "unknown error"}`, "error");
    }
  } catch (error) {
    setStatus(`Capture failed: ${error.message}`, "error");
  } finally {
    buttonEl.disabled = false;
  }
});
