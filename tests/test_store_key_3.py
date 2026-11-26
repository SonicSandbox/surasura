"""STORE-KEY 3: the three extra reads STORE-KEY 2 found, gone.

Why: (1) the journey page, written at the end of a Generate, opened a token store of its own to look up the known
words (`journey_render._known_terms`: the known-words key's settings.json read and a parse of the name tables), though
the run holds those very lemmas in-process. (2) With *Ignore names* on, every ignore-set read
(`token_index.ignored_names`) opened a fresh database connection (~13 ms on lib2k) and parsed the library's names list
again (5,447 names), even for a caller holding the store open: Generate, the arrivals view, Connect's known words at
each card, the Rarity slider's refresh. (3) `analyzer.load_ignore_set` read settings.json for the switch inside
Generate, which has its settings loaded. After it: the run hands its known lemmas to the page, a caller's open store is
read (its parse kept while the stored text is the same), and Generate hands its settings.

Real data: RP-2's real libraries (ja + zh, `plan_file_cases`) Generated in a child process as the dashboard runs it,
counted in its own process; the known-words slice of tests/Test Resources for the readers.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from app import analyzer, settings_manager
from app import sentence_corpus as sc
from app import token_index as ti
from tests import plan_file_cases as cases
from tests.test_store_key import known_file

# The child: one Generate, counted — the reads this lane removes, each told by who asked (the stack), printed as its
# last line only when the run finished (a failed Generate prints none, so a zh 0 can't pass for it).
_CHILD = r"""
import json, os, runpy, sqlite3, sys, traceback
from app import settings_manager as sm, token_index as ti
n = {"journey_opens": 0, "journey_settings": 0, "journey_parses": 0, "names_opens": 0, "names_settings": 0,
     "names_parses": 0}
def asked_by(name):
    return any(f.name == name for f in traceback.extract_stack())
real_connect, real_load, real_tables, real_loads = sqlite3.connect, sm.load_settings, ti.Store.names_tables, json.loads
def connect(db, *a, **k):
    if "token_store" in str(db):
        n["journey_opens"] += asked_by("_known_terms")
        n["names_opens"] += asked_by("ignored_names")
    return real_connect(db, *a, **k)
def load(*a, **k):
    n["journey_settings"] += asked_by("_known_terms")
    n["names_settings"] += asked_by("ignored_names")
    return real_load(*a, **k)
def tables(self, *a, **k):
    before = getattr(self, "_tables_read", None)
    got = real_tables(self, *a, **k)
    if asked_by("_known_terms") and getattr(self, "_tables_read", None) is not before:
        n["journey_parses"] += 1
    return got
def loads(s, *a, **k):
    n["names_parses"] += asked_by("ignored_names")
    return real_loads(s, *a, **k)
sqlite3.connect, sm.load_settings, ti.Store.names_tables = connect, load, tables
ti.json = type(sys)("json_counted"); ti.json.__dict__.update(json.__dict__); ti.json.loads = loads
what, language = sys.argv[1], sys.argv[2]
if what == "generate":
    sys.argv = ["analyzer.py", f"--language={language}", "--static", "--no-open"]
    try:
        runpy.run_path(os.path.join("app", "analyzer.py"), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
else:                                       # the arrivals view, on the store its caller holds
    from app import analyzer, arrivals, plan_engine
    plan = plan_engine.load(os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE))
    store = ti.open_store(language)
    try:
        arrivals.View.build(language, plan, store)
    finally:
        store.close()
