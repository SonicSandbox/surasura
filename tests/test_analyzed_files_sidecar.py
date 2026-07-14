"""Tests for the word_stats.json sidecars (analyzed_files.json + file_words.json).

Why these exist: on a large library, parsing the multi-hundred-MB word_stats.json on the Tk thread
froze the Content Manager. The analyzer now emits two tiny derived files; the Content Manager reads
those and falls back to word_stats.json only when they're absent. These tests pin BOTH the writer
(sidecars are byte-for-byte consistent with word_stats.json's semantics) and the readers (sidecar-first
with a correct fallback), using real Japanese text — never dummy ASCII.
"""
import os
import sys
import json
import shutil
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app.analyzer as analyzer
from app.content_importer_gui import ContentImporterApp


# --- Fixtures ------------------------------------------------------------------------------------ #
@pytest.fixture
def analyzer_env():
    """A temp User Data / User Files / Results layout with the analyzer's module paths pointed at it.
    (conftest restores analyzer module state after each test.)"""
    temp_dir = tempfile.mkdtemp()
    data_dir = os.path.join(temp_dir, "User Data", "data", "ja")
    for tier in ("HighPriority", "LowPriority", "GoalContent"):
        os.makedirs(os.path.join(data_dir, tier))
    user_files_dir = os.path.join(temp_dir, "User Files", "ja")
    os.makedirs(user_files_dir)
    with open(os.path.join(user_files_dir, "KnownWord.json"), 'w', encoding='utf-8') as f:
        json.dump({}, f)
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        with open(os.path.join(user_files_dir, name), 'w', encoding='utf-8') as f:
            f.write("")
    results_dir = os.path.join(temp_dir, "Results")
    os.makedirs(results_dir)

    analyzer.get_data_path = lambda lang: data_dir
    analyzer.get_user_files_path = lambda lang: user_files_dir
    analyzer.RESULTS_DIR = results_dir
    analyzer.OUTPUT_CSV = os.path.join(results_dir, "priority_learning_list.csv")
    analyzer.OUTPUT_STATS = os.path.join(results_dir, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results_dir, "progressive_learning_list.csv")

    yield {"data_dir": data_dir, "user_files_dir": user_files_dir, "results_dir": results_dir}
    shutil.rmtree(temp_dir, ignore_errors=True)


def _bare_cm(data_root):
    """A ContentImporterApp with just enough state to exercise the sidecar readers — no Tk."""
    app = ContentImporterApp.__new__(ContentImporterApp)
    app.data_root = data_root
    app.language = "ja"
    app.analyzed_filenames = set()
    app._last_stats_mtime = 0
    app._last_stats_size = 0
    app._last_stats_source = None
    return app


def _run_analyzer(files):
    """Write {relative_path: text} into the tier folders, then run one analysis."""
    sys.argv = ["analyzer.py", "--context-min", "0"]
    analyzer.main()


# --- Writer: sidecars match word_stats.json ------------------------------------------------------ #
def test_analyzer_writes_both_sidecars(analyzer_env):
    data_dir, results_dir = analyzer_env["data_dir"], analyzer_env["results_dir"]
    # Two real Japanese files sharing some vocabulary, so 'sources' spans multiple files.
    with open(os.path.join(data_dir, "HighPriority", "school.txt"), 'w', encoding='utf-8') as f:
        f.write("昨日は学校へ行きました。\n新しい学校が好きです。\n学校の先生と話した。\n")
    with open(os.path.join(data_dir, "LowPriority", "friend.txt"), 'w', encoding='utf-8') as f:
        f.write("友達と学校で会った。\n友達の家に行った。\n")

    _run_analyzer(None)

    ws_path = os.path.join(results_dir, "word_stats.json")
    af_path = os.path.join(results_dir, "analyzed_files.json")
    fw_path = os.path.join(results_dir, "file_words.json")
    assert os.path.exists(ws_path) and os.path.exists(af_path) and os.path.exists(fw_path)

    with open(ws_path, encoding='utf-8') as f:
        stats = json.load(f)
    with open(af_path, encoding='utf-8') as f:
        analyzed = json.load(f)
    with open(fw_path, encoding='utf-8') as f:
        file_words = json.load(f)

    # analyzed_files.json == sorted union of every word's 'sources' in word_stats.json.
    expected_analyzed = sorted({s for d in stats.values() for s in d.get("sources", [])})
    assert analyzed == expected_analyzed
    assert "school.txt" in analyzed and "friend.txt" in analyzed

    # file_words.json == reverse index (basename -> lemmas), same lemma extraction the reader uses.
    expected_fw = {}
    for key, d in stats.items():
        for s in d.get("sources", []):
            expected_fw.setdefault(s, set()).add(key.split("|")[0])
    assert set(file_words) == set(expected_fw)
    for src, lemmas in file_words.items():
        assert set(lemmas) == expected_fw[src]


