"""The journey's door's routes (app/services/journey_door.py, journey v3 SPEC §3.2–§3.4; the transport is app/door.py,
tests/test_door.py) and the word lists' door routes (app/services/word_marks.py's `door_route` / `door_undo` /
`door_state`).

What a wrong answer would cost: a lane's route that isn't built yet crashing the page's press instead of hiding its
control (or one that is built hidden), a press waiting in the page's queue erasing a mark made later in the window
(Charter G4), the page's Undo taking back the window's own last mark, `state` failing whole for one missing or broken
reader, a mark lost or half-written when Surasura quits mid-call, and a 3.0.18 learner meeting a door at all (it is
off until the v3 page ships). On the real Japanese and Chinese known-words files of Test Resources, through the door's
own HTTP, as the page calls it.
"""
import http.client
import json
import os
import shutil
import sys
import threading
import time
import types

import pytest

from app import anki_sync, door, path_utils
from app.services import journey_door, word_lists, word_marks

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
KNOWN_SAMPLE = {"ja": os.path.join(RES, "ja", "KnownWord.json"), "zh": os.path.join(RES, "zh", "KnownWords.json")}
# Words the samples' known words don't hold, as a learner would mark them on the page: a word met in a show (Known),
# a name (Ignore)
NEW = {"ja": ("喫茶店", "ハルヒ"), "zh": ("风筝", "鲁迅")}


@pytest.fixture(autouse=True)
def _fresh_session():
    word_lists._BACKED_UP.clear()
    word_marks._UNDO.clear()
    word_marks._CHANGED.clear()
    yield
    word_lists._BACKED_UP.clear()
    word_marks._UNDO.clear()
    word_marks._CHANGED.clear()
    door.stop()


@pytest.fixture(params=["ja", "zh"])
def lang(request):
    """A user's real known words, and an Ignore list with a comment and CRLF line ends."""
    language = request.param
    uf = path_utils.get_user_files_path(language)
    os.makedirs(uf, exist_ok=True)
    shutil.copy(KNOWN_SAMPLE[language], os.path.join(uf, "KnownWord.json"))
    with open(os.path.join(uf, "IgnoreList.txt"), "wb") as f:
        f.write(("# 無視する単語\r\n冒険 - adventure\r\n" if language == "ja" else "# 忽略\r\n冒险\r\n").encode("utf-8"))
    return language


class FakeServices:
    """The window's `Services` as far as the door's word routes use it: the marks written by `word_marks`, and each
    write's language heard (`_words_marked`, the window following a mark)."""

    def __init__(self):
        self.heard = []
        self.closing = threading.Event()

    def mark_words(self, language, marks):
        result = word_marks.apply(language, marks)
        if result.done:
            self.heard.append(language)
        return result

    def undo_marks(self, language, undo_id=None):
        result = word_marks.undo(language, undo_id)
        if result.done:
            self.heard.append(language)
        return result


def _app(services=None, logged=None):
    services = services or FakeServices()
    return journey_door.App(services=services, language=lambda: "ja", closing=services.closing.is_set,
                            log=(lambda where, e: logged.append((where, e))) if logged is not None else
                            (lambda where, e: None))


@pytest.fixture
def opened(tmp_path):
    """The window's door with the registry's routes, as `start_door` opens it."""
    services = FakeServices()
    logged = []
    d = door.start(journey_door.routes(_app(services, logged)), str(tmp_path / "results"))
    d.services, d.logged = services, logged
    return d


def _post(d, route, body):
    conn = http.client.HTTPConnection("127.0.0.1", d.port, timeout=10)
    data = json.dumps(dict(body, token=d.token), ensure_ascii=False).encode("utf-8")
    conn.request("POST", f"/v1/{route}", body=data,
                 headers={"Host": f"127.0.0.1:{d.port}", "Content-Type": "text/plain", "Origin": "null"})
    r = conn.getresponse()
    out = r.status, json.loads(r.read().decode("utf-8"))
    conn.close()
    return out


def _ms(ns):
    return ns // 1_000_000


# --- the registry -------------------------------------------------------------------------------------------------- #
def test_every_route_name_of_the_spec_is_in_the_registry_and_nothing_else():
    # SPEC §3.3: the names are frozen; the page and every lane build against them
    assert set(journey_door.ROUTES) == {"words/mark", "words/undo", "episode/prestudied", "episode/undo", "line/flag",
                                        "settings/set", "swap/queue", "card/make", "clip/cut", "word/audio"}
    assert set(journey_door.routes(_app())) == set(journey_door.ROUTES) | {"hello", "state"}


