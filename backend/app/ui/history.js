import { groupEventsByLocalDate, historyParameters } from "./history.mjs";
import { safePageUrl } from "./results.mjs";

const userInput = document.getElementById("user-id");
const button = document.getElementById("timeline-button");
const startInput = document.getElementById("history-start-date");
const endInput = document.getElementById("history-end-date");
const topicInput = document.getElementById("history-topic");
const status = document.getElementById("timeline-status");
const eventsContainer = document.getElementById("timeline-events");
const limitNote = document.getElementById("timeline-limit-note");
const timezoneLabel = document.getElementById("timeline-timezone");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const displayTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

timezoneLabel.textContent = `Display timezone: ${displayTimeZone}. API timestamps represent the recorded event instant.`;

function setStatus(message, kind = "") {
  status.textContent = message;
  status.className = `status ${kind}`;
}

function appendText(parent, tag, text, className = "") {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  parent.append(element);
  return element;
}

function renderEvent(event) {
  const card = document.createElement("article");
  card.className = "history-card";
  const top = document.createElement("div");
  top.className = "history-card-top";
  appendText(
    top, "time",
    new Intl.DateTimeFormat(undefined, {
      timeZone: displayTimeZone, hour: "numeric", minute: "2-digit",
    }).format(new Date(event.occurred_at)),
  );
  appendText(top, "span", event.domain || "Saved page", "history-domain");
  card.append(top);
  appendText(card, "h4", event.title || event.domain || "Untitled page");
  const topic = event.topic_status === "suggested"
    ? `Provisional topic: ${event.provisional_topic_id}`
    : event.topic_status === "unclassified"
      ? `Topic unclassified: ${event.topic_reason || "insufficient evidence"}`
      : "Topic unavailable";
  appendText(card, "p", topic, "history-topic");
  const href = safePageUrl(event.canonical_url);
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.className = "open-link";
    link.textContent = "Open page ↗";
    card.append(link);
  }
  return card;
}

function updateTopicOptions(topics) {
  const selected = topicInput.value;
  const options = [new Option("All topics", "")];
  for (const topic of topics) options.push(new Option(topic.name, topic.id));
  topicInput.replaceChildren(...options);
  if ([...topicInput.options].some((option) => option.value === selected)) {
    topicInput.value = selected;
  }
}

button.addEventListener("click", async () => {
  const userId = userInput.value.trim();
  if (!UUID.test(userId)) {
    setStatus("Enter a valid development user UUID above.", "error");
    userInput.focus();
    return;
  }
  let parameters;
  try {
    parameters = historyParameters(
      userId, startInput.value, endInput.value, topicInput.value,
    );
  } catch (error) {
    setStatus(error.message, "error");
    return;
  }
  sessionStorage.setItem("apogee-demo-user-id", userId);
  button.disabled = true;
  button.textContent = "Loading…";
  eventsContainer.replaceChildren();
  limitNote.hidden = true;
  setStatus("Loading recorded visits…", "loading");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch(`/api/v1/history?${parameters}`, { signal: controller.signal });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error?.message || `Timeline failed (HTTP ${response.status}).`);
    }
    const body = await response.json();
    if (!Array.isArray(body.events) || !Array.isArray(body.topics)) {
      throw new Error("The timeline service returned an unexpected response.");
    }
    updateTopicOptions(body.topics);
    if (!body.events.length) {
      setStatus("No recorded visits match these filters.");
    } else {
      setStatus(`${body.result_count} recorded ${body.result_count === 1 ? "visit" : "visits"}, newest first.`);
      for (const group of groupEventsByLocalDate(body.events, displayTimeZone)) {
        const section = document.createElement("section");
        section.className = "history-day";
        const labelDate = new Date(`${group.date}T12:00:00`);
        appendText(
          section, "h3",
          new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(labelDate),
        );
        const list = document.createElement("div");
        list.className = "history-day-events";
        list.replaceChildren(...group.events.map(renderEvent));
        section.append(list);
        eventsContainer.append(section);
      }
    }
    limitNote.hidden = !body.truncated;
  } catch (error) {
    setStatus(error.name === "AbortError" ? "Timeline timed out. Please try again." : error.message, "error");
  } finally {
    clearTimeout(timeout);
    button.disabled = false;
    button.textContent = "Load timeline ↗";
  }
});
