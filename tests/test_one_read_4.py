"""ONE-READ 4: a Generate opens the library store once for its whole run, a Generate whose known words hit their cache
never parses KnownWord.json, and the journey drawn without the store's facts never opens the store a second time.

Why (counted at the base, the bench's 2k / 20k libraries and RP-2's): a ja Generate made 7 library-store handles — the
store's helper, `prepare_library`, the indexer's lists, Connect's dates read ahead, `record_analysed`, the "In Anki"
fingerprint and the journey's render — each ~15 ms (the mode check's connection, the store's, the close's anchor); a
redraw 6. The run is one span now (`library_store.held(role="analyzer")` around `analyzer.main`): every open of a plain
role on the run's thread is that one handle, and a mode check inside it reads through it. The helper keeps its own
(its close is the checkpoint, under its maintenance lock) and so does a thread the run starts (an sqlite3 connection is
one thread's). A Generate whose known words hit the token store's cache still parsed KnownWord.json (~49 ms at 3 MB)
for the ignore set's IGNORED entries: they are kept beside the cache now, under the file's own signature. And a journey
whose one open found no ready store asked `analyzer.journey_marks`, which opened the store again to tell "no store"
from "a store it can't read now": the open's own look says it.

What a wrong answer would cost: a run reading a store closed under it, or one damaged or rebuilt meanwhile (its writes
lost, the list from a stale order), an ignore set missing the words dismissed in Migaku (they come back on the list),
or a journey signed as current while its stones couldn't be read (an Undo that leaves a stone). Real data: RP-2's real
libraries (ja + zh, `plan_file_cases`) Generated in a child process as the dashboard runs it, each run counted in a
child of its own; real words in the stores and files made here.
"""
import builtins
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import types

import pytest

from app import journey_render, library_store as ls
from app import token_index as ti
from tests import plan_file_cases as cases
from tests.test_library_store_support import LANGUAGES, migrated, roots

# The child: one run, counted on the run's own thread — the library store's handles made (and each one's role), its
# mode checks, the plain handles closed — and KnownWord.json's reads in the whole run. Its last line only when the
# run finished.
_CHILD = r"""
import builtins, io, json, os, runpy, sys, threading
from app import library_store as ls, path_utils as pu
n = {"opens": [], "probes": 0, "closes": 0, "elsewhere": 0, "known_reads": 0}
language = sys.argv[2]
KP = os.path.normcase(os.path.abspath(os.path.join(pu.get_user_files_path(language), "KnownWord.json")))
MAIN = threading.main_thread()
real_open = builtins.open
def opened(file, *a, **k):
    mode = a[0] if a else k.get("mode", "r")
    if (isinstance(file, (str, os.PathLike)) and "r" in mode and "+" not in mode
            and os.path.normcase(os.path.abspath(os.fspath(file))) == KP):
        n["known_reads"] += 1
    return real_open(file, *a, **k)
builtins.open = io.open = opened
real_init, real_probe, real_close = ls.Store.__init__, ls._probe, ls._close
handles = set()   # the plain handles' connections (the helper's own look, `_db_state`, is a bare connection)
def init(self, db_path, language, data_dir, user_files_dir, role="window"):
    main = threading.current_thread() is MAIN
    if main:
        n["opens"].append(role)
    else:
        n["elsewhere"] += 1
    made = real_init(self, db_path, language, data_dir, user_files_dir, role)
    if main and role != "helper":
        handles.add(id(self.conn))
    return made
def probe(*a, **k):
    n["probes"] += threading.current_thread() is MAIN
    return real_probe(*a, **k)
def close(conn, db_path, role):
    n["closes"] += threading.current_thread() is MAIN and id(conn) in handles
    return real_close(conn, db_path, role)
ls.Store.__init__, ls._probe, ls._close = init, probe, close
sys.argv = ["analyzer.py", f"--language={language}", "--static", "--no-open"] + (
    ["--from-plan"] if sys.argv[1] == "redraw" else [])
try:
    runpy.run_path(os.path.join("app", "analyzer.py"), run_name="__main__")
except SystemExit as e:
    if e.code not in (0, None):
        raise
print("COUNT " + json.dumps(n), flush=True)
"""

# One move on the root's library store (a show to the top of NOW), as test_one_read_3 makes it: the redraw's case.
_MOVE = r"""
import os, sys
from app import library_store as ls
language, root = sys.argv[1], sys.argv[2]
store = ls.open_store(language, os.path.join(root, "data", language), os.path.join(root, "User Files", language))
assert store is not None and store.move([store.ids("soon")[-1]], "now") is not None
store.close()
"""

