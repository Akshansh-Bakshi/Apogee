// Both search APIs return ranked chunks. Their first occurrence is each page's best-ranked chunk.
export function groupPages(results) {
  const pages = new Map();
  for (const hit of results) {
    if (hit?.page_id && !pages.has(hit.page_id)) pages.set(hit.page_id, hit);
  }
  return [...pages.values()];
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
