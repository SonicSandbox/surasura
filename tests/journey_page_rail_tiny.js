/* A second rail for the rail contract's test (journey v3 SPEC §1.1b): the smallest rail the page API allows — the
   episode where you are, its stone, ‹ ›. It is plugged in by the fixture's assemble(rail_css=…, rail_js=…) with no
   change to page.html: the proof that another rail (Flow) can be added later as one new part. It draws itself in its
   box, calls page.go / page.prestudied / page.epStep, and keeps nothing; it records which page calls it made, so the
   test can say it used the API and nothing else. */
window.JourneyRail = function (page, box) {
  "use strict";
  const USED = (window.__TINY_USED = new Set());
  const api = new Proxy(page, { get(t, k) { USED.add(String(k)); return t[k]; } });
  box.innerHTML = '<div class="tiny" data-r="rail-tiny"></div>';
  const el = box.firstChild;
  let drawn = "";
  function draw() {
    const w = api.where();
    const html = w.ep < 0 ? "<i>No episodes yet</i>"
      : `<button data-tiny="prev" aria-label="Episode before">‹</button><b>${api.esc(api.ep(w.ep).title)}</b>` +
        `<button data-tiny="pre" aria-label="Pre-studied">${api.ep(w.ep).pre.on ? "✧ on" : "✧ off"}</button><button data-tiny="next" aria-label="Next episode">›</button>`;
    if (html !== drawn) { el.innerHTML = html; drawn = html; }
  }
  box.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tiny]");          // its own button: a page stone ([data-pre]) the page presses itself
    if (!t) return;
    if (t.dataset.tiny === "pre") api.prestudied(api.where().ep);
    else {                                              // page.go to the next / last episode not yet watched
      const d = t.dataset.tiny === "next" ? 1 : -1, n = api.count();
      for (let j = api.where().ep + d; j >= 0 && j < n; j += d) if (!api.ep(j).watched) { api.go(j, 0); break; }
    }
  });
  return {
    name: "tiny",
    update(what) { if (what === "all" || what === "where" || what === "pre") draw(); },
  };
};