def test_word_stats_lean_by_default_full_with_debug_flag(analyzer_env, monkeypatch):
    """word_stats.json drops the heavy, unread selection inputs by default; SURASURA_DEBUG_WORD_STATS
    brings them back. The CHOSEN sentences (final_context_N) and all stats are kept in both modes."""
    data_dir, results_dir = analyzer_env["data_dir"], analyzer_env["results_dir"]
    with open(os.path.join(data_dir, "HighPriority", "school.txt"), 'w', encoding='utf-8') as f:
        f.write("昨日は学校へ行きました。\n新しい学校が好きです。\n学校の先生と話した。\n古い学校を見た。\n")

    # --- Lean (default) ---
    monkeypatch.delenv("SURASURA_DEBUG_WORD_STATS", raising=False)
    _run_analyzer(None)
    ws = os.path.join(results_dir, "word_stats.json")
    with open(ws, encoding='utf-8') as f:
        lean = json.load(f)
    entry = next(v for k, v in lean.items() if "学校" in k)
    assert "candidate_contexts" not in entry, "raw candidate pool must be dropped by default"
    assert "first_context" not in entry, "raw first_context must be dropped by default"
    assert "sources" in entry and "score" in entry, "stats must be kept"
    assert any(k.startswith("final_context_") for k in entry), "chosen sentences must be kept"
    lean_size = os.path.getsize(ws)

    # --- Full dump (flag) --- toggling the flag changes the run signature, so it re-runs (no skip).
    monkeypatch.setenv("SURASURA_DEBUG_WORD_STATS", "1")
    _run_analyzer(None)
    with open(ws, encoding='utf-8') as f:
        full = json.load(f)
    entry2 = next(v for k, v in full.items() if "学校" in k)
    assert "candidate_contexts" in entry2, "debug flag must restore the raw candidate pool"
    assert os.path.getsize(ws) > lean_size, "full dump should be larger than lean"


def test_empty_library_writes_empty_sidecars(analyzer_env):
    """No content -> the run still emits well-formed, empty sidecars (readers treat as 'nothing analyzed')."""
    _run_analyzer(None)
    results_dir = analyzer_env["results_dir"]
    af = os.path.join(results_dir, "analyzed_files.json")
    fw = os.path.join(results_dir, "file_words.json")
    # word_stats.json is only written when there ARE stats; when it exists, the sidecars must too.
    if os.path.exists(os.path.join(results_dir, "word_stats.json")):
        assert os.path.exists(af) and os.path.exists(fw)
        with open(af, encoding='utf-8') as f:
            assert json.load(f) == []
        with open(fw, encoding='utf-8') as f:
            assert json.load(f) == {}


# --- Readers: sidecar-first with word_stats fallback --------------------------------------------- #
def _make_results(results_dir, word_stats):
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "word_stats.json"), 'w', encoding='utf-8') as f:
        json.dump(word_stats, f, ensure_ascii=False)


