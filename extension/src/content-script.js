// Apogee content script. Passive until asked: it registers a listener and sends nothing anywhere
// on its own. Only a popup-triggered "APOGEE_EXTRACT" message reads the current page.
(() => {
  const SKIP_TAGS = new Set([
    "SCRIPT",
    "STYLE",
    "NOSCRIPT",
    "TEMPLATE",
    "IFRAME",
    "SVG",
    "CANVAS",
    "MENU",
    "NAV",
    "FOOTER",
    "FORM",
    "BUTTON",
    "INPUT",
    "SELECT",
    "TEXTAREA",
    "DIALOG",
  ]);
  const BLOCK_TAGS = new Set([
    "ADDRESS",
    "ARTICLE",
    "BLOCKQUOTE",
    "CAPTION",
    "DD",
    "DIV",
    "DL",
    "DT",
    "FIGCAPTION",
    "FIGURE",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "HEADER",
    "HR",
    "LI",
    "MAIN",
    "OL",
    "P",
    "PRE",
    "SECTION",
    "TABLE",
    "TBODY",
    "TD",
    "TFOOT",
    "TH",
    "THEAD",
    "TR",
    "UL",
  ]);
  const UI_ATTRIBUTE_HINT =
    /(?:^|\s)(?:cookie|consent|newsletter|subscribe|sign\s*in|sign\s*up|log\s*in|signin|signup|login|share|social|recommend(?:ed|ation|ations)?|related|ad|ads|advert(?:isement)?|sponsor(?:ed)?|promo|breadcrumb|pagination|toolbar|menu|site\s*nav|navigation)(?:\s|$)/;
  const UI_ROLES = new Set([
    "banner",
    "complementary",
    "contentinfo",
    "dialog",
    "menu",
    "menubar",
    "navigation",
    "search",
  ]);
  const BOILERPLATE_COPY = new Set([
    "accept",
    "accept all",
    "accept all cookies",
    "back to top",
    "cookie settings",
    "manage preferences",
    "menu",
    "privacy choices",
    "reject all",
    "share",
    "share this page",
    "sign in",
    "sign up",
    "skip to content",
    "skip to main content",
    "subscribe",
  ]);
  const CONTROL_CHARACTERS = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g;

  function isVisible(element, getComputedStyle) {
    for (let current = element; current && current.nodeType === 1; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        style.visibility === "collapse" ||
        current.hasAttribute("hidden") ||
        current.getAttribute("aria-hidden") === "true"
      ) {
        return false;
      }
    }
    return true;
  }

  function hasSemanticAncestor(element) {
    for (let current = element; current; current = current.parentElement) {
      if (
        current.tagName === "ARTICLE" ||
        current.tagName === "MAIN" ||
        current.getAttribute("role") === "main"
      ) {
        return true;
      }
    }
    return false;
  }

  function hasBoilerplateHint(element) {
    const role = (element.getAttribute("role") || "").toLowerCase();
    if (UI_ROLES.has(role)) return true;
    const attributes = ["id", "class", "aria-label", "data-testid", "data-test"]
      .map((name) => element.getAttribute(name) || "")
      .join(" ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ");
    return UI_ATTRIBUTE_HINT.test(attributes);
  }

  function isLinkHeavy(element) {
    if (!["ASIDE", "DIV", "HEADER", "OL", "SECTION", "UL"].includes(element.tagName)) return false;
    const links = [...element.querySelectorAll("a")];
    if (links.length < 4) return false;
    const textLength = (element.textContent || "").trim().length;
    if (!textLength) return false;
    const linkLength = links.reduce((total, link) => total + (link.textContent || "").trim().length, 0);
    return linkLength / textLength >= 0.84;
  }

  function shouldSkip(element, root, getComputedStyle) {
    if (!isVisible(element, getComputedStyle)) return true;
    const tag = element.tagName;
    const inContent = hasSemanticAncestor(element);
    if (SKIP_TAGS.has(tag) || hasBoilerplateHint(element)) return true;
    if (tag === "HEADER" && !inContent) return true;
    if (tag === "ASIDE" && !inContent) return true;
    if (isLinkHeavy(element) && element !== root) return true;
    return false;
  }

  function cleanTextNode(value, inPre) {
    let text = value
      .replace(/\r\n?/g, "\n")
      .replace(CONTROL_CHARACTERS, "")
      .replace(/[\u00a0\u200b\ufeff]/g, " ");
    if (!inPre) text = text.replace(/\s+/gu, " ");
    return text;
  }

  function listPrefix(element) {
    if (element.tagName !== "LI") return "";
    if (element.parentElement && element.parentElement.tagName === "OL") {
      const siblings = [...element.parentElement.children].filter((child) => child.tagName === "LI");
      const index = siblings.indexOf(element) + 1;
      return `${index > 0 ? index : 1}. `;
    }
    return "• ";
  }

  function render(node, root, getComputedStyle, inPre = false) {
    if (node.nodeType === 3) return cleanTextNode(node.nodeValue || "", inPre);
    if (node.nodeType !== 1 || shouldSkip(node, root, getComputedStyle)) return "";

    const tag = node.tagName;
    if (tag === "BR") return "\n";
    const codeContext = inPre || tag === "PRE";
    const body = [...node.childNodes]
      .map((child) => render(child, root, getComputedStyle, codeContext))
      .join("");
    if (!body.trim()) return "";

    const content = `${listPrefix(node)}${body}`;
    if (tag === "PRE") {
      const code = content.replace(/^\n+|\n+$/g, "");
      const longestBackticks = Math.max(0, ...[...code.matchAll(/`+/g)].map(([run]) => run.length));
      const fence = "`".repeat(Math.max(3, longestBackticks + 1));
      return `\n\n${fence}\n${code}\n${fence}\n\n`;
    }
    if (!BLOCK_TAGS.has(tag)) return content;
    if (codeContext) return `\n\n${content.replace(/^\n+|\n+$/g, "")}\n\n`;
    return `\n\n${content.trim()}\n\n`;
  }

  function extractFromRoot(root, getComputedStyle) {
    let text = [...root.childNodes]
      .map((node) => render(node, root, getComputedStyle))
      .join("");
    text = text
      .replace(/\r\n?/g, "\n")
      .replace(CONTROL_CHARACTERS, "")
      .replace(/[\u200b\ufeff]/g, "")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/^\n+|\n+$/g, "");

    const seen = new Set();
    const blocks = [];
    for (const block of text.split(/\n{2,}/)) {
      if (!block.trim()) continue;
      const normalized = block.replace(/[ \t]+$/gm, "");
      const key = normalized.trim();
      if (key.length >= 48 && seen.has(key)) continue;
      if (key.length >= 48) seen.add(key);
      if (!BOILERPLATE_COPY.has(key.toLowerCase())) blocks.push(normalized);
    }
    return blocks.join("\n\n");
  }

  function candidateScore(element, text) {
    const links = [...element.querySelectorAll("a")];
    const total = (element.textContent || "").trim().length;
    const linked = links.reduce((count, link) => count + (link.textContent || "").trim().length, 0);
    const linkRatio = total ? Math.min(1, linked / total) : 0;
    const semanticBonus = element.tagName === "ARTICLE" ? 1.08 : 1;
    return text.length * (1 - 0.8 * linkRatio) * semanticBonus;
  }

  function extractVisibleText(documentRef = document, getComputedStyle = window.getComputedStyle.bind(window)) {
    const body = documentRef.body;
    if (!body) return "";

    let best = "";
    let bestScore = 0;
    for (const candidate of documentRef.querySelectorAll("article, main, [role='main']")) {
      if (!isVisible(candidate, getComputedStyle)) continue;
      const text = extractFromRoot(candidate, getComputedStyle);
      const score = candidateScore(candidate, text);
      if (text && score > bestScore) {
        best = text;
        bestScore = score;
      }
    }
    return best || extractFromRoot(body, getComputedStyle);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "APOGEE_EXTRACT") return undefined;
    sendResponse({
      url: location.href,
      title: document.title,
      text: extractVisibleText(document),
    });
    return undefined;
  });
})();