LEVEL_2 = {"SURASURA_SENTENCE_TABLE": "2"}


def _env(root, **more):
    env = cases.child_env(root)
    env.update(LEVEL_2, **more)
    return env


def _counted(root, language, what, **env):
    p = subprocess.run([sys.executable, "-c", _CHILD, what, language], cwd=cases.REPO, env=_env(root, **env),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(line[-1][6:])
    got["out"] = p.stdout
    return got


def _moved_known(root, language):
    """KnownWord.json moved, as a sync that adds a word moves it: the run's known-words read misses."""
    path = os.path.join(root, "User Files", language, "KnownWord.json")
    later = time.time() + 5
    os.utime(path, (later, later))


@pytest.fixture(scope="module", params=["ja", "zh"])
def root(request, tmp_path_factory):
    """RP-2's library Generated once (the token store indexed, the library store built)."""
    language = request.param
    root = str(tmp_path_factory.mktemp(f"one-read-4-{language}") / "root")
    cases.build(root, f"rp2-{language}")
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)
    return root, language


def _one_handle(got):
    """The run's thread made one plain handle (and the helper's), closed once at the run's end."""
    plain = [role for role in got["opens"] if role != "helper"]
    assert plain == ["analyzer"], f"one handle on the run's thread, the span's: {got['opens']}"
    assert got["opens"].count("helper") <= 1, f"the helper's own, at most once: {got['opens']}"
    assert got["probes"] <= 1, f"one mode check, the span's first open's: {got}"
    assert got["closes"] == 1, f"the span's handle closed once, at the run's end: {got}"


def test_a_generate_opens_the_library_store_once_for_its_whole_run(root):
    # why: prepare_library, the indexer's lists, record_analysed, the "In Anki" fingerprint and the render each
    # opened the store (~15 ms each); the run is one span now, and its page still has its facts
    root, language = root
    _moved_known(root, language)
    got = _counted(root, language, "generate")
    assert "Journey written" in got["out"], got["out"][-1500:]
    _one_handle(got)


def test_a_generate_whose_known_words_hit_their_cache_never_parses_the_known_words(root):
    # why: the cache hit took the known words from the token store but parsed the whole file again for the ignore
    # set's IGNORED entries; the miss before it keeps them beside the cache, so the hit reads none
    root, language = root
    _moved_known(root, language)
    missed = _counted(root, language, "generate")
    assert "Reused cached known-words normalization." not in missed["out"], missed["out"][-1500:]
    assert missed["known_reads"] == 1, f"the miss parses it once, for both: {missed}"
    hit = _counted(root, language, "generate", SURASURA_FORCE_RUN="1")
    assert "Reused cached known-words normalization." in hit["out"], hit["out"][-1500:]
    assert hit["known_reads"] == 0, f"a hit parses KnownWord.json for nothing: {hit}"


def test_a_redraw_opens_the_library_store_once_for_its_whole_run(root):
    # why: the redraw from the plan (only the order moved) opened prepare_library's, record_analysed's, the
    # fingerprint's and the render's: one span too
    root, language = root
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)        # the plan of this very order
    p = subprocess.run([sys.executable, "-c", _MOVE, language, root], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]
    got = _counted(root, language, "redraw")
    assert "Redrew the journey" in got["out"], got["out"][-1500:]
    _one_handle(got)


