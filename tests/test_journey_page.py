"""The journey v3 page (templates/journey/): the template's own rules, read from its source, and its self-checks run in
headless Edge on the fixture (SHAPE v1 from Test Resources, ja + zh) — the speed rows of SPEC §5.4, the redraw budgets
of its Redraw rule, the door's three cases (SPEC §3.5), a route not yet built, the rail contract (SPEC §1.1b) and an
empty library. The page is inert until J-CUT: nothing in the app loads it yet.

The Edge runs skip where Edge isn't installed. On GitHub a timing row that misses is a warning, not a failure: the
speed rows are measured on Sonic's desktop (`with-lock.sh timed`), and a shared runner's clock isn't that desk; every
other check fails the test there too.
"""
import os
import re
import sys
import tempfile
import warnings

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import journey_page_fixture as fx  # noqa: E402
from journey_page_edge import find_edge  # noqa: E402

TEMPLATES = os.path.join(os.path.dirname(HERE), "templates", "journey")
PAGE = os.path.join(TEMPLATES, "page.html")
RAIL_JS = os.path.join(TEMPLATES, "rail-stepper.js")
RAIL_CSS = os.path.join(TEMPLATES, "rail-stepper.css")
TINY_RAIL = os.path.join(HERE, "journey_page_rail_tiny.js")

# SPEC §3.3: the frozen route names; the page sends each by this name and no other
ROUTES = ("hello", "state", "words/mark", "words/undo", "episode/prestudied", "episode/undo", "line/flag",
          "settings/set", "swap/queue", "card/make", "clip/cut", "word/audio")

# the one learning-side item the page may keep in the browser: its waiting queue (SPEC §3.2, §3.5), one per library
# and language. The view (where you are, List, Focus, what is open) is the page's own and no learning fact.
QUEUE_KEY = "surasura_door_queue_${LIB}"
VIEW_KEY = "surasura_journey_view_${LIB}"
VIEW_FIELDS = {"id", "name", "wi", "list", "focus", "filter", "order", "open"}

TIMING = re.compile(r"≤ [\d.,]+ ?(ms|s|MB)\b|long task|JS heap")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _sources():
    return {p: _read(p) for p in (PAGE, RAIL_JS, RAIL_CSS)}


# ---- the template, read from its source ----

def test_page_template_has_each_mark_once_and_the_rail_goes_in_the_head():
    # the render makes its two replacements; a second mark would put the data or a rail in twice
    page = _read(PAGE)
    assert page.count(fx.DATA_MARK) == 1 and page.count(fx.RAIL_MARK) == 1
    assert page.index(fx.RAIL_MARK) < page.index("</head>") < page.index(fx.DATA_MARK)


def test_every_route_of_spec_3_3_is_sent_by_its_frozen_name():
    page = _read(PAGE)
    for route in ROUTES:
        assert f'"{route}"' in page, route
    # nothing is sent under a name outside the table (a renamed route would answer 404 from the door)
    sent = set(re.findall(r'(?:doorCall|write)\("([a-z/]+)"', page))
    assert sent and sent <= set(ROUTES), sent - set(ROUTES)