def test_a_route_whose_owner_isnt_built_answers_not_yet_through_the_door(tmp_path, monkeypatch):
    # a lane's row before its file exists (a module missing) and before its function exists (the file there)
    monkeypatch.setitem(journey_door.ROUTES, "line/flag", ("app.services.no_such_flags_yet", "door_route"))
    monkeypatch.setitem(journey_door.ROUTES, "settings/set", ("app.services.word_marks", "no_such_route_yet"))
    d = door.start(journey_door.routes(_app()), str(tmp_path / "results"))
    for route in ("line/flag", "settings/set"):
        status, answer = _post(d, route, {"lang": "ja", "line_id": "a1"})
        assert status == 200 and answer["ok"] is False and answer["kind"] == journey_door.NOT_YET


def test_a_module_that_exists_but_fails_to_import_is_a_crash_never_not_yet(monkeypatch):
    # a bug in an owner's file must be said and logged, not hidden as a control the page leaves out
    def missing_dependency(name, *a, **k):
        raise ModuleNotFoundError("No module named 'tkinterdnd9'", name="tkinterdnd9")
    monkeypatch.setattr(journey_door.importlib, "import_module", missing_dependency)
    with pytest.raises(ModuleNotFoundError):
        journey_door.resolve(("app.services._door_owner_with_bad_import", "door_route"))


def test_a_built_route_is_found_from_its_owners_own_file(monkeypatch):
    # how a lane registers: only its own module, with the function the row names
    owner = types.ModuleType("app.services._door_test_owner")
    owner.door_route = lambda body, app: {"echo": body["line_id"], "lang": app.language()}
    monkeypatch.setitem(sys.modules, "app.services._door_test_owner", owner)
    monkeypatch.setitem(journey_door.ROUTES, "line/flag", ("app.services._door_test_owner", "door_route"))
    table = journey_door.routes(_app())
    assert table["line/flag"]({"line_id": "第3話:12"}) == {"echo": "第3話:12", "lang": "ja"}
    owner.door_route = "not a function"
    with pytest.raises(door.RouteError) as e:
        table["line/flag"]({"line_id": "x"})
    assert e.value.kind == journey_door.NOT_YET


def test_hello_lists_only_the_built_routes_and_the_pages_library(opened, lang, monkeypatch):
    stamp = types.ModuleType("app.journey_render")
    stamp.render_stamp = lambda language: 1763770000123 if language == lang else None
    monkeypatch.setitem(sys.modules, "app.journey_render", stamp)
    status, answer = _post(opened, "hello", {"lang": lang})
    assert status == 200 and answer["ok"] is True and answer["version"] == door.VERSION
    assert answer["lang"] == "ja" and answer["render_stamp"] == 1763770000123
    assert {"words/mark", "words/undo"} <= set(answer["routes"]) <= set(journey_door.ROUTES)
    for name in answer["routes"]:
        assert journey_door.resolve(journey_door.ROUTES[name]) is not None
    from app import library_store
    assert answer["library"] == library_store.library_key(path_utils.get_data_path(lang))


def test_hello_without_a_render_reader_answers_no_stamp_and_a_wrong_language_is_refused(opened, monkeypatch):
    monkeypatch.setitem(journey_door.__dict__, "RENDER_STAMP", ("app.no_such_render_yet", "render_stamp"))
    assert _post(opened, "hello", {"lang": "zh"})[1]["render_stamp"] is None
    for bad in ({}, {"lang": "en"}, {"lang": ["ja"]}):
        answer = _post(opened, "hello", bad)[1]
        assert answer["ok"] is False and answer["kind"] == "refused"


