import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_EXCLUDED_DOMAINS, canCapture, isCapturableScheme, isExcluded } from "../src/privacy.mjs";

test("http and https pages are capturable", () => {
  assert.equal(isCapturableScheme("http://example.com/a"), true);
  assert.equal(isCapturableScheme("https://example.com/a"), true);
});

test("non-http(s) schemes are not capturable", () => {
  for (const url of ["chrome://settings", "file:///etc/passwd", "about:blank", "javascript:alert(1)"]) {
    assert.equal(isCapturableScheme(url), false, url);
  }
});

test("an unparseable URL is not capturable", () => {
  assert.equal(isCapturableScheme("not a url"), false);
});

test("a domain not on the list is not excluded", () => {
  assert.equal(isExcluded("https://example.com/a", ["other.com"]), false);
});

test("an exact domain match is excluded", () => {
  assert.equal(isExcluded("https://chase.com/login", ["chase.com"]), true);
});

test("a subdomain of an excluded domain is excluded", () => {
  assert.equal(isExcluded("https://mail.google.com/mail/u/0", ["google.com"]), true);
});

test("a domain that merely contains the excluded string is NOT excluded", () => {
  assert.equal(isExcluded("https://notgoogle.com/", ["google.com"]), false);
});

test("matching is case-insensitive", () => {
  assert.equal(isExcluded("https://CHASE.com/", ["chase.COM"]), true);
});

test("a leading dot or wildcard on the excluded entry is ignored", () => {
  assert.equal(isExcluded("https://mail.google.com/", [".google.com"]), true);
  assert.equal(isExcluded("https://mail.google.com/", ["*.google.com"]), true);
});

test("an empty excluded list excludes nothing", () => {
  assert.equal(isExcluded("https://example.com/", []), false);
});

test("an unparseable URL is excluded (fail closed)", () => {
  assert.equal(isExcluded("not a url", ["example.com"]), true);
});

test("default excluded domains are a non-empty, deduplicated, frozen list", () => {
  assert.ok(DEFAULT_EXCLUDED_DOMAINS.length > 0);
  assert.equal(new Set(DEFAULT_EXCLUDED_DOMAINS).size, DEFAULT_EXCLUDED_DOMAINS.length);
  assert.ok(Object.isFrozen(DEFAULT_EXCLUDED_DOMAINS));
});

test("canCapture requires both a capturable scheme and an unexcluded domain", () => {
  assert.equal(canCapture("https://example.com/", []), true);
  assert.equal(canCapture("https://chase.com/", ["chase.com"]), false);
  assert.equal(canCapture("chrome://settings", []), false);
});
