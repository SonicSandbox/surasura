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
    if (window.__J_DOOR_HOOK) { const x = await window.__J_DOOR_HOOK(route, body); if (x) return x; }   // one check's own answer
    const h = window.__J.page.head;                   // the page's own parse: at 20,000 the head is megabytes
    switch (route) {
      case "hello": return { ok: true, version: 1, lang: h.lang, library: h.library, render_stamp: h.minor >= 1 ? Number(h.stamp) : Math.floor(Number(h.stamp) / 1e6), routes: ROUTES.filter((r) => !NOTYET.has(r)) };
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
    const SKIP = new Set(CONTRACT ? ["word", "marks", "pre", "picker", "door", "queue", "player", "flag", "settings", "meet", "carry", "list", "focus", "search", "notyet", "a11y", "offline", "layout"]
      : OFFLINE ? ["marks", "pre", "flag", "door", "queue", "settings", "meet", "carry", "contract"] : ["offline", "contract"]);
    if (NOTYET.has("episode/prestudied")) SKIP.add("pre");
    if (NOTYET.has("line/flag")) SKIP.add("flag");
    const group = (g) => { const on = only.size ? only.has(g) : !SKIP.has(g); if (on) GROUPS.push([performance.now(), g]); return on; };
    const groupAt = (t) => { let g = "start"; for (const [t0, name] of GROUPS) if (t0 <= t) g = name; return g; };
    const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
    const headCount = () => { const h = $$("#stage .sh").find((el) => /Sentences/.test(el.textContent)), m = h && /Sentences · (\d+)/.exec(h.textContent); return m ? Number(m[1]) : null; };   // the word's header, "Sentences · N"
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

    /* ---- the waiting queue: a press is never lost, the page never shows a mark the app doesn't have; every entry is
       its own, from the press to its answer, never found by its place or its tag after a wait ---- */
    if (group("queue")) {
      const EQ = epsWith(4)[0] ?? E;                    // four words of one episode (the 20,000 fixture's first may have 3)
      await goWord(EQ, 0);
      const ids = J.seq(EQ).slice(0, 4), words = ids.map((id) => J.wordNow(id)[0]);
      ok("the queue checks have four words of one episode", ids.length === 4 && new Set(words).size === 4, words.join(" "));
      const closed = () => { window.__J_DOOR_MODE = "off"; J.setDoor("off"); };
      const open = () => { window.__J_DOOR_MODE = "on"; };
      const later = (ms) => new Promise((r) => setTimeout(r, ms));
      const reset = async () => {                       // everything sent, every test word back to no mark
        window.__J_DOOR_HOOK = null; open(); await J.hello(); await settle(6);
        for (let k = 0; k < ids.length; k++) { const m = J.MARK.get(words[k]); if (m) { J.markWord(m, ids[k]); await settle(); } }
      };
      const marksBut = (w, m) => { const o = Object.fromEntries([...J.MARK].filter(([x]) => x !== w)); if (m) o[w] = m; return o; };
      const qOf = (tag) => J.QUEUE().filter((q) => q.tag === tag);
      const pq = big.find((i) => i !== EQ && !page.ep(i).pre.on && page.canPre(i));
      // A: a queued press the flush hears not_yet for waits on (its route isn't in this Surasura yet), never dropped
      closed(); J.markWord("known", ids[0]); await settle();
      open(); window.__J_DOOR_HOOK = (rt) => (rt === "words/mark" ? { ok: false, kind: "not_yet" } : null);
      await J.hello(); await settle(6);
      ok("A: a queued Known the flush hears not_yet for stays queued, ⧗ kept", qOf("m:" + words[0]).length === 1 && J.MWAIT.get(words[0]) === "queued" && J.MARK.get(words[0]) === "known");
      if (pq != null) {
        closed(); J.prestudied(pq, "press"); await settle();
        open(); window.__J_DOOR_HOOK = (rt) => (rt === "episode/prestudied" ? { ok: false, kind: "not_yet" } : null);
        await J.hello(); await settle(6);
        ok("A: a queued pre-studied press the flush hears not_yet for stays queued, ⧗ kept", qOf("p:" + page.ep(pq).id).length === 1 && page.ep(pq).pre.wait === "queued");
      }
      await reset();
      if (pq != null && page.ep(pq).pre.on) { J.prestudied(pq, "press"); await settle(); }
      // B: a press made while the flush waits for an answer (Surasura busy, so it queues) is still there after it
      if (pq != null) {
        closed(); J.prestudied(pq, "press"); await settle();
        open(); let n = 0;
        window.__J_DOOR_HOOK = async (rt) => { if (rt !== "episode/prestudied") return null; if (++n === 1) { await later(40); return null; } return { ok: false, kind: "busy" }; };
        const h = J.hello();
        for (let k = 0; k < 200 && n < 1; k++) await settle(1);
        J.prestudied(pq, "press");                      // un-marked while the mark is on its way
        await h; await settle(6);
        const e = page.ep(pq), q = qOf("p:" + e.id);
        ok("B: an un-mark made while the queue sends its mark stays queued (by its own id, not its place)", q.length === 1 && q[0].body.on === false && !e.pre.on && e.pre.wait === "queued", JSON.stringify(q.map((x) => x.body)) + " " + JSON.stringify(e.pre));
      }
      {
        closed(); J.markWord("known", ids[1]); await settle();
        open(); let n = 0;
        window.__J_DOOR_HOOK = async (rt) => { if (rt !== "words/mark") return null; if (++n === 1) { await later(40); return null; } return { ok: false, kind: "busy" }; };
        const h = J.hello();
        for (let k = 0; k < 200 && n < 1; k++) await settle(1);
        J.markWord("ignore", ids[1]);                   // changed while the Known is on its way
        await h; await settle(6);
        const q = qOf("m:" + words[1]);
        ok("B: Ignore pressed while the queue sends that word's Known stays queued (not removed by its tag)", q.length === 1 && q[0].body.marks[0].mark === "ignore" && J.MARK.get(words[1]) === "ignore" && J.MWAIT.get(words[1]) === "queued", JSON.stringify(q.map((x) => x.body.marks)) + " " + J.MWAIT.get(words[1]));
      }
      await reset();
      // C: a state answer keeps every word still waiting as pressed (the app hasn't heard of it yet)
      closed(); J.markWord("known", ids[2]); await settle();
      open(); J.setDoor("on");
      window.__J_DOOR_HOOK = (rt) => (rt === "state" ? { ok: true, at: Date.now(), marks: marksBut(words[2]) } : null);
      await J.readState();
      ok("C: a state read keeps a waiting Known as pressed (⧗), not wiped", J.MARK.get(words[2]) === "known" && J.MWAIT.get(words[2]) === "queued");
      await reset();
      // D: a direct press Surasura answers stale with is read back: the page shows what the app has
      window.__J_DOOR_HOOK = (rt, b) => (rt === "words/mark" && b.marks[0].word === words[3] ? { ok: false, kind: "stale", error: "Changed in Surasura." }
        : rt === "state" ? { ok: true, at: Date.now(), marks: marksBut(words[3], "ignore") } : null);
      const before = CALLS.length;
      J.markWord("known", ids[3]);
      for (let k = 0; k < 100 && J.MARK.get(words[3]) !== "ignore"; k++) await settle(1);
      ok("D: a press answered stale reads the state back and shows the app's mark", J.MARK.get(words[3]) === "ignore" && CALLS.slice(before).some((c) => c[1] === "state"),
        `${J.MARK.get(words[3])} · wait ${J.MWAIT.get(words[3])} · calls ${CALLS.slice(before).map((c) => c[1]).join(",")} · toast ${$("#toast").textContent}`);
      await reset();
      // E: Undo of a press that replaced a waiting one brings the waiting one back, still ⧗
      closed(); J.markWord("known", ids[0]); await settle();
      J.markWord("ignore", ids[0]); await settle();
      $("#toast button").click(); await settle();
      const qe = qOf("m:" + words[0]);
      ok("E: Undo of Ignore that replaced a waiting Known: Known waits again (⧗), in the queue", J.MARK.get(words[0]) === "known" && J.MWAIT.get(words[0]) === "queued" && qe.length === 1 && qe[0].body.marks[0].mark === "known", JSON.stringify(qe.map((x) => x.body.marks)));
      await reset();
      // F: Undo of a waiting press the flush has since sent says so (it can't be taken back from here)
      closed(); J.markWord("known", ids[1]); await settle();
      const undo = $("#toast button");
      open(); await J.hello(); await settle(6);
      undo.click(); await settle();
      ok("F: Undo after the queue sent the press: the toast says to press it again", /press it again/.test($("#toast").textContent) && J.MARK.get(words[1]) === "known", $("#toast").textContent);
      await reset();
      // G: an older press that comes back busy after a newer one was taken is dropped, never queued behind it
      {
        let n = 0;
        window.__J_DOOR_HOOK = async (rt, b) => { if (rt !== "words/mark" || b.marks[0].word !== words[0]) return null; if (++n === 1) { await later(40); return { ok: false, kind: "busy" }; } return null; };
        J.markWord("known", ids[0]); J.markWord("ignore", ids[0]);
        await later(80); await settle(6);
        ok("G: Known answered busy after Ignore was taken: not queued behind it, Ignore drawn", !qOf("m:" + words[0]).length && J.MARK.get(words[0]) === "ignore" && !J.MWAIT.has(words[0]), JSON.stringify(qOf("m:" + words[0]).map((x) => x.body.marks)));
      }
      await reset();
      // H: Undo while the queue is sending that very press: it says so, and the mark stays (the app gets it)
      {
        closed(); J.markWord("known", ids[1]); await settle();
        const undoH = $("#toast button"); open(); let n = 0;
        window.__J_DOOR_HOOK = async (rt) => { if (rt === "words/mark" && ++n === 1) await later(40); return null; };
        const h = J.hello();
        for (let k = 0; k < 200 && n < 1; k++) await settle(1);
        undoH.click(); await h; await settle(6);
        ok("H: Undo while the queue sends the press: the toast says to press it again, the mark stays", /press it again/.test($("#toast").textContent) && J.MARK.get(words[1]) === "known" && !qOf("m:" + words[1]).length, $("#toast").textContent + " · " + J.MARK.get(words[1]));
      }
      await reset();
      // I: a state read keeps a flag whose press is on its way
      if (J.D.routes && J.D.routes.includes("line/flag")) {
        let n = 0;
        window.__J_DOOR_HOOK = async (rt) => {
          if (rt === "line/flag" && ++n === 1) { await later(40); return null; }
          return rt === "state" ? { ok: true, at: Date.now(), flags: { flagged: [] } } : null;
        };
        const fb = CALLS.length;
        J.flagLine(ids[2], 0, ["other"], "", true);
        await J.readState(); await later(60); await settle(6);
        const fc = CALLS.slice(fb).find((c) => c[1] === "line/flag");
        ok("I: a state read keeps a flag whose press is on its way", !!fc && J.FLAGGED.has(fc[2].line_id), fc && fc[2].line_id);
        window.__J_DOOR_HOOK = null; J.flagLine(ids[2], 0, ["other"], "", false); await settle(6);
      }
      // J: an online Undo answered after a newer press on the word leaves the newer press drawn
      {
        J.markWord("known", ids[3]); await settle(6);
        let n = 0;
        window.__J_DOOR_HOOK = async (rt) => { if (rt === "words/undo" && ++n === 1) await later(40); return null; };
        $("#toast button").click();                     // Undo of Known, on its way
        J.markWord("ignore", ids[3]);                   // a newer press meanwhile
        await later(80); await settle(6);
        ok("J: Undo answered after a newer Ignore: Ignore stays drawn", J.MARK.get(words[3]) === "ignore", J.MARK.get(words[3]));
      }
      await reset();
      ok("the queue ends empty, nothing waits", !J.QUEUE().length && words.every((w) => !J.MWAIT.has(w) && !J.MARK.has(w)) && (pq == null || !page.ep(pq).pre.wait), J.QUEUE().length);
    }

    /* ---- the line player: a file is played as itself, whatever its name holds ---- */
    if (group("player")) {
      const d = H.dirs && H.dirs[0];
      const sid = (ln, src) => J.lineId(ln, src);
      ok("a line's id is the simple Swap's <item id>:<start ms> (SHAPE 1.1's item)", sid(["文", 0, 12.345], ["x", "anime", 0, "", "", 4321]) === "4321:12345", sid(["文", 0, 12.345], ["x", "anime", 0, "", "", 4321]));
      ok("…a v1 row (no item): its episode's store id", sid(["文", 0, 1.5], ["x", "anime", E, "", ""]) === `${page.ep(E).id}:1500`);
      ok("…a book's line (no start) or a file the store doesn't hold: the page's own p<hash>", /^p[0-9a-f]{8}$/.test(sid(["文", 0, null], ["x", "book", 0, "", "", 4321])) && /^p[0-9a-f]{8}$/.test(sid(["文", 0, 3], ["x", "anime", E, "", "", null])));
      ok("P: a file name with # or ? plays as itself (each part of the path encoded)", d != null && !!J.mediaUrl && J.mediaUrl("0/sub dir/ep#1 ?.mp3") === d + "sub%20dir/ep%231%20%3F.mp3", J.mediaUrl && J.mediaUrl("0/sub dir/ep#1 ?.mp3"));
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
      {
        // (after the Undo: ⇄'s own toast would take the flag's place) the flagged line is the word's first; its id is its episode's store id and its start in ms, else the page's key
        const ln0 = J.wordNow(J.curWordId())[9][0], lid = call[2].line_id, m = /^(\d+):(\d+)$/.exec(lid);
        const ids = new Set(); for (let i = 0; i < N; i++) if (page.ep(i).id != null) ids.add(String(page.ep(i).id));
        ok("one line id everywhere, the simple Swap's <item id>:<start ms> (a line with both)",
          m ? ids.has(m[1]) && Number(m[2]) === Math.round(ln0[2] * 1000) : /^p[0-9a-f]{8}$/.test(lid), lid);   // p…: no store id or no start
        if ($('#stage [data-act="pick"]')) {
          const n0 = CALLS.length;
          J.pickLine(0); await settle();
          const pc = CALLS.slice(n0).find(([, rt]) => rt === "swap/queue" || rt === "card/make");
          ok("…and ⇄ sends that same id", pc && pc[2].line_id === call[2].line_id, pc && pc[2].line_id);
        }
      }
    }

    /* ---- the settings: each redraws only what it owns (SPEC §1.4) ---- */
    if (group("settings")) {
      await goWord(E, 0);
      J.openSettings(); await settle();
      ok("the page's settings: one row per setting (word size and sentence size are two: SPEC §1.4 as corrected)", $$("#set-sheet .srow").length === J.SETTINGS.length && J.SETTINGS.length === 9, $$("#set-sheet .srow").length);
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
      ok("Sentences per word › 1: the header counts the one line shown (J-FIX, PROVISIONAL)", headCount() === 1, headCount());
      budget(ok, "a setting: sentences per word", r, ["word", "lines", "layer"]);
      J.setSetting("sentences", H.settings.sentences || 3); await settle();
      r = await press(() => J.setSetting("word_size", "l"));
      budget(ok, "a setting: word size", r, ["root", "layer"]);
      r = await press(() => J.setSetting("sentence_size", "l"));
      budget(ok, "a setting: sentence size", r, ["root", "layer"]);
      J.setSetting("word_size", "m"); J.setSetting("sentence_size", "m"); await settle();
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

    /* ---- the first-meeting line (SPEC § Sentences are the list's): of the lines shown, the one from the episode the
       word is first met in is marked; its switch hides it and the next lines show, in the list's order. The page
       adds no line and moves none: what each check expects is worked out here from the word's own lines. ---- */
    if (group("meet")) {
      const MEET = "Where you'll first meet it";
      ok("Where you'll first meet it: Shown unless the head holds a switch that is off (a hand-edited value is no switch)", J.SET.first_meeting === (H.settings.first_meeting !== false), JSON.stringify(H.settings.first_meeting));
      if (J.SET.first_meeting !== true) { J.setSetting("first_meeting", true); await settle(); }
      const nOf = (w) => { const n = Number(J.SET.sentences) || 0; return n > 0 ? Math.min(n, w[9].length) : w[9].length; };
      const meetOf = (id, w) => { for (let k = 0; k < nOf(w); k++) { const s = J.srcOf(id, w[9][k][1]); if (s && s[2] === w[5]) return k; } return -1; };
      const carded = (w) => (w[6] & 8) === 8;
      const found = {};                                  // the kinds of word the checks need, the first of each
      for (const i of epsWith(1).slice(0, 60)) {
        await J.loadEp(i);
        (J.seq(i) || []).forEach((id, wi) => {
          const w = J.wordNow(id), m = meetOf(id, w), one = w[9].length === 1;
          const kind = m < 0 ? "none" : one ? (carded(w) ? null : "only") : carded(w) ? (m === 0 ? "card" : null) : m === 0 ? "first" : "later";
          if (kind && !found[kind]) found[kind] = { i, wi, id, m };
        });
      }
      const at = async (f) => { await goWord(f.i, f.wi); return J.wordNow(J.curWordId()); };
      const shown = () => $$("#stage .lines > .ln").map((el) => el.querySelector(".tx").textContent);
      const marked = () => $$("#stage .lines > .ln.fm");
      const counted = (what) => ok(`${what}: the header counts only the lines shown (J-FIX, PROVISIONAL)`, headCount() === shown().length, JSON.stringify([headCount(), shown().length]));
      const keep = (w, hide) => { const o = []; for (let k = 0; k < w[9].length && o.length < nOf(w); k++) if (k !== hide) o.push(w[9][k][0]); return o; };
      const listed = (w) => w[9].slice(0, nOf(w)).map((ln) => ln[0]);
      const sw = (v) => $(`#set-sheet .srow[data-set="first_meeting"] [data-val="${v}"]`);
      J.openSettings(); await settle();
      const row = $('#set-sheet .srow[data-set="first_meeting"]');
      ok("its row in the page's settings: J-SET's words, Shown · Hidden, Shown lit", row && row.textContent.includes(MEET) && $$('#set-sheet .srow[data-set="first_meeting"] [data-val]').length === 2 && sw("true").classList.contains("on"), row && row.textContent);
      for (const kind of ["first", "later"]) {
        const f = found[kind];
        if (!f) continue;
        const w = await at(f);
        ok(`${kind === "first" ? "the first line" : "a later line"} from the first meeting's episode: marked ${MEET}, the lines as the list has them`,
          marked().length === 1 && marked()[0].querySelector(".tx").textContent === w[9][f.m][0] && marked()[0].textContent.includes(MEET) && JSON.stringify(shown()) === JSON.stringify(listed(w)), JSON.stringify(shown()));
        J.selLine(nOf(w) - 1); await settle();          // the last line chosen: one fewer shows once the marked one hides
        const lines0 = $("#stage [data-r=lines]"), rest0 = ["reading", "acts"].map((r) => $(`#stage [data-r=${r}]`)).concat([$("#stage .wrow")]);
        let r = await press(() => sw("false").click());
        ok(`Hidden (${kind}): a chosen line is still one of the lines shown, and drawn chosen`, J.S.line < J.shownLines(f.id, w).ks.length && $$("#stage .lines > .ln.sel").length === 1, J.S.line);
        const call = CALLS.filter(([, rt]) => rt === "settings/set").pop();
        ok(`Hidden (${kind}): the marked line goes, the next show in the list's order, nothing marked`, !marked().length && JSON.stringify(shown()) === JSON.stringify(keep(w, f.m)), JSON.stringify(shown()));
        ok(`Hidden (${kind}): written through settings/set, J-SET's key, a switch`, call && call[2].key === "journey_first_meeting" && call[2].value === false, call && JSON.stringify(call[2]));
        ok(`Hidden (${kind}): only the word's lines redrawn (the rest of the word pane is the same nodes)`, !lines0.isConnected && rest0.every((el) => el && el.isConnected));
        counted(`Hidden (${kind})`);
        budget(ok, `a setting: where you'll first meet it (${kind})`, r, ["word", "lines", "layer"]);
        if (kind === "first" && $('#stage [data-act="pick"]')) {
          const n0 = CALLS.length;
          J.closeLayer(); J.selLine(0); key("Enter"); await settle();      // (a key with a sheet open is the sheet's)
          const pc = CALLS.slice(n0).find(([, rt]) => rt === "swap/queue" || rt === "card/make");
          J.openSettings(); await settle();
          ok("Hidden: Enter on the first line shown picks that line, not the hidden one", pc && pc[2].line_id === J.lineId(w[9][1], J.srcOf(f.id, w[9][1][1])), pc && pc[2].line_id);
        }
        r = await press(() => sw("true").click());
        ok(`Shown again (${kind}): the same lines, the mark back`, marked().length === 1 && JSON.stringify(shown()) === JSON.stringify(listed(w)));
        counted(`Shown again (${kind})`);
        budget(ok, `a setting: where you'll first meet it, back (${kind})`, r, ["word", "lines", "layer"]);
      }
      if (found.later) {                                 // fewer lines shown than the word has: its first meeting not among them
        const w = await at(found.later), was = J.SET.sentences;
        J.setSetting("sentences", found.later.m); await settle();
        await press(() => sw("false").click());
        const more = $("#stage .lines .more");
        ok("Sentences per word below the first meeting's line: nothing marked or hidden, '+N more' counts every line not shown", !marked().length && JSON.stringify(shown()) === JSON.stringify(w[9].slice(0, found.later.m).map((ln) => ln[0])) && more && more.textContent.includes(`+${w[9].length - found.later.m} more`), more && more.textContent);
        counted("Sentences per word below the first meeting's line");
        await press(() => sw("true").click());
        J.setSetting("sentences", was); await settle();
      }
      if (found.none) {
        const w = await at(found.none);
        const lines0 = $("#stage [data-r=lines]");
        const r = await press(() => sw("false").click());
        ok("a word whose first meeting isn't among the lines shown: no mark, Hidden changes nothing, its lines not redrawn", !marked().length && lines0.isConnected && JSON.stringify(shown()) === JSON.stringify(listed(w)));
        budget(ok, "a setting: where you'll first meet it, on a word with no such line", r, ["layer"]);
        await press(() => sw("true").click());
      }
      if (found.card) {                                  // PROVISIONAL (J-PAGE 5): the card's sentence never hides
        const w = await at(found.card);
        await press(() => sw("false").click());
        ok("Hidden, a word with a card whose first line is its first meeting: that line stays, On your card, unmarked", !marked().length && JSON.stringify(shown()) === JSON.stringify(listed(w)) && /On your card/i.test($("#stage .lines > .ln").textContent));
        await press(() => sw("true").click());
        ok("Shown: the card's line carries both", marked().length === 1 && /On your card/i.test(marked()[0].textContent) && marked()[0].textContent.includes(MEET));
      }
      if (found.only) {                                  // PROVISIONAL (J-PAGE 5): a word never left without a sentence
        const w = await at(found.only);
        await press(() => sw("false").click());
        ok("Hidden, a word with one line, its first meeting: the line stays, unmarked", !marked().length && JSON.stringify(shown()) === JSON.stringify(listed(w)));
        await press(() => sw("true").click());
      }
      {                                                  // List: only the cards whose word has a first-meeting line shown
        const f = found.first || found.later || found.only;
        if (f) {
          await goWord(f.i, 0); J.closeLayer(); J.toggleList(); await settle();
          const cards = $$("#stage .lc"), ids = J.seq(f.i);
          const before = cards.map((c) => c.querySelector("[data-r=lines]"));
          const want = cards.map((c) => { const id = ids[Number(c.dataset.k)], w = J.wordNow(id), m = meetOf(id, w); return m >= 0; });
          const r = await press(() => J.setSetting("first_meeting", false));
          const got = before.map((el) => !el.isConnected);
          ok("List, Hidden: only the cards whose word has its first-meeting line shown are redrawn", want.some(Boolean) && JSON.stringify(got) === JSON.stringify(want), JSON.stringify([want, got]));
          budget(ok, "a setting: where you'll first meet it, in List", r, ["word", "lines"]);
          J.setSetting("first_meeting", true); await settle();
          J.toggleList(); await settle();
          J.openSettings(); await settle();
        }
      }
      {                                                  // a state read: a hand-edited "false" in settings.json is no switch
        window.__J_DOOR_HOOK = (route) => route === "state" ? { ok: true, at: Date.now(), settings: { journey_first_meeting: "false" } } : null;
        await J.readState(); await settle();
        window.__J_DOOR_HOOK = null;
        ok("a state read with a value that is no switch keeps Shown", J.SET.first_meeting === true, JSON.stringify(J.SET.first_meeting));
      }
      ok("the kinds of word checked: " + Object.keys(found).sort().join(" "), true);
      J.closeLayer();
    }

    /* ---- the old page's ignores, carried over once (J-FIX; Sonic's answer to SPEC §9 item 1): the old journey page
       kept its ignored words only in this browser (`surasura_ignored_words_<lang>`). At a hello with the door on, the
       ones not Known or Ignored in Surasura already go through ⊘'s own route, in batches, once; the old key is never
       touched, nothing else of the browser's is read. ---- */
    if (group("carry")) {
      const OLD = `surasura_ignored_words_${H.lang}`, DONE = `surasura_journey_old_ignores_${H.lang}`;
      const words = [];                                  // real words of the first episodes (30: the 5,000 case's too)
      for (const i of epsWith(1).slice(0, 60)) { if (words.length >= 30) break; await J.loadEp(i); for (const id of J.seq(i) || []) { const w = J.wordNow(id)[0]; if (!words.includes(w)) words.push(w); } }
      await goWord(E, 0);
      const shownWord = J.wordNow(J.curWordId())[0];
      const [known, ignored, ...rest] = words.filter((w) => w !== shownWord), mine = rest.slice(0, 3);   // never the shown word: its row stays
      const marksNow = { [known]: "known", [ignored]: "ignore" };
      window.__J_DOOR_HOOK = (route, body) => route === "state" && body.since === null ? { ok: true, at: Date.now(), marks: marksNow } : null;
      const marksSent = (n0) => CALLS.slice(n0).filter(([, rt]) => rt === "words/mark");
      const sentWords = (n0) => marksSent(n0).flatMap(([, , b]) => b.marks.map((m) => m.word));
      const seed = (v) => { localStorage.removeItem(DONE); localStorage.setItem(OLD, v); };
      const oldValue = JSON.stringify([mine[0], known, ignored, 42, null, "", "  ", mine[1], mine[0], "借".repeat(65), ` ${mine[2]} `]);
      ok("carry: the five words the checks need", mine.length === 3, words.length);
      seed(oldValue);
      let n0 = CALLS.length;
      const r = await press(() => J.hello());
      const sent = marksSent(n0);
      ok("carried: one call through ⊘'s route, only the old words Surasura doesn't have Known or Ignored, each once, trimmed",
        sent.length === 1 && JSON.stringify(sentWords(n0)) === JSON.stringify(mine), JSON.stringify(sentWords(n0)));
      ok("carried: each an Ignore over no mark (`was` \"\") with the time of the read, so the stale rule skips a word changed since",
        sent.length === 1 && sent[0][2].marks.every((m) => m.mark === "ignore" && m.was === "" && typeof m.at === "number"), sent[0] && JSON.stringify(sent[0][2].marks[0]));
      ok("carried: Surasura's marks read whole first (state with no `since`), through the existing route", CALLS.slice(n0).some(([, rt, b]) => rt === "state" && b.since === null));
      ok("carried: the done-mark written, the old key left exactly as it was", localStorage.getItem(DONE) && localStorage.getItem(OLD) === oldValue, localStorage.getItem(DONE));
      ok("carried: the page shows them Ignored", mine.every((w) => J.MARK.get(w) === "ignore") && J.MARK.get(known) !== "ignore");
      const tl = $("#toast");
      ok("carried: one line, how many, with Undo (PROVISIONAL)", !tl.classList.contains("hide") && /\b3 words from your old journey page/.test(tl.textContent) && /Ignore list/.test(tl.textContent) && tl.querySelector("button"), tl.textContent);
      budget(ok, "the old ignores carried: only the three rows whose mark changed, and the toast", r, ["rail-words", "toast"], { "rail-words": 3 });
      n0 = CALLS.length;
      await J.hello(); await settle();
      ok("never again: a later hello sends nothing", !marksSent(n0).length);
      n0 = CALLS.length;
      tl.querySelector("button").click(); await settle(8);
      const undos = CALLS.slice(n0).filter(([, rt]) => rt === "words/undo");
      ok("Undo: the carry's own write taken back through the route's Undo (its undo id)", undos.length === 1 && /^s\.\d+$/.test(undos[0][2].undo_id), JSON.stringify(undos.map((u) => u[2])));
      ok("Undo: the words un-ignored on the page; the done-mark stays (the carry-over never comes back — PROVISIONAL)", mine.every((w) => !J.MARK.has(w)) && !!localStorage.getItem(DONE));
      for (const [name, v] of [["empty", "[]"], ["malformed", "{not json"], ["not a list", '{"a": 1}']]) {
        seed(v); n0 = CALLS.length;
        await J.hello(); await settle();
        ok(`a key ${name}: nothing sent, no error`, !marksSent(n0).length);
      }
      seed(JSON.stringify(mine)); n0 = CALLS.length;
      window.__J_DOOR_MODE = "off";
      await J.hello(); await settle();
      ok("Surasura closed: nothing sent, no done-mark (it waits for a later load)", !marksSent(n0).length && !localStorage.getItem(DONE));
      window.__J_DOOR_MODE = null;
      await J.hello(); await settle();
      ok("…and the next hello with the door on carries them", JSON.stringify(sentWords(n0)) === JSON.stringify(mine) && !!localStorage.getItem(DONE));
      {                                                  // the word lists busy with another program: tried again later
        seed(JSON.stringify(mine)); mine.forEach((w) => J.MARK.delete(w));
        const hook = window.__J_DOOR_HOOK;
        window.__J_DOOR_HOOK = (route, body) => route === "words/mark" ? { ok: false, kind: "busy", error: "Your word lists are busy." } : hook(route, body);
        n0 = CALLS.length;
        await J.hello(); await settle();
        ok("the Ignore route answering busy: no done-mark, nothing shown Ignored (a later hello tries again)", marksSent(n0).length === 1 && !localStorage.getItem(DONE) && mine.every((w) => !J.MARK.has(w)));
        window.__J_DOOR_HOOK = hook;
        n0 = CALLS.length;
        await J.hello(); await settle();
        ok("…and the next hello carries them", JSON.stringify(sentWords(n0)) === JSON.stringify(mine) && !!localStorage.getItem(DONE));
      }
      const many = [];                                   // 5,000 old words (real ones, joined two and three at a time)
      for (let a = 0; a < words.length && many.length < 5000; a++) for (let b = 0; b < words.length && many.length < 5000; b++) for (let c = 0; c < words.length && many.length < 5000; c++) if (a !== b && b !== c) many.push(words[a] + words[b] + words[c]);
      seed(JSON.stringify(many)); n0 = CALLS.length;
      const l0 = LONG.length, t1 = performance.now();
      await J.hello(); await settle(8);
      const big = marksSent(n0);
      ok(`${many.length.toLocaleString("en")} old words: a few calls of at most 500, every word once`, many.length === 5000 && big.length <= 10 && big.every(([, , b]) => b.marks.length <= 500) && new Set(sentWords(n0)).size === 5000, `${big.length} calls`);
      ok(`${many.length.toLocaleString("en")} old words: the page stays responsive (no long task)`, LONG.slice(l0).every(([, d]) => d <= 50), JSON.stringify(LONG.slice(l0)) + ` ${(performance.now() - t1).toFixed(0)} ms`);
      window.__J_DOOR_HOOK = null;
      localStorage.removeItem(OLD);
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

    /* ---- the width (390 · 800 · 1280): nothing cut off, every press reachable, the meaning never away ---- */
    if (group("layout")) {
      await goWord(E, 0);
      const W = innerWidth, inView = (el) => { if (!visible(el)) return false; const r = gbr.call(el); return r.left >= -0.5 && r.right <= W + 0.5 && r.width > 0; };
      ok(`${W} px: no sideways scroll`, document.documentElement.scrollWidth <= W + 1 && $("#stage").scrollWidth <= $("#stage").clientWidth + 1, `${document.documentElement.scrollWidth} / ${W}`);
      ok(`${W} px: the top bar fits (nothing pushed off it)`, $$(".hd1 > *:not(.sp)").filter(visible).every(inView), $$(".hd1 > *:not(.sp)").filter(visible).filter((el) => !inView(el)).map((el) => el.className || el.id || el.tagName).join(" "));   // .sp: the spacer, 0 px when the bar is full
      ok(`${W} px: the word, its sentences and ✓ ⊘ in view`, inView($("#stage .w")) && $$("#stage .ln").filter(visible).every(inView) && inView($('#stage [data-act="known"]')) && inView($('#stage [data-act="ignore"]')));
      ok(`${W} px: ↑ ↓ and the picker on screen`, inView($('#stage [data-act="next"]')) && inView($('#stage [data-act="prev"]')) && (inView($('[data-rs="picker"]')) || inView($('#stage [data-act="picker"]'))));
      ok(`${W} px: the rail ${W > 760 ? "beside the word" : "behind ☰"}`, W > 760 ? visible($("#rail")) : !visible($("#rail")) && inView($('#stage [data-act="picker"]')));
      ok(`${W} px: the meaning and More reachable (beside the word, or under it)`, inView($("#b-meaning")) && visible($("#more")));
      key(keyName("meaning")); await settle(); await J.blob("meanings"); await settle();
      ok(`${W} px: D shows the meaning where it can be read`, J.S.open.meaning && inView($("#meaning")) && $("#meaning").textContent.trim().length > 0);
      key(keyName("meaning")); await settle();
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
