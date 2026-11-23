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
