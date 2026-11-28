"""ONE-READ 5: a Generate on a library with no manifest builds its library store from the tiers' folders, so the
store reads as ready and the run's one handle (ONE-READ 4's span) serves it.

Why (counted on the bench's zh400 library, a learner's Chinese with no master_manifest.json): its store never read as
ready — 8 mode checks a Generate, each a new connection, and no handle to share. The Generate's in-process helper
(`prepare_library` → `maintain`, no `--from-folders`) found no manifest, wrote the empty tables and stopped ("waits for
the Content Manager's helper"): a store file with no `migrated_at`. From then on nothing built it: the window builds
a fresh language from its folders only while there is no store file at all (`chores._fresh`), and the build trigger
only from a manifest (`spawn_build_if_waiting`). So a learner whose first Generate in a language came before the
window's own build (the CLI, hato's tools, a 3.0 before the window's fresh build) sat in JSON mode for good: no order
kept, no arrivals, every Generate's checks asked again. The Generate now applies the window's own rule (no manifest
at all → build from the folders), so a fresh language and one already left empty both come out ready.

What a wrong answer would cost: a manifest the learner (or 2.x) wrote that is damaged or empty set aside by a headless
run (only the Content Manager's open may do that), a manifest's order replaced by the folders', or the list's tiers
moved (the folder IS the tier with no manifest, as before). Real words: the test texts' names (`library`), RP-2's
real libraries (`plan_file_cases`) in a child process for the counts.
"""
import json
import os
import subprocess
import sys

import pytest

from app import analyzer
from app import library_store as ls
from tests import plan_file_cases as cases
from tests.test_library_store_support import LANGUAGES, library, write_manifest
from tests.test_one_read_4 import _CHILD, LEVEL_2


def _tiers(schedule):
    """{tier: sorted physical paths} of a store's schedule (`prepare_library`'s)."""
    return {tier: sorted(e["physical_path"] for e in rows) for tier, rows in schedule.items() if rows}


def _folders(doc):
    return {phase: sorted(e["physical_path"] for e in rows) for phase, rows in doc["schedule"].items() if rows}


# --- the units: prepare_library on each state ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_generate_with_no_manifest_builds_the_store_from_the_folders(language):
    # why: the headless helper stopped at the empty tables, so the store never read as ready (zh400: 8 mode checks a
    # Generate); with no manifest at all the folders are the library, as the window's fresh build reads them
    data_dir, user_files_dir, doc = library(language)
    assert not os.path.exists(ls.manifest_path(user_files_dir))
    out = analyzer.prepare_library(language, data_dir, user_files_dir)
    assert out["schedule"] is not None, "the store's list, not the folders' fallback"
    assert ls.check_mode(language, data_dir) == ("store", None)
    assert _tiers(out["schedule"]) == _folders(doc), "the folder is the tier, as the fallback read it"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_left_empty_by_an_earlier_generate_is_built_at_the_next(language):
    # why: a learner already in the state — an earlier Generate's helper left the empty tables (no `migrated_at`) —
    # was never built afterwards (the window's fresh build skips a store file); the next Generate builds it
    data_dir, user_files_dir, doc = library(language)
    assert ls.maintain(language, data_dir, user_files_dir, export=False) == ls.EXIT_NEEDS_YOU, "the headless wait"
    assert ls.check_mode(language, data_dir) == ("json", "not ready"), "the empty tables, as zh400's"
    out = analyzer.prepare_library(language, data_dir, user_files_dir)
    assert ls.check_mode(language, data_dir) == ("store", None)
    assert _tiers(out["schedule"]) == _folders(doc)
    again = analyzer.prepare_library(language, data_dir, user_files_dir)
    assert again["schedule"] == out["schedule"], "built once: the next run reads the same store"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_build_that_failed_is_never_walked_again_at_each_generate(language, monkeypatch):
    # why (complexity): a failed build is recorded for this version (`_build`'s `failed`), so the next Generate reads
    # the folders' fallback at once — never the whole library walked again, and failed again, at every Generate
    data_dir, user_files_dir, _doc = library(language)

    def broken(*a, **k):
        raise RuntimeError("the build failed")
    with monkeypatch.context() as m:
        m.setattr(ls, "_migrate", broken)
        assert analyzer.prepare_library(language, data_dir, user_files_dir)["schedule"] is None
    assert ls.check_mode(language, data_dir) == ("json", "migration failed")
    walks = []
    real_walk = ls.walk_tree
    monkeypatch.setattr(ls, "walk_tree", lambda *a, **k: walks.append(a) or real_walk(*a, **k))
    assert analyzer.prepare_library(language, data_dir, user_files_dir)["schedule"] is None
    assert walks == [], "no walk of the folders for a build already failed"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("shape", ["damaged", "empty"])
