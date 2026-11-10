"""JS-1's quiet re-render, held at the quiet run itself (Sonic 2026-10-23: with *Keep studying watched episodes* on, a
mark or its Undo re-renders the journey at once, a quiet run with no re-analysis — "This is a tricky one to double test
that it doesn't conflict with other decisions"). One scenario per decision the quiet run touches; the window's trigger
(shell after_commit -> Replan.stone_marked -> keeper.changed("stone"), JourneyKeeper._is_pending's report half) is
Mado's and is tested with it. Here the quiet run is what that trigger starts: a Generate the analyzer answers from its
reuse path (the analysis current, the render signature moved by the stone -> a re-render only).

  D2  the W-1 / W-1b counting rule: after a mark and its quiet run the counts equal a full Generate's from scratch at
      the same state; a Finished show stays out of the journey data; a set-aside mark (the option off) is a Generate.
  D3  *Keep studying* changes no counts: the quiet run leaves results/*.csv byte for byte; only the stones differ.
  D4  (the analysis half) after the quiet run `journey_is_current` and `_nothing_changed` both say current: a second
      press reopens the report. Before it, the analysis says current and the report half does not — the one question
      the window's trigger must ask.
  D5  the symmetric Undo: mark -> quiet run -> Undo -> quiet run is the report, the CSVs and the recorded render
      signature exactly as before the mark.
  D6  S19, update only what changed: the quiet run tokenizes nothing (a spy on fugashi and jieba in every process the
      Generate starts: 0 calls), and the run signature, the run stamp and the CSVs' modification times stay put.

Each was proved able to fail by breaking its condition once by hand in app/ (then restored; JS1-tests.md lists each):
  D2  the reuse path re-rendering with no marks (`marks=[]`): the quiet report lacks its stone, unlike the full run's;
      `Store.watched_marks` reading Finished too: a Finished episode's stone enters the journey; `_keep_watched` read
      inverted: an option-off mark leaves the analysis current (the quiet path).
  D3  `_keep_watched` read inverted: with the option on the watched episode is set aside — a re-analysis, CSVs moved.
  D4  the reuse path's re-render recording "" as its render signature: the report half never says current again.
  D5  a status Undo writing the marked value back: the stone stays, the report half has nothing to redraw.
  D6  the reuse gate turned off (`and not True`): the quiet run re-analyses; one fugashi / jieba call added to the
      reuse path: the spy counts it (ja and zh).

Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT, with real text from the bundled samples (the library
builders of tests/test_journey_stones.py). Never a real %APPDATA%: child_env moves both under the test root.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

import pytest

from app import analyzer
from app.cli import verbs
from tests.plan_file_cases import child_env
from tests.test_journey_stones import REPO, REUSED, _files, _library, _report, _settings, _stones, _words
from tests.test_library_store_support import LANGUAGES

ARGV = ["analyzer.py", "--static", "--no-open", "--min-freq", "1"]
UP_TO_DATE = "Report already up to date"
RE_RENDER = "Re-rendering report"

# Installed in every Python process a spied Generate starts (PYTHONPATH's sitecustomize): counts each call into fugashi's
# tagger and jieba's cutters — every tokenization ends in one of them — and writes the count at exit, one line a process
SPY = r'''
import atexit, json, os, sys
_out = os.environ.get("JS1_TOKENIZER_SPY")
if _out:
    CALLS = [0]

    def _counted(fn):
        def spy(*a, **k):
            CALLS[0] += 1
            return fn(*a, **k)
        return spy

    try:
        import fugashi
        _Real = fugashi.Tagger

        class Tagger:
            def __init__(self, *a, **k):
                self._t = _Real(*a, **k)

            def __call__(self, *a, **k):
                CALLS[0] += 1
                return self._t(*a, **k)

            def parseToNodeList(self, *a, **k):
                CALLS[0] += 1
                return self._t.parseToNodeList(*a, **k)

            def __getattr__(self, name):
                return getattr(self._t, name)

        fugashi.Tagger = Tagger
    except Exception:
        pass
    try:
        import jieba, jieba.posseg
        for _mod, _names in ((jieba, ("cut", "lcut", "cut_for_search", "lcut_for_search", "tokenize")),
                             (jieba.posseg, ("cut", "lcut"))):
            for _name in _names:
                if hasattr(_mod, _name):
                    setattr(_mod, _name, _counted(getattr(_mod, _name)))
    except Exception:
        pass

    @atexit.register
    def _write():
        with open(_out, "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": sys.argv, "calls": CALLS[0]}) + "\n")
'''


@pytest.fixture(autouse=True)
def _the_childs_token_store(monkeypatch):
    """The window's questions are asked in this process of the store the Generate child wrote (under the test root, as
    child_env has it), not conftest's per-test stand-in (test_cli_contract does the same)."""
    from app import token_index
    root = os.environ["SURASURA_TEST_ROOT"]
    monkeypatch.setattr(token_index, "store_path_for", lambda lang: os.path.join(root, "index", f"token_store_{lang}.db"))


