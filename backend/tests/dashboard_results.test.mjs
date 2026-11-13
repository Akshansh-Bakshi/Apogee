import assert from "node:assert/strict";
import { test } from "node:test";
import { groupPages, safePageUrl } from "../app/ui/results.mjs";

test("groups ranked chunks by page ID, retaining first chunk and stable page order", () => {
  const hits = [
    { page_id: "a", chunk_id: "a-best", text_preview: "best" },
    { page_id: "b", chunk_id: "b-best" },
    { page_id: "a", chunk_id: "a-worse", text_preview: "worse" },
    { page_id: "c", chunk_id: "c-best" },
  ];
  assert.deepEqual(groupPages(hits).map((hit) => hit.chunk_id), ["a-best", "b-best", "c-best"]);
  assert.deepEqual(groupPages([]), []);
});

test("only HTTP(S) canonical URLs are offered as open-page links", () => {
  assert.equal(safePageUrl("https://example.com/page"), "https://example.com/page");
  assert.equal(safePageUrl("javascript:alert(1)"), null);
  assert.equal(safePageUrl("data:text/html,evil"), null);
  assert.equal(safePageUrl("not a URL"), null);
});