# --- the span: one handle for the plain roles ---------------------------------------------------------------------- #
@pytest.fixture
def made(monkeypatch):
    """Every library-store handle made (`Store.__init__`) and every mode probe, by role, counted."""
    got = {"opens": [], "probes": 0}
    real_init, real_probe = ls.Store.__init__, ls._probe

    def init(self, *a, **k):
        got["opens"].append(k.get("role", a[4] if len(a) > 4 else "window"))
        return real_init(self, *a, **k)

    def probe(*a, **k):
        got["probes"] += 1
        return real_probe(*a, **k)
    monkeypatch.setattr(ls.Store, "__init__", init)
    monkeypatch.setattr(ls, "_probe", probe)
    return got


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_runs_span_serves_every_plain_role_with_one_handle_and_checks_its_mode_through_it(language, made):
    # why: the run's readers ask as "reader", its writer as "analyzer", Connect's dates as "window": in a run's span
    # all of them are one handle, opened once, its mode read through it — and closed only when the span ends
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    made["opens"].clear()
    made["probes"] = 0
    with ls.held(role="analyzer"):
        a = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
        assert a is not None and a.role == "analyzer"
        for role in ("reader", "window", "register", "analyzer"):
            assert ls.open_store(language, data_dir, user_files_dir, role=role) is a, role
        assert ls.check_mode(language, data_dir) == ("store", None)
        with a:                              # a reader's `with store:` leaves the run's handle open
            pass
        assert a.meta() is not None
        assert made["opens"] == ["analyzer"] and made["probes"] == 1, made
    with pytest.raises(sqlite3.ProgrammingError):
        a.conn.execute("SELECT 1")           # closed at the span's end


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_helper_and_connects_role_keep_handles_of_their_own_in_a_runs_span(language, made):
    # why: the helper's close is the checkpoint (under its lock) and Connect's commits trigger the copy: a run's
    # span never hands either the plain handle, nor hands them theirs; another thread opens its own (one thread's
    # connection)
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    with ls.held(role="analyzer"):
        plain = ls.open_store(language, data_dir, user_files_dir, role="reader")
        connect = ls.open_store(language, data_dir, user_files_dir, role="connect")
        assert plain is not None and connect is not None and connect is not plain and connect.role == "connect"
        helper = ls.open_store(language, data_dir, user_files_dir, role="helper")
        assert helper is not None and helper is not plain and helper.role == "helper"
        seen = {}

        def other_thread():
            store = ls.open_store(language, data_dir, user_files_dir, role="reader")
            seen["store"] = store
            if store is not None:
                store.close()
        worker = threading.Thread(target=other_thread)
        worker.start()
        worker.join(5)
        assert seen.get("store") is not None and seen["store"] is not plain


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_role_a_span_keeps_one_handle_a_role_as_before(language):
    # why: Connect's job spans (`held()`) are unchanged: a reader asked inside one gets a handle of its own — also
    # after a run's span on this thread ended, even by an exception (its role never outlives it)
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    with pytest.raises(KeyError):
        with ls.held(role="analyzer"):
            assert ls.open_store(language, data_dir, user_files_dir, role="reader").role == "analyzer"
            raise KeyError("the run stopped")
    with ls.held(role="analyzer"):
        with ls.held():                      # a span inside the run's joins it: still the run's one handle
            assert ls.open_store(language, data_dir, user_files_dir, role="reader").role == "analyzer"
    with ls.held():
        a = ls.open_store(language, data_dir, user_files_dir, role="connect")
        reader = ls.open_store(language, data_dir, user_files_dir, role="reader")
        assert a is not None and reader is not None and reader is not a and reader.role == "reader"
        reader.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_damaged_during_a_runs_span_is_let_go_and_answered_as_damaged(language):
    # why: the run holds its handle across the tokenize; a store marked damaged meanwhile must never be read through
    # it (Repair sets the file aside) — the next open is None and says why, without a second look
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    with ls.held(role="analyzer"):
        a = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
        assert a is not None
        ls.mark_damaged(a.db_path, "test: damaged during the run")
        try:
            assert ls.open_store_mode(language, data_dir, user_files_dir, role="reader") == (
                None, ("read-only", "damaged"))
            with pytest.raises(sqlite3.ProgrammingError):
                a.conn.execute("SELECT 1")   # let go of at once
            assert ls.check_mode(language, data_dir)[0] == "read-only"
        finally:
            os.remove(ls.damaged_marker(a.db_path))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_span_without_a_role_hands_each_role_its_own_handle_again_and_again(language, made):
    # why: Connect's job spans (`held()`, no role) keep one handle a role — the same reader asked twice is one handle,
    # opened once, and a run's role never reaches them
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    made["opens"].clear()
    with ls.held():
        reader = ls.open_store(language, data_dir, user_files_dir, role="reader")
        assert reader is not None and reader.role == "reader"
        assert ls.open_store(language, data_dir, user_files_dir, role="reader") is reader
        window = ls.open_store(language, data_dir, user_files_dir, role="window")
        assert window is not None and window is not reader and window.role == "window"
    assert made["opens"] == ["reader", "window"], made


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_runs_span_inside_a_span_without_a_role_joins_it_as_it_is(language):
    # why: a span inside another joins the outer one; the outer (Connect's job) set no role, so the inner run's role
    # changes nothing there — each role keeps its own handle, as the outer span's owner expects
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    with ls.held():
        with ls.held(role="analyzer"):
            reader = ls.open_store(language, data_dir, user_files_dir, role="reader")
            analyzer = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
            assert reader is not None and analyzer is not None and reader is not analyzer
            assert (reader.role, analyzer.role) == ("reader", "analyzer")
        assert ls.open_store(language, data_dir, user_files_dir, role="reader") is reader, "still the outer's"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mode_check_on_a_held_handle_whose_store_was_marked_damaged_says_damaged(language):
    # why: `check_mode` reads through the run's handle; a store marked damaged since (before any other open) must be
    # answered as damaged — never "store" from the handle's own read
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    with ls.held(role="analyzer"):
        a = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
        assert a is not None and ls.check_mode(language, data_dir) == ("store", None)
        ls.mark_damaged(a.db_path, "test: damaged during the run")
        try:
            assert ls.check_mode(language, data_dir) == ("read-only", "damaged")
        finally:
            os.remove(ls.damaged_marker(a.db_path))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_held_handle_closed_under_the_run_is_let_go_and_the_next_open_opens_anew(language, made):
    # why: a reader that closed the run's connection itself (not through `close()`) leaves a dead handle in the span;
    # a mode check still answers from the file, and the open after the one that found it dead opens a working one
    data_dir, user_files_dir = roots(language)
    migrated(language).close()
    made["opens"].clear()
    with ls.held(role="analyzer"):
        a = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
        assert a is not None
        a.conn.close()
        assert ls.check_mode(language, data_dir) == ("store", None)
        store, (mode, reason) = ls.open_store_mode(language, data_dir, user_files_dir, role="reader")
        assert store is None and mode == "read-only" and str(reason).startswith("io"), (mode, reason)
        b = ls.open_store(language, data_dir, user_files_dir, role="reader")
        assert b is not None and b is not a and b.meta() is not None
    assert made["opens"] == ["analyzer", "analyzer"], made


