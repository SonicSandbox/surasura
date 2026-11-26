"""STORE-KEY 2: the two extra reads STORE-KEY found, gone.

Why: (1) Connect's known-words read (`sentence_corpus.known_sets`, at each card Connect writes) read settings.json a
second time, for its ignore set's *Ignore names* switch (`token_index.ignored_names`), though its caller hands it the
settings it has just loaded. (2) Generate, the indexer and the arrivals view each parsed the library's name-tables blob
twice a run: once to read with them (`names.use_library_tables(store.names_tables())`) and once more for the
known-words key's stamp (`Store.known_suffix`). After it: the handed settings are read, and the tables parsed once a
run are handed to the key.

Real data: RP-2's real libraries (ja + zh, `plan_file_cases`) Generated in a child process as the dashboard runs it,
each run counted in its own process; the known-words slice of tests/Test Resources for the Connect read.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from app import analyzer, settings_manager
from app import sentence_corpus as sc
from app import token_index as ti
from tests import plan_file_cases as cases
from tests.test_store_key import Count, known_file

# The child: name-table parses counted for one run (a Generate, the indexer, the arrivals view), printed as its last
# line — only when the run finished (a Generate that exits with an error prints none, so a zh 0 can't pass for it).
_CHILD = r"""
import json, os, runpy, sys
from app import token_index as ti
n = {"parses": 0}
real_tables, real_read = ti.Store.names_tables, ti.read_names_tables
def tables(self, *a, **k):
    # a parse: every call before STORE-KEY 2; since, only when the store's kept parse is replaced
    before = getattr(self, "_tables_read", None)
    got = real_tables(self, *a, **k)
    if not hasattr(self, "_tables_read") or self._tables_read is not before:
        n["parses"] += 1
    return got
def read(*a, **k):
    n["parses"] += 1
    return real_read(*a, **k)
ti.Store.names_tables, ti.read_names_tables = tables, read
what, language = sys.argv[1], sys.argv[2]
if what == "generate":
    sys.argv = ["analyzer.py", f"--language={language}", "--static", "--no-open"]
    try:
        runpy.run_path(os.path.join("app", "analyzer.py"), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
elif what == "indexer":
    from app import indexer
    sys.argv = ["indexer.py", f"--language={language}"]
    indexer.main()
else:
    from app import analyzer, arrivals, plan_engine
    plan = plan_engine.load(os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE))
    store = ti.open_store(language)
    try:
        arrivals.View.build(language, plan, store)
    finally:
        store.close()
