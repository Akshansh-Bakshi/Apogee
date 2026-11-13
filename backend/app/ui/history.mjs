export function localCalendarDateKey(timestamp, timeZone) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export function groupEventsByLocalDate(events, timeZone) {
  const groups = new Map();
  for (const event of events) {
    const key = localCalendarDateKey(event.occurred_at, timeZone);
    if (!key) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  return [...groups.entries()].map(([date, items]) => ({ date, events: items }));
}

function localMidnightIso(dateText, addDays = 0) {
  if (!dateText) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateText);
  if (!match) throw new Error("Use valid calendar dates.");
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + addDays);
  if (Number.isNaN(date.getTime())) throw new Error("Use valid calendar dates.");
  return date.toISOString();
}

export function historyParameters(userId, startDate, endDate, topicId, limit = 100) {
  const parameters = new URLSearchParams({ user_id: userId, limit: String(limit) });
  const start = localMidnightIso(startDate);
  const end = localMidnightIso(endDate, 1);
  if (start && end && new Date(end) <= new Date(start)) {
    throw new Error("The through date must be on or after the from date.");
  }
  if (start) parameters.set("start_at", start);
  if (end) parameters.set("end_at", end);
  if (topicId) parameters.set("topic_id", topicId);
  return parameters;
}