print("COUNT " + json.dumps(n), flush=True)
"""


def _counted(root, language, what="generate"):
    p = subprocess.run([sys.executable, "-c", _CHILD, what, language], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    return json.loads(line[-1][6:])


def _names_switch(root, on):
    """Settings -> *Ignore names* in the root's settings.json, as the app finds the file."""
    path = os.path.join(root, "settings.json")
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("logic", {})["ignore_names"] = on
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _moved(root, language):
    """KnownWord.json moved, as a card Connect writes moves it: the run's known-words read misses."""
    path = os.path.join(root, "User Files", language, "KnownWord.json")
    later = time.time() + 5
    os.utime(path, (later, later))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_generate_reads_no_store_settings_or_names_twice_for_the_journey_and_its_ignore_set(tmp_path, language):
    # why: the journey page's known words are the run's own (handed down: no store of its own, no key worked out
    # again), and the run's ignore set reads the names from the run's open store with the run's settings — no fresh
    # connection, no settings.json read, the names list parsed once. Chinese has no names: no read, before as after;
    # its journey opened a store too. KnownWord.json moved first, so the known-words read misses (the costly case).
    root = str(tmp_path / "root")
    case = f"rp2-{language}"
    cases.build(root, case)
    _names_switch(root, True)
    cases.generate(root, case)                         # the store indexed, its names found
    _moved(root, language)
    got = _counted(root, language)
    assert got["journey_opens"] == 0, "the journey page: the run's known lemmas, no store of its own"
    assert got["journey_settings"] == 0 and got["journey_parses"] == 0, "the journey page: no key worked out again"
    assert got["names_opens"] == 0, "the ignore set: the run's open store, no fresh connection"
    assert got["names_settings"] == 0, "the ignore set: the run's settings, not settings.json again"
    assert got["names_parses"] == (1 if language == "ja" else 0), "the names list: parsed once"
    # the arrivals view reads its ignore set's names through the store it is handed, too
    got = _counted(root, language, "arrivals")
    assert (got["names_opens"], got["names_parses"]) == (0, 1 if language == "ja" else 0), "arrivals: its store"


def _store_with_names(tmp_path, words):
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    store.set_meta("names_words", json.dumps(words, ensure_ascii=False))
    return store


class _Opens:
    """Fresh connections opened to a token store, and parses of the names list."""

    def __init__(self, monkeypatch):
        self.opens = self.parses = 0
        real_connect, real_loads = sqlite3.connect, json.loads

        def connect(db, *a, **k):
            self.opens += "store" in str(db)
            return real_connect(db, *a, **k)

        def loads(s, *a, **k):
            self.parses += isinstance(s, str) and s.startswith('["')
            return real_loads(s, *a, **k)
        monkeypatch.setattr(sqlite3, "connect", connect)
        counted = type(json)("json_counted")
        counted.__dict__.update(json.__dict__)
        counted.loads = loads
        monkeypatch.setattr(ti, "json", counted)


ON = {"logic": {"ignore_names": True}}


def test_a_held_store_is_read_for_the_names_parsed_once_while_its_text_is_the_same(tmp_path, monkeypatch):
    # why: a caller holding the store (Generate, the arrivals view, Connect at each card, the Rarity slider) asks the
    # names through it — no new connection; the parse is kept while the stored text is the same, and a new index's
    # names (this process's or another's) are read at the next ask, never the old list
    store = _store_with_names(tmp_path, ["スドウ", "ミロナイ", ""])
    try:
        count = _Opens(monkeypatch)
        first = ti.ignored_names("ja", ON, store)
        assert first == ["スドウ", "ミロナイ"]
        assert ti.ignored_names("ja", ON, store) == first
        assert (count.opens, count.parses) == (0, 1), "no connection opened; parsed once"
        first.append("changed by a caller")
        assert ti.ignored_names("ja", ON, store) == ["スドウ", "ミロナイ"], "each caller gets a list of its own"
        store.set_meta("names_words", json.dumps(["ヒナ"], ensure_ascii=False))
        assert ti.ignored_names("ja", ON, store) == ["ヒナ"], "new names stored: read again"
        assert ti.ignored_names("ja", {"logic": {"ignore_names": False}}, store) == [], "the switch off: none"
        assert ti.ignored_names("zh", ON, store) == [], "Chinese: none"

        monkeypatch.setattr(ti, "_read_meta", lambda language, key: ["ヒナ", "フレッシュ"] if key == "names_words" else None)
        broken = ti.Store.__new__(ti.Store)             # a store that can't be read (closed): the fresh read, as before
        broken.conn, broken.language = sqlite3.connect(":memory:"), "ja"
        broken.conn.close()
        assert ti.ignored_names("ja", ON, broken) == ["ヒナ", "フレッシュ"], "an unreadable store: read fresh"

        reader = ti.Store.__new__(ti.Store)             # a reader made on a connection alone (surasura-cli's)
        reader.conn, reader.language = store.conn, "ja"
        assert ti.ignored_names("ja", ON, reader) == ["ヒナ"]
    finally:
        store.close()


