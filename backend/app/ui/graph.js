import { SVG, POSITIONS, graphData, detailLines, graphStatus, modelEvidence } from "./graph.mjs";

const section = document.getElementById("exploration-graph");
const canvas = document.getElementById("topic-graph");
const list = document.getElementById("graph-list");
const detail = document.getElementById("graph-detail");
const status = document.getElementById("graph-status");
const reset = document.getElementById("graph-reset");
const positions = POSITIONS;
const modelList = document.getElementById("graph-model-list");
let transform = { x: 0, y: 0, scale: 1 };
let layer = null;
let drag = null;

function svg(tag, attrs = {}) {
  const element = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  return element;
}
function text(tag, value, className = "") {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = value;
  return element;
}
function applyTransform() {
  if (layer) layer.setAttribute("transform", `translate(${transform.x} ${transform.y}) scale(${transform.scale})`);
}
function choose(node, graph) {
  detail.replaceChildren(text("h4", node.name), ...detailLines(node, graph).map(line => text("p", line)));
  detail.hidden = false;
  for (const element of canvas.querySelectorAll(".graph-node")) element.classList.toggle("selected", element.dataset.topicId === node.id);
  for (const element of list.querySelectorAll("button")) element.setAttribute("aria-pressed", String(element.dataset.topicId === node.id));
}

export function clearGraph(message = "Load exploration to see the topic graph.") {
  section.hidden = true;
  canvas.replaceChildren();
  list.replaceChildren();
  modelList.replaceChildren();
  detail.replaceChildren();
  detail.hidden = true;
  status.textContent = message;
}

export function renderGraph(coverage, definitions, model = null) {
  const graph = graphData(coverage, definitions, model);
  modelList.replaceChildren();
  if (graph.source === "model") {
    for (const node of graph.nodes.filter(n => n.model.rank <= 3).sort((a,b) => a.model.rank-b.model.rank)) {
      const card = text("article", "", "model-suggestion");
      card.append(text("h4", `${node.model.rank}. ${node.name}`),
        text("p", `Expected synthetic grade: ${Number(node.model.expected_synthetic_grade).toFixed(3)} / 2`, "model-grade"),
        text("p", modelEvidence(node)),
        text("p", `Model: ${model.model_version || "version unavailable"}. Trained on synthetic rubric labels; no verified real-world usefulness.`, "fine-print"));
      modelList.append(card);
    }
  } else modelList.append(text("p", "Model ranking unavailable. Rule-based prerequisite suggestions remain in their own section below."));
  section.hidden = false;
  status.textContent = graphStatus(graph, model);
  canvas.replaceChildren();
  list.replaceChildren();
  detail.hidden = true;
  detail.replaceChildren();
  transform = { x: 0, y: 0, scale: 1 };
  const defs = svg("defs");
  const marker = svg("marker", { id: "prerequisite-arrow", markerWidth: 10, markerHeight: 10,
    refX: 8, refY: 5, orient: "auto", markerUnits: "strokeWidth" });
  marker.append(svg("path", { d: "M 0 1 L 9 5 L 0 9 z", fill: "#688d7b" }));
  defs.append(marker);
  canvas.append(defs);
  layer = svg("g");
  canvas.append(layer);
  for (const edge of graph.edges) {
    const [x1, y1] = positions[edge.from];
    const [x2, y2] = positions[edge.to];
    const length = Math.hypot(x2 - x1, y2 - y1);
    const line = svg("line", { x1: x1 + 57 * (x2-x1)/length, y1: y1 + 57 * (y2-y1)/length,
      x2: x2 - 66 * (x2-x1)/length, y2: y2 - 66 * (y2-y1)/length,
      class: "graph-edge", "marker-end": "url(#prerequisite-arrow)" });
    layer.append(line);
  }
  for (const node of graph.nodes) {
    const [x, y] = positions[node.id];
    const g = svg("g", { class: `graph-node${node.highlighted ? " highlighted" : ""}${node.evidence.distinct_pages ? " observed" : ""}`,
      transform: `translate(${x} ${y})`, tabindex: 0, role: "button", "aria-label": `${node.name}, ${node.evidence.distinct_pages} captured pages${node.highlighted ? ", suggested topic" : ""}` });
    g.dataset.topicId = node.id;
    const radius = 44 + Math.min(12, Math.sqrt(node.evidence.distinct_pages) * 4);
    g.append(svg("circle", { r: radius }));
    const label = svg("text", { "text-anchor": "middle", y: -2 });
    const words = node.name.split(" ");
    if (node.name.length > 16 && words.length > 1) {
      const middle = Math.ceil(words.length/2);
      const first = svg("tspan", { x: 0, dy: -5 }); first.textContent = words.slice(0, middle).join(" ");
      const second = svg("tspan", { x: 0, dy: 15 }); second.textContent = words.slice(middle).join(" ");
      label.append(first, second);
    } else { label.textContent = node.name; }
    g.append(label);
    const count = svg("text", { "text-anchor": "middle", y: 24, class: "graph-count" });
    count.textContent = `${node.evidence.distinct_pages} pages`;
    g.append(count);
    g.addEventListener("click", () => choose(node, graph));
    g.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(node, graph); } });
    layer.append(g);
    const button = text("button", `${node.name} · ${node.evidence.distinct_pages} pages${node.highlighted ? " · suggested" : ""}`);
    button.type = "button";
    button.dataset.topicId = node.id;
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => choose(node, graph));
    list.append(button);
  }
  applyTransform();
  return graph;
}

canvas.addEventListener("wheel", event => {
  event.preventDefault();
  transform.scale = Math.max(.65, Math.min(2.5, transform.scale * (event.deltaY < 0 ? 1.1 : .9)));
  applyTransform();
}, { passive: false });
canvas.addEventListener("pointerdown", event => {
  if (event.target.closest(".graph-node")) return;
  drag = { x: event.clientX, y: event.clientY };
  canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener("pointermove", event => {
  if (!drag) return;
  const rect = canvas.getBoundingClientRect();
  transform.x += (event.clientX - drag.x) * 660 / rect.width;
  transform.y += (event.clientY - drag.y) * 490 / rect.height;
  drag = { x: event.clientX, y: event.clientY };
  applyTransform();
});
canvas.addEventListener("pointerup", () => { drag = null; });
canvas.addEventListener("pointercancel", () => { drag = null; });
reset.addEventListener("click", () => { transform = { x: 0, y: 0, scale: 1 }; applyTransform(); });
