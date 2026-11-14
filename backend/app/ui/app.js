import {
  canShowMore, isCurrentSearch, mergePageResults, pageSearchPayload,
  safePageUrl, searchStatus,
} from "./results.mjs";

const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const userInput = document.getElementById("user-id");
const button = document.getElementById("search-button");
const status = document.getElementById("status");
const count = document.getElementById("result-count");
const results = document.getElementById("results");
const note = document.getElementById("truncation-note");
const showMore = document.getElementById("show-more");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let activeRequestId = 0;
let activeController = null;
let searchContext = null;

userInput.value = sessionStorage.getItem("apogee-demo-user-id") || "";

function setStatus(message, kind = "") {
  status.textContent = message;
  status.className = `status ${kind}`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function makeCard(hit) {
  const card = document.createElement("article");
  card.className = "result-card";

  const meta = document.createElement("div");
  meta.className = "result-meta";
  const domain = document.createElement("span");
  domain.textContent = hit.domain || "Saved page";
  meta.append(domain);
  const seen = formatDate(hit.last_seen_at);
  if (seen) {
    const date = document.createElement("span");
    date.textContent = `Last seen ${seen}`;
    meta.append(date);
  }

  const title = document.createElement("h3");
  title.textContent = hit.title || hit.domain || "Untitled page";
  const url = document.createElement("p");
  url.className = "result-url";
  url.textContent = hit.canonical_url || "";
  const preview = document.createElement("p");
  preview.className = "preview";
  preview.textContent = hit.text_preview || "No text preview available.";

  card.append(meta, title, url, preview);
  const href = safePageUrl(hit.canonical_url);
  if (href) {
    const link = document.createElement("a");
    link.className = "open-link";
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Open page ↗";
    card.append(link);
  }
  return card;
}

async function fetchPageBatch() {
  if (!searchContext || activeController) return;
  const context = searchContext;
  const requestId = ++activeRequestId;
  const offset = context.pages.length;
  const endpoint = "/api/v1/search/pages";

  button.disabled = true;
  showMore.disabled = true;
  button.textContent = offset ? "Loading…" : "Searching…";
  setStatus(offset ? "Loading more possible matches…" : "Searching your saved pages…", "loading");
  const controller = new AbortController();
  activeController = controller;
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pageSearchPayload(context.userId, context.query, context.mode, offset)),
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error?.message || `Search failed (HTTP ${response.status}).`);
    }
    const body = await response.json();
    if (!Array.isArray(body.results)) throw new Error("The search service returned an unexpected response.");
    if (requestId !== activeRequestId) return;
    if (!isCurrentSearch(requestId, activeRequestId, searchContext, body)) {
      throw new Error("The search service returned results for a different query or mode.");
    }
    const pages = mergePageResults(context.pages, body.results);
    context.pages = pages;
    count.textContent = `${pages.length} ${pages.length === 1 ? "page" : "pages"}`;
    if (!pages.length) {
      setStatus(searchStatus(context.mode, 0));
    } else {
      setStatus(searchStatus(context.mode, pages.length));
      results.replaceChildren(...pages.map(makeCard));
    }
    showMore.hidden = !canShowMore(body, pages.length);
    note.hidden = pages.length < 50 || !body.truncated;
  } catch (error) {
    if (requestId !== activeRequestId) return;
    setStatus(error.name === "AbortError" ? "Search timed out. Please try again." : error.message, "error");
    showMore.hidden = !context.pages.length;
  } finally {
    clearTimeout(timeout);
    if (requestId === activeRequestId) {
      activeController = null;
      button.disabled = false;
      showMore.disabled = false;
      button.textContent = "Search ↗";
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  const userId = userInput.value.trim();
  if (!query) { setStatus("Enter a search query.", "error"); queryInput.focus(); return; }
  if (!UUID.test(userId)) { setStatus("Enter a valid development user UUID.", "error"); userInput.focus(); return; }
  sessionStorage.setItem("apogee-demo-user-id", userId);
  activeController?.abort();
  activeController = null;
  activeRequestId += 1;
  searchContext = { userId, query, mode: form.elements.mode.value, pages: [] };
  results.replaceChildren();
  count.textContent = "";
  showMore.hidden = true;
  note.hidden = true;
  fetchPageBatch();
});

showMore.addEventListener("click", fetchPageBatch);

form.elements.mode.forEach((input) => input.addEventListener("change", () => {
  activeController?.abort();
  activeController = null;
  activeRequestId += 1;
  searchContext = null;
  results.replaceChildren();
  count.textContent = "";
  showMore.hidden = true;
  note.hidden = true;
  button.disabled = false;
  button.textContent = "Search ↗";
  setStatus("Search mode changed. Submit the query to see possible matches.");
}));