def test_analyzed_reader_prefers_sidecar_and_falls_back(tmp_path):
    root = tmp_path
    data_root = os.path.join(root, "data", "ja")
    os.makedirs(data_root)
    results_dir = os.path.join(root, "results")
    word_stats = {
        "学校|ガッコウ": {"sources": ["school.txt", "friend.txt"]},
        "友達|トモダチ": {"sources": ["friend.txt"]},
    }
    _make_results(results_dir, word_stats)

    # No sidecar yet -> fallback derives the set from word_stats.json.
    app = _bare_cm(data_root)
    app._load_analyzed_filenames()
    assert app.analyzed_filenames == {"school.txt", "friend.txt"}
    assert app._last_stats_source.endswith("word_stats.json")

    # Now add the sidecar with a DIFFERENT set -> reader must switch to it (proves preference).
    with open(os.path.join(results_dir, "analyzed_files.json"), 'w', encoding='utf-8') as f:
        json.dump(["only_sidecar.txt"], f)
    app2 = _bare_cm(data_root)
    app2._load_analyzed_filenames()
    assert app2.analyzed_filenames == {"only_sidecar.txt"}
    assert app2._last_stats_source.endswith("analyzed_files.json")


def test_graduate_index_matches_between_sidecar_and_fallback(tmp_path):
    root = tmp_path
    data_root = os.path.join(root, "data", "ja")
    os.makedirs(data_root)
    results_dir = os.path.join(root, "results")
    word_stats = {
        "学校|ガッコウ": {"sources": ["school.txt", "friend.txt"]},
        "先生|センセイ": {"sources": ["school.txt"]},
        "友達|トモダチ": {"sources": ["friend.txt"]},
    }
    _make_results(results_dir, word_stats)

    # Fallback path (no sidecar): reverse index built from word_stats.json.
    fallback = _bare_cm(data_root)._load_graduate_index()
    assert set(fallback["school.txt"]) == {"学校", "先生"}
    assert set(fallback["friend.txt"]) == {"学校", "友達"}

    # Write the real file_words.json sidecar and confirm the reader returns an equivalent index.
    with open(os.path.join(results_dir, "file_words.json"), 'w', encoding='utf-8') as f:
        json.dump({"school.txt": ["学校", "先生"], "friend.txt": ["学校", "友達"]}, f, ensure_ascii=False)
    from_sidecar = _bare_cm(data_root)._load_graduate_index()
    assert {k: set(v) for k, v in from_sidecar.items()} == {k: set(v) for k, v in fallback.items()}


def test_graduate_index_empty_when_no_results(tmp_path):
    data_root = os.path.join(tmp_path, "data", "ja")
    os.makedirs(data_root)
    assert _bare_cm(data_root)._load_graduate_index() == {}


# --- Run-signature parity: the dashboard's in-process recompute must equal what a real run stores. #
# This is the safety net for the no-change Generate short-circuit: the GUI decides whether to skip the
# analyzer subprocess by recomputing the signature via the SAME shared functions the analyzer uses.
# If main() ever computed found_files/args/signature differently, this would fail.
def test_stored_run_signature_matches_shared_recompute(analyzer_env):
    from app import token_index
    data_dir = analyzer_env["data_dir"]
    with open(os.path.join(data_dir, "HighPriority", "school.txt"), 'w', encoding='utf-8') as f:
        f.write("昨日は学校へ行きました。\n新しい学校が好きです。\n学校の先生と話した。\n")
    with open(os.path.join(data_dir, "LowPriority", "friend.txt"), 'w', encoding='utf-8') as f:
        f.write("友達と学校で会った。\n友達の家に行った。\n")

    argv = ["analyzer.py", "--language", "ja", "--max-contexts", "4", "--context-min", "0"]
    sys.argv = argv
    analyzer.main()

    # Recompute exactly as the dashboard's _try_open_existing_report does.
    a = analyzer.parse_analysis_args(argv[1:])
    found = analyzer.resolve_found_files("ja", verbose=False)
    sig = analyzer.compute_run_signature("ja", found, a)

    store = token_index.open_store("ja")
    stored = store.get_meta("last_run_signature")
    store.close()

    assert sig, "signature should be computable"
    assert stored == sig, "dashboard-side recomputed signature must equal what the analyzer stored"

    # And a genuine change (edit a content file) must break the match, so the GUI won't wrongly skip.
    with open(os.path.join(data_dir, "HighPriority", "school.txt"), 'a', encoding='utf-8') as f:
        f.write("学校はとても新しいです。\n")
    changed = analyzer.compute_run_signature("ja", analyzer.resolve_found_files("ja", verbose=False), a)
    assert changed != stored, "a content change must change the signature"