def test_state_leaves_out_a_reader_not_built_and_one_that_fails_and_answers_the_rest(opened, lang, monkeypatch):
    owner = types.ModuleType("app.services._door_state_owner")
    owner.door_state = lambda language, since_ns, app: {"since_ns": since_ns}
    owner.broken = lambda language, since_ns, app: 1 / 0
    owner.quiet = lambda language, since_ns, app: None
    monkeypatch.setitem(sys.modules, "app.services._door_state_owner", owner)
    monkeypatch.setattr(journey_door, "READERS", {
        "flags": ("app.services._door_state_owner", "door_state"),
        "prestudied": ("app.services.no_such_prestudied_yet", "door_state"),
        "settings": ("app.services._door_state_owner", "broken"),
        "swaps": ("app.services._door_state_owner", "quiet"),
        "marks": ("app.services.word_marks", "door_state")})
    render = _ms(time.time_ns()) + 60_000               # a render newer than both word lists
    status, answer = _post(opened, "state", {"lang": lang, "since": render})
    assert status == 200 and answer["ok"] is True
    assert answer["flags"] == {"since_ns": render * 1_000_000}
    assert "prestudied" not in answer and "settings" not in answer and "swaps" not in answer
    assert "marks" not in answer                        # (neither list written since the render)
    assert opened.logged and opened.logged[0][0] == "journey_door.state settings"
    assert abs(answer["at"] - time.time() * 1000) < 60_000
    # no `since` (a page with no render stamp): every reader answers whole
    whole = _post(opened, "state", {"lang": lang})[1]
    assert whole["flags"] == {"since_ns": None} and isinstance(whole["marks"], dict)


# --- the stale-press rule (Charter G4) ---------------------------------------------------------------------------- #
def test_a_press_is_stale_only_when_its_record_changed_after_it():
    at = 1763770000123
    assert journey_door.stale(at, (at + 1) * 1_000_000) is True
    assert journey_door.stale(at, at * 1_000_000 + 999_999) is False   # the same ms: the press stands
    assert journey_door.stale(at, at * 1_000_000 - 1) is False
    assert journey_door.stale(None, at * 1_000_000 + 1) is False    # sent at once, not from the queue
    assert journey_door.stale(at, None) is False                    # a record never changed
    assert journey_door.stale(True, 10 ** 30) is False and journey_door.stale("1", 10 ** 30) is False
    assert journey_door.stale(float(at), (at + 1) * 1_000_000) is True     # (a float stamp: exact)
    assert journey_door.stale(at + 0.5, (at + 1) * 1_000_000) is True
    assert journey_door.stale(at + 1.5, (at + 1) * 1_000_000) is False


# --- the words' routes through the door --------------------------------------------------------------------------- #
def test_a_mark_round_trip_known_ignore_state_and_undo_through_the_door(opened, lang):
    known, name = NEW[lang]
    status, answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "known"},
                                                                         {"word": name, "mark": "ignore"}]})
    assert status == 200 and answer["ok"] is True and answer["done"] == 2 and answer["stale"] == []
    assert word_marks.marks(lang)[known] == "known" and word_marks.marks(lang)[name] == "ignore"
    assert opened.services.heard == [lang]                          # the window followed, as for the card's marks
    state = _post(opened, "state", {"lang": lang, "since": 0})[1]
    assert state["marks"][known] == "known" and state["marks"][name] == "ignore"
    # the page's Undo takes back its own write, by its id
    undone = _post(opened, "words/undo", {"lang": lang, "undo_id": answer["undo_id"]})[1]
    assert undone == {"ok": True, "done": 2}
    assert known not in word_marks.marks(lang) and name not in word_marks.marks(lang)
    # the ignore list's comment and line ends are as they were
    with open(word_lists.list_path("ignore", lang), "rb") as f:
        assert f.read().startswith("# 無視する単語\r\n".encode("utf-8") if lang == "ja" else "# 忽略\r\n".encode("utf-8"))


def test_the_pages_undo_never_takes_back_the_windows_own_last_mark(opened, lang):
    known, name = NEW[lang]
    page = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "known"}]})[1]
    word_marks.apply(lang, [(name, "ignore")])                      # the window's word card, after it
    assert _post(opened, "words/undo", {"lang": lang, "undo_id": page["undo_id"]})[1]["done"] == 1
    assert known not in word_marks.marks(lang) and word_marks.marks(lang)[name] == "ignore"
    session, _dot, number = page["undo_id"].partition(".")
    for bad in ({"lang": lang}, {"lang": lang, "undo_id": None}, {"lang": lang, "undo_id": True},
                {"lang": lang, "undo_id": int(number)}, {"lang": lang, "undo_id": "1"},
                {"lang": lang, "undo_id": f"{session}.-1"}, {"lang": lang, "undo_id": f"{session}.١"},
                {"lang": lang, "undo_id": f"0000ffff.{number}"}, {"lang": "en", "undo_id": page["undo_id"]}):
        answer = _post(opened, "words/undo", bad)[1]
        assert answer["ok"] is False and answer["kind"] == "refused"
    assert word_marks.marks(lang)[name] == "ignore"
    # an id already undone (or gone from the stack): nothing is put back
    assert _post(opened, "words/undo", {"lang": lang, "undo_id": page["undo_id"]})[1]["done"] == 0