def test_a_runs_span_on_one_language_opens_the_others_store_as_its_own(made):
    # why: the span's handle is one store's (one file): a ja run asked for the zh store must never be handed the ja
    # handle, nor have the zh mode checked through it
    ja_data, ja_user = roots("ja")
    zh_data, zh_user = roots("zh")
    window = migrated("ja")
    try:
        window.set_watched([window.ids("now")[0]], True)          # the ja store's marks differ from the zh one's
    finally:
        window.close()
    migrated("zh").close()
    zh_marks = ls.read_watched_marks("zh", zh_data)
    assert zh_marks != ls.read_watched_marks("ja", ja_data)
    made["opens"].clear()
    with ls.held(role="analyzer"):
        ja = ls.open_store("ja", ja_data, ja_user, role="analyzer")
        assert ls.read_watched_marks("zh", zh_data) == zh_marks, "the zh marks, never read through the ja handle"
        zh = ls.open_store("zh", zh_data, zh_user, role="reader")
        assert ja is not None and zh is not None and zh is not ja
        assert (ja.language, zh.language) == ("ja", "zh")
        assert ls.open_store("zh", zh_data, zh_user, role="window") is zh, "the zh store's one handle too"
        assert ls.check_mode("zh", zh_data) == ("store", None)
    assert made["opens"] == ["analyzer", "analyzer"], made


# --- the journey without the store's facts: the open's own look ---------------------------------------------------- #
@pytest.mark.parametrize("found, marks", [
    (("json", "no store"), None),
    (("json", "not ready"), None),
    (("read-only", "damaged"), None),
    (("read-only", "made by a newer Surasura"), None),
    (("read-only", ls.NEWER_COPY), None),
    (("read-only", "busy"), ls.UNREAD),
    (("read-only", "io: disk I/O error"), ls.UNREAD),
])
def test_a_journey_open_that_found_no_store_says_how_it_is_signed(monkeypatch, found, marks):
    # why: `analyzer.journey_marks` opened the store a second time to tell no store (the report as before) from one
    # that can't be read now (never signed as current); the open's look already knows
    monkeypatch.setattr(ls, "open_store_mode", lambda *a, **k: (None, found))
    assert journey_render.open_library_look("ja") == (None, marks)


def test_a_journey_open_whose_look_raised_is_never_signed_as_current(monkeypatch):
    # why: an open that raised (a folder it can't work out, a broken store module) is neither "no store" nor current
    def raised(*a, **k):
        raise OSError("test: the data folder is gone")
    monkeypatch.setattr(ls, "open_store_mode", raised)
    assert journey_render.open_library_look("ja") == (None, ls.UNREAD)