def _argv(language):
    return [ARGV[0], f"--language={language}"] + ARGV[1:]


def _generate(root, language, spy=None, tmp_path=None):
    """A Generate in its own process, as the dashboard starts it (the store's helper after) -> (report data, what it
    printed). `spy`: a file name; every process the Generate starts counts its tokenizer calls into it."""
    env = child_env(root)
    if spy:
        spy_dir = tmp_path / "spy"
        spy_dir.mkdir(exist_ok=True)
        (spy_dir / "sitecustomize.py").write_text(SPY, encoding="utf-8")
        env["PYTHONPATH"] = str(spy_dir) + os.pathsep + env["PYTHONPATH"]
        env["JS1_TOKENIZER_SPY"] = str(tmp_path / spy)
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py")] + _argv(language)[1:]
    p = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    return _report(root), p.stdout


def _spied(tmp_path, spy):
    """The spy's lines: one per process -> [(argv, calls)]."""
    with open(tmp_path / spy, encoding="utf-8") as f:
        return [(r["argv"], r["calls"]) for r in map(json.loads, f)]


def _results(root):
    return os.path.join(root, "results")


def _csvs(root):
    """results/*.csv, byte for byte -> {name: bytes}."""
    out = {}
    for path in sorted(glob.glob(os.path.join(_results(root), "*.csv"))):
        with open(path, "rb") as f:
            out[os.path.basename(path)] = f.read()
    assert out, "a Generate writes its CSVs"
    return out


def _mtimes(root):
    return {os.path.basename(p): os.stat(p).st_mtime_ns for p in glob.glob(os.path.join(_results(root), "*.csv"))}


def _signatures(root, language):
    """What says which analysis results/ holds: the token store's last run signature and the results' stamp."""
    return (analyzer._token_store_meta(language, "last_run_signature"), analyzer.read_run_stamp(_results(root)))


def _current(language):
    """(the analysis half, the window's whole "reopen, don't run" question) — as the Generate button asks them."""
    return analyzer.journey_is_current(_argv(language), language), verbs._nothing_changed(_argv(language), language)


def _kept_on(language):
    """Show A Ep01–03 then Show B Ep01–03 in NOW, *Keep studying* on, one full Generate -> (store, ids, names, root,
    the report data)."""
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    store.set_library_options(keep_watched=True)
    first, said = _generate(root, language)
    assert REUSED not in said and _stones(first) == {}
    return store, ids, names, root, first


# --- D2 · the W-1 / W-1b counting rule ------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d2_after_a_mark_and_its_quiet_run_the_counts_equal_a_full_generate_from_scratch(language):
    # why (D2, the W-1 / W-1b rule): the quiet run re-uses the last analysis; it is right only if a Generate from scratch
    # at the same state — the stone on — counts exactly the same, so the reused counts can never be stale ones
    store, ids, names, root, first = _kept_on(language)
    store.set_watched([ids["A2"]])
    quiet, said = _generate(root, language)
    assert REUSED in said and RE_RENDER in said, "the quiet run: a re-render"
    quiet_csvs = _csvs(root)
    shutil.rmtree(_results(root))                       # from scratch: no results for any reuse to start from
    full, said = _generate(root, language)
    assert REUSED not in said, "a full analysis"
    assert _csvs(root) == quiet_csvs, "the full Generate's lists, byte for byte"
    assert full == quiet, "and its journey: the same files, words, counts and stone"
    assert _stones(quiet) == {names["A2"]: False}, "counted AND watched"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_d2_a_finished_show_stays_out_of_the_journey_through_a_quiet_run(language):
    # why (D2): Finished is its own view (W-1); a quiet run that re-draws the journey for a stone on Show A must not
    # bring back Show B, finished with stones on its episodes, as files or as stones
    store, ids, names, root, first = _kept_on(language)
    show_b = [ids[k] for k in ("B1", "B2", "B3")]
    b_names = {names[k] for k in ("B1", "B2", "B3")}
    store.set_watched(show_b)
    store.finish(show_b)
    finished, said = _generate(root, language)
    assert REUSED not in said, "a Finish is a Generate"
    assert not b_names & set(_files(finished) + [f["filename"] for f in finished["completed_files"]])
    store.set_watched([ids["A2"]])
    quiet, said = _generate(root, language)
    assert REUSED in said and RE_RENDER in said
    assert not b_names & set(_files(quiet) + [f["filename"] for f in quiet["completed_files"]]), \
        "Finished stays out of the journey"
    assert _stones(quiet) == {names["A2"]: False}, "the one stone: A2's, counted"
    assert _files(quiet) == _files(finished)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_d2_a_set_aside_mark_with_the_option_off_takes_the_generate_path_never_the_quiet_one(language):
    # why (D2, W-1b): with the option off a mark sets its episode's words aside — the counts change, so the analysis
    # must say "not current" and the press must re-analyse; a quiet run would keep counting an episode set aside
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    first, _said = _generate(root, language)
    before = _csvs(root)
    store.set_watched([ids["A2"]])
    assert _current(language) == (False, False), "the analysis isn't current: no quiet run can answer it"
    marked, said = _generate(root, language)
    assert REUSED not in said, "a Generate"
    assert _stones(marked) == {names["A2"]: True} and _words(marked, names["A2"]) == [], "set aside, no counts"
    assert _csvs(root) != before, "its words stepped back"
    store.close()