def test_a_manifest_that_cant_be_read_still_waits_for_the_content_manager(language, shape):
    # why: a manifest file there (2.x's, the learner's, an outside tool's) is never set aside nor replaced by the
    # folders on a headless run — only the Content Manager's open does that (`--from-folders` over a file)
    data_dir, user_files_dir, _doc = library(language)
    os.makedirs(user_files_dir, exist_ok=True)
    target = ls.manifest_path(user_files_dir)
    text = '{"schedule": {"PHASE_1_NOW": [' if shape == "damaged" else ""
    with open(target, "w", encoding="utf-8") as f:
        f.write(text)
    out = analyzer.prepare_library(language, data_dir, user_files_dir)
    assert out["schedule"] is None, "no store: the file's fallback, as before"
    assert ls.check_mode(language, data_dir)[0] == "json"
    with open(target, encoding="utf-8") as f:
        assert f.read() == text, "left where it is, as it was"
    assert not os.path.isdir(os.path.join(user_files_dir, ".trash")), "never set aside"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_manifest_is_still_what_the_store_is_built_from(language):
    # why: the folders are the library only when there is no manifest; a manifest's tiers (here a 6+ Months file in
    # the NOW folder) win, never the folder each file sits in
    data_dir, user_files_dir, doc = library(language)
    moved = doc["schedule"]["PHASE_1_NOW"].pop(0)
    doc["schedule"]["PHASE_3_LATER"].append(moved)
    write_manifest(user_files_dir, doc)
    out = analyzer.prepare_library(language, data_dir, user_files_dir)
    assert ls.check_mode(language, data_dir) == ("store", None)
    assert moved["physical_path"] in [e["physical_path"] for e in out["schedule"]["PHASE_3_LATER"]]
    assert moved["physical_path"] not in [e["physical_path"] for e in out["schedule"]["PHASE_1_NOW"]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_language_with_no_content_at_all_gets_an_empty_ready_store(language):
    # why: a fresh language (no tier folder yet, no manifest) reaches the store's empty state, as the window's fresh
    # build does, rather than the empty tables that never read as ready
    data_dir, user_files_dir = os.path.join(os.environ["SURASURA_TEST_ROOT"], "data", language), \
        os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", language)
    out = analyzer.prepare_library(language, data_dir, user_files_dir)
    assert ls.check_mode(language, data_dir) == ("store", None)
    assert not any(out["schedule"].values()), out["schedule"]


# --- the counts: a whole Generate in a child, ja + zh ----------------------------------------------------------- #

def _counted(root, language, **more):
    env = cases.child_env(root)
    env.update(LEVEL_2, **more)
    p = subprocess.run([sys.executable, "-c", _CHILD, "generate", language], cwd=cases.REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    return json.loads(line[-1][6:]), p.stdout


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_generate_with_no_manifest_shares_one_ready_handle(language, tmp_path):
    # why: zh400's Generate made 8 mode checks (each a connection) and kept no handle: the store never read as ready.
    # The first Generate builds it; the next one opens it once for the whole run, as a ja library with a manifest
    root = str(tmp_path / "root")
    case = f"rp2-{language}"
    cases.build(root, case)
    os.remove(os.path.join(root, "User Files", language, "master_manifest.json"))     # the folders are the library
    first, out = _counted(root, language)
    assert "Journey written" in out, out[-1500:]
    assert first["probes"] <= 2, f"the build's run: its look and the span's first open, never one per open: {first}"
    second, out = _counted(root, language, SURASURA_FORCE_RUN="1")
    assert "Journey written" in out, out[-1500:]
    assert [role for role in second["opens"] if role != "helper"] == ["analyzer"], second
    assert second["probes"] <= 1, f"one mode check, the span's first open's: {second}"


# --- item 3: a long Generate's names tables, read once ----------------------------------------------------------- #

# The child: one ja Generate with the names tables' re-look due at once (`names.REFRESH` 0: a lib20k run is past its
# 30 s by the ignore set), counting the token store's connections and the tables read from its file
_TABLES_CHILD = r"""
import json, os, runpy, sqlite3, sys
from app import names, token_index as ti
names.REFRESH = 0.0
n = {"ts_connects": 0, "tables_read": 0}
real_connect, real_read = sqlite3.connect, ti.read_names_tables
def connect(db, *a, **k):
    n["ts_connects"] += "token_store" in str(db)
    return real_connect(db, *a, **k)
def read(language):
    n["tables_read"] += 1
    return real_read(language)
sqlite3.connect, ti.read_names_tables = connect, read
sys.argv = ["analyzer.py", "--language=ja", "--static", "--no-open"]
try:
    runpy.run_path(os.path.join("app", "analyzer.py"), run_name="__main__")
except SystemExit as e:
    if e.code not in (0, None):
        raise
print("COUNT " + json.dumps(n), flush=True)
"""


def test_a_long_generate_reads_its_names_tables_once_through_its_own_store(tmp_path):
    # why: the run handed the tables it read through its open store, unpinned, so 30 s on (lib20k: at the ignore set's
    # kana lines) the next word looked again and opened the token store's file a second time; its one reconcile is
    # done by then, so the tables can't have moved — the run keeps them to its end
    root = str(tmp_path / "root")
    cases.build(root, "rp2-ja")
    cases.generate(root, "rp2-ja", extra_env=LEVEL_2)
    env = cases.child_env(root)
    env.update(LEVEL_2, SURASURA_FORCE_RUN="1")
    p = subprocess.run([sys.executable, "-c", _TABLES_CHILD], cwd=cases.REPO, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("COUNT ")]
    assert p.returncode == 0 and line, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(line[-1][6:])
    assert got == {"ts_connects": 1, "tables_read": 0}, f"the run's one token store, its tables through it: {got}"


def test_the_runs_names_tables_are_let_go_when_it_ends(monkeypatch):
    # why: a pin left behind would keep a later reader in the same process (a batch's next run, a test) on this run's
    # tables for good; let go, they stay the ones applied and are looked for again after `names.REFRESH`, as before
    from app import names
    tables = {"k": {}, "j": {}, "w": {}, "stamp": "one-read-5"}
    with monkeypatch.context() as patched:              # no library store module: the plain run
        patched.setattr(analyzer, "_library_store", lambda: None)

        @analyzer._one_library_handle
        def run():
            names.use_library_tables(tables, pin=True)
            assert names._library["pinned"]
            return 7
        assert run() == 7
        assert not names._library["pinned"] and names.library_tables() is tables

    # the real store span: a run raising inside it

    @analyzer._one_library_handle
    def raising():
        names.use_library_tables(tables, pin=True)
        raise RuntimeError("stopped mid-run")
    with pytest.raises(RuntimeError):
        raising()
    assert not names._library["pinned"], "let go on a raise too"
    assert names.library_tables() is tables
    names._library.update(stamp=("db", "wal"))         # as a look that read them keeps its stamp
    before = dict(names._library)
    names.let_go_library_tables()                       # none pinned: nothing changes, the stamp kept (no re-read)
    assert names._library == before
