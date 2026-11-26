"""ONE-READ: one run reads settings.json once, opens the token store once, parses the names once.

Why: STORE-KEY 3's count said a Japanese Generate still read settings.json 17 times — the run signature twice, the
store's build signature five times (one read per switch), the phrase switch, the known-words key, the Ignore names
switch, the workers' count, the sentence choice, the journey page and the render signature, each on its own — and opened
the token store twice (the sentence choice opened a reader of its own inside the run). The journey's redraw opened a
second store for the page's known words too, Junban's known words read the names through a fresh connection after
closing its own store, and the window's first preview read the names only to throw them away. After it: the run reads
settings once, at its start (fresh: a change between runs is still seen), and hands that one copy down; the run's store
is the one every step reads; the names are read through it, parsed once.

The import's own read (the analyzer's LOGIC, at import) is the module's, not the run's, and is told apart: a run made
from source imports the analyzer twice (as the script, then as `app.analyzer`), the frozen app once.

Real data: RP-2's real libraries (ja + zh, `plan_file_cases`) Generated in a child process as the dashboard runs it,
each run counted in a child of its own.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from tests import plan_file_cases as cases

# The child: one run, counted — every read of settings.json told by who asked (the first caller outside the settings
# reader), the analyzer's import apart; token-store connections; the name tables and the names list parsed. Its
# last line only when the run finished (a failed run prints none, so a 0 can't pass for it).
_CHILD = r"""
import builtins, io, json, os, runpy, sqlite3, sys, traceback
from app import path_utils as pu, settings_manager as sm, token_index as ti
n = {"settings": [], "import_settings": 0, "opens": [], "tables": 0, "names": 0, "process_tables": 0, "page_known": None}
SP = os.path.normcase(os.path.abspath(pu.get_settings_path()))
SKIP = ("path_utils.py", "settings_manager.py")
def caller(skip=SKIP):
    for f in reversed(traceback.extract_stack()[:-2]):
        if not f.filename.endswith(skip) and f.name not in ("connect", "meta"):   # (this counter's own wrappers)
            return f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
    return "?"
real_open = builtins.open
def opened(file, *a, **k):
    mode = a[0] if a else k.get("mode", "r")
    if (isinstance(file, (str, os.PathLike)) and "r" in mode and "+" not in mode
            and os.path.normcase(os.path.abspath(os.fspath(file))) == SP):
        who = caller()
        if who.startswith("analyzer.py") and who.endswith("<module>"):
            n["import_settings"] += 1          # the module's LOGIC, read at import
        else:
            n["settings"].append(who)
    return real_open(file, *a, **k)
builtins.open = io.open = opened
real_connect, real_tables, real_words, real_meta = sqlite3.connect, ti.Store.names_tables, ti.Store.names_words, ti._read_meta
def connect(db, *a, **k):
    if "token_store" in str(db):
        n["opens"].append(caller(SKIP + ("token_index.py",)))   # (who asked the store module for it)
        if "library_tables" in n["opens"][-1]:
            n["opens"].pop()
            n["process_tables"] += 1         # the tokenizer's name tables, the process's (names.REFRESH): not a call's
    return real_connect(db, *a, **k)
def tables(self, *a, **k):
    before = getattr(self, "_tables_read", None)
    got = real_tables(self, *a, **k)
    n["tables"] += getattr(self, "_tables_read", None) is not before
    return got
def words(self, *a, **k):
    before = getattr(self, "_words_read", None)
    got = real_words(self, *a, **k)
    n["names"] += getattr(self, "_words_read", None) is not before
    return got
def meta(language, key):
    n["names"] += key == "names_words"
    return real_meta(language, key)
sqlite3.connect, ti.Store.names_tables, ti.Store.names_words, ti._read_meta = connect, tables, words, meta
from app import journey_render as jr
real_terms = jr._known_terms
def terms(*a, **k):                          # the page's own known-words lookup (a redraw's: none handed)
    got = real_terms(*a, **k)
    n["page_known"] = len(got)
    return got
jr._known_terms = terms
what, language = sys.argv[1], sys.argv[2]
out = None
if what in ("generate", "redraw"):
    sys.argv = ["analyzer.py", f"--language={language}", "--static", "--no-open"] + (
        ["--from-plan"] if what == "redraw" else [])
    try:
        runpy.run_path(os.path.join("app", "analyzer.py"), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
else:
    settings = sm.load_settings()            # the caller's own read, at its start (Connect's `choose`, Junban's job)
    if os.environ.get("ONE_READ_NAMES_OFF"):
        settings["logic"]["ignore_names"] = False    # in the caller's copy only: settings.json still says on
    n["settings"].clear()
    from app import analyzer
    analyzer.SANITIZE_JA = language == "ja"   # (as Connect and Junban set it before they read)
    if what == "connect":
        from app import sentence_corpus
        store = ti.open_store(language)
        n["opens"].clear()                    # (the caller's store)
        try:
            out = sentence_corpus.known_sets(language, store, settings)
        finally:
            store.close()
    elif what == "junban":
        from modules.junban import reposition
        out = reposition._known_sets(language, settings)
    elif what == "preview":
        ti.prepare_preview(language, pu.get_user_files_path(language))
if out is not None:
    print("IGNORED " + json.dumps(sorted(out[2]), ensure_ascii=False), flush=True)
print("COUNT " + json.dumps(n), flush=True)
"""

# One move on the root's library store (a show to the top of NOW), as test_e_redraw makes it: the redraw's case.
_MOVE = r"""
import os, sys
from app import library_store as ls
language, root = sys.argv[1], sys.argv[2]
store = ls.open_store(language, os.path.join(root, "data", language), os.path.join(root, "User Files", language))
assert store is not None and store.move([store.ids("soon")[-1]], "now") is not None
store.close()
"""

LEVEL_2 = {"SURASURA_SENTENCE_TABLE": "2"}


def _env(root):
    env = cases.child_env(root)
    env.update(LEVEL_2)
    return env


def _counted(root, language, what, **extra):
    env = _env(root)
    env.update(extra)
    p = subprocess.run([sys.executable, "-c", _CHILD, what, language], cwd=cases.REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(line[-1][6:])
    ignored = [ln for ln in p.stdout.splitlines() if ln.startswith("IGNORED ")]
    got["ignored"] = set(json.loads(ignored[-1][8:])) if ignored else None
    got["out"] = p.stdout
    return got


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


def _moved_known(root, language):
    """KnownWord.json moved, as a card Connect writes moves it: the run's known-words read misses (the costly case)."""
    path = os.path.join(root, "User Files", language, "KnownWord.json")
    later = time.time() + 5
    os.utime(path, (later, later))


@pytest.fixture(scope="module", params=["ja", "zh"])
def root(request, tmp_path_factory):
    """RP-2's library Generated once (the store indexed, its names found), *Ignore names* on."""
    language = request.param
    root = str(tmp_path_factory.mktemp(f"one-read-{language}") / "root")
    cases.build(root, f"rp2-{language}")
    _names_switch(root, True)
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)
    return root, language


