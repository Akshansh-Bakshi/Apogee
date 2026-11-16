import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { graphData, detailLines, graphStatus, SCOPE, POSITIONS, activityExplanation, modelEvidence } from "../app/ui/graph.mjs";

const definitions = [
  {id:"programming", name:"Programming", description:"Code", prerequisites:[]},
  {id:"algorithms", name:"Algorithms", description:"Algorithms", prerequisites:["programming"]},
  {id:"databases", name:"Databases", description:"SQL", prerequisites:[]},
  {id:"information-retrieval", name:"Information retrieval", description:"Search", prerequisites:["databases"]},
  {id:"machine-learning", name:"Machine learning", description:"Models", prerequisites:[]},
  {id:"cloud-systems", name:"Cloud systems", description:"Cloud", prerequisites:[]},
  {id:"web-development", name:"Web development", description:"Web", prerequisites:["programming"]},
  {id:"security-privacy", name:"Security and privacy", description:"Privacy", prerequisites:[]},
];
const coverage = { taxonomy_version:"apogee-technical-v1", topics:definitions.map((item,i) => ({
  topic_id:item.id, name:item.name, distinct_pages:i ? 0 : 2, visits:i ? 0 : 3, last_seen_at:null,
})), recommendations:[{topic_id:"databases"}] };
const model = { source:"model", taxonomy_version:coverage.taxonomy_version,
  ranking:definitions.map((item,i) => ({topic_id:item.id, rank:i+1, expected_synthetic_grade:.4})),
  rule_recommendations:coverage.recommendations };

test("all eight topics render; arrows use only directed frozen prerequisites", () => {
  const graph = graphData(coverage, definitions, model);
  assert.equal(graph.nodes.length, 8);
  assert.deepEqual(graph.edges, [{from:"programming", to:"algorithms"},
    {from:"databases", to:"information-retrieval"}, {from:"programming", to:"web-development"}]);
  assert.equal(graph.nodes.filter(n => n.highlighted).length, 3);
  assert.equal(graph.nodes.find(n => n.id === "databases").evidence.distinct_pages, 0);
  assert.equal(graph.nodes.find(n => n.id === "databases").highlighted, true);
});

test("selection details describe counts, graph links, provisional status and synthetic grade", () => {
  const graph = graphData(coverage, definitions, model);
  const lines = detailLines(graph.nodes[0], graph).join(" ");
  assert.match(lines, /2 assigned captured pages · 3 recorded visits/);
  assert.match(lines, /Directly related successors: Algorithms, Web development/);
  assert.match(lines, /provisional zero-shot BGE/);
  assert.match(lines, /expected synthetic rubric grade 0.400/);
});

test("rule fallback and absent evidence are explicit", () => {
  const graph = graphData(coverage, definitions, {source:"rule_based", fallback_reason:"artifact_missing", rule_recommendations:coverage.recommendations});
  assert.equal(graph.source, "rule_based");
  assert.deepEqual(graph.nodes.filter(n => n.highlighted).map(n => n.id), ["databases"]);
  assert.match(graphStatus(graph, {fallback_reason:"artifact_missing"}), /Model ranking unavailable.*artifact missing/);
  assert.match(detailLines(graph.nodes[2], graph).join(" "), /No recorded visit/);
  assert.throws(() => graphData({...coverage, topics:[]}, definitions, model));
});

test("graph uses safe DOM text and keyboard selection with async fallback", () => {
  const source = readFileSync(new URL("../app/ui/graph.js", import.meta.url), "utf8");
  const integration = readFileSync(new URL("../app/ui/exploration.js", import.meta.url), "utf8");
  assert.match(source, /textContent =/);
  assert.doesNotMatch(source, /innerHTML/);
  assert.match(source, /event\.key === "Enter" \|\| event\.key === " "/);
  assert.match(source, /aria-pressed/);
  assert.match(integration, /model_unavailable/);
  assert.match(integration, /if \(requestId !== activeExplore/);
  assert.match(integration, /catch \(error\)/);
});

test("recommendations explicitly use overall history independent of query", () => {
  assert.match(SCOPE, /overall captured browsing history/);
  assert.match(SCOPE, /current search query does not affect/);
  assert.match(graphStatus(graphData(coverage, definitions, model), model), /overall captured browsing history/);
  const html = readFileSync(new URL('../app/ui/index.html', import.meta.url), 'utf8');
  assert.match(html, /Model-ranked next topics/);
  assert.match(html, /Rule-based prerequisite suggestions/);
  assert.match(html, /<details class="topic-breakdown">/);
  assert.match(html, /<summary>Browse topics as an accessible list/);
});

test("zero direct pages can retain a breadth contribution without implying mastery", () => {
  const message = activityExplanation({distinct_pages:0, visits:0, activity_index:.1, observed_subtopics:2, total_subtopics:2});
  assert.match(message, /Activity index 0.10/);
  assert.match(message, /Related topics contribute 0.10/);
  assert.match(message, /no directly assigned pages/);
  assert.match(message, /does not measure knowledge or mastery/);
});

test("selected evidence explains novelty and actual model inputs without causal claims", () => {
  const node = {evidence:{distinct_pages:0}, model:{evidence:{candidate_page_count:0, candidate_visit_count:0,
    candidate_recency_days:null, observed_prerequisite_count:0, candidate_prerequisite_count:0,
    observed_topic_breadth:6, candidate_is_graph_gap:false, candidate_is_direct_extension:false}}};
  assert.match(modelEvidence(node), /Novel relative to this capture corpus/);
  assert.match(modelEvidence(node), /0 direct pages, 0 eligible visits; recency unavailable/);
  assert.match(modelEvidence(node), /6 topics observed overall/);
  assert.match(modelEvidence(node), /not a causal explanation/);
});

test("compact layout keeps eight distinct non-overlapping nodes and real edges", () => {
  assert.equal(Object.keys(POSITIONS).length, 8);
  for (const [id,[x,y]] of Object.entries(POSITIONS)) {
    assert.ok(x >= 60 && x <= 600 && y >= 60 && y <= 430);
    for (const [other,[ox,oy]] of Object.entries(POSITIONS)) {
      if (id !== other) assert.ok(Math.hypot(x-ox,y-oy) >= 140);
    }
  }
  assert.equal(graphData(coverage, definitions, model).edges.length, 3);
});