def test_marks_the_page_cant_read_are_refused_and_nothing_is_written(opened, lang):
    before = word_marks.marks(lang)
    for bad in ({"lang": lang, "marks": "喫茶店"}, {"lang": "en", "marks": []},
                {"lang": lang, "marks": [{"word": "喫茶店", "mark": "learning"}]},
                {"lang": lang, "marks": [{"word": 12, "mark": "known"}]},
                {"lang": lang, "marks": [{"word": "喫茶店", "mark": "known", "was": "maybe"}]},
                {"lang": lang, "marks": [{"word": "喫茶店", "mark": "known"}] * (word_marks.DOOR_MOST + 1)}):
        answer = _post(opened, "words/mark", bad)[1]
        assert answer["ok"] is False and answer["kind"] == "refused"
    assert word_marks.marks(lang) == before and opened.services.heard == []


def test_a_waiting_mark_never_erases_a_mark_made_in_the_window_since(opened, lang):
    # the page pressed Known on a word while Surasura was closed (queued, at T); later the window marked it Ignore;
    # the page's queue then arrives: its Known is skipped, said, and the window's Ignore stays
    known, name = NEW[lang]
    pressed = _ms(time.time_ns()) - 5_000
    word_marks.apply(lang, [(known, "ignore")])
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [
        {"word": known, "mark": "known", "was": "", "at": pressed},
        {"word": name, "mark": "ignore", "was": "", "at": pressed}]})[1]
    assert answer["ok"] is True and answer["stale"] == [known] and answer["done"] == 1
    assert word_marks.marks(lang)[known] == "ignore" and word_marks.marks(lang)[name] == "ignore"


def test_a_waiting_mark_still_lands_when_only_other_words_changed_since(opened, lang):
    # an Anki sync (or another mark) wrote the known words after the press, but not this word: the press stands
    known, name = NEW[lang]
    pressed = _ms(time.time_ns()) - 5_000
    word_marks.apply(lang, [(name, "known")])                        # another word, after the press
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "known", "was": "",
                                                                   "at": pressed}]})[1]
    assert answer["stale"] == [] and answer["done"] == 1 and word_marks.marks(lang)[known] == "known"


def test_a_waiting_clear_of_a_mark_cleared_since_is_stale_and_one_older_than_the_change_stands(opened, lang):
    known, _name = NEW[lang]
    word_marks.apply(lang, [(known, "known")])
    after_mark = _ms(time.time_ns()) + 1_000                         # pressed after the mark was written
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "", "was": "known",
                                                                   "at": after_mark}]})[1]
    assert answer["stale"] == [] and known not in word_marks.marks(lang)
    # pressed Ignore with the page still showing Known, but the window cleared it after the press
    pressed = _ms(time.time_ns()) - 5_000
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "ignore", "was": "known",
                                                                   "at": pressed}]})[1]
    assert answer["stale"] == [known] and answer["undo_id"] is None and known not in word_marks.marks(lang)


def test_a_waiting_mark_on_a_word_that_lost_its_mark_outside_this_surasura_is_stale_only_if_a_list_was_written_since(
        opened, lang):
    # the page showed Known and queued Ignore; then something other than this Surasura (an Anki sync, an earlier
    # window) took the word out of the known words: no change of ours to go by, so any list written after the press
    # makes it stale (the word has no mark now: either file could have taken it); lists all older than the press: it lands
    known, name = NEW[lang]
    word_marks.apply(lang, [(known, "known"), (name, "ignore")])        # (both lists there: a missing one is "now")
    word_marks.apply(lang, [(known, None)])
    word_marks._CHANGED[lang].pop(word_marks._norm(known), None)          # (not this Surasura's change)
    pressed = _ms(time.time_ns()) - 5_000                                 # the lists written after the press
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "ignore", "was": "known",
                                                                   "at": pressed}]})[1]
    assert answer["stale"] == [known] and known not in word_marks.marks(lang)
    older = (pressed - 60_000) * 1_000_000
    for path in (anki_sync._known_path(lang), word_lists.list_path("ignore", lang)):
        os.utime(path, ns=(older, older))                                 # both lists last written before it
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "ignore", "was": "known",
                                                                   "at": pressed}]})[1]
    assert answer["stale"] == [] and word_marks.marks(lang)[known] == "ignore"


