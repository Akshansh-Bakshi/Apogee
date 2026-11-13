export function topicCountText(topic) {
  if (!topic.distinct_pages) return "No captured pages assigned directly to this topic";
  return `${topic.distinct_pages} captured ${topic.distinct_pages === 1 ? "page" : "pages"} · ${topic.visits} ${topic.visits === 1 ? "visit" : "visits"}`;
}

export function summaryText(data) {
  return `${data.assigned_pages} provisional topic ${data.assigned_pages === 1 ? "assignment" : "assignments"} · ${data.unclassified_pages} unclassified ${data.unclassified_pages === 1 ? "page" : "pages"} · ${data.total_events} recorded visits`;
}

export function ambiguityText(topic) {
  if (topic.mean_top_two_cosine_margin == null) {
    return "Top-two topic margin unavailable.";
  }
  return `Mean top-two cosine margin: ${Number(topic.mean_top_two_cosine_margin).toFixed(3)}. Smaller means the nearest alternative topic was closer; this is not confidence.`;
}