def test_a_journey_open_with_a_handle_signs_a_failed_read_as_unread(monkeypatch):
    # why: a store there whose facts couldn't be read through the handle is never signed as current
    handle = object()
    monkeypatch.setattr(ls, "open_store_mode", lambda *a, **k: (handle, ("store", None)))
    assert journey_render.open_library_look("ja") == (handle, ls.UNREAD)


@pytest.mark.parametrize("without", [None, ls.UNREAD])
def test_the_journey_drawn_without_facts_never_opens_the_store_again(monkeypatch, without):
    # why: `_write_journey` asked `analyzer.journey_marks` (a second connection) when its open found no store
    from app import analyzer
    from app import static_html_generator as shg

    seen = {}

    def render(language, **k):
        seen.update(k)
        return types.SimpleNamespace(head={"counts": {"eps": 0, "words": 0}})
    monkeypatch.setattr(journey_render, "open_library_look", lambda *a, **k: (None, without))
    monkeypatch.setattr(journey_render, "render", render)
    monkeypatch.setattr(journey_render, "write_page", lambda *a, **k: None)
    monkeypatch.setattr(analyzer, "journey_marks", lambda language: pytest.fail("opened the store again"))
    # the run's render signature takes these marks: no store -> as before (None), unreadable -> never current
    assert shg._write_journey("ja", open_browser=False) is without
    assert seen["library"] is False and seen["facts"] is False


# --- the IGNORED entries beside the known-words cache -------------------------------------------------------------- #
KNOWN = [{"dictForm": "冒険", "knownStatus": "KNOWN"}, {"dictForm": "準備", "hasCard": 1},
         {"dictForm": "危険", "knownStatus": "IGNORED"}, {"dictForm": " 価値 ", "knownStatus": "IGNORED"},
         {"dictForm": "", "knownStatus": "IGNORED"}]
KNOWN_ZH = [{"dictForm": "冒险", "knownStatus": "KNOWN"}, {"dictForm": "准备", "hasCard": 1},
            {"dictForm": "危险", "knownStatus": "IGNORED"}, {"dictForm": " 价值 ", "knownStatus": "IGNORED"}]


def _known_file(language):
    folder = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", language)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": KNOWN if language == "ja" else KNOWN_ZH}, f, ensure_ascii=False)
    return folder, path


class _Reads:
    """KnownWord.json's reads through `path_utils.read_text` (the analyzer's and the token index's), counted."""

    def __init__(self, monkeypatch, path):
        from app import analyzer, path_utils
        self.n = 0
        self._inside = False
        target = os.path.normcase(os.path.abspath(path))
        real, real_open = path_utils.read_text, builtins.open

        def read_text(p, *a, **k):
            self.n += os.path.normcase(os.path.abspath(p)) == target
            self._inside = True             # its own open() of the file is this same read
            try:
                return real(p, *a, **k)
            finally:
                self._inside = False

        def opened(file, *a, **k):          # a raw open() of the file counts too (a reader past read_text)
            mode = a[0] if a else k.get("mode", "r")
            if (not self._inside and isinstance(file, (str, os.PathLike)) and "r" in mode and "+" not in mode
                    and os.path.normcase(os.path.abspath(os.fspath(file))) == target):
                self.n += 1
            return real_open(file, *a, **k)
        monkeypatch.setattr(path_utils, "read_text", read_text)
        monkeypatch.setattr(analyzer, "read_text", read_text)
        monkeypatch.setattr(builtins, "open", opened)


def _tokenizer(language):
    from app import analyzer
    return analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_known_cache_hit_hands_the_ignore_set_its_entries_without_a_parse(monkeypatch, language):
    # why: the hit parsed the 3 MB file for the IGNORED entries alone; the miss keeps them beside the cache, and the
    # ignore set the hit builds is the one a fresh parse gives
    from app import analyzer
    folder, path = _known_file(language)
    monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
    tokenizer = _tokenizer(language)
    store = ti.open_store(language)
    try:
        sig = ti.known_signature(path, getattr(tokenizer, "script", "asis"))
        missed = analyzer.read_known_words(store, path, sig, tokenizer)
        fresh = ti._ignored_file_entries(folder, language)
        assert len(fresh) == 2, fresh
        monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})          # the next run: a new process
        count = _Reads(monkeypatch, path)
        hit = analyzer.read_known_words(store, path, sig, tokenizer)
        got = ti._ignored_file_entries(folder, language)
    finally:
        store.close()
    assert hit == missed
    assert got == fresh, "the same entries as the file's own parse"
    assert count.n == 0, f"the hit parses KnownWord.json for none of them: {count.n}"
    assert analyzer.load_ignore_set(folder, language=language) >= set(fresh)