print("COUNT " + json.dumps(n), flush=True)
"""


def _counted(root, what, language):
    p = subprocess.run([sys.executable, "-c", _CHILD, what, language], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    return json.loads(line[-1][6:])


def _moved(root, language):
    """KnownWord.json moved, as a card Connect writes moves it: the next read misses."""
    path = os.path.join(root, "User Files", language, "KnownWord.json")
    later = time.time() + 5
    os.utime(path, (later, later))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_generate_the_indexer_and_arrivals_each_parse_the_name_tables_once_a_run(tmp_path, language):
    # why: each run reads with the tables it applies, and the known-words key's stamp is those tables' own — handed
    # down, never parsed again (ja). Chinese has no name tables: no parse, before as after. Each run misses the
    # known-words cache (the file moved first), so the key is worked out in every one.
    root = str(tmp_path / "root")
    case = f"rp2-{language}"
    cases.build(root, case)
    parses = 1 if language == "ja" else 0
    cases.generate(root, case)                         # the store indexed, its tables computed
    _moved(root, language)
    # Generate: once, in the run's store (the journey page takes the run's known words: no store of its own since
    # STORE-KEY 3)
    assert _counted(root, "generate", language)["parses"] == parses, "Generate: the tables parsed once a run"
    _moved(root, language)
    assert _counted(root, "indexer", language)["parses"] == parses, "the indexer: once"
    _moved(root, language)
    assert _counted(root, "arrivals", language)["parses"] == parses, "the arrivals view: once"


def _names_on(on):
    settings = settings_manager.load_settings()
    settings["logic"]["ignore_names"] = on
    settings_manager.save_settings(settings)
    return settings_manager.load_settings()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_connects_known_read_takes_ignore_names_from_the_settings_it_is_handed(
        tmp_path, monkeypatch, language, ja_resources_dir, zh_resources_dir):
    # why: Connect hands `known_sets` the settings it has just loaded; the ignore set's Ignore names switch is read
    # from them — one settings read a call (the key's own, read fresh: STORE-KEY), not two. Chinese reads none.
    resources = ja_resources_dir if language == "ja" else zh_resources_dir
    monkeypatch.setattr(analyzer, "SANITIZE_JA", language == "ja")
    known_file(language, resources)
    settings = _names_on(True)
    store = ti.open_store(language, path=str(tmp_path / "store.db"))
    try:
        count = Count(monkeypatch, store)
        first = sc.known_sets(language, store, settings)
        reads = 1 if language == "ja" else 0
        assert count.take()[0] == reads, "a miss: the key's read only"
        assert sc.known_sets(language, store, settings)[:2] == first[:2]
        assert count.take()[0] == reads, "a hit: the key's read only"
    finally:
        store.close()


def test_the_handed_settings_decide_ignore_names_and_a_partial_dict_reads_the_file(tmp_path, monkeypatch,
                                                                                   ja_resources_dir):
    # why: the switch the caller loaded is the one its run reads with (on in the handed settings: the names are
    # ignored; off: they count) — and a caller that hands no logic (a few keys only) still gets settings.json's.
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    known_file("ja", ja_resources_dir)
    on = _names_on(True)
    # the library's names as the last index found them (read through the store Connect holds: STORE-KEY 3)
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    store.set_meta("names_words", json.dumps(["スドウ", "ミロナイ"], ensure_ascii=False))
    try:
        assert {"スドウ", "ミロナイ"} <= sc.known_sets("ja", store, on)[2]
        off = dict(on, logic=dict(on["logic"], ignore_names=False))
        assert not {"スドウ", "ミロナイ"} & sc.known_sets("ja", store, off)[2], "the handed switch, off"
        assert {"スドウ", "ミロナイ"} <= sc.known_sets("ja", store, {})[2], "no logic handed: settings.json's"
    finally:
        store.close()


def test_the_kept_parse_follows_the_stored_tables_and_a_bare_reader_reads_them_too(tmp_path):
    # why: the parse is kept only while the stored text is the same — an index that computes new tables (this
    # process's reconcile or another's) is read at the next ask, never the old dict; and a reader made on a connection
    # alone (`Store.__new__`, as surasura-cli's known-words lookup makes one) reads the tables as an opened store does
    first = {"k": {"スドウ": [3, "スドウ", "スドウ", "スドウ"]}, "j": {}, "w": {}, "stamp": "a1"}
    later = {"k": {"ミロナイ": [2, "ミロナイ", "ミロナイ", "ミロナイ"]}, "j": {}, "w": {}, "stamp": "b2"}
    store = ti.open_store("ja", path=str(tmp_path / "store.db"))
    try:
        assert store.names_tables() is None, "none before the first index"
        store.set_meta("names_tables", json.dumps(first, ensure_ascii=False))
        got = store.names_tables()
        assert got == first and store.names_tables() is got, "parsed once while the text is the same"
        store.set_meta("names_tables", json.dumps(later, ensure_ascii=False))
        assert store.names_tables() == later, "new tables stored: read again"
        assert ":b2" in store._known_key("sig"), "the known-words key's stamp: the new tables'"

        reader = ti.Store.__new__(ti.Store)
        reader.conn, reader.language = store.conn, "ja"
        assert reader.names_tables() == later
    finally:
        store.close()