def test_without_a_store_the_names_are_read_from_the_file_as_before(tmp_path, monkeypatch):
    # why: a caller with no store open (the word lists, practice, surasura-cli) still reads the names the last index
    # found, fresh, through a read-only connection — and none before a first index
    monkeypatch.setattr(ti, "store_path_for", lambda language: str(tmp_path / "store.db"))
    assert ti.ignored_names("ja", ON) == [], "no store yet: none"
    _store_with_names(tmp_path, ["スドウ"]).close()
    assert ti.ignored_names("ja", ON) == ["スドウ"]


def test_the_ignore_set_takes_the_handed_settings_and_store(tmp_path, monkeypatch, ja_resources_dir):
    # why: Generate hands load_ignore_set its loaded settings and its open store — the switch read from them (on in
    # the handed settings: the names ignored, whatever settings.json says) and the names from the store, with no
    # settings.json read and no connection of its own
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    path = known_file("ja", ja_resources_dir)
    settings = settings_manager.load_settings()
    settings["logic"]["ignore_names"] = False
    settings_manager.save_settings(settings)
    store = _store_with_names(tmp_path, ["スドウ", "ミロナイ"])
    try:
        reads = [0]
        real_load = settings_manager.load_settings

        def load(*a, **k):
            reads[0] += 1
            return real_load(*a, **k)
        monkeypatch.setattr(settings_manager, "load_settings", load)
        count = _Opens(monkeypatch)
        user_files = os.path.dirname(path)
        got = analyzer.load_ignore_set(user_files, "asis", "ja", ON, store)
        assert {"スドウ", "ミロナイ"} <= got
        assert (reads[0], count.opens) == (0, 0), "no settings.json read, no connection of its own"
        assert not {"スドウ", "ミロナイ"} & analyzer.load_ignore_set(user_files, "asis", "ja"), \
            "nothing handed: settings.json's switch (off), as before"
    finally:
        store.close()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_connects_known_read_and_the_rarity_preview_read_the_names_through_their_store(
        tmp_path, monkeypatch, language, ja_resources_dir, zh_resources_dir):
    # why: Connect's known words (`sentence_corpus.known_sets`, at each card it writes) and the Rarity slider's
    # preview (`preview_lists`) each hold the store: the names come through it, never a fresh connection a call
    resources = ja_resources_dir if language == "ja" else zh_resources_dir
    monkeypatch.setattr(analyzer, "SANITIZE_JA", language == "ja")
    path = known_file(language, resources)
    settings = settings_manager.load_settings()
    settings["logic"]["ignore_names"] = True
    settings_manager.save_settings(settings)
    settings = settings_manager.load_settings()
    store = ti.open_store(language, path=str(tmp_path / "store.db"))
    store.set_meta("names_words", json.dumps(["スドウ"], ensure_ascii=False))
    try:
        # a fresh read would find other names, in a store file of their own: it would show, opened and read
        elsewhere = ti.open_store(language, path=str(tmp_path / "elsewhere.db"))
        elsewhere.set_meta("names_words", json.dumps(["フレッシュ"], ensure_ascii=False))
        elsewhere.close()
        monkeypatch.setattr(ti, "store_path_for", lambda lang: str(tmp_path / "elsewhere.db"))
        count = _Opens(monkeypatch)
        names = {"スドウ"} if language == "ja" else set()
        assert sc.known_sets(language, store, settings)[2] & {"スドウ", "フレッシュ"} == names
        assert ti.preview_lists(store, language, os.path.dirname(path))["ignore_set"] & {"スドウ", "フレッシュ"} == names
        assert count.opens == 0, "the names through the held store"
    finally:
        store.close()