@pytest.mark.parametrize("language", LANGUAGES)
def test_kept_entries_of_another_file_are_never_handed_on(monkeypatch, language):
    # why: the row is the file as the miss parsed it; a file written since (a sync) is read again, never answered from
    # the older row — and a store from before the row (none kept) reads the file as before
    folder, path = _known_file(language)
    store = ti.open_store(language)
    try:
        assert store.cached_ignored(ti.known_signature(path)) is None, "no row yet"
        store.set_cached_known(ti.known_signature(path), set(), set(), suffix="",
                               ignored=(ti.known_signature(path), ["危険"]))
        assert store.cached_ignored(ti.known_signature(path)) == ["危険"]
        later = time.time() + 7
        os.utime(path, (later, later))
        assert store.cached_ignored(ti.known_signature(path)) is None, "a file written since: read again"
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_miss_keeps_the_ignored_entries_it_parsed_in_its_one_commit(monkeypatch, language):
    # why: the row is written with the known words' cache (one commit a miss), from the miss's own parse — never a
    # second parse to write it
    from app import analyzer
    folder, path = _known_file(language)
    monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
    tokenizer = _tokenizer(language)
    count = _Reads(monkeypatch, path)
    store = ti.open_store(language)
    try:
        analyzer.read_known_words(store, path, ti.known_signature(path, getattr(tokenizer, "script", "asis")),
                                  tokenizer)
        kept = store.cached_ignored(ti.known_signature(path))
    finally:
        store.close()
    assert count.n == 1, f"one parse a miss: {count.n}"
    assert kept is not None and len(kept) == 2 and all(e.strip() == e and e for e in kept), kept


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_hit_on_a_store_from_before_the_row_keeps_it_once_and_the_next_hit_parses_none(monkeypatch, language):
    # why: a store whose cache came before the row never meets a miss while KnownWord.json stays as it is (no sync):
    # without the row its every hit parsed the file; the first hit writes it from the ignore set's own parse — a reader
    # that writes nothing (`keep=False`) leaves it
    from app import analyzer
    folder, path = _known_file(language)
    monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
    tokenizer = _tokenizer(language)
    sig = ti.known_signature(path, getattr(tokenizer, "script", "asis"))
    store = ti.open_store(language)
    try:
        known = analyzer.read_known_words(store, path, sig, tokenizer)
        store.set_meta("known_ignored", "")                     # the cache as a store from before the row holds it
        monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
        analyzer.read_known_words(store, path, sig, tokenizer, keep=False)
        assert store.cached_ignored(ti.known_signature(path)) is None, "a reader that writes nothing wrote it"
        monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
        count = _Reads(monkeypatch, path)
        assert analyzer.read_known_words(store, path, sig, tokenizer) == known
        assert count.n == 1, f"the first hit parses once (the ignore set's parse, kept): {count.n}"
        assert ti._ignored_file_entries(folder, language) and count.n == 1
        monkeypatch.setattr(ti, "_IGNORED_ENTRIES", {})
        analyzer.read_known_words(store, path, sig, tokenizer)
        assert ti._ignored_file_entries(folder, language) and count.n == 1, f"the next hit parses none: {count.n}"
    finally:
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_journeys_marks_read_inside_a_run_take_the_runs_handle(language, monkeypatch):
    # why: the up-to-date path signs its check with `analyzer.journey_marks`, which opened a read-only connection of
    # its own inside a run already holding the store: read through the run's handle, the same marks
    import sqlite3
    data_dir, user_files_dir = roots(language)
    window = migrated(language)
    try:
        window.set_watched([window.ids("now")[0]], True)
    finally:
        window.close()
    outside = ls.read_watched_marks(language, data_dir)
    assert outside and outside != ls.UNREAD
    connects = []
    real = sqlite3.connect
    with ls.held(role="analyzer"):
        assert ls.open_store(language, data_dir, user_files_dir, role="analyzer") is not None
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: connects.append(a[0]) or real(*a, **k))
        inside = ls.read_watched_marks(language, data_dir)
        monkeypatch.setattr(sqlite3, "connect", real)
    assert inside == outside
    assert connects == [], f"no connection of its own: {connects}"
