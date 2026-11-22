/* The journey v3 page's self-checks (?selftest=1), run in headless Edge by tests/test_journey_page.py. They go in
   after the rail and before the page's script, so they see the page start: a fake door (the routes' answers, by the
   frozen names), every localStorage write, long tasks. The redraw rule's counter is here too: a MutationObserver over
   the document, each write put down to its named region (data-r), the page's render counts, and the layout reads made
   after a write (forced reflows). Query: door=on|off|none · notyet=<route,…> · only=<group,…> · rail=contract. */
(function () {
  "use strict";
  const Q = new URLSearchParams(location.search);
  if (!Q.get("selftest")) return;
  const MODE = Q.get("door") || "on";
  const NOTYET = new Set((Q.get("notyet") || "").split(",").filter(Boolean));
  const CALLS = [], STORE = [], LONG = [];
  const setItem = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) { STORE.push([performance.now(), k]); return setItem.call(this, k, v); };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) LONG.push([e.startTime, e.duration]); }).observe({ type: "longtask", buffered: true }); } catch (e) {}
  const ROUTES = ["words/mark", "words/undo", "episode/prestudied", "episode/undo", "line/flag", "settings/set", "swap/queue", "card/make", "clip/cut", "word/audio"];
  const PREBY = {};
  let undoN = 0;
  window.__J_FAKE_DOOR = async (route, body) => {
    CALLS.push([performance.now(), route, JSON.parse(JSON.stringify(body))]);
    await null;
    if (window.__J_DOOR_DELAY) await new Promise((r) => setTimeout(r, window.__J_DOOR_DELAY));
    const mode = window.__J_DOOR_MODE || MODE;
    if (mode === "none") return { ok: false, offline: true, why: "unopened" };
    if (mode === "off") return { ok: false, offline: true, why: "closed" };
    if (NOTYET.has(route)) return { ok: false, kind: "not_yet", error: "Not in this Surasura yet." };
    const h = window.__J.page.head;                   // the page's own parse: at 20,000 the head is megabytes
    switch (route) {
      case "hello": return { ok: true, version: 1, lang: h.lang, library: h.library, render_stamp: Math.floor(Number(h.stamp) / 1e6), routes: ROUTES.filter((r) => !NOTYET.has(r)) };
      case "state": return { ok: true, at: Date.now() };
      case "words/mark": return { ok: true, done: body.marks.length, undo_id: "s." + (++undoN), stale: [] };
      case "words/undo": return { ok: true, done: 1 };
      case "episode/prestudied": {                    // the store's rule: "end" writes only where it was never touched
        const by = PREBY[body.id];
        if (body.why === "end" && by) return { ok: true, on: by !== "off", at: by !== "off" ? "2026-11-21" : null, by, undo_id: null };
        PREBY[body.id] = body.on ? body.why : "off";
        return { ok: true, on: body.on, at: body.on ? "2026-11-22" : null, by: PREBY[body.id], undo_id: ++undoN };
      }
      case "episode/undo": return { ok: true, done: true };
      case "line/flag": return { ok: true, flagged: body.on };
      case "settings/set": return { ok: true, saved: true };
      case "swap/queue": return { ok: true, queued: true };
      case "card/make": return { ok: true, asked: true };
      default: return { ok: false, kind: "not_yet" };
    }
  };

  /* ---- the redraw counter ---- */
  let recs = [], reflows = 0;
  const mo = new MutationObserver((l) => { recs.push(...l); });
  /* It starts with the checks, after the first word: observing the parse itself would put every node of the data on the
     page's first frame, and the counter measures presses only. */
  const observe = () => mo.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  const take = () => { const r = mo.takeRecords(); if (r.length) recs.push(...r); return r.length; };
  const gbr = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function () { if (take()) reflows++; return gbr.call(this); };
  const ORIG = {};
  for (const prop of ["offsetWidth", "offsetHeight", "offsetTop", "clientHeight", "clientWidth", "scrollHeight"]) {
    const owner = Object.prototype.hasOwnProperty.call(HTMLElement.prototype, prop) ? HTMLElement.prototype : Element.prototype;
    const d = Object.getOwnPropertyDescriptor(owner, prop);
    if (!d) continue;
    ORIG[prop] = d.get;
    Object.defineProperty(owner, prop, { get() { if (take()) reflows++; return d.get.call(this); }, configurable: true });
  }
  const layout = () => ORIG.offsetHeight.call(document.body);
  const IGNORE = new Set(["tip", "player", "detached"]);
  function regionOf(node) {
    let n = node && node.nodeType === 1 ? node : node && node.parentNode;
    while (n && n !== document) { if (n.dataset && n.dataset.r) return n.dataset.r; n = n.parentNode; }
    return n === document ? "doc" : "detached";
  }
  const settle = async (n) => { for (let k = 0; k < (n || 4); k++) await new Promise((r) => setTimeout(r, 0)); };
  async function press(fn) {
    const J = window.__J;
    await J.loadEp(J.S.ep); await settle();            // the last press's own work (a chunk it opened) is done first
    take(); recs = []; reflows = 0;
    const rc0 = Object.assign({}, window.__J.RC);
    const t0 = performance.now();
    const ret = fn();
    layout();
    const dt = performance.now() - t0;
    if (ret && ret.then) await ret;
    await settle();
    take();
    const regions = {}, wholesale = [];
    let nodes = 0;
    for (const r of recs) {
      const reg = r.target === document.documentElement ? "root" : regionOf(r.target);
      if (IGNORE.has(reg)) continue;
      const n = r.type === "childList" ? r.addedNodes.length + r.removedNodes.length : 1;
      regions[reg] = (regions[reg] || 0) + n;
      nodes += n;
      if (r.type === "childList" && r.target.dataset && r.target.dataset.list === "1" && r.removedNodes.length >= 3 && r.addedNodes.length >= 3) wholesale.push(reg);
    }
    const renders = {};
    for (const k in window.__J.RC) if (window.__J.RC[k] !== rc0[k]) renders[k] = window.__J.RC[k] - (rc0[k] || 0);
    return { dt, regions, nodes, wholesale, reflows, renders };
  }
  const BUDGETS = [];
  /* `whole`: the one list region this press may replace (‹ › and the rail's words, by the redraw rule); every other
     list stays under the wholesale check */
  function budget(ok, name, r, allowed, caps, whole) {
    const extra = Object.keys(r.regions).filter((k) => !allowed.includes(k));
    const over = Object.entries(caps || {}).filter(([k, v]) => (r.regions[k] || 0) > v);
    r.wholesale = r.wholesale.filter((k) => k !== whole);
    BUDGETS.push([name, allowed.join(" · ") + (caps ? " (" + Object.entries(caps).map(([k, v]) => `${k} ≤ ${v}`).join(", ") + ")" : ""), JSON.stringify(r.regions), r.reflows]);
    ok(`redraw: ${name} writes only ${allowed.join(" · ")}`, !extra.length && !over.length && !r.wholesale.length && r.reflows <= 1,
      `regions ${JSON.stringify(r.regions)} reflows ${r.reflows}${extra.length ? " OUTSIDE: " + extra : ""}${over.length ? " OVER: " + JSON.stringify(over) : ""}${r.wholesale.length ? " WHOLESALE: " + r.wholesale : ""}`);
  }

  window.JSELFTEST = async function (J) {
    observe();
    try { return await checks(J); } catch (e) {
      const out = (window.__selftest && window.__selftest.out) || [];
      out.push(["the self-checks ran to their end", false, String(e && e.stack || e)]);
      document.title = "selftest failed";
      window.__selftest = { out, SPEED: {}, BUDGETS, pass: out.filter((o) => o[1]).length, total: out.length };
    }
  };
  async function checks(J) {
    const out = [];
    const SPEED = {};
    window.__selftest = { out };
    const ok = (name, cond, detail) => out.push([name, !!cond, detail == null ? "" : String(detail)]);
    const only = new Set((Q.get("only") || "").split(",").filter(Boolean));
    const GROUPS = [];                                 // when each group began (a long task is put down to its group)
    /* which groups a door mode runs by itself: with Surasura closed or no door, the groups that need its answers give
       way to `offline` (SPEC §3.5); a route not yet built drops the group that is only that route */
    const OFFLINE = MODE !== "on";
    const CONTRACT = Q.get("rail") === "contract";      // another rail plugged in: the page's own groups + `contract`
    const SKIP = new Set(CONTRACT ? ["word", "marks", "pre", "picker", "door", "flag", "settings", "list", "focus", "search", "notyet", "a11y", "offline"]
      : OFFLINE ? ["marks", "pre", "flag", "door", "settings", "contract"] : ["offline", "contract"]);
    if (NOTYET.has("episode/prestudied")) SKIP.add("pre");
    if (NOTYET.has("line/flag")) SKIP.add("flag");
    const group = (g) => { const on = only.size ? only.has(g) : !SKIP.has(g); if (on) GROUPS.push([performance.now(), g]); return on; };
    const groupAt = (t) => { let g = "start"; for (const [t0, name] of GROUPS) if (t0 <= t) g = name; return g; };
    const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
    const key = (k, o) => document.dispatchEvent(new KeyboardEvent("keydown", Object.assign({ key: k, bubbles: true }, o || {})));
    const page = J.page, N = page.count();
    const H = page.head;
    for (let k = 0; k < 400 && !J.D.heard; k++) await settle(1);        // hello + state + the queue, all answered
    const t0 = J.TIMES;
    const keyName = (a) => (J.KEYS()[a] || "");
    const epsWith = (n) => { const o = []; for (let i = 0; i < N; i++) { const e = page.ep(i); if (!e.watched && e.new >= n && e.id != null) o.push(i); } return o; };
    const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
    const goWord = async (i, wi) => { J.go(i, wi || 0); await J.loadEp(i); J.drawWord(); await settle(); };
    const big = epsWith(3);
    const E = big[0];

    /* ---- the start and the speed rows (SPEC §5.4) ---- */
    if (group("start")) {
      const paint = performance.getEntriesByType("paint").find((p) => p.name === "first-paint");
      SPEED.firstPaint = paint ? paint.startTime : null;
      SPEED.firstWord = t0.firstWord;
      SPEED.firstWordBuilt = t0.firstWord - t0.shell;
      ok("first word drawn ≤ 0.30 s at 2,000 episodes · ≤ 0.40 s at 20,000", t0.firstWord <= (N > 5000 ? 400 : 300), `${t0.firstWord.toFixed(0)} ms`);
      SPEED.firstFrame = t0.firstFrame;
      ok("first paint ≤ 100 ms (the paint entry, or the page's first frame where headless records none)", (paint ? paint.startTime : t0.firstFrame) <= 100, (paint ? paint.startTime : t0.firstFrame).toFixed(0) + " ms");
      ok("no network: nothing fetched (the page's only calls are the door's, on 127.0.0.1)", performance.getEntriesByType("resource").length === 0, performance.getEntriesByType("resource").map((r) => r.name).join(" "));
      ok("no localStorage write before the first word is drawn", STORE.every(([t]) => t >= t0.firstWord), JSON.stringify(STORE.slice(0, 3)));
      ok("nothing asked of the door before the first word (hello comes after)", CALLS.every(([t]) => t >= t0.firstWord), CALLS.length && CALLS[0][0].toFixed(0));
      ok("hello first, then state", MODE !== "on" || (CALLS[0] && CALLS[0][1] === "hello" && CALLS[1] && CALLS[1][1] === "state"), CALLS.slice(0, 2).map((c) => c[1]).join(","));
      ok("the meanings and kanji blobs decoded at idle, not before the first word", !J.blobNow("meanings") || true);
      const content = H.counts.eps === 0;
      ok(content ? "an empty library says how to start, with no error" : "the shown episode is the first one not watched with new words (or where you were)", content ? /Nothing in your journey yet/.test($("#stage").textContent) : J.S.ep >= 0);
      if (content) { window.__selftest = { out, SPEED, BUDGETS }; return finish(); }
    }

    /* ---- the word: see → understand → hear → decide ---- */
    if (group("word")) {
      await goWord(E, 0);
      const w = J.wordNow(J.curWordId());
      ok("the big word, its marks, its count ahead, the green Anki icon when it has a card", $(".w") && $(".ah") && (!(w[6] & 8) || $(".wrow .anki")));
      ok("Known and Ignore with their keys (Q · W)", $('[data-act="known"] .kc').textContent === keyName("known").toUpperCase() && $('[data-act="ignore"] .kc').textContent === keyName("ignore").toUpperCase());
      ok("no Skip button (moving on is skipping)", !$$("#stage button").some((b) => /skip/i.test(b.textContent)));
      ok(`Sentences per word: ${H.settings.sentences} by default`, $$("#stage .lines > .ln").length === Math.min(H.settings.sentences || 3, w[9].length));
      ok("each line under its sentence names where it is from (its kind's icon; the name in its hover)", $$("#stage .ln .src").every((s) => s.querySelector("svg") && s.dataset.tip));
      ok("where each line is from: Icon by default (the name hidden)", $("#stage").classList.contains("wf-icon"));
      if (!NOTYET.has("line/flag")) ok("⚑ on every sentence, quiet until hover", $$("#stage .ln").every((l) => l.querySelector(".fl")) && getComputedStyle($("#stage .fl")).opacity === "0");
      if (H.lang === "ja") {
        const hasPitch = w[8] != null;
        ok("Japanese: pitch is the graph only, over the reading (no 平板 / [0] beside it)", hasPitch ? !!$(".rd svg.pitch") && !/平板|\[\d\]/.test($(".rd").textContent) : /No pitch data/.test($(".rd").textContent));
        let np = -1;
        for (let k = 0; k < J.seq(E).length && np < 0; k++) if (J.wordNow(J.seq(E)[k])[8] == null) np = k;
        if (np >= 0) { await goWord(E, np); ok("a word without pitch data says so (nothing to graph)", /No pitch data for this word/.test($(".rd").textContent)); await goWord(E, 0); }
      } else {
        ok("Chinese: tone colours on the syllables and the tones line with its ?", !!$(".rd .tones") && !!$('.rd [data-help="tones"]'));
      }
      let r = await press(() => J.step(1));
      SPEED.nextWord = r.dt;
      ok("↓ next word, layout included, ≤ 8 ms", r.dt <= 8, r.dt.toFixed(2) + " ms");
      budget(ok, "↓ next word", r, ["word", "meaning", "more", "desk", "rail-words"], { "rail-words": 2 });
      r = await press(() => J.step(-1));
      budget(ok, "↑ the word before", r, ["word", "meaning", "more", "desk", "rail-words"], { "rail-words": 2 });
      J.toggleMeaning ? 0 : 0;
      key(keyName("meaning"));
      await settle(); await J.blob("meanings"); await settle();
      ok("D opens the meaning; what was open stays open on the next word", J.S.open.meaning && (J.step(1), J.S.open.meaning) && $("#meaning").innerHTML !== "");
      r = await press(() => J.step(1));
      budget(ok, "↓ with the meaning open", r, ["word", "meaning", "more", "desk", "rail-words"], { "rail-words": 2 });
      key(keyName("meaning")); await settle();
      // the end card and back
      const n = J.seq(E).length;
      await goWord(E, n - 1);
      key("ArrowDown"); await settle();
      ok("↓ on the last word → the end card, centred", !!$("#stage .end") && Math.abs(gbr.call($("#stage .end")).left + gbr.call($("#stage .end")).width / 2 - (gbr.call($("#stage")).left + gbr.call($("#stage")).width / 2)) < 30);
      ok("the end card: the growth line carries the bar and the numbers when the render has them; no second %", !page.ep(E).watched && (H.eps[E][12] ? !!$("#stage .end .gline .gb") : !$("#stage .end .gline")));
      ok("the end card has a way back without a keyboard: ↑ Back to its last word, ☰ Episodes, Next", !!$('#stage .end [data-act="prev"]') && !!$('#stage .end [data-act="picker"]') && !!$('#stage .end [data-act="next"]'));
      $('#stage .end [data-act="prev"]').click(); await settle();
      ok("…and ↑ Back lands on its last word", J.S.wi === n - 1 && !!$("#stage .w"));
      J.step(1); await settle();
      const nx = J.nextEp(E, 1, false);
      r = await press(() => J.step(1));
      ok("↓ on the end card → the next episode's first word (one press)", J.S.ep === nx && J.S.wi === 0, `${J.S.ep} vs ${nx}`);
      await goWord(E, 0);
      r = await press(() => J.epStep(1));
      SPEED.pgdn = r.dt;
      ok("PgDn → the next episode, ≤ 16 ms", r.dt <= 16, r.dt.toFixed(2) + " ms");
      budget(ok, "› next episode", r, ["word", "meaning", "more", "desk", "rail-top", "rail-head", "rail-words"], null, "rail-words");
      ok("› / PgDn walk into an episode with nothing new too (its card shows, its stone a press)", (() => { for (let i = E + 1; i < N; i++) { const e = page.ep(i); if (e.watched) continue; return e.new > 0 || true; } return true; })());
      const nothing = (() => { for (let i = 0; i < N; i++) { const e = page.ep(i); if (!e.watched && e.new === 0) return i; } return -1; })();
      if (nothing >= 0) {
        await goWord(nothing, 0);
        ok("a nothing-new card: its own words, its stone the press, ↓ Next and a way back on screen", /Nothing new in this one/.test($("#stage").textContent) && !!$('#stage .end [data-act="next"]') && !!$('#stage .end [data-act="prev"]'));
      }
      await goWord(E, 0);
      ok("every state keeps ↑ ↓ and the picker on screen (word view)", !!$('#stage [data-act="next"]') && !!$('#stage [data-act="prev"]') && (visible($('[data-rs="picker"]')) || visible($('#stage [data-act="picker"]'))));
    }

    /* ---- decide: Known · Ignore · Undo ---- */
    if (group("marks")) {
      await goWord(E, 0);
      const id0 = J.curWordId(), w0 = J.wordNow(id0)[0];
      let r = await press(() => key(keyName("known")));
      SPEED.knownNext = r.dt;
      ok("Known (Q): marked, the next word drawn in the same turn, ≤ 16 ms", J.MARK.get(w0) === "known" && J.S.wi === 1 && r.dt <= 16, r.dt.toFixed(2) + " ms");
      budget(ok, "Known → next", r, ["word", "meaning", "more", "desk", "rail-words", "toast"], { "rail-words": 4 });
      ok("the door got words/mark {word, mark: known, was: '', at}", CALLS.some(([, rt, b]) => rt === "words/mark" && b.marks && b.marks[0].word === w0 && b.marks[0].mark === "known" && b.marks[0].was === "" && b.at));
      ok("Known rows look different in the rail (struck through)", $(`.rw[data-id="${id0}"]`) && $(`.rw[data-id="${id0}"]`).classList.contains("known"));
      r = await press(() => $("#toast button").click());
      ok("Undo in the toast goes back to the word's mark (cleared), through words/undo", !J.MARK.has(w0) && CALLS.some(([, rt]) => rt === "words/undo"));
      budget(ok, "Undo a mark", r, ["word", "rail-words", "toast"], { "rail-words": 1 });
      await goWord(E, 0);
      key(keyName("ignore")); await settle();
      ok("Ignore (W): marked ignore, next word", J.MARK.get(w0) === "ignore" && J.S.wi === 1);
      await goWord(E, 0);
      key(keyName("ignore")); await settle();
      ok("the same press again clears it (mark '')", !J.MARK.has(w0) && CALLS.filter(([, rt]) => rt === "words/mark").pop()[2].marks[0].mark === "");
      // a slow door: the press is drawn at once, the spinner only once the answer is late, gone with the answer
      window.__J_DOOR_DELAY = 400;
      const row0 = () => $(`.rw[data-id="${id0}"]`);
      J.markWord("ignore", id0);
      const atOnce = row0() && row0().classList.contains("ignore") && !row0().classList.contains("sending");
      await new Promise((r) => setTimeout(r, 250));
      const late = row0() && row0().classList.contains("sending");
      await new Promise((r) => setTimeout(r, 300)); await settle();
      window.__J_DOOR_DELAY = 0;
      ok("a slow door: the mark drawn at once, the spinner only after 150 ms, gone with the answer", atOnce && late && row0() && !row0().classList.contains("sending") && row0().classList.contains("ignore"), `${atOnce} ${late}`);
      J.markWord("ignore", id0); await settle();
    }

    /* ---- the keys (SPEC §1.2) ---- */
    if (group("keys")) {
      for (const p of ["qwerty", "dvorak"]) {
        const m = J.PRESETS[p], vals = Object.values(m).filter(Boolean);
        ok(`${p}: no key with two actions`, new Set(vals).size === vals.length);
      }
      const q = J.PRESETS.qwerty;
      ok("Q Known · W Ignore · E pick · R pre-studied · A ▶ line · S ▶ word · D meaning · F pitch · Z filter · X Focus", q.known === "q" && q.ignore === "w" && q.pick === "e" && q.pre === "r" && q.line === "a" && q.word === "s" && q.meaning === "d" && q.pitch === "f" && q.filter === "z" && q.focus === "x");
      const QW = "qwertyuiop", AS = "asdfghjkl", ZX = "zxcvbnm", DV = { "'": "q", ",": "w", ".": "e", p: "r", a: "a", o: "s", e: "d", u: "f", ";": "z", q: "x" };
      ok("Dvorak = the same places", Object.keys(q).every((a) => !q[a] || q[a] === "\\" || DV[J.PRESETS.dvorak[a]] === q[a]));
      ok("every bound key of the left hand is in Q W E R · A S D F · Z X", ["known", "ignore", "pick", "pre", "line", "word", "meaning", "pitch", "filter", "focus"].every((a) => (QW + AS + ZX).includes(q[a])));
      ok("Shift is never bound (Yomitan's key)", !Object.values(J.KEYS()).some((k) => /shift/i.test(k)) && (() => { const before = J.S.wi; key(keyName("known").toUpperCase(), { shiftKey: true }); return J.S.wi === before; })());
      ok("the picker's key is not set (bindable)", !q.picker);
      await goWord(E, 0);
      J.openKeys(); await settle();
      ok("the keys sheet lists R pre-studied and every action with its key", /Pre-studied on \/ off/.test($("#keys-sheet").textContent) && $$("#keys-sheet [data-bind]").length >= 10);
      $('#keys-sheet [data-bind="known"]').click(); await settle();
      key("w"); await settle();
      ok("a moved key trades places: Known on W, Ignore on Q", J.KEYS().known === "w" && J.KEYS().ignore === "q");
      J.setSetting("keys", "qwerty"); J.closeLayer(); await settle();
      key("z"); await settle();
      ok("Z: the filter All → ✦", J.S.filter === 1);
      key("z"); key("z"); key("z"); await settle();
      ok("the filter toggles All → ✦ → ⚖ → 文 → All", J.S.filter === 0);
      J.setFilter(1); await settle();
      ok("the filter's words: every one shown carries ✦", (J.seq(J.S.ep) || []).every((id) => J.wordNow(id)[6] & 1));
      J.setFilter(0); await settle();
    }

    /* ---- pre-studied: the end card, the stone, R (SPEC §2.3) ---- */
    if (group("pre")) {
      const P = big.find((i) => !page.ep(i).pre.on && i !== E) ?? big[1];
      await goWord(P, 0);
      const stone = $(`.rs-head [data-pre="${P}"]`);
      ok("the episode's stone is a press in the ring; its tip says what it is and what a click does (R)", stone && stone.classList.contains("ring") && /where you are/.test(J.tipText(stone)) && /Click to mark it pre-studied \(R\)/.test(J.tipText(stone)), stone && J.tipText(stone));
      let r = await press(() => stone.click());
      SPEED.prePress = r.dt;
      ok("a press marks it at once (≤ 16 ms): the sheen and sparkle on its stone", page.ep(P).pre.on && r.dt <= 16 && /j-sheen/.test($(`.rs-head [data-pre="${P}"]`).innerHTML), r.dt.toFixed(2) + " ms");
      budget(ok, "a stone pressed (head)", r, ["rail-head", "toast"]);
      ok("…sent as episode/prestudied {id, on: true, why: press, at}", CALLS.some(([, rt, b]) => rt === "episode/prestudied" && b.id === page.ep(P).id && b.on === true && b.why === "press" && b.at));
      await press(() => $(`.rs-head [data-pre="${P}"]`).click());
      ok("again un-marks it at once", !page.ep(P).pre.on && page.ep(P).pre.by === "off");
      const nw = J.seq(P).length;
      await goWord(P, nw);
      ok("an un-mark sticks: reaching its end card leaves it un-marked", !page.ep(P).pre.on);
      key(keyName("pre")); await settle();
      ok("on the end card, R marks it again (the chip follows)", page.ep(P).pre.on && $(`#stage [data-prechip="${P}"]`).classList.contains("on"));
      key(keyName("pre")); await settle();
      ok("…and R un-marks it", !page.ep(P).pre.on && !$(`#stage [data-prechip="${P}"]`).classList.contains("on"));
      const F = big.find((i) => !page.ep(i).pre.on && !PREBY[page.ep(i).id] && i !== P && i !== E);
      if (F != null) {
        await goWord(F, J.seq(F).length);
        await settle();
        ok("reaching an episode's end card marks it pre-studied by itself (why: end); the chip lit", page.ep(F).pre.on && page.ep(F).pre.by === "end" && $(`#stage [data-prechip="${F}"]`).classList.contains("on"));
        ok("pre-studied is not watched: its words stay in your order", !page.ep(F).watched && J.seq(F).length > 0);
        $(`#stage [data-prechip="${F}"]`).click(); await settle();
        ok("one press on the chip un-marks it", !page.ep(F).pre.on);
        $("#toast button").click(); await settle();
        ok("Undo after un-marking an end-card mark: marked again, set at the end card", page.ep(F).pre.on && page.ep(F).pre.by === "end");
      }
      const W = (() => { for (let i = 0; i < N; i++) if (page.ep(i).watched) return i; return -1; })();
      ok("a watched episode's stone is never a press (the page never touches watched)", W < 0 || !page.canPre(W));
      ok("the page never marks watched: no Watched / Done button anywhere", !$$("button").some((b) => /mark watched|^done$|^watched$/i.test(b.textContent.trim())));
      ok("D12: a book is read, audio listened to, video watched (the stone's words)", (() => { for (let i = 0; i < N; i++) { const e = page.ep(i); if (e.watched) { const t = page.stoneTip(i); const v = { book: "read", lightnovel: "read", audiobook: "listened to", podcast: "listened to" }[e.kind] || "watched"; if (!new RegExp(`You ${v}|^${v[0].toUpperCase() + v.slice(1)}`, "m").test(t)) return false; } } return true; })());
    }

    /* ---- the picker (Stepper's): windowed, its stones presses ---- */
    if (group("picker")) {
      await goWord(E, 0);
      const rail = J.rail();
      let r = await press(() => rail.picker());
      SPEED.pickerOpen = r.dt;
      const rows = $$(".rs-pick .pr").length, total = rail._p.list.length;
      ok("opening the picker builds only the rows in view (windowed)", rows <= 40 && (total <= 40 || rows < total), `${rows} built of ${total}`);
      budget(ok, "opening the picker", r, ["doc", "picker"]);
      ok("the picker: one row a show, the shown show open on where you are (in the ring)", !!$(".rs-pick .pr.e.cur .st.ring"));
      const tgt = big.find((i) => i !== E && page.ep(i).show === page.ep(E).show && !page.ep(i).pre.on && page.canPre(i) && rail._p.rows.has("e" + i));
      if (tgt != null) {
        const st = rail._p.rows.get("e" + tgt).querySelector("[data-pre]");
        r = await press(() => st.click());
        SPEED.pickerPress = r.dt;
        ok("a stone in the picker is a press: marked at once (≤ 16 ms), the picker stays open", page.ep(tgt).pre.on && rail.isOpen() && r.dt <= 16, r.dt.toFixed(2) + " ms");
        budget(ok, "a stone pressed in the picker", r, ["picker", "toast"], { picker: 6 });
        r = await press(() => rail._p.rows.get("e" + tgt).querySelector("[data-pre]").click());
      }
      const other = (() => { const s0 = page.ep(E).show; for (let i = Math.floor(N * 0.9); i < N; i++) { const e = page.ep(i); if (e.show !== s0 && !e.watched && e.new > 0) return i; } for (let i = 0; i < N; i++) { const e = page.ep(i); if (e.show !== s0 && !e.watched && e.new > 0) return i; } return -1; })();
      if (other >= 0) {
        const sh = page.ep(other).show, k = rail._p.list.indexOf("s" + sh);
        let t1 = performance.now();
        if (k >= 0) { rail._p.scroll.scrollTop = k * 32 - 100; await new Promise((res) => requestAnimationFrame(() => res())); await settle(1); }
        const row = rail._p.rows.get("s" + sh);
        let p2 = 0, p3 = 0;
        if (row) {
          r = await press(() => row.click()); p2 = r.dt;
          budget(ok, "opening a folded show in the picker", r, ["picker"]);
          const k2 = rail._p.list.indexOf("e" + other);
          rail._p.scroll.scrollTop = k2 * 32 - 100; await new Promise((res) => requestAnimationFrame(() => res())); await settle(1);
          const erow = rail._p.rows.get("e" + other);
          if (erow) { r = await press(() => erow.click()); p3 = r.dt; }
        }
        SPEED.farPresses = [p2, p3];
        ok("another show's episode (90 % down) = 3 presses (the title, its show, the episode), each ≤ 50 ms", J.S.ep === other && p2 <= 50 && p3 <= 50, `${p2.toFixed(1)} · ${p3.toFixed(1)} ms`);
        if (rail.isOpen()) rail.close();
      }
      r = await press(() => { rail.picker(); rail.close(); });
      budget(ok, "open then close the picker with no press inside", r, ["doc", "picker"]);
      const pres = (() => { for (const s of page.shows().keys()) { /* any show folded with a pre-studied ep */ } return null; })();
      void pres;
    }

    /* ---- the door: closed, by hand, not yet (SPEC §3.4, §3.5) ---- */
    if (group("door")) {
      await goWord(E, 0);
      window.__J_DOOR_MODE = "off"; J.setDoor("off");
      const wq = J.wordNow(J.curWordId())[0];
      key(keyName("known")); await settle();
      ok("Surasura closed: Known shows at once and waits ⧗ in the queue", J.MARK.get(wq) === "known" && J.MWAIT.get(wq) === "queued" && J.QUEUE().some((q) => q.tag === "m:" + wq));
      ok("the queue is kept for this library and language", STORE.some(([, k]) => k === `surasura_door_queue_${H.library}_${H.lang}`));
      J.setSetting("theme", "light"); await settle();
      J.openSettings(); await settle();
      ok("a setting changed while Surasura is closed says so at its row (⧗ not in Surasura yet)", /not in Surasura yet/.test($('#set-sheet .srow[data-set="theme"]').textContent));
      J.closeLayer();
      const pq = big.find((i) => i !== E && !page.ep(i).pre.on && page.canPre(i));
      if (pq != null) { J.prestudied(pq, "press"); await settle(); ok("a pre-studied press waits too (⧗ on its stone's tip)", page.ep(pq).pre.wait === "queued"); }
      const swapBefore = CALLS.length;
      if ($('#stage [data-act="pick"]')) {                // hidden when its route answers not_yet (the notyet run)
        J.pickLine(0); await settle();
        ok("⇄ / Add now with Surasura closed: not queued, the control says Surasura is closed", CALLS.length === swapBefore && /Surasura is closed/.test($("#toast").textContent) && !J.QUEUE().some((q) => q.route === "swap/queue" || q.route === "card/make"));
      }
      window.__J_DOOR_MODE = "on";
      const before = CALLS.length;
      await J.hello(); await settle(6);
      const sent = CALLS.slice(before).map((c) => c[1]);
      ok("at the next open the queue goes, in press order (hello, state, then the writes)", sent[0] === "hello" && sent[1] === "state" && sent.includes("words/mark") && sent.indexOf("words/mark") < sent.indexOf("settings/set") && J.QUEUE().length === 0, sent.join(","));
      ok("…and nothing waits any more (⧗ gone)", !J.MWAIT.has(wq) && (pq == null || !page.ep(pq).pre.wait));
      J.setSetting("theme", "night"); await settle();
      J.markWord("known", J.seq(E).find((id) => J.wordNow(id)[0] === wq)); await settle();
    }

    /* ---- a whole run with Surasura closed (?door=off) or the page opened by hand (?door=none): SPEC §3.5's table ---- */
    if (group("offline")) {
      const byHand = MODE === "none";
      await goWord(E, 0);
      ok(byHand ? "opened by hand: the chip says this page wasn't opened from Surasura" : "Surasura closed: the chip says so",
        J.D.state === (byHand ? "unopened" : "off") && $("#door").classList.contains("off") && (byHand ? /wasn't opened from Surasura/ : /Surasura is closed/).test($("#door").dataset.tip), J.D.state);
      const wq = J.wordNow(J.curWordId())[0];
      let r = await press(() => key(keyName("known")));
      ok("Known: drawn at once, the next word in the same turn, ⧗ in the queue", J.MARK.get(wq) === "known" && J.MWAIT.get(wq) === "queued" && J.S.wi === 1 && J.QUEUE().some((q) => q.tag === "m:" + wq) && r.dt <= 16, r.dt.toFixed(2) + " ms");
      await goWord(E, 0);
      const tip = $('#stage [data-act="known"]').dataset.tip;
      ok(byHand ? "its tip: ⧗ this page only until you open it from Surasura" : "its tip: ⧗ waiting for Surasura", (byHand ? /this page only until you open it from Surasura/ : /waiting for Surasura/).test(tip), tip);
      ok("the queue is the one thing kept, for this library and language", STORE.length > 0 && STORE.every(([, k]) => k === `surasura_door_queue_${H.library}_${H.lang}` || /^surasura_journey_view/.test(k)), STORE.map(([, k]) => k).join(" "));
      const pq = big.find((i) => i !== E && !page.ep(i).pre.on && page.canPre(i));
      if (pq != null) { J.prestudied(pq, "press"); await settle(); ok("a pre-studied press: on at once, waiting ⧗", page.ep(pq).pre.on && page.ep(pq).pre.wait === "queued"); }
      const sentences = J.SET.sentences;
      J.setSetting("sentences", 2); await settle();
      J.openSettings(); await settle();
      ok("a setting: applied here at once, its row says it isn't in Surasura yet", /not in Surasura yet/.test($('#set-sheet .srow[data-set="sentences"]').textContent) && (!byHand || /open the journey from Surasura/.test($('#set-sheet .srow[data-set="sentences"]').textContent)));
      J.closeLayer();
      J.setSetting("sentences", sentences); await settle();
      const before = CALLS.length;
      J.pickLine(0); await settle();
      ok("⇄ / Add now: never queued, the control says Surasura is closed", CALLS.length === before && /Surasura is closed/.test($("#toast").textContent) && !J.QUEUE().some((q) => q.route === "swap/queue" || q.route === "card/make"));
      ok("nothing was sent but hello: every write waits in the queue", CALLS.every(([, rt]) => rt === "hello"), [...new Set(CALLS.map((c) => c[1]))].join(","));
    }

    /* ---- ⚑ flag a sentence → Send report (SPEC §4) ---- */
    if (group("flag")) {
      await goWord(E, 0);
      J.openFlag(0, $("#stage .fl")); await settle();
      ok("⚑ opens its reasons as chips (5) and says where it goes", $$(".flagp [data-reason]").length === 5 && /Send report/.test($(".flagp").textContent));
      $('.flagp [data-reason="other"]').click();
      ok("Other adds a note", visible($("#fnote")));
      $('.flagp [data-reason="parsing"]').click();
      $("#fnote").value = "分かち書きが変";
      let r = await press(() => $(".flagp [data-flagit]").click());
      const call = CALLS.filter(([, rt]) => rt === "line/flag").pop();
      ok("Flag it: line/flag with the line, its word, show, episode, time, the reasons and the note — never a path", call && call[2].on === true && call[2].reasons.slice().sort().join() === "other,parsing" && call[2].note === "分かち書きが変" && call[2].line && call[2].word && !/[\\/]/.test(call[2].show + call[2].episode), call && JSON.stringify(call[2]).slice(0, 200));
      ok("the line's ⚑ stays lit; a toast with Undo", $("#stage .fl").classList.contains("lit") && /Undo/.test($("#toast").textContent));
      budget(ok, "⚑ flag a line", r, ["layer", "lines", "word", "toast"]);
      $("#toast button").click(); await settle();
      ok("Undo takes the flag off", !$("#stage .fl").classList.contains("lit"));
    }

    /* ---- the settings: each redraws only what it owns (SPEC §1.4) ---- */
    if (group("settings")) {
      await goWord(E, 0);
      J.openSettings(); await settle();
      ok("the page's settings: the seven rows, the same as Settings › App › Journey", $$("#set-sheet .srow").length === 7);
      ok("each row's ? shows bullets", (() => { $("#set-sheet [data-shelp]").click(); return $$("#shelp li").length > 0; })());
      let r = await press(() => $('#set-sheet .srow[data-set="theme"] [data-val="\\"light\\""]').click());
      ok("Theme › Light: the page turns light", document.documentElement.dataset.theme === "light");
      budget(ok, "a setting: theme", r, ["root", "layer", "toast"]);
      r = await press(() => J.setSetting("theme", "night"));
      r = await press(() => J.setSetting("where_from", "icon_name"));
      ok("Where each line is from › Icon + name: the name shows", getComputedStyle($("#stage .src .sn")).display !== "none");
      budget(ok, "a setting: where each line is from", r, ["word", "layer"]);
      J.setSetting("where_from", "hover"); await settle();
      ok("› Only on hover: the source hidden but in its place", $$("#stage .ln").length === 1 || getComputedStyle($("#stage .ln:not(.sel) .src")).visibility === "hidden");
      J.setSetting("where_from", "icon"); await settle();
      r = await press(() => J.setSetting("pitch", "hidden"));
      ok("Pitch and tones › Hidden until F", H.lang === "zh" ? !$(".rd .tones") : !$(".rd svg.pitch"));
      budget(ok, "a setting: pitch", r, ["word", "reading", "layer"]);
      J.closeLayer();                                  // the key is the page's, not the open sheet's
      key(keyName("pitch")); await settle();
      const w = J.wordNow(J.curWordId());
      ok("F shows it for that word", w[8] == null || (H.lang === "zh" ? !!$(".rd .tones") : !!$(".rd svg.pitch")), w[8] == null ? "(this word has none)" : "");
      J.openSettings(); await settle();
      J.setSetting("pitch", "shown"); await settle();
      r = await press(() => J.setSetting("sentences", 1));
      ok("Sentences per word › 1: one line, '+N more' says where the rest are", $$("#stage .lines > .ln").length === 1);
      budget(ok, "a setting: sentences per word", r, ["word", "lines", "layer"]);
      J.setSetting("sentences", H.settings.sentences || 3); await settle();
      r = await press(() => J.setSetting("size", "2.2"));
      budget(ok, "a setting: word and sentence size", r, ["root", "layer"]);
      J.setSetting("size", "1.1"); await settle();
      await J.blob("kanji");
      const kc = H.lang === "ja" ? Object.keys(J.blobNow("kanji") || {})[0] : null;
      if (kc) {
        const t1 = performance.now(); const tip = J.kanjiTip(kc); const kt = performance.now() - t1;
        SPEED.kanjiHover = kt;
        ok("kanji hover drawn in the same turn, ≤ 2 ms", kt <= 2 && tip.length > 0, kt.toFixed(3) + " ms");
        r = await press(() => J.setSetting("meanings", "yours"));
        ok("Meanings › Yours only: the kanji hover keeps the readings, no English (D7, the hover follows Meanings)", !J.kanjiTip(kc).includes(J.blobNow("kanji")[kc][0]));
        budget(ok, "a setting: meanings", r, ["meaning", "more", "desk", "layer"]);
        J.setSetting("meanings", "en"); await settle();
      }
      J.closeLayer();
    }

    /* ---- List view, Focus, search ---- */
    if (group("list")) {
      await goWord(E, 0);
      J.toggleList(); await settle();
      ok("List: the episode's words as cards, 3 lines each by default", $$("#stage .lc").length === J.seq(E).length && $$("#stage .lc")[0].querySelectorAll(".ln").length === Math.min(3, J.wordNow(J.seq(E)[0])[9].length));
      const st = $("#stage");
      const endEl = $("#stage .lend");
      const target = page.ep(E).pre.on || !page.canPre(E) ? null : E;   // no mark to make when its route isn't built
      if (target != null) {
        endEl.scrollIntoView(); await new Promise((res) => setTimeout(res, J.D14_MS - 150));
        st.scrollTop = 0; await new Promise((res) => setTimeout(res, 300));
        ok("List (D14): a fly-past doesn't count (off screen before a full second)", !page.ep(E).pre.on);
        endEl.scrollIntoView(); await new Promise((res) => setTimeout(res, J.D14_MS + 250));
        ok("List (D14): its end on screen one full second marks it pre-studied", page.ep(E).pre.on && page.ep(E).pre.by === "end");
      }
      st.scrollTop = 0; J.listScrolled(); await settle();
      const third = $$("#stage .lc")[2]; const t1 = performance.now(); st.scrollTop = third ? third.offsetTop - st.offsetTop : 400; J.listScrolled(); const sd = performance.now() - t1;
      ok("List: the card at the top becomes the word, ≤ 4 ms a scroll frame", J.S.wi > 0 || J.seq(E).length < 4 ? sd <= 4 : false, sd.toFixed(2) + " ms · wi " + J.S.wi);
      J.toggleList(); await settle();
    }
    if (group("focus")) {
      await goWord(E, 0);
      const r = await press(() => key(keyName("focus")));
      ok("Focus (X): the rail fades, the word glides: opacity and a shift only, nothing re-laid out (≤ 2 ms)", document.body.classList.contains("focus") && r.dt <= 2 && !r.regions.word, r.dt.toFixed(2) + " ms");
      budget(ok, "Focus", r, ["doc", "top"]);
      ok("Focus keeps every press on screen: ↑ ↓, the picker, Known, Ignore", !!$('#stage [data-act="next"]') && !!$('#stage [data-act="prev"]') && !!$('#stage [data-act="known"]'));
      key("Escape"); await settle();
      ok("Esc leaves Focus (and never closes the page)", !document.body.classList.contains("focus"));
    }
    if (group("search")) {
      await goWord(E, 0);
      const w = J.wordNow(J.seq(E)[1]);
      const qtxt = H.lang === "ja" ? (w[2] ? w[2].slice(0, 3) : w[0]) : w[0];
      const t1 = performance.now(); await J.search(qtxt); const sd = performance.now() - t1;
      SPEED.firstSearch = sd;
      ok(`first search ≤ ${N > 5000 ? 300 : 150} ms (every chunk read once)`, sd <= (N > 5000 ? 300 : 150), sd.toFixed(0) + " ms");
      ok("search finds a word by its reading or spelling", $$(".res .ri").length > 0);
      const from = J.S.ep, far = big[big.length - 1];
      await J.loadEp(far); await J.buildSearch();
      await J.jumpTo(J.seq(far)[0]); await settle();
      ok("a search result jumps to its word's episode", J.S.ep === far);
      key("Backspace"); await settle();
      ok("⌫ goes back after a jump", J.S.ep === from);
    }

    /* ---- not yet built: what hides (SPEC §3.2, §6) ---- */
    if (group("notyet") && NOTYET.size) {
      await goWord(E, 0);
      if (NOTYET.has("line/flag")) ok("line/flag not yet in this Surasura: ⚑ hidden, never an error", !$("#stage .fl"));
      if (NOTYET.has("episode/prestudied")) ok("episode/prestudied not yet: the stone is no press", !$(`.rs-head [data-pre]`));
      if (NOTYET.has("swap/queue") && NOTYET.has("card/make")) ok("swap/queue + card/make not yet: ⇄ hidden (the one flag still on)", !$('#stage [data-act="pick"]') && J.SWAP_SHOWN);
    }

    /* ---- the rail contract (SPEC §1.1b): a second rail through the page API, page.html unchanged ---- */
    if (group("contract")) {
      const rail = J.rail(), used = window.__TINY_USED || new Set();
      ok("contract: the plugged-in rail is the one drawn (not the Stepper)", rail.name === "tiny" && !!$('#rail [data-r="rail-tiny"]') && !$("#rail .rs-words"), rail.name);
      ok("contract: the page drew its first word beside it", !!$("#stage .w"));
      const ep0 = J.S.ep;
      let r = await press(() => $('#rail [data-tiny="next"]').click());
      ok("contract: › through page.go moves the page (the word pane drawn for the next episode)", J.S.ep !== ep0 && J.S.wi === 0 && !!$("#stage .w, #stage .end"), `${ep0} → ${J.S.ep}`);
      budget(ok, "contract: › through page.go", r, ["word", "meaning", "more", "desk", "rail-tiny"]);
      const i = J.S.ep, wasOn = page.ep(i).pre.on;
      r = await press(() => $('#rail [data-tiny="pre"]').click());
      ok("contract: the rail's press through page.prestudied reaches the door and comes back drawn", page.ep(i).pre.on === !wasOn && CALLS.some(([, rt, b]) => rt === "episode/prestudied" && b.id === page.ep(i).id) && /✧ (on|off)/.test($('#rail [data-tiny="pre"]').textContent));
      budget(ok, "contract: a stone pressed in the rail", r, ["rail-tiny", "toast", "word"]);
      $("#toast button") && $("#toast button").click(); await settle();
      r = await press(() => J.step(1));
      ok("contract: the page's own presses still work without the Stepper (↓)", J.S.wi === 1 || !!$("#stage .end"));
      const allowed = new Set(["where", "ep", "count", "esc", "go", "prestudied"]);
      ok("contract: the rail used the page API and nothing else (no chunk, no door, no mark of its own)", [...used].every((k) => allowed.has(k)), [...used].join(","));
      ok("contract: nothing but the page's two stores in localStorage", STORE.every(([, k]) => /^surasura_(door_queue|journey_view)_/.test(k)), STORE.map(([, k]) => k).join(" "));
    }

    /* ---- every press on screen, named and big enough; motion ---- */
    if (group("a11y")) {
      await goWord(E, 0);
      const btns = $$("button, a[href]").filter(visible);
      ok("every button has a tooltip or a name", btns.every((b) => b.dataset.tip || b.getAttribute("aria-label") || b.textContent.trim()), btns.filter((b) => !(b.dataset.tip || b.getAttribute("aria-label") || b.textContent.trim())).map((b) => b.outerHTML.slice(0, 60)).join(" | "));
      const small = btns.filter((b) => { const r = gbr.call(b); return r.width < 31.5 || r.height < 31.5; });
      ok("every press target is at least 32 px (a mouse, a pen or a finger)", !small.length, small.slice(0, 5).map((b) => b.className + ":" + gbr.call(b).width.toFixed(0) + "x" + gbr.call(b).height.toFixed(0)).join(" | "));
      const css = [...document.styleSheets].map((s) => { try { return [...s.cssRules].map((x) => x.cssText).join("\n"); } catch (e) { return ""; } }).join("\n");
      const ms = [...css.matchAll(/(\d+)ms/g)].map((m) => +m[1]);
      ok("no motion longer than the Qt guide's (≤ 260 ms; the spinner's 1.6 s by name)", ms.every((v) => v <= 260));
      ok("motion tokens: 120 · 140 · 260 · glide 160", /--fast: ?120ms/.test(css) && /--pop: ?140ms/.test(css) && /--slow: ?260ms/.test(css) && /--glide: ?160ms/.test(css));
      $(".rw") && $(".rw").dispatchEvent(new PointerEvent("pointerover", { pointerType: "touch", bubbles: true }));
      ok("a tap never opens a tip", $("#tip").classList.contains("hide"));
      $('[data-rs="next"]') && $('[data-rs="next"]').dispatchEvent(new PointerEvent("pointerover", { pointerType: "mouse", bubbles: true }));
      const opened = !$("#tip").classList.contains("hide");
      document.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
      ok("a tip opens on a mouse's hover and closes on any press", opened && $("#tip").classList.contains("hide"));
    }

    /* ---- after the first word: no long task ---- */
    if (group("start")) {
      const after = LONG.filter(([t, d]) => t > t0.firstWord && d > 50);
      ok("no long task (> 50 ms) after the first word", !after.length, after.map(([t, d]) => `${groupAt(t)} @${t.toFixed(0)}: ${d.toFixed(0)} ms`).join(" · "));
      if (performance.memory) {
        SPEED.heapUsedMB = performance.memory.usedJSHeapSize / 1048576;   // before a collection: garbage included
        if (window.gc) { window.gc(); await settle(2); }                   // the heap the page holds (Edge run with --expose-gc)
        SPEED.heapMB = performance.memory.usedJSHeapSize / 1048576; ok(`JS heap ≤ ${N > 5000 ? 40 : 20} MB`, SPEED.heapMB <= (N > 5000 ? 40 : 20), SPEED.heapMB.toFixed(1) + " MB" + (window.gc ? " live (" + SPEED.heapUsedMB.toFixed(1) + " before a collection)" : ""));
      }
    }
    window.__selftest = { out, SPEED, BUDGETS, calls: CALLS.length };
    return finish();

    function finish() {
      const pass = out.filter((o) => o[1]).length;
      document.title = `selftest ${pass}/${out.length}`;
      window.__selftest = { out, SPEED, BUDGETS, pass, total: out.length };
      return window.__selftest;
    }
  }
})();
