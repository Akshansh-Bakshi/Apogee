// Both search APIs return ranked chunks. Their first occurrence is each page's best-ranked chunk.
export function groupPages(results) {
  const pages = new Map();
  for (const hit of results) {
    if (hit?.page_id && !pages.has(hit.page_id)) pages.set(hit.page_id, hit);
  }
  return [...pages.values()];
}

export const PAGE_BATCH_SIZE = 10;
export const MAX_PAGE_RESULTS = 50;

export function pageSearchPayload(userId, query, mode, offset = 0) {
  return {
    user_id: userId,
    query,
    mode,
    limit: Math.min(PAGE_BATCH_SIZE, MAX_PAGE_RESULTS - offset),
    offset,
  };
}

export function mergePageResults(existing, incoming) {
  return groupPages([...existing, ...incoming]).slice(0, MAX_PAGE_RESULTS);
}

export function canShowMore(response, displayedCount) {
  return Boolean(response?.truncated) && displayedCount < MAX_PAGE_RESULTS;
}

export function isCurrentSearch(requestId, activeRequestId, context, response) {
  return requestId === activeRequestId
    && response?.query === context?.query
    && response?.mode === context?.mode;
}

export function searchStatus(mode, resultCount) {
  if (resultCount) return mode === "lexical"
    ? "Possible keyword matches — matching terms do not establish page relevance."
    : "Possible semantic matches — these are nearest neighbors; relevance is uncertain.";
  return mode === "lexical"
    ? "No chunks matched this full-text query. This does not establish that the topic is absent from your saved pages."
    : "No embedded chunks were returned. There may be no searchable embedded pages for this user yet.";
}

// Captured URLs are untrusted data. Only web URLs become clickable links.
export function safePageUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