def test_a_mark_the_known_words_lock_refuses_is_busy_and_the_page_keeps_it(opened, lang, monkeypatch):
    monkeypatch.setattr(anki_sync, "hold_known_words",
                        lambda language, verb: (None, ("Anki is updating your known words: try again soon.",)))
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": NEW[lang][0], "mark": "known"}]})[1]
    assert answer["ok"] is False and answer["kind"] == "busy" and "Anki" in answer["error"]


def test_state_reads_marks_only_once_a_list_was_written_after_the_render(lang):
    render = time.time_ns() + 10 ** 12                              # a render newer than both files
    assert word_marks.door_state(lang, render, _app()) is None
    word_marks.apply(lang, [(NEW[lang][0], "known")])
    assert word_marks.door_state(lang, 0, _app())[NEW[lang][0]] == "known"


# --- Surasura closing ---------------------------------------------------------------------------------------------- #
def test_surasura_quitting_mid_call_answers_that_call_then_closes_the_rest(tmp_path, lang):
    # the quit (`stop_door`) waits for a mark already being written, so it is never half-done; a call after the quit
    # began answers *closed* (the page keeps it); after the quit nothing listens
    entered, release = threading.Event(), threading.Event()
    services = FakeServices()
    real = services.mark_words

    def slow_mark(language, marks):
        entered.set()
        release.wait(5)
        return real(language, marks)
    services.mark_words = slow_mark
    d = door.start(journey_door.routes(_app(services)), str(tmp_path / "results"))
    answers = []
    caller = threading.Thread(target=lambda: answers.append(
        _post(d, "words/mark", {"lang": lang, "marks": [{"word": NEW[lang][0], "mark": "known"}]})))
    caller.start()
    assert entered.wait(5)
    stopper = threading.Thread(target=door.stop)
    stopper.start()
    with d._calls_done:                                             # the quit has begun (`stop` says so)
        assert d._calls_done.wait_for(lambda: d._closing, 5)
    late = _post(d, "words/mark", {"lang": lang, "marks": [{"word": NEW[lang][1], "mark": "ignore"}]})
    assert late[0] == 503 and late[1]["kind"] == journey_door.CLOSED
    assert stopper.is_alive()                                       # still waiting for the first call
    release.set()
    caller.join(10)
    stopper.join(10)
    assert answers[0][0] == 200 and answers[0][1]["done"] == 1
    assert word_marks.marks(lang)[NEW[lang][0]] == "known" and NEW[lang][1] not in word_marks.marks(lang)
    with pytest.raises(OSError):
        _post(d, "hello", {"lang": lang})


def test_a_route_asked_once_the_window_is_closing_answers_closed():
    services = FakeServices()
    services.closing.set()
    with pytest.raises(door.RouteError) as e:
        journey_door.routes(_app(services))["words/mark"]({"lang": "ja", "marks": []})
    assert e.value.kind == journey_door.CLOSED


# --- on since the cut-over (J-CUT); off for a run that asks ------------------------------------------------------- #
def test_the_door_is_on_since_the_v3_page_ships_and_off_for_a_run_that_asks(monkeypatch):
    # The cut-over's one line (journey_door.ON); SURASURA_DOOR=0 is the pre-cut world for one run (the old renderer's
    # tests, their child processes), =1 on whatever ON says, anything else is ON's.
    monkeypatch.delenv(journey_door.ENV, raising=False)
    assert journey_door.ON is True and journey_door.enabled() is True
    monkeypatch.setenv(journey_door.ENV, "0")
    assert journey_door.enabled() is False
    monkeypatch.setenv(journey_door.ENV, "1")
    assert journey_door.enabled() is True
    monkeypatch.setattr(journey_door, "ON", False)
    assert journey_door.enabled() is True
    monkeypatch.setenv(journey_door.ENV, "yes")
    assert journey_door.enabled() is False


