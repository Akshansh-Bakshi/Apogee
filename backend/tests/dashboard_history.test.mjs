import assert from "node:assert/strict";
import { test } from "node:test";
import {
  groupEventsByLocalDate,
  historyParameters,
  localCalendarDateKey,
} from "../app/ui/history.mjs";

test("local calendar grouping respects the explicit display timezone", () => {
  const first = { occurred_at: "2026-01-01T23:30:00Z", event_id: "first" };
  const second = { occurred_at: "2026-01-02T00:30:00Z", event_id: "second" };
  assert.equal(localCalendarDateKey(first.occurred_at, "UTC"), "2026-01-01");
  assert.equal(localCalendarDateKey(first.occurred_at, "Asia/Kolkata"), "2026-01-02");
  const groups = groupEventsByLocalDate([first, second], "Asia/Kolkata");
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0].events, [first, second]);
});

test("history query uses an exclusive day-after boundary and preserves topic", () => {
  const parameters = historyParameters(
    "11111111-1111-1111-1111-111111111111",
    "2026-11-01", "2026-11-01", "algorithms", 100,
  );
  assert.equal(parameters.get("topic_id"), "algorithms");
  assert.equal(parameters.get("limit"), "100");
  assert.ok(new Date(parameters.get("end_at")) > new Date(parameters.get("start_at")));
});

test("history query rejects a reversed local calendar range", () => {
  assert.throws(
    () => historyParameters("user", "2026-11-02", "2026-11-01", "", 100),
    /through date/,
  );
});