# --- Robustness: a stale sidecar (older than word_stats) must be ignored ------------------------- #
def test_reader_ignores_stale_sidecar(tmp_path):
    data_root = os.path.join(tmp_path, "data", "ja")
    os.makedirs(data_root)
    results_dir = os.path.join(tmp_path, "results")
    os.makedirs(results_dir)
    # A leftover sidecar with WRONG content, then a fresher word_stats.json = the source of truth.
    af = os.path.join(results_dir, "analyzed_files.json")
    with open(af, 'w', encoding='utf-8') as f:
        json.dump(["stale.txt"], f)
    _make_results(results_dir, {"学校|ガッコウ": {"sources": ["fresh.txt"]}})
    ws = os.path.join(results_dir, "word_stats.json")
    now = os.path.getmtime(ws)
    os.utime(af, (now - 100, now - 100))    # sidecar strictly older -> must be ignored

    app = _bare_cm(data_root)
    app._load_analyzed_filenames()
    assert app.analyzed_filenames == {"fresh.txt"}

    # Once the sidecar is refreshed to be newer, it wins again (fast path restored).
    with open(af, 'w', encoding='utf-8') as f:
        json.dump(["fresh.txt", "extra.txt"], f)
    os.utime(af, (now + 100, now + 100))
    app2 = _bare_cm(data_root)
    app2._load_analyzed_filenames()
    assert app2.analyzed_filenames == {"fresh.txt", "extra.txt"}


# --- Backfill (skip-path safety net) ------------------------------------------------------------- #
def test_backfill_creates_sidecars_and_is_idempotent(tmp_path):
    results_dir = os.path.join(tmp_path, "results")
    os.makedirs(results_dir)
    _make_results(results_dir, {
        "学校|ガッコウ": {"sources": ["a.txt", "b.txt"]},
        "友達|トモダチ": {"sources": ["b.txt"]},
    })
    af = os.path.join(results_dir, "analyzed_files.json")
    fw = os.path.join(results_dir, "file_words.json")
    assert not os.path.exists(af) and not os.path.exists(fw)

    analyzer._backfill_sidecars(results_dir)
    assert os.path.exists(af) and os.path.exists(fw)
    with open(af, encoding='utf-8') as f:
        assert set(json.load(f)) == {"a.txt", "b.txt"}
    with open(fw, encoding='utf-8') as f:
        assert set(json.load(f)["b.txt"]) == {"学校", "友達"}

    # Fresh sidecars already present -> second backfill is a no-op (no rewrite).
    m1 = os.path.getmtime(af)
    analyzer._backfill_sidecars(results_dir)
    assert os.path.getmtime(af) == m1


def test_backfill_rebuilds_when_stale(tmp_path):
    results_dir = os.path.join(tmp_path, "results")
    os.makedirs(results_dir)
    with open(os.path.join(results_dir, "analyzed_files.json"), 'w', encoding='utf-8') as f:
        json.dump(["old.txt"], f)
    with open(os.path.join(results_dir, "file_words.json"), 'w', encoding='utf-8') as f:
        json.dump({"old.txt": ["旧"]}, f)
    _make_results(results_dir, {"新聞|シンブン": {"sources": ["new.txt"]}})
    ws = os.path.join(results_dir, "word_stats.json")
    now = os.path.getmtime(ws)
    for name in ("analyzed_files.json", "file_words.json"):
        os.utime(os.path.join(results_dir, name), (now - 100, now - 100))

    analyzer._backfill_sidecars(results_dir)
    with open(os.path.join(results_dir, "analyzed_files.json"), encoding='utf-8') as f:
        assert set(json.load(f)) == {"new.txt"}