def test_the_window_starts_no_door_while_it_is_off_and_one_with_the_registry_when_on(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    from app.qt import shell
    monkeypatch.setattr(path_utils, "get_user_file", lambda name: str(tmp_path / name))

    class Window:
        services = types.SimpleNamespace(closing=threading.Event())
        language = "zh"
        asked = 0

        def door_routes(self):
            Window.asked += 1
            return shell.ShellWindow.door_routes(self)
    monkeypatch.setenv(journey_door.ENV, "0")
    door.stop()
    assert shell.start_door(Window()) is None and door.current() is None and Window.asked == 0
    monkeypatch.delenv(journey_door.ENV, raising=False)            # the cut-over's default: on
    shell.start_door(Window()).join(10)
    d = door.current()
    try:
        assert d is not None and set(d.routes) == set(journey_door.ROUTES) | {"hello", "state"}
        assert _post(d, "hello", {"lang": "zh"})[1]["lang"] == "zh"
    finally:
        shell.stop_door()
    assert door.current() is None


def test_with_the_door_off_neither_the_start_nor_your_journey_imports_the_door(tmp_path):
    # the door off for a run (SURASURA_DOOR=0, the pre-cut world): the window's start after its first frame and *Your
    # journey* run as before the cut, the door's module (and its server's imports) never loaded; in a fresh process
    pytest.importorskip("PyQt6")
    import subprocess
    results = tmp_path / "results"
    results.mkdir()
    (results / "reading_list_static.html").write_text("<html>第1話</html>", encoding="utf-8")
    code = (
        "import sys, threading, types\n"
        "from app.qt import shell\n"
        "from app import static_html_generator as gen\n"
        "opened = []\n"
        "gen.webbrowser.open = opened.append\n"
        f"gen.get_user_file = lambda name: {str(results)!r}\n"
        "w = types.SimpleNamespace(services=types.SimpleNamespace(closing=threading.Event()), language='ja',\n"
        "                          door_routes=lambda: 1 / 0)\n"
        "assert shell.start_door(w) is None\n"
        "assert gen.open_report(file='第1話.srt') is True and opened[-1].endswith('journey_open.html'), opened\n"
        "shell.stop_door()\n"
        "print('door imported:', 'app.door' in sys.modules)\n")
    env = dict(os.environ, **{journey_door.ENV: "0"})
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stderr
    assert "door imported: False" in run.stdout


def test_a_time_the_page_cant_have_sent_is_no_time(opened, lang):
    # JSON carries NaN and Infinity (Python reads them): `state` answers whole rather than failing, and a waiting mark
    # with such a press time is treated as one sent at once
    for since in (float("nan"), float("inf"), -1, "1763770000123", True, 2 ** 60):
        assert journey_door._ms_time(since) is False
        answer = _post(opened, "state", {"lang": lang, "since": since})[1]
        assert answer["ok"] is True and isinstance(answer["marks"], dict)
        assert journey_door.stale(since, 10 ** 30) is False


# --- the review's cases (register: j-door-register.md) ------------------------------------------------------------ #
def test_a_waiting_mark_never_erases_a_word_changed_in_the_window_and_back_since(opened, lang):
    # the page showed Known and queued Ignore; the window then cleared the word and marked it Known again: the word
    # reads as the page showed it, but it is newer work than the press (Charter G4)
    known, _name = NEW[lang]
    word_marks.apply(lang, [(known, "known")])
    pressed = _ms(time.time_ns()) - 60_000                                # pressed a minute ago...
    word_marks._CHANGED[lang][word_marks._norm(known)] = (pressed - 60_000) * 1_000_000   # ...after an older Known
    word_marks.apply(lang, [(known, None)])
    word_marks.apply(lang, [(known, "known")])
    answer = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "ignore", "was": "known",
                                                                   "at": pressed}]})[1]
    assert answer["stale"] == [known] and word_marks.marks(lang)[known] == "known"


