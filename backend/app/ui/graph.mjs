export const SVG = "http://www.w3.org/2000/svg";
export const SCOPE = "Based on overall captured browsing history. The current search query does not affect these suggestions.";
export const POSITIONS = {
  programming: [100, 100], algorithms: [300, 80], "web-development": [300, 230],
  databases: [100, 350], "information-retrieval": [300, 380],
  "machine-learning": [530, 90], "cloud-systems": [530, 245], "security-privacy": [530, 400],
};

export function activityExplanation(topic) {
  const breadth = topic.total_subtopics ? topic.observed_subtopics / topic.total_subtopics : 0;
  return `Activity index ${Number(topic.activity_index || 0).toFixed(2)} / 1 combines direct pages (45%), visits (25%), recency (20%) and related-topic breadth (10%). Related topics contribute ${(0.10 * breadth).toFixed(2)}. ${topic.distinct_pages === 0 ? "There are no directly assigned pages; related-topic evidence can still raise the index." : "This describes captured browsing activity."} It does not measure knowledge or mastery.`;
}

export function modelEvidence(node) {
  const f = node.model?.evidence;
  const novelty = node.evidence.distinct_pages === 0
    ? "Novel relative to this capture corpus: no directly assigned pages. This does not establish a user's interests or knowledge."
    : "This topic already has directly assigned pages.";
  if (!f) return novelty;
  return `${novelty} Model inputs: ${f.candidate_page_count} direct pages, ${f.candidate_visit_count} eligible visits; recency ${f.candidate_recency_days == null ? "unavailable" : `${Number(f.candidate_recency_days).toFixed(1)} days`}; ${f.observed_prerequisite_count}/${f.candidate_prerequisite_count} prerequisites observed; ${f.observed_topic_breadth} topics observed overall. Prerequisite-gap flag: ${f.candidate_is_graph_gap ? "yes" : "no"}; direct-extension flag: ${f.candidate_is_direct_extension ? "yes" : "no"}. These are observed inputs, not a causal explanation of the learned rank. A high rank can still have a low synthetic grade.`;
}

export function graphData(coverage, definitions, model) {
  if (!Array.isArray(coverage?.topics) || !Array.isArray(definitions) || coverage.topics.length !== 8 || definitions.length !== 8) {
    throw new Error("The topic graph needs eight taxonomy definitions and evidence rows.");
  }
  const evidence = new Map(coverage.topics.map(topic => [topic.topic_id, topic]));
  const ids = new Set(definitions.map(topic => topic.id));
  if (ids.size !== 8 || evidence.size !== 8 || [...ids].some(id => !evidence.has(id))) throw new Error("Topic graph taxonomy mismatch.");
  const edges = definitions.flatMap(topic => (topic.prerequisites || []).map(parent => {
    if (!ids.has(parent)) throw new Error("Unknown prerequisite in taxonomy.");
    return { from: parent, to: topic.id };
  }));
  const ranked = model?.source === "model" && Array.isArray(model.ranking) && model.taxonomy_version === coverage.taxonomy_version
    ? new Map(model.ranking.map(row => [row.topic_id, row])) : new Map();
  const source = ranked.size === 8 && [...ranked.keys()].every(id => ids.has(id)) ? "model" : "rule_based";
  const ruleIds = new Set((model?.rule_recommendations || coverage.recommendations || []).map(row => row.topic_id));
  return {
    nodes: definitions.map(topic => ({ ...topic, evidence: evidence.get(topic.id), model: source === "model" ? ranked.get(topic.id) : null,
      highlighted: source === "model" ? ranked.get(topic.id)?.rank <= 3 : ruleIds.has(topic.id) })),
    edges, source,
  };
}

export function detailLines(node, graph) {
  const item = node.evidence;
  const date = item.last_seen_at ? new Date(item.last_seen_at) : null;
  const latest = date && !Number.isNaN(date.getTime())
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
    : "No recorded visit for assigned pages";
  const parents = node.prerequisites?.length ? node.prerequisites.map(id => graph.nodes.find(t => t.id === id)?.name || id).join(", ") : "None";
  const children = graph.edges.filter(edge => edge.from === node.id).map(edge => graph.nodes.find(t => t.id === edge.to)?.name || edge.to).join(", ") || "None";
  return [node.description, `${item.distinct_pages} assigned captured pages · ${item.visits} recorded visits`,
    `Last observed activity: ${latest}`, "Topic assignment: provisional zero-shot BGE suggestion",
    `Prerequisites: ${parents}`, `Directly related successors: ${children}`,
    node.model ? `Model rank ${node.model.rank} of 8 · expected synthetic rubric grade ${Number(node.model.expected_synthetic_grade).toFixed(3)} of 2. This is not confidence or real-world usefulness.`
      : "Model grade unavailable. Any highlighted suggestion follows the fixed prerequisite rule.",
    SCOPE, activityExplanation(item), modelEvidence(node),
  ];
}

export function graphStatus(graph, model) {
  if (graph.source === "model") return `${SCOPE} The three outlined topics are highest in the synthetic-trained ranking. Scores are expected synthetic rubric grades, not confidence or mastery.`;
  const reason = model?.fallback_reason ? ` (${model.fallback_reason.replaceAll("_", " ")})` : "";
  return `Model ranking unavailable${reason}. Outlined topics follow the existing prerequisite rule; no captured evidence does not mean not learned.`;
}
