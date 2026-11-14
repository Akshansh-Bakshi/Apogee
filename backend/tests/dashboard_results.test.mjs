import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MAX_PAGE_RESULTS, PAGE_BATCH_SIZE, canShowMore, groupPages, isCurrentSearch,
  mergePageResults, pageSearchPayload, safePageUrl, searchStatus,
} from "../app/ui/results.mjs";

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

test("search copy treats returned hits as possible and distinguishes empty modes", () => {
  assert.match(searchStatus("semantic", 2), /relevance is uncertain/);
  assert.match(searchStatus("lexical", 2), /do not establish page relevance/);
  assert.match(searchStatus("semantic", 0), /No embedded chunks/);
  assert.match(searchStatus("lexical", 0), /does not establish that the topic is absent/);
});

test("page API results keep their best-chunk order and remain compatible with grouping", () => {
  const pages = [
    { page_id: "b", chunk_id: "b-best", similarity: 0.8 },
    { page_id: "a", chunk_id: "a-best", similarity: 0.7 },
    { page_id: "c", chunk_id: "c-best", similarity: 0.6 },
  ];
  assert.deepEqual(groupPages(pages), pages);
  assert.match(searchStatus("semantic", pages.length), /relevance is uncertain/);
});

test("requests ten pages initially and advances through bounded result windows", () => {
  assert.equal(PAGE_BATCH_SIZE, 10);
  assert.deepEqual(pageSearchPayload("user", "game development", "semantic"), {
    user_id: "user", query: "game development", mode: "semantic", limit: 10, offset: 0,
  });
  assert.deepEqual(pageSearchPayload("user", "game development", "lexical", 10), {
    user_id: "user", query: "game development", mode: "lexical", limit: 10, offset: 10,
  });
  assert.equal(pageSearchPayload("user", "q", "semantic", 45).limit, 5);
});

test("expansion preserves rank order, removes duplicates, and stops at fifty", () => {
  const first = Array.from({ length: 10 }, (_, i) => ({ page_id: `p${i}` }));
  const next = [{ page_id: "p9" }, ...Array.from({ length: 45 }, (_, i) => ({ page_id: `p${i + 10}` }))];
  const merged = mergePageResults(first, next);
  assert.equal(merged.length, MAX_PAGE_RESULTS);
  assert.deepEqual(merged.slice(0, 12).map((page) => page.page_id),
    Array.from({ length: 12 }, (_, i) => `p${i}`));
  assert.equal(canShowMore({ truncated: true }, 10), true);
  assert.equal(canShowMore({ truncated: false }, 10), false);
  assert.equal(canShowMore({ truncated: true }, 50), false);
  assert.deepEqual(mergePageResults([], []), []);
});

test("stale or mode-mismatched asynchronous responses are rejected", () => {
  const context = { query: "game development", mode: "semantic" };
  assert.equal(isCurrentSearch(4, 4, context, { query: "game development", mode: "semantic" }), true);
  assert.equal(isCurrentSearch(3, 4, context, { query: "game development", mode: "semantic" }), false);
  assert.equal(isCurrentSearch(4, 4, context, { query: "game development", mode: "lexical" }), false);
  assert.equal(isCurrentSearch(4, 4, context, { query: "different", mode: "semantic" }), false);
});