def test_a_generate_reads_settings_once_opens_the_store_once_and_parses_the_names_once(root):
    # why: every step of the run takes the one copy of the settings it read at its start, and reads the run's own
    # store — the sentence choice no reader of its own; the name tables (the phrase basis, the known-words key) and
    # the names list (the ignore set) parsed once in that store. Chinese has no names: none read.
    root, language = root
    _moved_known(root, language)
    got = _counted(root, language, "generate")
    assert len(got["settings"]) == 1, f"settings.json once a run, at its start: {got['settings']}"
    assert got["import_settings"] >= 1, "the import's own read, told apart (the counter sees reads)"
    assert len(got["opens"]) == 1, f"the token store opened once: {got['opens']}"
    assert got["tables"] == (1 if language == "ja" else 0), "the name tables parsed once"
    assert got["names"] == (1 if language == "ja" else 0), "the names list parsed once"


def test_a_redraw_after_a_move_reads_settings_once_and_opens_the_store_once(root):
    # why: the journey's redraw from the plan (only the order moved) is a run too: one settings read, and the page's
    # known words are looked up in the run's open store, never a reader of its own
    root, language = root
    if language != "ja":
        pytest.skip("the redraw's known-words lookup is the same code for both; the ja library is the one moved")
    _moved_known(root, language)
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)        # the plan of this very known-words file
    p = subprocess.run([sys.executable, "-c", _MOVE, language, root], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]
    got = _counted(root, language, "redraw")
    assert "Redrew the journey" in got["out"], got["out"][-1500:]
    assert len(got["settings"]) == 1, f"settings.json once a redraw: {got['settings']}"
    assert len(got["opens"]) == 1, f"the token store opened once: {got['opens']}"
    assert got["tables"] <= 1 and got["names"] == 0
    # the run's store still open when the page reads it: the sentence choice reads through it and leaves it open (a
    # store it closed found no known word: the page's kanji lost their known examples, ONE-READ 2)
    assert got["page_known"], f"the page found the known words in the run's store: {got['page_known']}"


def test_connect_and_junban_read_the_known_words_with_the_settings_they_hold_and_one_store(root):
    # why: Connect's known words (at each card it writes) and Junban's (each job) hold settings they read at their
    # start: the known-words key and the Ignore names switch take those — no settings.json read of their own — and
    # the names come through the store each holds (Junban's read before it closes it: no fresh connection). The
    # tokenizer's own name tables (a kana line of the ignore set read into words) are the process's, read once every
    # `names.REFRESH` seconds in a window — told apart, not a call's.
    root, language = root
    ja = language == "ja"
    connect = _counted(root, language, "connect")
    assert connect["settings"] == [], f"Connect's known words: its own settings ({connect['settings']})"
    assert connect["opens"] == [] and connect["names"] == (1 if ja else 0)
    junban = _counted(root, language, "junban")
    assert junban["settings"] == [], f"Junban's known words: its own settings ({junban['settings']})"
    assert len(junban["opens"]) == 1, f"Junban's one store: {junban['opens']}"
    assert junban["names"] == (1 if ja else 0)
    assert junban["ignored"] == connect["ignored"], "the same ignore set, names included"
    if ja:
        assert connect["ignored"], "the library's names are in it (Ignore names on)"
        # the switch is the held copy's, not the file's nor the import's: off in the copy, the names leave the set
        # (no read proves only that nothing was read — ONE-READ 2's review)
        for what in ("connect", "junban"):
            off = _counted(root, language, what, ONE_READ_NAMES_OFF="1")
            assert off["settings"] == [] and off["ignored"] < connect["ignored"], (what, len(off["ignored"]))


def test_the_window_previews_known_words_entries_without_reading_the_names(root):
    # why: the window's first Rarity preview decodes KnownWord.json's IGNORED entries ahead of the slider; the names are
    # read at each refresh anyway (the switch and the tables change without the file), so reading them here was thrown
    # away — a fresh connection and a parse
    root, language = root
    got = _counted(root, language, "preview")
    assert got["opens"] == [] and got["names"] == 0, (got["opens"], got["names"])
