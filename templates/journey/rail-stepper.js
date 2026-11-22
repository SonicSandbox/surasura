/* The Stepper rail (journey v3 SPEC §1.1, §1.1b): one episode at a time — its stone (the pre-studied press), its
   number in its show, % known with the growth bar, *N new* — its words one row each, ‹ › to the next, and the picker
   (one row a show, the shown one open) for the rest. A rail draws itself in its box, calls page.go and
   page.prestudied, and opens its hover; it never reads a chunk, draws the word, calls the door or keeps a mark.
   Every write is the one a press needs (the redraw rule): a row's class, a row, a stone — never a list it didn't
   change. The picker builds only the rows in view. */
window.JourneyRail = function (page, box) {
  "use strict";
  const esc = page.esc, ROW = 32;
  const N = page.count();
  box.innerHTML = '<div class="rs-top" data-r="rail-top"></div><div class="rs-line" data-r="rail-line"></div>' +
    '<div data-r="rail-head"></div><div class="rs-words" data-r="rail-words" data-list="1"></div>';
  const [topEl, lineEl, headEl, wordsEl] = box.children;
  const set = (el, html) => { if (el.__h !== html) { el.innerHTML = html; el.__h = html; } };
  const swap = page.swap;                               // an element for its new source, only when the source differs

  /* each show's episodes, in the study order */
  const SHOW_EPS = new Map();
  for (let i = 0; i < N; i++) { const s = page.ep(i).show; if (!SHOW_EPS.has(s)) SHOW_EPS.set(s, []); SHOW_EPS.get(s).push(i); }
  const showEps = (s) => SHOW_EPS.get(s) || [];
  let drawnEp = -1, drawnWi = -1, drawnKey = "";

  function navTip(j, dir) {
    if (j < 0) return dir > 0 ? "No episode after this one" : "No episode before this one";
    const e = page.ep(j);
    return `${dir > 0 ? "Next episode" : "Episode before"}: ${e.part}${e.new ? ` · ${e.new} new` : " · nothing new"} (${dir > 0 ? "PgDn" : "PgUp"})`;
  }
  function topHtml(w) {
    if (w.ep < 0) return `<span class="rs-empty">No episodes yet</span>`;
    const e = page.ep(w.ep), list = showEps(e.show), show = page.shows()[e.show];
    const prev = nextOf(w.ep, -1), next = nextOf(w.ep, 1);
    const showTitle = show ? show[1] : e.title;
    return `<button class="nav" data-rs="prev" aria-label="Episode before" data-tip="${esc(navTip(prev, -1))}" ${prev < 0 ? "disabled" : ""}>‹</button>` +
      `<button class="rs-title" data-rs="picker" aria-label="Episodes and chapters" data-tip="${esc(e.title)}\nAll your shows: click to open the picker">${page.kindIcon(e.kind, e.gem)}` +
      `${list.length > 1 ? `<span class="t1">${esc(showTitle)}</span><span class="pt">· ${esc(e.part)}</span><span class="of">of ${list.length}</span>` : `<span class="t1">${esc(e.title)}</span>`}<span class="of">▾</span></button>` +
      `<button class="nav" data-rs="next" aria-label="Next episode" data-tip="${esc(navTip(next, 1))}" ${next < 0 ? "disabled" : ""}>›</button>`;
  }
  function nextOf(i, dir) {
    for (let j = i + dir; j >= 0 && j < N; j += dir) { if (!page.ep(j).watched) return j; }
    return -1;
  }
  function lineHtml() {
    const f = page.filter();
    return `<button class="ofb" data-rs="order" data-tip="Order and filter (this view only: your order in Surasura stays)\nFilter: ${esc(page.keyOf("filter") || "not set")}">${f.order === "freq" ? "Most frequent" : "In order"} · ${esc(f.name)} ▾</button><span class="sp"></span>` +
      `<button class="ib" data-rs="picker" aria-label="Episodes and chapters" data-tip="Episodes and chapters${page.keyOf("picker") ? " (" + esc(page.keyOf("picker")) + ")" : ""}">☰</button>` +
      `<button class="q" data-rs="help" aria-label="About the rail" data-tip="About the rail">?</button>`;
  }
  function headHtml(w) {
    if (w.ep < 0) return "";
    const e = page.ep(w.ep);
    return `<div class="rs-head">${page.kindIcon(e.kind, e.gem)}<span class="ht" data-tip="${esc(e.title)}">${esc(e.part)}</span>` +
      `<span class="pc ${page.pcClass(e.pct)}">${page.fmtPct(e.pct)}</span><span class="nn">· <b>${e.new}</b> new</span>${page.stone(w.ep, true)}</div>` +
      `<div class="rs-gb">${page.growth(w.ep)}</div>`;
  }
  /* a row is its class (where you are, its mark, waiting) and its inside (the word): a mark is one class write, and
     its glyph is the CSS's (rail-stepper.css) */
  function rowCls(r, k, cur) {
    return "rw" + (k === cur ? " cur" : "") + (r.mark ? " " + r.mark : "") + (r.wait === "wait" ? " sending" : r.wait === "queued" ? " waiting" : "");
  }
  function rowIn(r, k) {
    return `<span class="n">${k + 1}</span><span class="t jp">${esc(r.word)}</span>${page.marksHtml(r.marks)}${r.marks & 8 ? '<span class="anki">★</span>' : ""}<span class="x">×${r.ahead}</span><span class="m2"></span>`;
  }
  function placeholder(w, rows) {
    if (w.ep < 0) return `<div class="rs-empty">Add something in Surasura and press Generate.</div>`;
    if (!rows) return `<div class="rs-empty">Opening…</div>`;
    return `<div class="rs-empty">${page.ep(w.ep).new ? "None of its words in this filter." : "Nothing new in this one."}</div>`;
  }
  let rowsKey = "";                                     // the episode + filter whose rows are in the list ("" = none)
  function drawWords(w) {                               // the list rebuilt only for another episode or filter
    const rows = w.ep >= 0 ? page.words(w.ep) : null, key = w.ep + "|" + filterKey();
    if (rows && rows.length && key === rowsKey && wordsEl.children.length === rows.length) { patchAll(rows, w.wi); return; }
    if (!rows || !rows.length) { rowsKey = ""; set(wordsEl, placeholder(w, rows)); return; }
    wordsEl.innerHTML = rows.map((r, k) => `<div class="${rowCls(r, k, w.wi)}" data-k="${k}" data-id="${r.id}">${rowIn(r, k)}</div>`).join("");
    wordsEl.__h = null; rowsKey = key;
    const els = wordsEl.children;
    for (let k = 0; k < els.length; k++) els[k].__in = rowIn(rows[k], k);
  }
  function patch(el, r, k, cur) {                       // only what differs: the class, else the inside
    const c = rowCls(r, k, cur), inner = rowIn(r, k);
    if (el.className !== c) el.className = c;
    if ((el.__in != null ? el.__in : el.innerHTML) !== inner) el.innerHTML = inner;
    el.__in = inner;
  }
  function patchAll(rows, cur) {
    const els = wordsEl.children;
    for (let k = 0; k < els.length && k < rows.length; k++) patch(els[k], rows[k], k, cur);
  }
  function drawAll() {
    const w = page.where();
    set(topEl, topHtml(w)); set(lineEl, lineHtml()); set(headEl, headHtml(w));
    drawnWi = w.wi; drawWords(w);
    drawnEp = w.ep; drawnKey = filterKey();
  }
  const filterKey = () => { const f = page.filter(); return f.index + ":" + f.order; };
  function where() {
    const w = page.where();
    if (w.ep !== drawnEp || filterKey() !== drawnKey) { drawAll(); wordsEl.scrollTop = 0; return; }
    if (w.wi === drawnWi) return;
    const a = wordsEl.querySelector(`.rw[data-k="${drawnWi}"]`), b = wordsEl.querySelector(`.rw[data-k="${w.wi}"]`);
    if (a) a.classList.remove("cur");
    if (b) { b.classList.add("cur"); requestAnimationFrame(() => b.scrollIntoView({ block: "nearest" })); }
    drawnWi = w.wi;
  }
  function word(id) {                                   // one word's row (its mark changed)
    const el = wordsEl.querySelector(`.rw[data-id="${id}"]`);
    if (!el) return;
    const rows = page.words(drawnEp), k = Number(el.dataset.k);
    if (rows && rows[k]) patch(el, rows[k], k, drawnWi);
  }
  function marks() {                                    // marks read back from Surasura: only rows that changed
    const rows = page.words(drawnEp);
    if (rows && rowsKey) patchAll(rows, drawnWi);
  }
  function pre(i) {                                     // a stone's mark: that stone, its row, its show's mark
    if (i === drawnEp) { const st = headEl.querySelector(`[data-pre="${i}"], .st`); if (st) { swap(st, page.stone(i, true)); headEl.__h = null; } }
    if (P.open) {
      const row = P.rows.get("e" + i);
      if (row) { const st = row.querySelector(".st"); if (st) swap(st, page.stone(i, i === page.where().ep)); }
      const s = page.ep(i).show;
      SHOW_INFO.delete(s);
      const srow = P.rows.get("s" + s);
      if (srow) swap(srow.querySelector(".r"), showRight(s));
    }
  }

  /* ---- the picker ---- */
  const P = { open: false, el: null, scroll: null, space: null, list: [], rows: new Map(), shows: new Set() };
  const SHOW_INFO = new Map();
  function showInfo(s) {
    let v = SHOW_INFO.get(s);
    if (v) return v;
    const eps = showEps(s);
    let left = 0, nw = 0, tier = 3;
    const pres = [];
    for (const i of eps) { const e = page.ep(i); if (!e.watched) { left++; nw += e.new; tier = Math.min(tier, e.tier); } if (e.pre.on) pres.push(e.part); }
    if (tier === 3) tier = page.ep(eps[0]).tier;
    v = { left, nw, tier, pres, n: eps.length };
    SHOW_INFO.set(s, v);
    return v;
  }
  function showRight(s) {
    const v = showInfo(s);
    const mark = v.pres.length ? `<span class="mk3" data-tip="${esc("✧ Pre-studied: " + v.pres.slice(0, 6).join(" · ") + (v.pres.length > 6 ? ` +${v.pres.length - 6}` : ""))}">${page.sparkle()}</span>` : `<span class="mk3"></span>`;
    return `<span class="r">${v.left ? `${v.left} of ${v.n} left · ${v.nw} new` : "all done"}${mark}</span>`;
  }
  function epRight(i) {
    const e = page.ep(i);
    return `<span class="r">${page.growth(i)}<span class="pc ${page.pcClass(e.pct)}">${page.fmtPct(e.pct)}</span>${e.watched ? "· ✓" : `· <b>${e.new}</b> new`}${page.stone(i, i === page.where().ep)}</span>`;
  }
  function buildList() {                                // the rows, as keys: groups, shows, the open shows' episodes
    const out = [], byTier = [[], [], []], cur = page.where().ep;
    for (const s of SHOW_EPS.keys()) byTier[Math.min(2, showInfo(s).tier)].push(s);
    for (let t = 0; t < 3; t++) {
      if (!byTier[t].length) continue;
      out.push("g" + t);
      for (const s of byTier[t]) {
        const eps = showEps(s);
        if (eps.length === 1) { out.push("e" + eps[0]); continue; }
        out.push("s" + s);
        if (P.shows.has(s)) for (const i of eps) out.push("e" + i);
      }
    }
    const fin = page.finished();
    if (fin.length) { out.push("gf"); fin.forEach((f, k) => out.push("f" + k)); }
    P.list = out;
    P.curRow = out.indexOf("e" + cur);
  }
  function rowFor(key, idx) {
    const top = `style="top:${idx * ROW}px"`;
    const t = key[0], n = key.slice(1);
    if (t === "g") return `<div class="pr g" ${top} data-key="${key}">${n === "f" ? "Finished" : esc(page.tiers[Number(n)])}</div>`;
    if (t === "s") {
      const s = Number(n), show = page.shows()[s], first = page.ep(showEps(s)[0]);
      return `<div class="pr s" ${top} data-key="${key}" data-show="${s}" data-tip="${esc(show[1])}"><span class="car">${P.shows.has(s) ? "▾" : "▸"}</span>${page.kindIcon(first.kind, first.gem)}<span class="tt">${esc(show[1])}</span>${showRight(s)}</div>`;
    }
    if (t === "f") {
      const f = page.finished()[Number(n)];
      return `<div class="pr" ${top} data-key="${key}"><span class="car"></span>${page.kindIcon(f[2], f[3])}<span class="tt">${esc(f[1])}</span><span class="r">Finished${page.finishedStone(f)}</span></div>`;
    }
    const i = Number(n), e = page.ep(i), single = showEps(e.show).length === 1;
    return `<div class="pr e ${single ? "one" : ""} ${i === page.where().ep ? "cur" : ""}" ${top} data-key="${key}" data-ep="${i}" data-tip="${esc(e.title)}">${single ? `<span class="car"></span>${page.kindIcon(e.kind, e.gem)}` : ""}<span class="tt">${esc(single ? e.title : e.part)}</span>${epRight(i)}</div>`;
  }
  function windowRows() {                               // only the rows in view (and a few each side) are in the page
    const sc = P.scroll, h = sc.clientHeight || 600, top = sc.scrollTop;
    const a = Math.max(0, Math.floor(top / ROW) - 6), b = Math.min(P.list.length, Math.ceil((top + h) / ROW) + 6);
    const want = new Set();
    for (let k = a; k < b; k++) want.add(P.list[k]);
    for (const [key, el] of P.rows) if (!want.has(key)) { el.remove(); P.rows.delete(key); }
    let html = "";
    const add = [];
    for (let k = a; k < b; k++) { const key = P.list[k]; if (!P.rows.has(key)) { html += rowFor(key, k); add.push(key); } }
    if (html) {
      P.space.insertAdjacentHTML("beforeend", html);
      for (const el of P.space.querySelectorAll(".pr:not([data-in])")) { el.dataset.in = "1"; P.rows.set(el.dataset.key, el); }
    }
  }
  function relist() {                                   // a show opened or folded: the list below it moves
    buildList();
    for (const el of P.rows.values()) el.remove();
    P.rows.clear();
    P.space.style.height = P.list.length * ROW + "px";
    windowRows();
  }
  function openPicker() {
    if (P.open) return;
    const cur = page.where().ep;
    if (cur >= 0) P.shows.add(page.ep(cur).show);
    buildList();
    const el = document.createElement("div");
    el.className = "rs-pick"; el.dataset.r = "picker";
    el.innerHTML = `<div class="rs-sheet" role="dialog" aria-modal="true" aria-label="Episodes and chapters"><div class="ph"><b>Episodes and chapters</b><span>${N} in ${SHOW_EPS.size} shows</span><button class="x" data-rs="close" aria-label="Close" data-tip="Close (Esc)">×</button></div><div class="rs-scroll" data-list="1"><div class="rs-space" style="height:${P.list.length * ROW}px"></div></div></div>`;
    document.body.appendChild(el);
    P.el = el; P.scroll = el.querySelector(".rs-scroll"); P.space = el.querySelector(".rs-space"); P.open = true;
    P.scroll.scrollTop = Math.max(0, P.curRow * ROW - 220);
    windowRows();
    P.scroll.addEventListener("scroll", () => { if (!P.raf) P.raf = requestAnimationFrame(() => { P.raf = 0; if (P.open) windowRows(); }); }, { passive: true });
    el.addEventListener("click", onPickClick);
  }
  function closePicker() {
    if (!P.open) return;
    P.el.remove(); P.open = false; P.rows.clear(); P.el = P.scroll = P.space = null;
  }
  function onPickClick(ev) {
    const t = ev.target, c = (s) => t.closest(s);
    if (t === P.el || c('[data-rs="close"]')) { closePicker(); return; }
    let el;
    if ((el = c("[data-pre]"))) { ev.stopPropagation(); page.prestudied(Number(el.dataset.pre)); return; }
    if ((el = c("[data-show]"))) {
      const s = Number(el.dataset.show);
      if (P.shows.has(s)) P.shows.delete(s); else P.shows.add(s);
      relist(); return;
    }
    if ((el = c("[data-ep]"))) { closePicker(); page.go(Number(el.dataset.ep), 0); }
  }
  ev(box);
  function ev(root) {
    root.addEventListener("click", (e) => {
      const t = e.target.closest("[data-rs],[data-k]");
      if (!t || t.closest("[data-pre]")) return;
      const a = t.dataset.rs;
      if (a === "prev") page.epStep(-1);
      else if (a === "next") page.epStep(1);
      else if (a === "picker") openPicker();
      else if (a === "order") page.menu("order", t);
      else if (a === "help") page.help("rail");
      else if (t.dataset.k != null) page.go(page.where().ep, Number(t.dataset.k));
    });
  }
  return {
    name: "stepper",
    update(what, arg) {
      if (what === "all") drawAll();
      else if (what === "where") where();
      else if (what === "word") word(arg);
      else if (what === "marks" || what === "mark") marks();
      else if (what === "pre") pre(arg);
      else if (what === "words") { if (arg === drawnEp) drawWords(page.where()); }
      else if (what === "filter") { set(lineEl, lineHtml()); where(); }
    },
    picker: () => (P.open ? closePicker() : openPicker()),
    isOpen: () => P.open,
    close: closePicker,
    _p: P,
  };
};
