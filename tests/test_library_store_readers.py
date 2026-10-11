"""The library store's readers (Library_Store_Spec §7 Phase 2, §10 WP-L6; L2.1 row 2.1.1).

Generate, the readers (the report, the sentence dictionary, Anki matching, Junban) and the indexer take the
library's list from the store once it is ready, and from the file before that, exactly as 2.4 did. The proofs:
the analysis output is byte-identical before and after the move to the store; a library with no usable
manifest stays in JSON mode until its first build; a reader never builds; the journey check decides by the run
signature and records what it hashed; a JSON fallback records nothing; read-only mode still analyses a dropped
file and writes nothing.

Every library is synthetic and lives under the per-test SURASURA_TEST_ROOT (tests/conftest.py); the text is real
Japanese and Chinese from tests/Test Resources/ and samples/, and every proof runs for both languages.
"""

import json
import os
import shutil
import sys
import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, indexer
from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, names, read_doc, write_manifest

HERE = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(HERE, "Test Resources")
SAMPLES = os.path.join(os.path.dirname(HERE), "samples")

# Real text per language: (file name, the resource it is copied from)
TEXTS = {
    "ja": [("H_priority_sample_1.txt", os.path.join(SAMPLES, "ja", "HighPriority", "H_priority_sample_1.txt")),
           ("H_priority_sample_2.srt", os.path.join(SAMPLES, "ja", "HighPriority", "H_priority_sample_2.srt")),
           ("context_test.txt", os.path.join(RESOURCES, "ja", "context_test.txt")),
           ("phrases_sample.srt", os.path.join(RESOURCES, "ja", "phrases_sample.srt"))],
    "zh": [("chinese_text_1.txt", os.path.join(RESOURCES, "zh", "chinese_text_1.txt")),
           ("context_test.txt", os.path.join(RESOURCES, "zh", "context_test.txt")),
           ("traditional_news.txt", os.path.join(RESOURCES, "zh", "traditional_news.txt")),
           ("mixed_script_transcript.txt", os.path.join(RESOURCES, "zh", "mixed_script_transcript.txt"))],
}
KNOWN = {"ja": os.path.join(RESOURCES, "ja", "KnownWord.json"), "zh": os.path.join(RESOURCES, "zh", "KnownWords.json")}


@pytest.fixture
def env():
    """The test root's layout (data/<lang>, User Files/<lang>, results/), so every reader — the analyzer, the
    store's helpers, Junban — resolves the same folders without patching each one."""
    root = os.environ["SURASURA_TEST_ROOT"]
    results = os.path.join(root, "results")
    os.makedirs(results, exist_ok=True)
    return {"root": root, "results": results}


