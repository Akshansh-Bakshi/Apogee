import assert from "node:assert/strict";
import { test } from "node:test";
import { buildCapturePayload } from "../src/payload.mjs";

const BASE = {
  userId: "11111111-1111-1111-1111-111111111111",
  deviceId: "22222222-2222-2222-2222-222222222222",
  url: "https://example.com/article",
  title: "An article",
  text: "Some visible page text, long enough to be meaningful.",
  occurredAt: "2026-01-01T12:00:00Z",
};

test("builds exactly the fields the capture API accepts", () => {
  const payload = buildCapturePayload(BASE);
  assert.deepEqual(
    Object.keys(payload).sort(),
    ["content", "device_id", "occurred_at", "title", "url", "user_id"].sort()
  );
});

test("maps camelCase input to the API's snake_case fields", () => {
  const payload = buildCapturePayload(BASE);
  assert.equal(payload.user_id, BASE.userId);
  assert.equal(payload.device_id, BASE.deviceId);
  assert.equal(payload.occurred_at, BASE.occurredAt);
  assert.equal(payload.content, BASE.text);
});

test("omits content entirely when there is no visible text", () => {
  const payload = buildCapturePayload({ ...BASE, text: "" });
  assert.equal("content" in payload, false);
});

test("omits content when text is only whitespace", () => {
  const payload = buildCapturePayload({ ...BASE, text: "   \n\t  " });
  assert.equal("content" in payload, false);
});

test("a missing title becomes null, not omitted", () => {
  const payload = buildCapturePayload({ ...BASE, title: "" });
  assert.equal(payload.title, null);
});

test("session_id is included only when provided", () => {
  const withSession = buildCapturePayload({ ...BASE, sessionId: "33333333-3333-3333-3333-333333333333" });
  assert.equal(withSession.session_id, "33333333-3333-3333-3333-333333333333");

  const withoutSession = buildCapturePayload(BASE);
  assert.equal("session_id" in withoutSession, false);
});

test("defaults occurred_at to now when not provided", () => {
  const before = Date.now();
  const payload = buildCapturePayload({ ...BASE, occurredAt: undefined });
  const parsed = Date.parse(payload.occurred_at);
  assert.ok(parsed >= before && parsed <= Date.now() + 1000);
});

test("extra/sensitive fields on the input never appear in the output", () => {
  const dirty = {
    ...BASE,
    cookies: "sid=abc123",
    password: "hunter2",
    formValues: { card: "4111111111111111" },
    authToken: "Bearer abc123",
  };
  const payload = buildCapturePayload(dirty);
  for (const key of ["cookies", "password", "formValues", "authToken", "form_values", "auth_token"]) {
    assert.equal(key in payload, false, key);
  }
});

test("throws when userId or deviceId is missing", () => {
  assert.throws(() => buildCapturePayload({ ...BASE, userId: "" }));
  assert.throws(() => buildCapturePayload({ ...BASE, deviceId: "" }));
});

test("throws when url is missing", () => {
  assert.throws(() => buildCapturePayload({ ...BASE, url: "" }));
});
