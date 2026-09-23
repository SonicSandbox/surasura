"""The "nothing changed" skip must never reopen the OTHER language's results.

results/ holds one set of outputs shared by both languages, while each language remembers its own
last run signature in its own token store. Generating in Japanese, then Chinese, then Japanese again
with nothing changed matched the Japanese signature and skipped — reopening the CHINESE results as
the Japanese report. A completed run now stamps results/ with its signature (analyzer.RUN_STAMP_FILE)
and both skips require the stamp to match.

The change had to be delicate: a matching run must still skip exactly as before, a missing stamp
costs one full run and no more, and nothing about the outputs themselves changes.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app import analyzer

JA = "冒険に出かけた。冒険は楽しい。林檎を食べる。"
ZH = "学习很重要。我们一起学习。今天吃苹果。"
LONG_AGO = 946684800   # 2000-01-01: a sentinel mtime, so a rewrite is unmistakable


@pytest.fixture
def env(tmp_path):
    for lang, text in (("ja", JA), ("zh", ZH)):
        uf = tmp_path / "User Files" / lang
        uf.mkdir(parents=True)
        (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
        high = tmp_path / "data" / lang / "HighPriority"
        high.mkdir(parents=True)
        (high / "content.txt").write_text(text, encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    return {"root": tmp_path, "results": results}


def _run(env, language):
    """One analyzer run, exactly as the harness in test_selection_integration.py does it."""
    root, results = env["root"], env["results"]
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda lang=None: str(root / "data" / lang) if lang else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda lang=None: str(root / "User Files" / lang) if lang else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", language, "--min-freq", "1"]):
        analyzer.main()


def _words(env):
    return pd.read_csv(env["results"] / "priority_learning_list.csv")["Word"].tolist()


def _age_csv(env):
    csv = env["results"] / "priority_learning_list.csv"
    os.utime(csv, (LONG_AGO, LONG_AGO))
    return csv


def test_switching_language_and_back_reruns_instead_of_reopening_the_other_language(env):
    _run(env, "ja")
    _run(env, "zh")
    assert "学习" in _words(env)

    _run(env, "ja")          # nothing changed for Japanese — but results/ holds the Chinese run

    words = _words(env)
    assert "冒険" in words, "the Japanese report was served from the Chinese results"
    assert "学习" not in words


def test_an_unchanged_rerun_still_skips(env):
    """The guard for 'delicate': a matching stamp must leave the skip exactly as it was."""
    _run(env, "ja")
    assert analyzer.read_run_stamp(str(env["results"])), "a completed run must stamp results/"
    csv = _age_csv(env)

    _run(env, "ja")

    assert os.stat(csv).st_mtime == LONG_AGO, "an unchanged rerun rewrote the outputs"


def test_a_missing_stamp_costs_one_full_run_then_skipping_resumes(env):
    """Results written before the stamp existed carry none: rerun once, then skip as usual."""
    _run(env, "ja")
    os.remove(env["results"] / analyzer.RUN_STAMP_FILE)
    csv = _age_csv(env)

    _run(env, "ja")
    assert os.stat(csv).st_mtime != LONG_AGO, "no stamp, yet the old outputs were reused"

    _age_csv(env)
    _run(env, "ja")
    assert os.stat(csv).st_mtime == LONG_AGO, "skipping did not resume after the stamped run"


def test_a_run_that_dies_part_way_leaves_no_stamp(env):
    """Half-written outputs must never be taken for a finished run."""
    _run(env, "ja")
    with open(env["root"] / "data" / "ja" / "HighPriority" / "content.txt", "a", encoding="utf-8") as f:
        f.write("新しい冒険が始まる。")                     # a real change, so this run is not skipped

    with patch("app.analyzer.load_simple_list", side_effect=RuntimeError("crashed mid-run")), \
         pytest.raises(RuntimeError):
        _run(env, "ja")

    assert analyzer.read_run_stamp(str(env["results"])) is None


# --- The dashboard's in-process fast path (reopens the report without spawning the analyzer) --- #
def _fast_path_state(stamp):
    """Everything _try_open_existing_report checks, set up to say "nothing changed" — except the
    stamp, which each test chooses. Runs in conftest's sandbox (SURASURA_TEST_ROOT)."""
    from app import token_index
    root = os.environ["SURASURA_TEST_ROOT"]
    for rel, text in (("data/ja/HighPriority/content.txt", JA),
                      ("User Files/ja/KnownWord.json", json.dumps({"words": []}))):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    argv = ["analyzer.py", "--language", "ja", "--static"]
    a = analyzer.parse_analysis_args(argv[1:])
    sig = analyzer.compute_run_signature("ja", analyzer.resolve_found_files("ja", verbose=False), a)
    store = token_index.open_store("ja")
    store.set_meta("last_run_signature", sig)
    store.set_meta("last_render_sig", analyzer.compute_render_signature(a))
    store.close()

    results = os.path.join(root, "results")
    os.makedirs(results, exist_ok=True)
    for name in ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json",
                 "reading_list_static.html"):
        with open(os.path.join(results, name), "w", encoding="utf-8") as f:
            f.write("x")
    analyzer._set_run_stamp(results, sig if stamp == "this run" else stamp)
    return argv


