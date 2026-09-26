// Apogee content script. Passive until asked: it registers a listener and sends nothing anywhere
// on its own. Runs on every http(s) page (see manifest.json "content_scripts"), so it must never
// read or transmit anything by itself; only a popup-triggered "APOGEE_EXTRACT" message causes it
// to read the current page, and its response goes back to the popup, not to the network.
(() => {
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "IFRAME", "SVG", "CANVAS"]);

  function isVisible(element) {
    if (!element) return true;
    const style = window.getComputedStyle(element);
    if (style.display === "none") return false;
    if (style.visibility === "hidden" || style.visibility === "collapse") return false;
    if (element.getAttribute && element.getAttribute("aria-hidden") === "true") return false;
    return true;
  }

  function extractVisibleText(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
        if (!isVisible(parent)) return NodeFilter.FILTER_REJECT;
        return node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      },
    });
    const pieces = [];
    let node;
    while ((node = walker.nextNode())) pieces.push(node.textContent.trim());
    return pieces.join("\n");
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "APOGEE_EXTRACT") return undefined;
    sendResponse({
      url: location.href,
      title: document.title,
      text: extractVisibleText(document.body),
    });
    return undefined; // response already sent synchronously above
  });
})();
