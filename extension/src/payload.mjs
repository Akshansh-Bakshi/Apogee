// Pure payload construction: builds exactly the object POST /api/v1/capture accepts. Always
// returns a FRESH object containing only these named keys, so anything else on the input
// (cookies, passwords, form values, ...) can never leak through into what gets sent.

export function buildCapturePayload({ userId, deviceId, url, title, text, occurredAt, sessionId }) {
  if (!userId || !deviceId) throw new Error("userId and deviceId are required");
  if (!url) throw new Error("url is required");

  const payload = {
    user_id: userId,
    device_id: deviceId,
    url,
    title: title || null,
    occurred_at: occurredAt || new Date().toISOString(),
  };
  if (sessionId) payload.session_id = sessionId;
  if (text && text.trim()) payload.content = text; // omitted entirely when there is no visible text

  return payload;
}