def test_an_undo_from_an_earlier_surasura_is_refused_never_another_write_undone(opened, lang, monkeypatch):
    # undo numbers start again in each Surasura: the page's Undo kept from before a restart must not take back
    # whatever this one numbered the same
    known, name = NEW[lang]
    old = _post(opened, "words/mark", {"lang": lang, "marks": [{"word": known, "mark": "known"}]})[1]["undo_id"]
    monkeypatch.setattr(word_marks, "_DOOR_SESSION", "0badcafe")            # (Surasura opened again)
    word_marks.apply(lang, [(name, "ignore")])
    answer = _post(opened, "words/undo", {"lang": lang, "undo_id": old})[1]
    assert answer["ok"] is False and answer["kind"] == "refused"
    assert word_marks.marks(lang)[known] == "known" and word_marks.marks(lang)[name] == "ignore"


def test_a_known_words_file_deleted_since_the_render_is_read_as_changed(lang):
    word_marks.apply(lang, [(NEW[lang][0], "known")])
    render = time.time_ns()
    for path in (anki_sync._known_path(lang), word_lists.list_path("ignore", lang)):   # both written before it
        os.utime(path, ns=(render - 10 ** 10, render - 10 ** 10))
    assert word_marks.door_state(lang, render, _app()) is None
    os.remove(anki_sync._known_path(lang))
    after = word_marks.door_state(lang, render, _app())                   # read: the render's Known marks are gone
    assert after is not None and NEW[lang][0] not in after and set(after.values()) == {"ignore"}


def test_hello_shows_a_broken_owner_so_its_press_says_so(opened, monkeypatch):
    def broken(name, *a, **k):
        if name == "app.services.flags":
            raise ModuleNotFoundError("No module named 'tkinterdnd9'", name="tkinterdnd9")
        return __import__("importlib").import_module(name)
    real = journey_door.importlib.import_module
    monkeypatch.setattr(journey_door.importlib, "import_module",
                        lambda name, *a, **k: broken(name) if name == "app.services.flags" else real(name, *a, **k))
    monkeypatch.setitem(journey_door.ROUTES, "line/flag", ("app.services.flags", "door_route"))
    answer = _post(opened, "hello", {"lang": "ja"})[1]
    assert "line/flag" in answer["routes"] and opened.logged
    assert _post(opened, "line/flag", {"lang": "ja"})[1]["kind"] == "crashed"


# --- J-FIX 2: the old page's ignores carried over, never over a word known by any source -------------------------- #
def _known_through_anki(language):
    """Two words the real sample holds as known with no mark of this module (an Anki card read by the sync), and one
    word not known (ja: an UNKNOWN entry of it): what a learner's KnownWord.json has after a sync."""
    _data, words = anki_sync._read_known_file(language)
    known = [e["dictForm"] for e in words if anki_sync._is_known(e) and e.get("source") != word_marks.MARKED_SOURCE
             and e.get("dictForm") and word_lists._term(e["dictForm"], language) == e["dictForm"]]
    unknown = [e["dictForm"] for e in words if not anki_sync._is_known(e) and e.get("dictForm")
               and e["dictForm"] not in known]
    assert len(known) >= 2, "the sample holds Anki-known words"
    return known[0], known[1], unknown[0] if unknown else "熊猫"     # (zh's sample: every entry known; a word not in it)


def test_a_carried_ignore_of_a_word_known_through_anki_or_marked_known_is_skipped_and_counted_as_skipped(opened, lang):
    # the old journey page's ignores are carried with "unless_known": an old ignore must never undo what the learner
    # knows — a word Known through Anki (KnownWord.json's other entries, not in `state`'s marks) or marked Known here
    anki_a, anki_b, not_known = _known_through_anki(lang)
    mine, name = NEW[lang]
    word_marks.apply(lang, [(mine, "known")])
    known_before = open(anki_sync._known_path(lang), "rb").read()
    at = _ms(time.time_ns()) + 1_000
    answer = _post(opened, "words/mark", {"lang": lang, "unless_known": True, "marks": [
        {"word": anki_a, "mark": "ignore", "was": "", "at": at},
        {"word": name, "mark": "ignore", "was": "", "at": at},
        {"word": f" {anki_b} ", "mark": "ignore", "was": "", "at": at},     # as the route reads a word: trimmed
        {"word": mine, "mark": "ignore", "was": "", "at": at},
        {"word": not_known, "mark": "ignore", "was": "", "at": at}]})[1]
    assert answer["ok"] is True and answer["stale"] == []
    assert answer["skipped"] == [anki_a, f" {anki_b} ", mine]       # each as the page sent it: the page draws them
    assert answer["done"] == 2                                      # the words actually added: the toast's number
    marks = word_marks.marks(lang)
    assert marks[name] == "ignore" and marks[not_known] == "ignore" and marks[mine] == "known"
    assert anki_a not in marks and anki_b not in marks              # never on the Ignore list
    ignore = open(word_lists.list_path("ignore", lang), "rb").read().decode("utf-8")
    assert anki_a not in ignore.splitlines() and anki_b not in ignore.splitlines()
    assert open(anki_sync._known_path(lang), "rb").read() == known_before   # the known words untouched
    # the carry's Undo takes back what it added, nothing else
    assert _post(opened, "words/undo", {"lang": lang, "undo_id": answer["undo_id"]})[1]["done"] == 2
    assert name not in word_marks.marks(lang) and word_marks.marks(lang)[mine] == "known"