def test_no_network_but_the_door_on_127_0_0_1():
    for path, src in _sources().items():
        for url in re.findall(r"https?://[^\s\"'`<>)]+", src):
            # the door, and Nadeshiko's search: a link the browser opens on a click (CLAUDE.md §1), never fetched
            assert url.startswith("http://127.0.0.1:") or url.startswith("https://nadeshiko.co/"), (path, url)
        for call in ("XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "import(", "@import", "<link", "<iframe"):
            assert call not in src, (path, call)
    page = _read(PAGE)
    assert len(re.findall(r"\bfetch\(", page)) == 1 and "fetch(`http://127.0.0.1:${DOOR.port}/v1/${route}`" in page
    nadeshiko = [ln for ln in page.splitlines() if "nadeshiko.co" in ln]
    assert nadeshiko and all('<a class="ib" href="https://nadeshiko.co/' in ln for ln in nadeshiko)
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page).group(1)
    rules = dict((r.split(" ", 1) + [""])[:2] for r in (x.strip() for x in csp.split(";")) if r)
    assert rules["default-src"] == "'none'" and rules["connect-src"] == "http://127.0.0.1:*"
    assert all("http" not in v or "127.0.0.1" in v for v in rules.values()), rules


def test_local_storage_holds_only_the_waiting_queue_and_the_view():
    page = _read(PAGE)
    keys = re.findall(r"localStorage\.setItem\((\w+),", page)
    assert set(keys) == {"QKEY", "VIEW_KEY", "OLD_DONE"}, keys       # OLD_DONE: the carry-over's done-mark (below)
    assert f"const QKEY = `{QUEUE_KEY}`;" in page and f"const VIEW_KEY = `{VIEW_KEY}`;" in page
    view = re.search(r"localStorage\.setItem\(VIEW_KEY, JSON\.stringify\(\{(.*?)\}\)\)", page).group(1)
    fields = set(re.findall(r"(\w+):", view))
    assert fields <= VIEW_FIELDS, fields - VIEW_FIELDS          # no mark, stone, flag or setting in the view
    for path in (RAIL_JS, RAIL_CSS):
        assert "localStorage" not in _read(path) and "sessionStorage" not in _read(path), path   # a rail keeps nothing


def test_the_old_pages_ignores_are_the_one_thing_read_from_the_browser_and_go_through_the_ignore_route():
    # J-FIX (Sonic's answer to SPEC §9 item 1): nothing of the old journey page's is read from the browser but its
    # ignored words, once, sent through the ⊘ press's own route (no second writer); the old ✓ Completed marks are
    # dropped on purpose, and nothing of the learner's is deleted (the old key is read, never written or removed)
    page = _read(PAGE)
    assert "const OLD_IGNORES = `surasura_ignored_words_${LANG}`;" in page      # the old page's key, per language
    assert set(re.findall(r"localStorage\.getItem\((\w+)", page)) == {"QKEY", "VIEW_KEY", "OLD_IGNORES", "OLD_DONE"}
    assert set(re.findall(r"localStorage\.removeItem\((\w+)", page)) == {"QKEY"}
    assert "surasura_completed" not in page                                     # the old ✓ Completed marks: dropped
    carry = re.search(r"async function carryOldIgnores\(\) \{(.*?)\n\}", page, re.S).group(1)
    assert 'doorCall("words/mark"' in carry and 'mark: "ignore"' in carry
    from app.services import word_marks
    assert int(re.search(r"const OLD_BATCH = (\d+);", page).group(1)) <= word_marks.DOOR_MOST   # what one call takes


def test_the_stepper_rail_never_reads_a_chunk_or_calls_the_door():
    # SPEC §1.1b: a rail draws itself and calls page.go / page.prestudied; the page reads chunks and calls the door
    rail = _read(RAIL_JS)
    for word in ("doorCall", "fetch", "j-c", "gunzip", "DecompressionStream", "MARK", "QUEUE"):
        assert word not in rail, word


def test_the_page_colours_a_percent_by_the_windows_own_bands():
    # one owner for the % bands (app/services/view_rows.py): the page repeats its numbers, so a change there shows here
    from app.services import view_rows
    m = re.search(r"const LEARNED_AT = (\d+), HEADS_UP_BELOW = (\d+);", _read(PAGE))
    assert m and (int(m.group(1)), int(m.group(2))) == (view_rows.LEARNED_AT, view_rows.HEADS_UP_BELOW)


def test_the_page_writes_only_the_settings_keys_of_spec_1_4():
    # the app's own keys (J-SET-TABLE § 2, the same names as the data): the page never invents one
    keys = set(re.findall(r'\{ k: "\w+", key: "([\w.]+)"', _read(PAGE)))
    assert keys == {"logic.context.max_contexts", "journey_pitch", "journey_meanings", "source_display", "journey_word_size",
                    "journey_sentence_size", "theme", "journey_keys", "journey_first_meeting"}, keys


def test_the_keys_sheet_says_shift_is_left_free_for_yomitan_in_plain_words():
    # (a tester on 3.0.20) "Shift is never taken: it is Yomitan's." read like stray text in the keys sheet: it says
    # plainly that the page leaves Shift free for Yomitan (the selftest still checks no key is bound to Shift)
    page = _read(PAGE)
    assert "Shift is left free for Yomitan" in page
    assert "Shift is never taken" not in page


def test_the_render_inlines_only_the_chosen_rail():
    parts = fx.build("ja", 12)
    tiny = fx.assemble(parts, rail_css=".tiny{}", rail_js=_read(TINY_RAIL))
    assert 'name: "tiny"' in tiny and 'name: "stepper"' not in tiny and "rs-words" not in tiny
    stepper = fx.assemble(parts)
    assert 'name: "stepper"' in stepper and 'name: "tiny"' not in stepper


def test_the_open_guard_lets_only_a_headless_browser_on_its_own_profile_through():
    # the Edge runs below start msedge headless on a throwaway profile: no window opens, so the guard lets that one
    # through; a browser with a window, or headless on the desktop's own profile, is still refused
    guard = sys.modules["open_guard"]
    edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
    own = os.path.join(tempfile.gettempdir(), "j-page-edge-1")
    assert not guard.viewer([edge, "--headless=new", "--user-data-dir=" + own, "about:blank"])
    assert not guard.viewer(["chrome", "--headless", "--user-data-dir=" + own])
    assert guard.viewer([edge, "--headless=new", "--user-data-dir=", "file:///C:/journey.html"])        # no folder
    profile = os.path.join(os.environ.get("USERPROFILE") or "C:\\Users\\x", "Edge Profile")
    assert guard.viewer([edge, "--headless=new", "--user-data-dir=" + profile, "file:///C:/journey.html"])   # not a temp one
    assert guard.viewer([edge, "file:///C:/journey.html"])
    assert guard.viewer([edge, "--headless=new", "file:///C:/journey.html"])
    assert guard.viewer([edge, "--user-data-dir=H:\\tmp\\p", "file:///C:/journey.html"])
    assert guard.viewer(f'"{edge}" --app=file:///C:/journey.html')
    assert guard.viewer(["firefox", "--headless", "--user-data-dir=/tmp/p"])


# ---- the self-checks in headless Edge ----

needs_edge = pytest.mark.skipif(not find_edge(), reason="Edge isn't installed")

CASES = [
    ("ja", 2000, "", None),
    ("zh", 2000, "", None),
    ("ja", 20000, "", None),
    ("zh", 20000, "", None),
    ("ja", 2000, "door=none", None),                 # the page opened by hand
    ("zh", 2000, "door=off", None),                  # Surasura closed since
    ("ja", 2000, "notyet=line/flag,episode/prestudied,swap/queue,card/make", None),
    ("zh", 2000, "rail=contract", "tiny"),           # a second rail through the page API, page.html unchanged
]


@needs_edge
@pytest.mark.parametrize("lang,n,query,rail", CASES, ids=[f"{c[0]}-{c[1]}-{c[2] or 'door-on'}" for c in CASES])
def test_page_self_checks_in_headless_edge(tmp_path, lang, n, query, rail):
    import journey_page_run as runner
    kw = {"rail_css": ".tiny{display:flex;gap:6px;padding:8px}", "rail_js": _read(TINY_RAIL)} if rail else {}
    path = runner.page_file(str(tmp_path), lang, n, **kw)
    res, errs = runner.run(path, query)
    assert res, f"the self-checks gave no result: {errs}"
    assert not errs, errs
    fails = [(name, detail) for name, good, detail in res["out"] if not good]
    timing = [f for f in fails if TIMING.search(f[0])]
    other = [f for f in fails if f not in timing]
    assert not other, other
    if timing and os.environ.get("GITHUB_ACTIONS") == "true":
        warnings.warn(f"timing rows missed on a shared runner ({lang} {n} {query}): {timing}")
    else:
        assert not timing, timing
    assert res["total"] >= (25 if rail else 70)        # the groups ran (a crash ends them early, and says so)


@needs_edge
@pytest.mark.parametrize("lang,width", [("ja", 390), ("zh", 390), ("ja", 800), ("zh", 800)])
def test_page_at_a_phone_and_a_half_screen_width(tmp_path, lang, width):
    # 1280 is the runs above; here nothing is cut off, every press is reachable and 32 px, the meaning never away
    import journey_page_run as runner
    path = runner.page_file(str(tmp_path), lang, 2000)
    res, errs = runner.run(path, "only=layout,a11y", width=width)
    assert res and not errs, errs
    fails = [(name, detail) for name, good, detail in res["out"] if not good]
    assert not fails, fails
    assert any(name.startswith(f"{width} px") for name, _, _ in res["out"])


# JOURNEY-NAMES: the screens the card names, as CSS px at each Windows scale (width / scale, height / scale), and a phone
SIZES = [(round(w / s), round(h / s), s) for w, h in ((1366, 768), (1920, 1080), (2560, 1440)) for s in (1.0, 1.25, 1.5)]
SIZES.append((390, 844, 3.0))
# the episodes measured: the first show's (its part the whole long name) and the second's (a long show, a short part)
NAMED_EPS = """(() => { const p = window.__J.page, out = [];
  for (const show of [0, 1]) for (let i = 0; i < p.count(); i++) { const e = p.ep(i); if (e.show === show && !e.watched && e.new > 0) { out.push(i); break; } }
  return out; })()"""


def _press_tab(e):
    for kind in ("keyDown", "keyUp"):
        e.call("Input.dispatchKeyEvent", type=kind, key="Tab", code="Tab", windowsVirtualKeyCode=9, nativeVirtualKeyCode=9)


@needs_edge
@pytest.mark.parametrize("lang,names", [("ja", "ja"), ("zh", "zh"), ("ja", "en")])
def test_a_long_name_cuts_in_its_own_box_at_every_width_and_scale(tmp_path, lang, names):
    # A long show or episode name ran on under the rail's › button and into the word pane (a tester's screenshot,
    # 3.0.18). Each header row that shows a name is measured at 1366, 1920 and 2560 at 100-150 % and a phone: the
    # name cuts with … inside its own box, nothing of the row is outside the row or its pane, the title ends before the
    # next button, and the full name is on hover and on keyboard focus (journey_page_names.js says what it measures)
    from journey_page_edge import Edge
    path = os.path.join(str(tmp_path), f"names-{lang}-{names}.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fx.assemble(fx.build(lang, 40, long_names=names), extra_js=_read(os.path.join(HERE, "journey_page_names.js"))))
    misses = []
    with Edge() as e:
        assert e.open("file:///" + path.replace("\\", "/"), seconds=30), e.errors()
        eps = e.evaluate(NAMED_EPS)
        assert len(eps) == 2, eps
        titles = [e.evaluate(f"window.__J.page.ep({i}).title") for i in eps]
        assert all(len(t) > 30 for t in titles), titles    # the fixture's long names reached the page
        for width, height, scale in SIZES:
            e.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=False)
            for i in eps:
                misses += [f"{width}x{height} @{int(scale * 100)} %, episode {i}: {m}" for m in e.evaluate(f"window.__names({i})")]
        # keyboard focus: Tab (a real key, through DevTools) onto the rail's title shows the tip with the full name, and
        # the next Tab takes it away with the focus
        e.call("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
        for i, title in zip(eps, titles):
            e.evaluate(f"(async () => {{ const J = window.__J; J.go({i}, 0); await J.loadEp({i}); J.drawWord(); document.getElementById('b-set').focus(); return 1; }})()")
            on = False
            for _ in range(4):
                _press_tab(e)
                if e.evaluate("document.activeElement.classList.contains('rs-title')"):
                    on = True
                    break
            assert on, e.evaluate("document.activeElement.outerHTML.slice(0, 120)")
            tip = e.evaluate("window.__tipNow()")
            if title not in tip:
                misses.append(f"episode {i}: Tab onto the rail's title shows no tip with the full name ({tip!r})")
            _press_tab(e)
            if e.evaluate("window.__tipNow()") == tip:
                misses.append(f"episode {i}: the title's tip stays after the focus leaves it")
        errs = e.errors()
    assert not errs, errs
    assert not misses, "\n".join(misses[:40]) + f"\n({len(misses)} in all)"


PITCH_EPS = 6         # the fixture's first episodes: every word with a pitch on them (yōon, っ, long readings)
PITCH_SIZES = [(1366, 768, 1.0), (1280, 720, 1.5), (390, 844, 3.0)]
PITCH_HIDDEN_THEN_F = """(() => { const J = window.__J; J.setSetting('pitch', 'hidden');
  const k = document.querySelector('[data-r="reading"] .mo'), r = document.createRange();
  let top = null; if (k) { r.selectNodeContents(k); top = r.getBoundingClientRect().top; }
  const hidden = !document.querySelector('[data-r="reading"] svg.pitch');
  J.doAction('pitch'); const m = window.__pitch(); J.setSetting('pitch', 'shown'); return [top, hidden, m]; })()"""


@needs_edge
def test_the_pitch_graph_sits_on_its_kana_with_room_under_the_word_at_every_size(tmp_path):
    # (a tester on 3.0.20) the pitch graph ran into the big word above it and drifted off its kana: it stepped a fixed
    # 19 px a mora while the reading's font set each kana at 12-17 px (a ゃゅょ pair at ~25), so by いっしょうけんめい's
    # last mora a point stood 24 px right of its kana, and the graph's top sat 4 px inside the word's box. Measured in
    # headless Edge (journey_page_pitch.js), as positions: every point stands over its own kana (the text's box in its slot), the graph clears
    # the word and sits on its reading, and the reading stays where it is when F shows a hidden graph (no jump) — at
    # three screens, each word size, pitch shown and hidden-then-F
    from journey_page_edge import Edge
    path = os.path.join(str(tmp_path), "pitch-ja.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fx.assemble(fx.build("ja", 40), extra_js=_read(os.path.join(HERE, "journey_page_pitch.js"))))
    misses, seen, yoon = [], 0, 0
    with Edge() as e:
        assert e.open("file:///" + path.replace("\\", "/"), seconds=60), e.errors()
        for width, height, scale in PITCH_SIZES:
            e.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=False)
            for size in ("s", "m", "l"):
                for ep in range(PITCH_EPS):
                    e.evaluate(f"(async () => {{ const J = window.__J; J.setSetting('word_size', '{size}'); "
                               f"J.setSetting('pitch', 'shown'); J.go({ep}, 0); await J.loadEp({ep}); return 1; }})()")
                    for wi in range(e.evaluate(f"(window.__J.seq({ep}) || []).length")):
                        has, m = e.evaluate(f"(() => {{ const J = window.__J; J.go({ep}, {wi}); J.drawWord(); "
                                            f"const w = J.wordNow(J.curWordId()); "
                                            f"return [w[8] != null && !!(w[3] || w[2]), window.__pitch()]; }})()")
                        if not m:
                            if has:                                   # a pitch and a reading: its graph
                                misses.append(f"{width}x{height} @{int(scale * 100)} %, size {size}, episode {ep} "
                                              f"word {wi}: no graph")
                            continue
                        where = f"{width}x{height} @{int(scale * 100)} %, size {size}, {m['text']}"
                        seen += 1
                        yoon += any(len(mo["ch"]) > 1 for mo in m["morae"])
                        assert len(m["pts"]) == len(m["morae"]), where
                        for (x, _y), mo in zip(m["pts"], m["morae"]):
                            ink = (mo["inkL"] + mo["inkR"]) / 2
                            if not mo["inkL"] <= x <= mo["inkR"] or abs(x - ink) > 3:
                                misses.append(f"{where}: the point over {mo['ch']} at {x:.1f}, "
                                              f"its kana {mo['inkL']:.1f}-{mo['inkR']:.1f}")
                        room = m["svg"]["top"] - m["word"]["bottom"]
                        if room < 4:
                            misses.append(f"{where}: the graph's top {room:.1f} px under the word")
                        sit = m["morae"][0]["top"] - m["svg"]["bottom"]
                        if not -2 <= sit <= 6:
                            misses.append(f"{where}: the graph {sit:.1f} px over its reading")
                        top, hidden, again = e.evaluate(PITCH_HIDDEN_THEN_F)
                        if not hidden or top is None or abs(top - m["morae"][0]["top"]) > 0.5 or not again or again["pts"] != m["pts"]:
                            misses.append(f"{where}: hidden then F moves the reading or its graph "
                                          f"({top} vs {m['morae'][0]['top']})")
        errs = e.errors()
    assert not errs, errs
    assert seen >= 30 and yoon, (seen, yoon)              # the fixture's pitch words reached the page, ゃゅょ ones too
    assert not misses, "\n".join(misses[:40]) + f"\n({len(misses)} in all)"


CHIP_SIZES = [(1366, 768, 1.0), (1024, 640, 1.5), (683, 384, 2.0)]   # wide, between the breakpoints, narrow (1366 at 200 %)
CHIP_MEASURE = """(() => {
  const out = [];
  for (const chip of document.querySelectorAll('#stage .prechip')) {
    const c = chip.getBoundingClientRect(), card = chip.closest('.end').getBoundingClientRect();
    const svg = chip.querySelector('svg').getBoundingClientRect();
    const t = [...chip.childNodes].find((n) => n.nodeType === 3), r = document.createRange();
    r.selectNodeContents(t);
    const lines = new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size, tb = r.getBoundingClientRect();
    out.push({ text: t.textContent, cls: chip.className, lines, chip: [c.left, c.top, c.right, c.bottom],
               card: [card.left, card.right], svg: [svg.left, svg.top, svg.right, svg.bottom],
               txt: [tb.left, tb.top, tb.right, tb.bottom], over: chip.scrollWidth - chip.clientWidth });
  }
  return out; })()"""


@needs_edge
def test_the_end_cards_pre_studied_chip_fits_its_words_on_one_line_at_every_width_and_state(tmp_path):
    # (a tester on 3.0.21) the end card's chip read "Pre- / studied · / un-mark" on three lines, spilling out of its
    # pill: its stone's SVG had no size inside the chip (only `.st svg` is 20 px), so it grew and the words were
    # squeezed into what was left. Measured in headless Edge, as positions: the chip's words on one line, inside the
    # pill, right of a 20 px stone; nothing overflows the pill and the pill stays inside its card — at three widths,
    # the word view's end card and the list's, every stone (rock, mined, nothing new, cut) × on / off × the ⧗ and the
    # spinner of a waiting press
    from journey_page_edge import Edge
    path = os.path.join(str(tmp_path), "chip-ja.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fx.assemble(fx.build("ja", 40)))
    misses, seen, texts = [], 0, set()
    with Edge() as e:
        assert e.open("file:///" + path.replace("\\", "/"), seconds=60), e.errors()
        # one episode of each stone the fixture has: rock (no cards), raw (mined), nothing (nothing new), cut (finished)
        eps = e.evaluate("""(() => { const J = window.__J, EPS = J.page.head.eps, got = {};
          for (let i = 0; i < EPS.length; i++) if (EPS[i][0] != null && !(EPS[i][9] in got)) got[EPS[i][9]] = i;
          return got; })()""")
        assert {"rock", "raw", "nothing", "cut"} <= set(eps), eps
        for width, height, scale in CHIP_SIZES:
            e.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=False)
            for stone, ep in sorted(eps.items()):
                for on in ((True,) if stone == "cut" else (True, False)):   # a finished one shows its chip only on
                    for wait in ("", "wait", "queued"):
                        for view in ("word", "list"):
                            m = e.evaluate(f"""(async () => {{ const J = window.__J; await J.loadEp({ep});
                              if (J.S.list !== ({'true' if view == 'list' else 'false'})) J.toggleList();
                              J.go({ep}, (J.seq({ep}) || []).length); J.drawWord();
                              J.PRE.set({ep}, {{ on: {'true' if on else 'false'}, by: '{'end' if on else 'off'}',
                                               wait: '{wait}' || undefined }});
                              J.drawWord(); return {CHIP_MEASURE}; }})()""")
                            where = f"{width}x{height} @{int(scale * 100)} %, {stone}, {'on' if on else 'off'}, " \
                                    f"wait '{wait}', {view} view"
                            if not m:
                                misses.append(f"{where}: no chip")
                                continue
                            for ch in m:
                                seen += 1
                                texts.add(ch["text"])
                                cls = set(ch["cls"].split())   # the state set reached the chip drawn
                                if ("on" in cls) != on or (wait and wait not in cls) or (not wait and cls & {"wait", "queued"}):
                                    misses.append(f"{where}: the chip drawn as '{ch['cls']}'")
                                (cl, ct, cr, cb), (sl, st, sr, sb), (tl, tt, tr, tb) = ch["chip"], ch["svg"], ch["txt"]
                                if ch["lines"] != 1:
                                    misses.append(f"{where}: '{ch['text']}' on {ch['lines']} lines")
                                if not (cl < sl and sr <= tl and tr < cr and ct <= tt and tb <= cb and ct <= st and sb <= cb):
                                    misses.append(f"{where}: '{ch['text']}' outside its pill: chip {ch['chip']}, "
                                                  f"stone {ch['svg']}, words {ch['txt']}")
                                if not 14 <= sr - sl <= 24:
                                    misses.append(f"{where}: the stone {sr - sl:.1f} px wide")
                                if ch["over"] > 0:
                                    misses.append(f"{where}: the pill's contents overflow it by {ch['over']} px")
                                if not (ch["card"][0] <= cl and cr <= ch["card"][1]):
                                    misses.append(f"{where}: the pill {ch['chip']} outside its card {ch['card']}")
        errs = e.errors()
    assert not errs, errs
    assert texts == {"Pre-studied · un-mark", "Not pre-studied · mark it"}, texts
    assert seen >= 3 * (3 * 2 + 1) * 3 * 2, seen
    assert not misses, "\n".join(misses[:40]) + f"\n({len(misses)} in all)"


def test_a_hand_edited_first_meeting_switch_reaches_the_page_as_shown():
    # settings.json edited by hand ("false", 0): J-SET's reader takes it as no switch, the default (Shown); the page
    # reads the head's value only when it is a switch (the Edge case below with a "false" head)
    from app import journey_render as jr
    assert jr.page_settings({"journey_first_meeting": "false"})["first_meeting"] is True
    assert jr.page_settings({"journey_first_meeting": 0})["first_meeting"] is True
    assert jr.page_settings({"journey_first_meeting": False})["first_meeting"] is False
    assert jr.page_settings({})["first_meeting"] is True


# (lang, sentences per word, the head's first_meeting, the kinds of word each case must reach). Every sixth fixture
# word's first line is from another episode (Only i+1's case), so the first meeting is second or not shown at all.
MEET_CASES = [
    ("ja", 3, None, {"first", "later", "none", "card"}),
    ("zh", 3, None, {"first", "later", "none", "card"}),
    ("ja", 1, "false", {"only", "none"}),             # one line a word, and a hand-edited head value
    ("zh", 1, "false", {"only", "none"}),
]


@needs_edge
@pytest.mark.parametrize("lang,sentences,head,kinds", MEET_CASES, ids=[f"{c[0]}-{c[1]}" for c in MEET_CASES])
def test_the_first_meeting_line_is_marked_and_its_switch_redraws_only_those_lines(tmp_path, lang, sentences, head, kinds):
    # Sonic's ruling: the first-meeting sentence is its own marked line, shown by default, hideable. The page marks the
    # line already shown whose source is the word's own episode and adds, drops or moves no other: the checks work
    # out each word's expected lines from its own data, and count what each press of the switch redrew
    import journey_page_run as runner
    parts = fx.build(lang, 200, sentences=sentences, first_meeting=head)
    path = runner.page_file(str(tmp_path), lang, 200, parts=parts)
    res, errs = runner.run(path, "only=meet")
    assert res and not errs, errs
    fails = [(name, detail) for name, good, detail in res["out"] if not good]
    assert not fails, fails
    reached = next(name for name, _g, _d in res["out"] if name.startswith("the kinds of word checked"))
    assert kinds <= set(reached.split(": ", 1)[1].split()), reached


@needs_edge
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_old_pages_ignores_are_carried_once_and_only_those_surasura_lacks(tmp_path, lang):
    # J-FIX: a learner's ignores kept only by the old journey page must not vanish at the update. The self-checks'
    # `carry` group: only the old words Surasura has neither Known nor Ignored, through ⊘'s route, in batches of the
    # route's most, once; nothing while Surasura is closed; an empty or malformed key sends nothing; 5,000 old words
    # in a few calls with no long task; one line with Undo; the old key never touched
    import journey_page_run as runner
    path = runner.page_file(str(tmp_path), lang, 2000)
    res, errs = runner.run(path, "only=carry")
    assert res and not errs, errs
    fails = [(name, detail) for name, good, detail in res["out"] if not good]
    assert not fails, fails
    assert res["total"] >= 15                           # the group ran to its end


@needs_edge
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_empty_library_opens_on_its_empty_state(tmp_path, lang):
    # no episodes at all: the page says what to do, the rail says so too, and nothing throws
    from journey_page_edge import Edge
    path = os.path.join(str(tmp_path), f"empty-{lang}.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fx.assemble(fx.build(lang, 0)))
    with Edge() as e:
        opened = e.open("file:///" + path.replace("\\", "/"), until="window.__J", seconds=30)
        first = e.open_wait("window.__J.TIMES.firstWord", 10) if opened else False
        # the start runs on after the first word: hello answers (here: no door) and redraws the marks, so wait for it
        heard = e.open_wait("window.__J.D.heard", 10) if first else False
        assert opened and first and heard, (opened, first, heard, e.errors())
        # the first-meeting switch with no word to mark: its row is there, the press redraws nothing that throws
        e.evaluate("window.__J.openSettings(), window.__J.setSetting('first_meeting', false), window.__J.closeLayer()")
        switched = e.evaluate("window.__J.SET.first_meeting")
        stage = e.evaluate("document.getElementById('stage').textContent")
        rail = e.evaluate("document.getElementById('rail').textContent")
        errs = e.errors()
    assert not errs, errs
    assert switched is False
    assert "Generate" in stage and "Generate" in rail, (stage, rail)
