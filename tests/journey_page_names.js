/* JOURNEY-NAMES: every header row that shows a name, measured. Run by test_journey_page.py at each width and scale
   (window.__names(i) after the page has opened episode i): a name cuts with … inside its own box, never under a button
   or into the other pane, and its full title is on hover and named to keyboard focus (the test presses Tab for the
   tip). Returns the misses, [] when all hold. */
window.__names = async function (i) {
  "use strict";
  const J = window.__J, e = J.page.ep(i), title = e.title, miss = [];
  const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
  const $ = (s, root) => (root || document).querySelector(s);
  const shown = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const R = (el) => el.getBoundingClientRect();
  const px = (n) => n.toFixed(1);
  const tag = (el) => el.className || el.tagName;
  // `el` (and each part of it) inside `box`, left to right; half a pixel for subpixel layout
  function inside(what, el, box) {
    const a = R(el), b = R(box);
    if (a.left < b.left - 0.5 || a.right > b.right + 0.5) miss.push(`${what}: ${tag(el)} ${px(a.left)}–${px(a.right)} outside ${tag(box)} ${px(b.left)}–${px(b.right)}`);
  }
  function before(what, el, next) {                     // el ends before next begins (a row's order)
    const a = R(el), b = R(next);
    if (a.right > b.left + 0.5) miss.push(`${what}: ${tag(el)} ends at ${px(a.right)}, under ${tag(next)} from ${px(b.left)}`);
  }
  function cut(what, el) {                              // a name longer than its box is cut with …, on one line
    const cs = getComputedStyle(el);
    if (el.scrollWidth > el.clientWidth + 1 && !(cs.textOverflow === "ellipsis" && cs.overflowX === "hidden" && cs.whiteSpace === "nowrap"))
      miss.push(`${what}: ${tag(el)} is ${el.scrollWidth} px in ${el.clientWidth} px, not cut with …`);
    if (R(el).height > parseFloat(cs.fontSize) * 2.2) miss.push(`${what}: ${tag(el)} wraps (${px(R(el).height)} px high)`);
  }
  function rowInside(what, row, box) {                  // every part of a row inside the row, the row inside its pane
    inside(what, row, box);
    for (const el of row.querySelectorAll("*")) if (shown(el) && !el.closest("svg, .tip")) inside(what, el, row);
  }
  for (const list of [false, true]) {
    if (J.S.list !== list) J.toggleList();
    J.go(i, 0); await J.loadEp(i); J.drawWord(); await frame();
    const view = list ? "List" : "word view", stage = $("#stage"), rail = $("#rail");
    // the rail: ‹ [the episode's name] ›, then its own head (the episode, % known, N new, its stone)
    if (shown(rail)) {
      const top = $(".rs-top", rail), btn = $(".rs-title", rail), prev = $('[data-rs="prev"]', rail), next = $('[data-rs="next"]', rail);
      rowInside(`${view}, the rail's top row`, top, rail);
      for (const el of btn.querySelectorAll("*")) if (shown(el) && !el.closest("svg")) inside(`${view}, the rail's title`, el, btn);
      before(`${view}, the rail's top row`, prev, btn);
      before(`${view}, the rail's top row`, btn, next);
      for (const el of btn.querySelectorAll(".t1, .pt")) cut(`${view}, the rail's title`, el);
      if (!(btn.dataset.tip || "").includes(title)) miss.push(`${view}: the rail's title has no hover with the full name`);
      if (!(btn.getAttribute("aria-label") || "").includes(title)) miss.push(`${view}: the rail's title doesn't say the full name to keyboard focus (aria-label: ${btn.getAttribute("aria-label")})`);
      const head = $(".rs-head", rail), ht = $(".rs-head .ht", rail);
      rowInside(`${view}, the rail's head`, head, rail);
      before(`${view}, the rail's head`, ht, $(".rs-head .pc", rail));
      cut(`${view}, the rail's head`, ht);
      if (ht.dataset.tip !== title) miss.push(`${view}: the rail's head has no hover with the full name`);
    }
    // the word pane's heading: Word N of M · the episode's name · ↑ ↓ (word view); the episode's name · N words (List)
    const meta = $("#stage .meta"), ml = meta && $(".ml", meta);
    if (!ml) { miss.push(`${view}: no heading with the episode's name`); continue; }
    rowInside(`${view}, the word pane's heading`, meta, stage);
    const nav = $(".wnav", meta);
    if (nav) before(`${view}, the word pane's heading`, ml, nav);
    if (shown(rail)) inside(`${view}, the word pane's heading`, meta, stage);
    cut(`${view}, the word pane's heading`, ml);
    if (ml.dataset.tip !== title) miss.push(`${view}: the word pane's heading has no hover with the full name`);
  }
  // the episode's end (word view): its name in the heading wraps inside the card; *Up next* cuts in its own row
  if (J.S.list) J.toggleList();
  J.go(i, (J.seq(i) || []).length); J.drawWord(); await frame();
  const end = $("#stage .end"), h2 = end && $("h2", end), upn = end && $(".upn", end);
  if (!h2) miss.push("no end card");
  else {
    inside("the end card's heading", h2, end);
    for (const el of h2.children) inside("the end card's heading", el, end);
    const nx = $(".next .btn", end);
    if (nx) {
      rowInside("the end card's Next", nx, end);
      cut("the end card's Next", $(".nt", nx));
      if (!(nx.dataset.tip || "").includes($(".nt", nx).textContent)) miss.push("the end card's Next has no hover with the full name");
    }
    if (upn) {
      rowInside("the end card's Up next", upn, end);
      const jp = $(".jp", upn);
      cut("the end card's Up next", jp);
      if (!jp.dataset.tip || jp.dataset.tip !== jp.textContent) miss.push("the end card's Up next has no hover with the full name");
    }
    if ($("#stage").scrollWidth > $("#stage").clientWidth + 1) miss.push(`the end card scrolls sideways: ${$("#stage").scrollWidth} / ${$("#stage").clientWidth}`);
  }
  J.go(i, 0); J.drawWord(); await frame();
  if (document.documentElement.scrollWidth > innerWidth + 1) miss.push(`the page scrolls sideways: ${document.documentElement.scrollWidth} / ${innerWidth}`);
  return miss;
};
/* the tip's text while it shows ("" when hidden): the test presses Tab through DevTools (a real keyboard focus) */
window.__tipNow = () => { const t = document.getElementById("tip"); return t.classList.contains("hide") ? "" : t.textContent; };
