import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const contentScript = readFileSync(new URL("../src/content-script.js", import.meta.url), "utf8");

function text(value) {
  return { nodeType: 3, nodeValue: value, parentElement: null };
}

function element(tagName, attributes = {}, children = []) {
  const node = {
    nodeType: 1,
    tagName: tagName.toUpperCase(),
    attributes: new Map(Object.entries(attributes)),
    childNodes: children,
    parentElement: null,
    get children() {
      return this.childNodes.filter((child) => child.nodeType === 1);
    },
    get textContent() {
      return this.childNodes.map((child) => child.textContent ?? child.nodeValue ?? "").join("");
    },
    getAttribute(name) {
      return this.attributes.get(name) ?? null;
    },
    hasAttribute(name) {
      return this.attributes.has(name);
    },
    querySelectorAll(selector) {
      const selectors = selector.split(",").map((part) => part.trim().toLowerCase());
      const matches = (candidate, query) => {
        const roleMatch = query.match(/^\[role=['"]?([^\]'" ]+)['"]?\]$/);
        if (roleMatch) return candidate.getAttribute("role") === roleMatch[1];
        return candidate.tagName.toLowerCase() === query;
      };
      const results = [];
      const visit = (parent) => {
        for (const child of parent.childNodes) {
          if (child.nodeType !== 1) continue;
          if (selectors.some((query) => matches(child, query))) results.push(child);
          visit(child);
        }
      };
      visit(this);
      return results;
    },
  };
  for (const child of children) child.parentElement = node;
  return node;
}

function capture(root) {
  let listener;
  let result;
  const document = {
    body: root,
    title: "Fixture page",
    querySelectorAll: (selector) => root.querySelectorAll(selector),
  };
  vm.runInNewContext(contentScript, {
    chrome: { runtime: { onMessage: { addListener: (callback) => (listener = callback) } } },
    document,
    location: { href: "https://example.test/article" },
    window: {
      getComputedStyle: (node) => {
        const style = node.getAttribute("style") || "";
        return {
          display: /display\s*:\s*none/i.test(style) ? "none" : "block",
          visibility: /visibility\s*:\s*hidden/i.test(style) ? "hidden" : "visible",
        };
      },
    },
  });
  listener({ type: "APOGEE_EXTRACT" }, {}, (value) => (result = value));
  return result;
}

const articleCopy =
  "Breadth-first search visits vertices level by level and is useful for shortest paths in an unweighted graph.";

test("article and main content survive while unrelated navigation and footer are excluded", () => {
  const root = element("body", {}, [
    element("nav", {}, [element("a", {}, [text("Home")]), element("a", {}, [text("Topics")])]),
    element("main", {}, [
      element("article", {}, [element("h1", {}, [text("Breadth-first search")]), element("p", {}, [text(articleCopy)])]),
      element("aside", { class: "related-articles" }, [text("Recommended articles and popular posts")]),
    ]),
    element("footer", {}, [text("Copyright and site links")]),
  ]);

  const result = capture(root).text;
  assert.match(result, /Breadth-first search/);
  assert.match(result, /visits vertices level by level/);
  assert.doesNotMatch(result, /Home|Topics|Recommended articles|Copyright/);
});

test("fallback suppresses navigation-heavy site chrome without article or main landmarks", () => {
  const menu = element(
    "div",
    { class: "primary-links" },
    Array.from({ length: 5 }, (_, index) => element("a", {}, [text(`Section ${index}`)])),
  );
  const root = element("body", {}, [
    element("header", {}, [text("Global header and account links")]),
    menu,
    element("div", { id: "unrelated-article-copy" }, [element("p", {}, [text(articleCopy)])]),
  ]);

  const result = capture(root).text;
  assert.match(result, /Breadth-first search visits vertices/);
  assert.doesNotMatch(result, /Global header|Section [0-4]/);
});

test("cookie banners and sign-up UI are removed conservatively", () => {
  const root = element("body", {}, [
    element("div", { id: "cookie-consent-banner", role: "dialog" }, [
      element("p", {}, [text("We use cookies to improve your experience. Accept all cookies.")]),
    ]),
    element("main", {}, [element("p", {}, [text(articleCopy)])]),
  ]);

  const result = capture(root).text;
  assert.match(result, /Breadth-first search/);
  assert.doesNotMatch(result, /cookies|Accept all cookies/i);
});

test("technical headings, lists, inline terms, and code formatting are preserved", () => {
  const code = "def bfs(graph, start):\n    queue = deque([start])\n    visited = {start}";
  const root = element("body", {}, [
    element("article", {}, [
      element("h2", {}, [text("BFS implementation")]),
      element("p", {}, [text("Use a "), element("code", {}, [text("deque")]), text(" for O(1) queue operations.")]),
      element("ol", {}, [element("li", {}, [text("Initialize the queue")]), element("li", {}, [text("Visit neighbors")])]),
      element("pre", {}, [element("code", {}, [text(code)])]),
    ]),
  ]);

  const result = capture(root).text;
  assert.match(result, /BFS implementation/);
  assert.match(result, /a deque for O\(1\) queue operations/);
  assert.match(result, /1\. Initialize the queue[\s\S]*2\. Visit neighbors/);
  assert.match(result, /```[\s\S]*```/);
  assert.ok(result.includes("\n    queue = deque([start])"), result);
});

test("a page without article or main falls back to visible body content", () => {
  const root = element("body", {}, [
    element("div", { class: "content" }, [
      element("h1", {}, [text("A graph traversal note")]),
      element("p", {}, [text("Depth-first search explores a branch before backtracking to alternatives.")]),
    ]),
  ]);

  const result = capture(root).text;
  assert.match(result, /A graph traversal note/);
  assert.match(result, /explores a branch before backtracking/);
});

test("exact repeated content blocks are emitted once while different blocks remain", () => {
  const repeated = "This exact introductory paragraph is duplicated by the page template.";
  const root = element("article", {}, [
    element("p", {}, [text(repeated)]),
    element("p", {}, [text("A distinct paragraph explains how the algorithm processes each vertex.")]),
    element("p", {}, [text(repeated)]),
  ]);

  const result = capture(element("body", {}, [root])).text;
  assert.equal(result.split(repeated).length - 1, 1);
  assert.match(result, /processes each vertex/);
});

test("short useful content is retained and empty or hidden pages safely produce no text", () => {
  const shortPage = element("body", {}, [element("article", {}, [element("p", {}, [text("Short useful note.")])])]);
  const emptyPage = element("body", {}, [
    element("main", { style: "display:none" }, [element("p", {}, [text(articleCopy)])]),
    element("nav", {}, [text("Menu Home Search")]),
  ]);

  assert.equal(capture(shortPage).text, "Short useful note.");
  assert.equal(capture(emptyPage).text, "");
  assert.doesNotThrow(() => capture(element("body")));
});

test("hidden, aria-hidden, and executable content stays excluded", () => {
  const root = element("body", {}, [
    element("main", {}, [
      element("p", { "aria-hidden": "true" }, [text("Hidden duplicate navigation text")]),
      element("p", { style: "visibility:hidden" }, [text("Invisible text")]),
      element("script", {}, [text("secret script contents")]),
      element("p", {}, [text(articleCopy)]),
    ]),
  ]);

  const result = capture(root).text;
  assert.match(result, /Breadth-first search/);
  assert.doesNotMatch(result, /Hidden duplicate|Invisible text|secret script/);
});
