import { ambiguityText, summaryText, topicCountText } from "./exploration.mjs";

const userInput = document.getElementById("user-id");
const button = document.getElementById("explore-button");
const status = document.getElementById("explore-status");
const summary = document.getElementById("explore-summary");
const cards = document.getElementById("topic-cards");
const recommendations = document.getElementById("recommendations");
const list = document.getElementById("recommendation-list");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function setStatus(message, kind = "") {
  status.textContent = message;
  status.className = `status ${kind}`;
}

function paragraph(text, className = "") {
  const element = document.createElement("p");
  element.className = className;
  element.textContent = text;
  return element;
}

function renderTopic(topic) {
  const card = document.createElement("article");
  card.className = "topic-card";
  const title = document.createElement("h3");
  title.textContent = topic.name;
  const date = topic.last_seen_at ? new Date(topic.last_seen_at) : null;
  const dateText = date && !Number.isNaN(date.getTime())
    ? `Latest recorded visit: ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date)}`
    : "No recorded visits for assigned pages.";
  const breadth = topic.total_subtopics
    ? `Related topic breadth: ${topic.observed_subtopics} of ${topic.total_subtopics} listed subtopics have captured pages.`
    : "No subtopics listed in this taxonomy.";
  card.append(
    title,
    paragraph(topicCountText(topic), "topic-counts"),
    paragraph(dateText, "fine-print"),
    paragraph(breadth, "fine-print"),
    paragraph(ambiguityText(topic), "ambiguity-note"),
    paragraph(`Browsing activity index: ${Number(topic.activity_index).toFixed(2)} / 1`, "activity-index"),
  );
  return card;
}

button.addEventListener("click", async () => {
  const userId = userInput.value.trim();
  if (!UUID.test(userId)) {
    setStatus("Enter a valid development user UUID above.", "error");
    userInput.focus();
    return;
  }
  sessionStorage.setItem("apogee-demo-user-id", userId);
  button.disabled = true;
  button.textContent = "Loading…";
  setStatus("Reading captured browsing evidence…", "loading");
  summary.textContent = "";
  cards.replaceChildren();
  list.replaceChildren();
  recommendations.hidden = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch(`/api/v1/topics/coverage?user_id=${encodeURIComponent(userId)}`, { signal: controller.signal });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error?.message || `Exploration failed (HTTP ${response.status}).`);
    }
    const body = await response.json();
    if (!Array.isArray(body.topics) || !Array.isArray(body.recommendations)) {
      throw new Error("The exploration service returned an unexpected response.");
    }
    summary.textContent = summaryText(body);
    if (!body.total_pages) {
      setStatus("No captured pages found for this user.");
    } else {
      setStatus(body.assigned_pages
        ? "Observed browsing activity across the fixed topic taxonomy."
        : "There is not enough embedded page content to suggest topics yet.");
      cards.replaceChildren(...body.topics.map(renderTopic));
      if (body.recommendations.length) {
        recommendations.hidden = false;
        for (const item of body.recommendations) {
          const card = document.createElement("article");
          card.className = "recommendation-card";
          const title = document.createElement("h4");
          title.textContent = item.name;
          card.append(title, paragraph(item.explanation));
          list.append(card);
        }
      } else if (body.assigned_pages) {
        recommendations.hidden = false;
        list.append(paragraph("No sparse prerequisite topics follow from the current captured evidence.", "fine-print"));
      }
    }
  } catch (error) {
    setStatus(error.name === "AbortError" ? "Exploration timed out. Please try again." : error.message, "error");
  } finally {
    clearTimeout(timeout);
    button.disabled = false;
    button.textContent = "Explore topics ↗";
  }
});