@pytest.mark.parametrize("stamp, reopens", [
    ("this run", True),                        # the ordinary same-language case: unchanged
    ("signature-of-the-chinese-run", False),   # results/ belongs to the other language
    (None, False),                             # results from before the stamp existed
])
def test_dashboard_fast_path_reopens_only_this_runs_results(stamp, reopens):
    from app.main import MasterDashboardApp
    argv = _fast_path_state(stamp)
    dashboard = SimpleNamespace(var_language=MagicMock(get=MagicMock(return_value="ja")),
                                _refresh_band_preview=MagicMock())

    with patch("app.static_html_generator.open_report") as open_report:
        assert MasterDashboardApp._try_open_existing_report(dashboard, argv) is reopens
    assert open_report.called is reopens


# --- The Generate button's state: the same question as the fast path, asked on its own -------- #
def test_the_generate_button_knows_when_the_journey_is_up_to_date():
    """`journey_is_current` is what puts the thin blue border on Generate (False) or the check mark
    beside it (True). It must agree with the fast path exactly: up to date only for THIS run's
    results; out of date once the known words change (an Anki sync) — and so the moment they do."""
    from app.main import journey_is_current
    argv = _fast_path_state("this run")
    assert journey_is_current(argv, "ja") is True

    known = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "ja", "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        f.write(json.dumps({"words": [{"dictForm": "冒険", "knownStatus": "KNOWN"}]}))
    assert journey_is_current(argv, "ja") is False


def test_the_generate_button_is_out_of_date_for_another_runs_results_and_before_any():
    from app.main import journey_is_current
    argv = _fast_path_state("signature-of-the-chinese-run")
    assert journey_is_current(argv, "ja") is False
    for name in ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json"):
        os.remove(os.path.join(os.environ["SURASURA_TEST_ROOT"], "results", name))
    assert journey_is_current(argv, "ja") is False, "never generated: Generate has work to do"


def test_not_opening_the_report_is_not_an_analysis_input():
    """`--no-open` (the quiet Generate) changes nothing a run computes, so it must never change the
    run signature — otherwise every automatic Generate would look like new work to the next one."""
    _fast_path_state("this run")
    found = analyzer.resolve_found_files("ja", verbose=False)
    plain = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    quiet = analyzer.parse_analysis_args(["--language", "ja", "--static", "--no-open"])
    assert quiet.no_open is True and plain.no_open is False
    assert analyzer.compute_run_signature("ja", found, plain) == \
        analyzer.compute_run_signature("ja", found, quiet)
