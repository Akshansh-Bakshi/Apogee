import assert from "node:assert/strict";
import { test } from "node:test";
import { ambiguityText, summaryText, topicCountText } from "../app/ui/exploration.mjs";

test("exploration copy distinguishes absent evidence from zero learning", () => {
  assert.equal(topicCountText({ distinct_pages: 0, visits: 0 }), "No captured pages assigned directly to this topic");
  assert.equal(topicCountText({ distinct_pages: 1, visits: 2 }), "1 captured page · 2 visits");
});

test("summary presents provisional assignments and unclassified pages", () => {
  assert.equal(
    summaryText({ assigned_pages: 3, unclassified_pages: 1, total_events: 4 }),
    "3 provisional topic assignments · 1 unclassified page · 4 recorded visits"
  );
});

test("ambiguity copy labels cosine margin without calling it confidence", () => {
  const message = ambiguityText({ mean_top_two_cosine_margin: 0.12345 });
  assert.match(message, /0\.123/);
  assert.match(message, /not confidence/);
  assert.equal(
    ambiguityText({ mean_top_two_cosine_margin: null }),
    "Top-two topic margin unavailable."
  );
});