def _dirs(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    return os.path.join(root, "data", language), os.path.join(root, "User Files", language)


def _library(language, manifest=True):
    """Four real texts: two shows and a loose file, with one row whose phase differs from its folder (a show
    in GoalContent scheduled in NOW, as 851 laptop rows are) — the store keeps the phase, as Generate does."""
    data_dir, user_files_dir = _dirs(language)
    show_a, show_b = names(language)[0], names(language)[1]
    (n1, s1), (n2, s2), (n3, s3), (n4, s4) = TEXTS[language]
    rels = [(f"GoalContent/{show_a}/{n1}", s1, "PHASE_1_NOW"),
            (f"GoalContent/{show_a}/{n2}", s2, "PHASE_1_NOW"),
            (f"LowPriority/{show_b}/{n3}", s3, "PHASE_2_SOON"),
            (f"HighPriority/{n4}", s4, "PHASE_3_LATER")]
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for rel, src, phase in rels:
        dst = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
        doc["schedule"][phase].append(ls.make_entry(rel, "Manual Import", None, with_source_type=False))
    os.makedirs(user_files_dir, exist_ok=True)
    shutil.copy(KNOWN[language], os.path.join(user_files_dir, "KnownWord.json"))
    if manifest:
        write_manifest(user_files_dir, doc)
    return data_dir, user_files_dir, doc


def _run(env, language, *extra):
    results = env["results"]
    with patch("app.analyzer.RESULTS_DIR", results), \
         patch("app.analyzer.OUTPUT_CSV", os.path.join(results, "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", os.path.join(results, "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", os.path.join(results, "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", language, "--min-freq", "1", *extra]):
        analyzer.main()


def _outputs(env):
    out = {}
    for name in ("priority_learning_list.csv", "progressive_learning_list.csv"):
        with open(os.path.join(env["results"], name), "rb") as f:
            out[name] = f.read()
    out["signature"] = analyzer.read_run_stamp(env["results"])
    return out


def _clear_results(env):
    shutil.rmtree(env["results"])
    os.makedirs(env["results"])


def _db(language):
    return ls.library_db_path(language, _dirs(language)[0])


def _versions(language):
    store = ls.open_store(language, *_dirs(language))
    with store:
        return store.versions()


def _argv(language, *extra):
    return ["analyzer.py", "--language", language, "--min-freq", "1", *extra]


def _journey(env, language, *extra):
    with patch("app.path_utils.get_user_file", side_effect=lambda p: os.path.join(env["root"], p)):
        return analyzer.journey_is_current(_argv(language, *extra), language)


# --- #1 Byte-identical ------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_generate_output_is_byte_identical_before_and_after_the_move_to_the_store(env, language):
    """I1: for a manifest whose rows resolve, the store hands Generate the same list — same strings, order,
    labels, weights and source_type — so the CSVs and the run signature are byte-identical. 'Before' is the
    JSON path (2.4's), with the store module unavailable; 'after' the first Generate migrates and reads the
    store; a third run reads the store it left (and the copy the helper writes)."""
    _library(language)
    with patch.object(analyzer, "_library_store", lambda: None):
        _run(env, language)
    before = _outputs(env)
    assert not os.path.exists(_db(language)), "the JSON path must leave no store"

    _clear_results(env)
    _run(env, language)
    after = _outputs(env)
    assert os.path.exists(_db(language)), "the first Generate builds the store from the manifest"
    schedule, _v = analyzer.read_library_schedule(language)
    assert schedule is not None, "and the list now comes from the store"
    assert after == before

    assert ls.maintain(language, *_dirs(language)) == ls.EXIT_DONE      # the helper's export
    assert "surasura_library" in read_doc(_dirs(language)[1])
    _clear_results(env)
    _run(env, language)
    assert _outputs(env) == before


def test_the_japanese_snapshot_still_matches_expected_output_through_the_store(env, ja_resources_dir):
    """`expected_output.csv` (the analyzer's snapshot, test_analyzer_snapshot) with its two sample files listed
    in a manifest: the run that migrates to the store and reads it produces the same words, counts and scores."""
    data_dir, user_files_dir = _dirs("ja")
    high = os.path.join(data_dir, "HighPriority")
    shutil.copytree(os.path.join(SAMPLES, "ja", "HighPriority"), high)
    os.makedirs(user_files_dir, exist_ok=True)
    shutil.copy(os.path.join(ja_resources_dir, "KnownWord.json"), os.path.join(user_files_dir, "KnownWord.json"))
    rows = [ls.make_entry(f"HighPriority/{n}", "Disk Sync", None, with_source_type=False) for n in sorted(os.listdir(high))]
    write_manifest(user_files_dir, {"schedule": {"PHASE_1_NOW": rows, "PHASE_2_SOON": [], "PHASE_3_LATER": []}})
    _run(env, "ja")
    assert os.path.exists(_db("ja"))
    df_gen = pd.read_csv(os.path.join(env["results"], "priority_learning_list.csv"))
    df_exp = pd.read_csv(os.path.join(ja_resources_dir, "expected_output.csv"))
    df_gen = df_gen.sort_values(by="Word").reset_index(drop=True)
    df_exp = df_exp.sort_values(by="Word").reset_index(drop=True)
    pd.testing.assert_frame_equal(df_gen, df_exp, check_dtype=False)


# --- #2 No usable manifest; the zero-rows rule -------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_usable_manifest_generate_stays_on_the_folders_until_the_first_build(env, language):
    """No manifest: Generate can't build (the Content Manager's `--from-folders` build does, §6.8), so it scans
    the folders as 2.4 did; after that build the list comes from the store, every language the same."""
    _library(language, manifest=False)
    folder_scan = [p for p, *_ in analyzer.resolve_found_files(language, verbose=False)]
    _run(env, language)
    assert analyzer.read_library_schedule(language) == (None, None), "no store is ready: JSON mode"
    assert ls.check_mode(language, _dirs(language)[0])[0] == "json"

    assert ls.maintain(language, *_dirs(language), from_folders=True) == ls.EXIT_DONE
    schedule, _v = analyzer.read_library_schedule(language)
    assert schedule is not None
    from_store = [p for p, *_ in analyzer.resolve_found_files(language, verbose=False)]
    assert sorted(map(os.path.normpath, from_store)) == sorted(map(os.path.normpath, folder_scan))


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_a_store_or_its_copy_an_empty_list_is_an_empty_run_never_a_folder_scan(env, language):
    """K21: after Graduate (no file moves, L5) every file still sits in its tier folder; 2.4's zero-rows
    fallback would analyse them all. From the store, and from a copy the store wrote, the list is empty. A
    plain manifest with zero rows keeps 2.4's scan."""
    data_dir, user_files_dir, _doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        store.set_tier([i for t in ls.ANALYSED for i in store.ids(t)], "graduated")
    assert analyzer.resolve_found_files(language, verbose=False) == []

    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    copy = read_doc(user_files_dir)
    assert all(copy["schedule"][p] == [] for p in ls.PHASES) and "surasura_library" in copy
    with patch.object(analyzer, "read_library_schedule", lambda *a, **k: (None, None)):   # read-only: the copy
        assert analyzer.resolve_found_files(language, verbose=False) == []
    write_manifest(user_files_dir, {"schedule": {p: [] for p in ls.PHASES}})
    with patch.object(analyzer, "read_library_schedule", lambda *a, **k: (None, None)):
        assert len(analyzer.resolve_found_files(language, verbose=False)) == 4, "a plain manifest: 2.4's scan"


# --- #5 Readers never build --------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_readers_never_build_a_store_and_read_the_file_meanwhile(env, language):
    """A usable manifest and no store: every reader (they all resolve through `resolve_found_files`, and the
    indexer) takes the JSON path and leaves no database behind — only Generate, the helper and `register` build."""
    _library(language)
    listed = analyzer.resolve_found_files(language, verbose=False)
    assert [os.path.basename(p) for p, *_ in listed] == [n for n, _s in TEXTS[language][:3]] + [TEXTS[language][3][0]]
    assert sorted(map(os.path.normpath, indexer._content_files(_dirs(language)[0], language))) == sorted(
        os.path.normpath(p) for p, *_ in listed)
    assert analyzer.read_library_schedule(language) == (None, None)
    assert not os.path.exists(_db(language))
    assert not os.path.exists(os.path.dirname(_db(language))) or not any(
        n.startswith(f"library_{language}_") for n in os.listdir(os.path.dirname(_db(language))))


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_indexer_reads_the_stores_list_so_a_graduated_file_is_never_tokenized(env, language):
    """K2: Graduate leaves the file in its tier folder. The walk would tokenize it on every cycle (and the
    analyzer's reconcile would drop it again); with a store the indexer's list is the analyzer's."""
    data_dir, user_files_dir, doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        gone = store.ids("now")[0]
        gone_path = store.item(gone)["rel_path"]
        store.set_tier([gone], "graduated")
    files = indexer._content_files(data_dir, language)
    assert files == [p for p, *_ in analyzer.resolve_found_files(language, verbose=False)]
    assert os.path.join(data_dir, *gone_path.split("/")) not in files
    assert os.path.exists(os.path.join(data_dir, *gone_path.split("/"))), "the store never moves a file"


# --- #6 The journey check, both ways ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_journey_check_decides_by_the_signature_not_by_the_versions(env, language):
    """Versions unchanged but a setting changed → not current. A move and its reverse (versions moved, the
    signature equal) → current, and the store records the order_version it hashed as analysed, so Junban's
    "journey pending" clears without a Generate."""
    data_dir, user_files_dir, _doc = _library(language)
    _run(env, language)
    v0 = _versions(language)
    assert v0["analysed_order_version"] == v0["order_version"], "the Generate recorded what it read"
    assert _journey(env, language) is True
    assert _journey(env, language, "--min-freq", "2") is False, "a setting changed, the versions didn't"

    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        first, second = store.ids("now")[:2]
        store.move([first], "now", after_id=second)
        store.move([first], "now", before_id=second)
        assert store.journey_pending()
    v1 = _versions(language)
    assert v1["order_version"] == v0["order_version"] + 2
    assert _journey(env, language) is True, "the same list: nothing for Generate to do"
    v2 = _versions(language)
    assert v2["analysed_order_version"] == v1["order_version"]

    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        store.move([first], "now", after_id=second)        # a real change: not current, nothing recorded
    assert _journey(env, language) is False
    assert _versions(language)["analysed_order_version"] == v1["order_version"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_journey_check_takes_in_a_file_dropped_into_a_folder(env, language):
    """The check syncs the disk first (A10's dashboard half): a hato drop turns the ✓ off before Generate."""
    data_dir, _uf, _doc = _library(language)
    _run(env, language)
    assert _journey(env, language) is True
    drop = os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), f"{names(language)[5]}.txt")
    os.makedirs(os.path.dirname(drop), exist_ok=True)
    shutil.copy(TEXTS[language][0][1], drop)
    assert _journey(env, language) is False
    schedule, _v = analyzer.read_library_schedule(language)
    assert schedule["PHASE_1_NOW"][0]["physical_path"].endswith(os.path.basename(drop)), "the top of NOW"


# --- #7 A JSON fallback ------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_database_error_mid_generate_falls_back_to_the_file_and_records_nothing(env, language):
    """The store fails while Generate reads it: the run completes from the file (the copy), and
    `analysed_order_version` is unchanged — what the run read is not what `order_version` names."""
    data_dir, user_files_dir, _doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        store.move([store.ids("now")[0]], "soon")
    before = _versions(language)
    assert before["analysed_order_version"] < before["order_version"]

    def broken(self, with_versions=False):
        raise sqlite3.DatabaseError("disk I/O error")
    with patch.object(ls.Store, "schedule", broken):
        _run(env, language)
    assert os.path.exists(os.path.join(env["results"], "priority_learning_list.csv")), "the run completed"
    after = _versions(language)
    assert after["analysed_order_version"] == before["analysed_order_version"]


# --- #8 Read-only mode -------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_read_only_mode_analyses_a_dropped_file_and_writes_nothing(env, language):
    """A damaged store (read-only until Repair): Generate reads the copy (no folder fallback), adds a file
    dropped into a show's folder in memory — after the show's last row, §6.10 rule 3 — and writes nothing: not
    the copy, not the store."""
    data_dir, user_files_dir, _doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = _db(language)
    ls.mark_damaged(db, "test: quick_check found damage")
    assert ls.check_mode(language, data_dir)[0] == "read-only"
    show = names(language)[1]
    dropped = os.path.join(data_dir, "LowPriority", show, f"{names(language)[6]}.txt")
    shutil.copy(TEXTS[language][1][1], dropped)
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        copy_bytes = f.read()
    db_stat = os.stat(db).st_mtime_ns

    _run(env, language)
    with open(os.path.join(env["results"], "file_statistics.txt"), encoding="utf-8") as f:
        stats = f.read()
    assert os.path.basename(dropped) in stats, "the dropped file was analysed"
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        assert f.read() == copy_bytes, "nothing writes the copy in read-only mode"
    assert os.stat(db).st_mtime_ns == db_stat

    schedule = ls.read_only_schedule(language, data_dir, user_files_dir)
    soon = [e["physical_path"] for e in schedule["PHASE_2_SOON"]]
    assert soon[-1].endswith(os.path.basename(dropped)), "after the show's last row"


@pytest.mark.parametrize("language", LANGUAGES)
def test_generate_takes_in_a_file_dropped_since_the_last_run(env, language):
    """The rule in plain words: a file dropped into the hato folder after the last run is in Generate's list
    on the next run. Generate's own schedule (prepare_library) syncs the disk first; without that sync the
    dropped file is missing from the schedule until some later step notices it."""
    data_dir, user_files_dir, _doc = _library(language)
    _run(env, language)
    drop = os.path.join(data_dir, *ls.HATO_FOLDER.split("/"), f"{names(language)[5]}.txt")
    os.makedirs(os.path.dirname(drop), exist_ok=True)
    shutil.copy(TEXTS[language][0][1], drop)
    out = analyzer.prepare_library(language, data_dir=data_dir, user_files_dir=user_files_dir)
    top = out["schedule"]["PHASE_1_NOW"]
    assert top and top[0]["physical_path"].endswith(os.path.basename(drop)), "the dropped file is the top of NOW"


@pytest.mark.parametrize("language", LANGUAGES)
def test_generate_starts_the_store_helper_exactly_when_an_export_is_due(env, store_helper_spawns, language):
    """Generate starts the store's helper only when the copy is behind the store: after a fresh export nothing
    spawns, and once a row moves the export is due and exactly one spawn is recorded."""
    data_dir, user_files_dir, _doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        assert not store.export_due(), "precondition: the copy was just exported"
    store_helper_spawns.clear()
    analyzer.prepare_library(language, data_dir=data_dir, user_files_dir=user_files_dir)
    assert store_helper_spawns == [], "no export due, no helper"
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        store.move([store.ids("now")[0]], "soon")
    analyzer.prepare_library(language, data_dir=data_dir, user_files_dir=user_files_dir)
    assert store_helper_spawns == [(language,)], "an export is due, so the helper starts once"


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_a_read_only_store_adds_untracked_files_and_json_mode_gets_no_schedule(env, capsys, language):
    """In JSON mode (no store) Generate gets no schedule and prints no read-only note, even with an untracked
    file in the library; only a read-only store (damaged, read-only until Repair) reads the copy with untracked
    files added and says so."""
    data_dir, user_files_dir, _doc = _library(language)
    untracked = os.path.join(data_dir, "HighPriority", f"{names(language)[6]}.txt")
    shutil.copy(TEXTS[language][0][1], untracked)
    with patch.object(ls, "maintain", lambda *a, **k: ls.EXIT_NOTHING):
        out = analyzer.prepare_library(language, data_dir=data_dir, user_files_dir=user_files_dir)
    assert out["schedule"] is None, "JSON mode: the file, as 2.4"
    assert "read-only" not in capsys.readouterr().out
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test")
    # A second file dropped after the maintain above, so it is untracked when read-only mode starts.
    late = os.path.join(data_dir, "HighPriority", f"{names(language)[6]}_late.txt")
    shutil.copy(TEXTS[language][0][1], late)
    out = analyzer.prepare_library(language, data_dir=data_dir, user_files_dir=user_files_dir)
    assert out["schedule"] is not None, "read-only mode: the copy with untracked files added"
    paths = [e["physical_path"] for phase in out["schedule"].values() for e in phase]
    assert any(p.endswith(os.path.basename(late)) for p in paths), "the untracked file is in the schedule"
    assert "read-only" in capsys.readouterr().out


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_journey_check_starts_the_build_helper_when_a_manifest_waits_with_no_store(env, language, store_helper_spawns, monkeypatch):
    """A library with a manifest and no store yet: the journey check hands the build to the helper, so the next
    run finds a store. The once-a-minute throttle is cleared first so an earlier test's spawn cannot hide it."""
    _library(language)
    monkeypatch.setattr(ls, "_build_spawned", {})
    _journey(env, language)
    assert store_helper_spawns == [(language,)], "one build helper for the language, nothing more"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_ready_store_is_used_even_when_its_copy_file_is_gone(env, language):
    """A library the store has built stays on the store's list when master_manifest.json is removed: the
    store, not the copy file, decides what is analysed once it is ready. Without the copy, a reader that
    skipped the store would fall to a scan that finds nothing and analyse an empty run."""
    data_dir, user_files_dir, _doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    # Graduate one file in the store only: the folders still hold all four, so a folder scan would return 4
    # and the store's list returns 3. The test then tells a store-driven read from a fallback scan.
    before = [p for p, *_ in analyzer.resolve_found_files(language, verbose=False)]
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        store.set_tier([[i for t in ls.ANALYSED for i in store.ids(t)][0]], "graduated")
    os.remove(ls.manifest_path(user_files_dir))
    listed = [p for p, *_ in analyzer.resolve_found_files(language, verbose=False)]
    assert len(listed) == 3, "the store's list, no copy file, the graduated file left out"
    assert set(before) - set(listed), "the graduated file is the one that left the list"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_damaged_store_in_read_only_mode_still_keeps_a_graduated_file_out_of_the_indexer(env, language):
    """A damaged store is read-only until Repair. Read-only mode must still take the store's list: a file Graduate
    left in its tier folder is no longer analysed, so the indexer must not fall back to the folder walk and index it."""
    data_dir, user_files_dir, _doc = _library(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        gone = store.ids("now")[0]
        gone_path = store.item(gone)["rel_path"]
        store.set_tier([gone], "graduated")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE  # the copy records the graduation
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test")
    assert ls.check_mode(language, data_dir)[0] == "read-only"
    files = indexer._content_files(data_dir, language)
    gone_file = os.path.normpath(os.path.join(data_dir, *gone_path.split("/")))
    # the indexer's list is the analyzer's list: non-empty, equal, and the graduated file is out of it
    assert files, "the surviving files are still indexed (an empty list would pass the check below)"
    assert files == [p for p, *_ in analyzer.resolve_found_files(language, verbose=False)]
    assert gone_file not in [os.path.normpath(p) for p in files]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_indexer_asks_for_its_list_with_its_language_so_a_store_library_is_read(env, monkeypatch, language):
    """The indexer passes its language to `_content_files`: with a library store that is the analyzer's list (K2).
    Called with the data path alone, the store is never consulted and the folder walk runs instead."""
    seen = []

    def stop_after_the_call(*args, **kwargs):
        seen.append((args, kwargs))
        raise SystemExit(0)

    monkeypatch.setattr(indexer, "_content_files", stop_after_the_call)
    monkeypatch.setattr(sys, "argv", ["indexer.py", "--language", language])
    with pytest.raises(SystemExit):
        indexer.main()
    args, kwargs = seen[0]
    assert len(seen) == 1 and language in args[1:] + tuple(kwargs.values())