# --- D3 · *Keep studying* changes no counts ------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d3_the_quiet_runs_csvs_are_byte_identical_and_only_the_stones_differ(language):
    # why (D3): with the option on a watched episode keeps counting — a mark moves no count, so the lists the learner
    # studies are byte for byte what they were; the report changes only by the stone
    store, ids, names, root, first = _kept_on(language)
    before = _csvs(root)
    store.set_watched([ids["A2"]])
    quiet, said = _generate(root, language)
    assert REUSED in said and RE_RENDER in said
    assert _csvs(root) == before, "no count moved"
    marked = json.loads(json.dumps(quiet))
    entry_ = next(e for e in marked["progressive"] if e["filename"] == names["A2"])
    assert entry_.pop("watched") is True
    assert marked == first, "the report's data differs only by A2's stone"
    store.close()


# --- D4 · Generate's "up to date", the analysis half ---------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d4_after_the_quiet_run_the_journey_and_the_report_say_current_and_a_second_press_reopens(language):
    # why (D4): the quiet run must leave nothing for a second press to do — the Generate button says up to date and a
    # press reopens the report. Before it, the analysis is current but the report isn't: the report half is the only
    # thing that tells the window's trigger (JourneyKeeper._is_pending) a stone is waiting to be drawn
    store, ids, names, root, first = _kept_on(language)
    assert _current(language) == (True, True), "a fresh Generate: current"
    store.set_watched([ids["A2"]])
    assert _current(language) == (True, False), "the mark: the analysis current, the report not"
    _quiet, said = _generate(root, language)
    assert REUSED in said and RE_RENDER in said
    assert _current(language) == (True, True), "the quiet run: both current"
    again, said = _generate(root, language)
    assert UP_TO_DATE in said and RE_RENDER not in said, "a second press reopens, never redraws"
    assert _stones(again) == {names["A2"]: False}
    store.close()


# --- D5 · the symmetric Undo ---------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d5_mark_quiet_run_undo_quiet_run_is_exactly_as_before_the_mark(language):
    # why (D5): an Undo puts back what its mark did — the journey, the lists and what the report is recorded as
    # showing; a render signature left at the mark's would keep the stone's report "current" or re-render forever
    store, ids, names, root, first = _kept_on(language)
    before_csvs, before_sig = _csvs(root), analyzer._token_store_meta(language, "last_render_sig")
    assert before_sig
    change = store.set_watched([ids["A2"]])
    marked, said = _generate(root, language)
    assert RE_RENDER in said and _stones(marked) == {names["A2"]: False}
    assert analyzer._token_store_meta(language, "last_render_sig") != before_sig, "the stone was signed"
    store.undo(change)
    assert _current(language) == (True, False), "the Undo: the report half waits for its quiet run"
    undone, said = _generate(root, language)
    assert REUSED in said and RE_RENDER in said, "the Undo's quiet run"
    assert undone == first, "the journey data as before the mark"
    assert _csvs(root) == before_csvs, "the lists byte for byte"
    assert analyzer._token_store_meta(language, "last_render_sig") == before_sig, "the pre-mark render signature"
    assert _current(language) == (True, True)
    store.close()


# --- D6 · S19, update only what changed ----------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d6_the_quiet_run_tokenizes_nothing_and_takes_the_reuse_path(language, tmp_path):
    # why (D6, S19): a mark changes one stone, so the quiet run re-draws the report and reads nothing else — no
    # tokenizer call in any process it starts, no new analysis (the run signature and stamp unchanged, the CSVs never
    # rewritten). The first Generate is spied too: the spy must see a tokenizer when one runs, or its 0 proves nothing
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    store.set_library_options(keep_watched=True)
    _first, said = _generate(root, language, spy="first.jsonl", tmp_path=tmp_path)
    assert REUSED not in said
    assert sum(calls for _argv_, calls in _spied(tmp_path, "first.jsonl")) > 0, "the spy sees a run's tokenizer"
    sigs, mtimes = _signatures(root, language), _mtimes(root)
    assert all(sigs)
    store.set_watched([ids["A2"]])
    quiet, said = _generate(root, language, spy="quiet.jsonl", tmp_path=tmp_path)
    assert REUSED in said and RE_RENDER in said, "the analyzer's reuse path, a re-render"
    spied = _spied(tmp_path, "quiet.jsonl")
    assert spied and all(calls == 0 for _argv_, calls in spied), spied
    assert _signatures(root, language) == sigs, "the run signature and the stamp unchanged: nothing re-analysed"
    assert _mtimes(root) == mtimes, "no list rewritten"
    assert _stones(quiet) == {names["A2"]: False}
    store.close()