def test_a_carry_whose_every_word_is_known_writes_nothing_and_says_none_added(opened, lang):
    anki_a, anki_b, _not_known = _known_through_anki(lang)
    before = {p: open(p, "rb").read() for p in (anki_sync._known_path(lang), word_lists.list_path("ignore", lang))}
    answer = _post(opened, "words/mark", {"lang": lang, "unless_known": True, "marks": [
        {"word": anki_a, "mark": "ignore", "was": ""}, {"word": anki_b, "mark": "ignore", "was": ""}]})[1]
    assert answer == {"ok": True, "done": 0, "undo_id": None, "stale": [], "skipped": [anki_a, anki_b]}
    assert {p: open(p, "rb").read() for p in before} == before and opened.services.heard == []


def test_an_ordinary_ignore_press_on_a_word_known_through_anki_lands_as_before_and_says_nothing_skipped(opened, lang):
    # the guard is the carry's to ask for: ⊘ pressed on the page (no "unless_known") behaves exactly as today
    anki_a, _anki_b, _not_known = _known_through_anki(lang)
    for off in ({}, {"unless_known": False}):
        word_marks._UNDO.clear()
        answer = _post(opened, "words/mark", dict({"lang": lang, "marks": [{"word": anki_a, "mark": "ignore"}]},
                                                  **off))[1]
        assert answer["ok"] is True and answer["done"] == (1 if not off else 0) and "skipped" not in answer
        assert word_marks.marks(lang)[anki_a] == "ignore"


def test_an_unless_known_the_route_cant_read_is_refused_and_nothing_is_written(opened, lang):
    before = word_marks.marks(lang)
    for bad in ("yes", 1, [True]):
        answer = _post(opened, "words/mark", {"lang": lang, "unless_known": bad,
                                              "marks": [{"word": NEW[lang][1], "mark": "ignore"}]})[1]
        assert answer["ok"] is False and answer["kind"] == "refused"
    assert word_marks.marks(lang) == before and opened.services.heard == []


def test_an_unless_known_of_null_is_off_as_an_ordinary_press_sends_it(opened, lang):
    # null is no ask: a client that sends the key empty gets the ordinary press, never a refusal
    anki_a, _anki_b, _not_known = _known_through_anki(lang)
    answer = _post(opened, "words/mark", {"lang": lang, "unless_known": None,
                                          "marks": [{"word": anki_a, "mark": "ignore"}]})[1]
    assert answer["ok"] is True and answer["done"] == 1 and "skipped" not in answer


def test_a_carry_whose_known_words_cant_be_read_writes_nothing_and_says_so(opened, lang, monkeypatch):
    # the guard fails closed: a known-words file that can't be read at the check (a moment's lock, a half-written
    # copy) never lets the batch through unchecked, even if the write's own read would then succeed
    anki_a, _anki_b, _not_known = _known_through_anki(lang)
    before = word_marks.marks(lang)
    real, calls = anki_sync._read_known_file, []
    def once(language, path=None):
        calls.append(language)
        if len(calls) == 1:
            raise anki_sync._KnownFileError("Your known words couldn't be read just now.")
        return real(language, path)
    monkeypatch.setattr(anki_sync, "_read_known_file", once)
    answer = _post(opened, "words/mark", {"lang": lang, "unless_known": True,
                                          "marks": [{"word": anki_a, "mark": "ignore"}]})[1]
    assert answer["ok"] is False and answer["kind"] == "failed"       # not "refused": the page tries again later
    assert len(calls) == 1 and word_marks.marks(lang) == before and opened.services.heard == []
