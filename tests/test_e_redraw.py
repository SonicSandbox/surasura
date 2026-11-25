"""E-REDRAW (part 1): the list's sentences and the redraw on the one score at release 2 (SPEC § 10.3; § 7 rows 3, 23,
33, 36; § 6.1 row 8; § 6.3 rows 14–15).

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each through a full Generate at level 2
(`SURASURA_SENTENCE_TABLE=2`, a child process as the dashboard runs it). What these prove:
  - **the parity suite** (§ 7 row 23): after a move — one show to the top, a show between tiers, then the move undone
    — the journey redrawn from the old plan (`--from-plan`: the engine's re-plan, its rows handed to the one reader
    with the new order) shows, for every word of the list, the same Context / Src columns as the one reader asked of
    a fresh Generate's own table for that order;
  - a format-5 plan carries its sentences in the table: the engine's move reads no first sentence and the lean load
    opens no table (§ 6.1 row 8); a format-4 plan at level 2 reads "Generate first";
  - *Only i+1* (§ 6.3 row 15): the fast re-plan still stands aside with it on (the redraw Generates), and the reader's
    `clean_only` keeps every word today's i+1 list keeps;
  - the redraw marker names the day it was drawn for, and a journey drawn on another day is owed again (§ 7 row 36);
  - the redraw keeps the text of the lines it shows (results/shown.json.gz) and reads them from there the next time;
  - below level 2 nothing of it runs (the formats stay 4; the tree's level is 0).
"""
import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

from app import analyzer, plan_engine, plan_rules, sentence_table
from tests import plan_file_cases as cases

LEVEL_2 = {"SURASURA_SENTENCE_TABLE": "2"}


def _env(root):
    env = cases.child_env(root)
    env.update(LEVEL_2)
    return env


_MOVE = r"""
import json, os, sys
from app import library_store as ls
language, root, step = sys.argv[1], sys.argv[2], sys.argv[3]
store = ls.open_store(language, os.path.join(root, "data", language), os.path.join(root, "User Files", language))
assert store is not None
soon, goal, now = store.ids("soon"), store.ids("goal"), store.ids("now")
if step == "top":                 # a show to the top
    assert store.move([soon[-1]], "now") is not None
elif step == "between":           # a show between tiers
    assert store.move([now[1]], "goal", before_id=goal[0]) is not None
note = os.path.join(root, "e_redraw_moves.json")      # what was moved, for the undo
first = json.load(open(note)) if os.path.exists(note) else {}
if step == "undo":                # both undone, as Undo puts them back
    assert store.move([first["between"]], "now", after_id=now[0]) is not None
    assert store.move([first["top"]], "soon", after_id=soon[-1]) is not None
elif step == "top":
    first["top"] = soon[-1]
elif step == "between":
    first["between"] = now[1]
json.dump(first, open(note, "w"))
store.close()
"""


def _move(root, language, step):
    """One of the parity cases' moves, made on the root's library store in a child (the store lives in the root's
    own local data folder, as the Generate's does)."""
    p = subprocess.run([sys.executable, "-c", _MOVE, language, root, step], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]


def _columns(results):
    """{(Word, Reading): [Context 1, Src 1, …]} of the priority list, in its order."""
    with open(os.path.join(results, "priority_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    n = sum(1 for c in (rows[0] if rows else {}) if c.startswith("Context "))
    out = {}
    for r in rows:
        cols = [v for i in range(1, n + 1) for v in (r[f"Context {i}"], r[f"Src {i}"])]
        while cols and not cols[-1] and not cols[-2]:
            del cols[-2:]                   # (a row with fewer sentences than columns is padded with "")
        out[(r["Word"], r["Reading"])] = cols
    return out


def _redraw(root, language):
    """The keeper's redraw (`--from-plan`), as the window starts it -> its output."""
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                        "--static", "--no-open", "--from-plan"], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return p.stdout


_READER = r"""
import json, sys
from app import analyzer, plan_rules
language, results, keys = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
chooser = analyzer.ListSentences(language, int(sys.argv[4]), sys.argv[5] == "1", results_dir=results)
got = chooser([tuple(k) for k in keys], None)
print(json.dumps(None if got is None else [[list(k), v] for k, v in got.items()], ensure_ascii=False))
"""


def _reader(root, language, keys, max_contexts=3, clean_only=False):
    """The one reader asked of `root`'s own table for the list's rows in its own order (what the level-2 Generate's
    columns are: SPEC § 5.2) -> {key: columns}. `clean_only`: *Only i+1*."""
    p = subprocess.run([sys.executable, "-c", _READER, language, os.path.join(root, "results"),
                        json.dumps([list(k) for k in keys], ensure_ascii=False), str(max_contexts),
                        "1" if clean_only else "0"],
                       cwd=cases.REPO, env=_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(p.stdout.strip().splitlines()[-1])
    assert got is not None, "the fresh Generate's table answers"
    return {tuple(k): v for k, v in got}


def _release_2(monkeypatch, on=True):
    """This process read as at level 2 (a child takes it from SURASURA_SENTENCE_TABLE, at import), or as below it."""
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 2 if on else 0)
    monkeypatch.setattr(plan_engine, "FORMAT", 5 if on else 4)
    monkeypatch.setattr(plan_engine, "FORMATS", (1, 2, 3, 4, 5) if on else (1, 2, 3, 4))


def _generated(language, folder, **kw):
    case = f"rp2-{language}"
    root = str(folder)
    cases.build(root, case)
    cases.generate(root, case, extra_env=LEVEL_2, **kw)
    return root


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """One case's library and its Generate at level 2 (read only: each test that moves makes its own)."""
    language = request.param
    root = _generated(language, tmp_path_factory.mktemp(f"e-redraw-{language}"))
    return types.SimpleNamespace(language=language, case=f"rp2-{language}", root=root,
                                 results=os.path.join(root, "results"),
                                 plan_path=os.path.join(root, "results", analyzer.PLAN_FILE), tmp=tmp_path_factory)


@pytest.fixture(scope="module")
def moved(run):
    """Another of the same library, one show moved to the top and the journey redrawn (the token store holds each
    file by its path: a copied root would read none of its text, so it is generated in place)."""
    root = _generated(run.language, run.tmp.mktemp(f"moved-{run.language}"))
    _move(root, run.language, "top")
    out = _redraw(root, run.language)
    assert "Redrew the journey" in out, out[-1500:]
    return types.SimpleNamespace(language=run.language, root=root, results=os.path.join(root, "results"))


def _fresh(root, case, tmp):
    """A copy of `root` as it stands, Generated in full (its own token store: the copy's paths are its own)."""
    fresh = str(tmp.mktemp("fresh"))
    shutil.rmtree(fresh)
    shutil.copytree(root, fresh, ignore=shutil.ignore_patterns("index"))
    for left in (analyzer.REDRAW_FILE, analyzer.SHOWN_FILE):
        if os.path.exists(os.path.join(fresh, "results", left)):
            os.remove(os.path.join(fresh, "results", left))
    cases.generate(fresh, case, extra_env=dict(LEVEL_2, SURASURA_FORCE_RUN="1"))
    return fresh


@pytest.fixture(scope="module")
def level_1(run):
    """The same library Generated at level 1: today's plan (format 4) with its own first sentences and pools."""
    root = str(run.tmp.mktemp(f"level1-{run.language}"))
    cases.build(root, run.case)
    cases.generate(root, run.case, extra_env={"SURASURA_SENTENCE_TABLE": "1"})
    return os.path.join(root, "results", analyzer.PLAN_FILE)


MOVES = ["top", "between", "undo"]       # a show to the top, a show between tiers, both undone


def test_the_journey_redrawn_after_each_move_shows_what_a_fresh_generate_reads(run):
    # why: the parity suite (SPEC § 7 row 23) — the redraw's sentences come from the old table with the new order
    # handed in; a fresh Generate's come from its own table and its own list. Equal for every word, or the redraw
    # (seconds) and the Generate (minutes) would disagree about what a card gets.
    root = _generated(run.language, run.tmp.mktemp(f"parity-{run.language}"))
    compared = []
    for name in MOVES:
        _move(root, run.language, name)
        out = _redraw(root, run.language)
        assert "Redrew the journey" in out, (name, out[-1500:])
        drawn = _columns(os.path.join(root, "results"))
        assert drawn and any(any(v) for v in drawn.values()), (name, "the redraw shows sentences")
        fresh = _fresh(root, run.case, run.tmp)
        listed = _columns(os.path.join(fresh, "results"))
        assert list(listed) == list(drawn), (name, "the same list, in the same order (the engine's parity)")
        want = _reader(fresh, run.language, list(listed))
        differ = [k for k in drawn if drawn[k] != want.get(k)]
        assert not differ, (name, len(differ), [(k, drawn[k], want.get(k)) for k in differ[:3]])
        compared.append((name, len(drawn)))
        shutil.rmtree(fresh, ignore_errors=True)
    assert [n for n, _ in compared] == MOVES


def test_the_redraw_keeps_the_shown_lines_text_and_reads_it_back(moved, tmp_path):
    # why: SPEC § 5.3 — the text of the lines the journey shows is kept by the table's run, so the next redraw reads
    # only lines that are new; a kept file of another run is never read
    results = moved.results
    table = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=moved.language)
    forms = {}
    kept = analyzer._read_shown(results, table.head["run_signature"], forms)
    assert kept, "the shown lines' text is kept"
    shown = {v for cols in _columns(results).values() for v in cols[0::2] if v}
    assert len(kept) >= len(shown) > 0
    assert analyzer._read_shown(results, "another run") == {}, "another run's kept text is never read"
    with open(os.path.join(results, analyzer.SHOWN_FILE), "rb") as f:
        first = f.read()
    analyzer._write_shown(str(tmp_path), table.head["run_signature"], kept, forms)
    with open(os.path.join(str(tmp_path), analyzer.SHOWN_FILE), "rb") as f:
        assert f.read() == first, "the same lines, the same bytes (no time inside)"


def test_a_format_5_plan_holds_its_sentences_in_the_table_and_a_move_reads_none(run, level_1, monkeypatch):
    # why: SPEC § 6.1 row 8 / § 6.3 row 14 — at release 2 the plan's pools and first sentences are never decoded,
    # and the engine's move (the window's own numbers) and the lean load open no sentence table
    with gzip.open(run.plan_path, "rb") as f:
        assert json.loads(f.readline())["format"] == 5, "a level-2 Generate writes format 5"
    _release_2(monkeypatch)
    opened = []
    monkeypatch.setattr(sentence_table, "open_table", lambda *a, **k: opened.append(a) or None)
    for pools in (True, False):
        plan = plan_engine.load(run.plan_path, pools=pools)
        assert plan.firsts is None and plan.pools == {} and plan.sentences == [] and not plan.picks
        eng = plan_engine.Engine(plan)
        assert all(len(fs) == 0 for fs in eng._fs), "no first sentence a file"
        soon = [entry[0] for entry in plan.files if entry[1] == "soon"]
        changed, moved = eng.move([soon[-1]], "now")
        assert moved == [soon[-1]] and changed
    assert opened == [], "the move and the lean load open no sentence table"
    # the same numbers as today's plan of the same library (format 4, its old tables decoded): the move doesn't
    # hang on them
    a = plan_engine.Engine(plan_engine.load(run.plan_path))
    b = plan_engine.Engine(plan_engine.load(level_1))
    assert any(len(fs) for fs in b._fs), "(format 4: the first sentences read)"
    assert a.move([soon[-1]], "now") == b.move([soon[-1]], "now")


def test_a_format_5_plan_with_no_chooser_or_no_table_is_a_generate(run, monkeypatch):
    # why: a release-2 plan's sentences are the table's alone: with none to ask, the redraw Generates, never shows
    # the plan's leftovers
    _release_2(monkeypatch)
    eng = plan_engine.Engine(plan_engine.load(run.plan_path))
    with pytest.raises(plan_engine.PlanError):
        eng.result(pick=True)
    with pytest.raises(plan_engine.PlanError):
        eng.result(pick=True, chooser=lambda keys, order: None)
    asked = []

    def chooser(keys, order):
        asked.append((list(keys), dict(order)))
        return {keys[0]: ["その文", "HighPriority/x.srt"]}
    got = eng.result(pick=True, chooser=chooser)
    keys, order = asked[0]
    assert [(r["Word"], r["Reading"]) for r in got.priority] == keys, "the rows in rank order"
    places = {}
    for at, r in enumerate(got.progressive):
        places.setdefault((r["Word"], r["Reading"]), at)
    assert order == places, "each row's place: its first row in the progressive list (the table's `places`)"
    assert got.priority[0]["Context 1"] == "その文"
    assert got.priority[1]["Context 1"] == plan_engine.load(run.plan_path).rows[
        [tuple(k[:2]) for k in plan_engine.load(run.plan_path).keys].index(keys[1])][6][0], \
        "a row the chooser leaves out keeps the Generate's own columns"


def test_a_format_4_plan_at_release_2_reads_generate_first(run, level_1, monkeypatch):
    # why: SPEC § 3.4 — an older plan's sentences are not the table's: "Generate first", never a crash or a guess
    old = level_1                       # (today's plan, format 4)
    _release_2(monkeypatch)
    assert plan_engine.read_header(old) is None
    plan = plan_engine.load(old)
    verdict = plan_engine.check(plan, run.language, plan.header["engine"], plan.header["run_signature"], None)
    assert verdict == ("generate-first", "format")
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 0)
    assert plan_engine.check(plan, run.language, plan.header["engine"], plan.header["run_signature"], None) == \
        ("generate-first", "signature"), "below release 2 the format is not asked (today's verdict)"


def _skipped(results):
    """The *Only i+1* line of results/file_statistics.txt: how many words the Generate left off -> int."""
    with open(os.path.join(results, "file_statistics.txt"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("i+1 Constraint: "):
                return int(line.split()[2])
    raise AssertionError("no i+1 line")


def test_only_i_plus_one_at_release_2_lists_a_word_only_with_a_clean_line_by_the_order_it_is_studied_in(
        run, tmp_path, monkeypatch):
    # why: SPEC § 6.3 row 15 — *Only i+1* skips a word with no i+1 sentence. At release 2 the Generate asks the one
    # reader (`clean_only`: every line of the word, not 60 + 15) by the order the learner studies in (the lead's
    # ruling 1, PROVISIONAL): every word left on the list shows only clean lines, the list's columns are the reader's
    # for its own table, the words it leaves off are counted as today, and it keeps today's list (the ladder's, by
    # the priority order) but for at most one word in fifty. The fast re-plan still stands aside with it on
    # (`aside_reasons`: "i+1"), so a move Generates, as today.
    case, language = run.case, run.language
    today = str(tmp_path / "today")
    cases.build(today, case)
    cases.generate(today, case, extra_env={"SURASURA_SENTENCE_TABLE": "0"}, extra_args=["--only-i-plus-one"])
    kept_today = list(_columns(os.path.join(today, "results")))
    root = _generated(language, tmp_path / "root", extra_args=["--only-i-plus-one"])
    results = os.path.join(root, "results")
    listed = _columns(results)
    assert listed and all(cols and cols[0] for cols in listed.values()), "every word left on shows a sentence"
    want = _reader(root, language, list(listed), clean_only=True)
    differ = [k for k in listed if listed[k] != want.get(k)]
    assert not differ, (len(differ), [(k, listed[k], want.get(k)) for k in differ[:3]])
    every = list(_columns(run.results))             # the same library at release 2, *Only i+1* off: every word
    assert set(listed) <= set(every)
    assert _skipped(results) == len(every) - len(listed), "the words left off, counted (file_statistics.txt)"
    lost = [k for k in kept_today if k not in listed]
    gained = [k for k in listed if k not in kept_today]
    assert len(lost) * 50 <= len(kept_today), (len(lost), len(kept_today), lost[:5])
    _release_2(monkeypatch)
    plan = plan_engine.load(os.path.join(results, analyzer.PLAN_FILE), pools=False)
    assert "i+1" in plan_engine.aside_reasons(plan)
    _move(root, language, "top")
    out = _redraw(root, language)
    assert "Redrew the journey" not in out and "generating" in out
    print(f"Only i+1 ({language}): release 2 lists {len(listed)} (today {len(kept_today)}: {len(lost)} of today's "
          f"left off, {len(gained)} added) of {len(every)}")


def test_only_i_plus_one_with_a_coverage_target_at_release_2_leaves_off_only_words_the_cut_reaches(run, tmp_path):
    # why: the lead's ruling on coverage + *Only i+1* at release 2 — each round the reader is asked for the list after
    # the coverage cut, so a word is left off for want of a clean line only if the cut reached it: every word left off
    # ranks above the list's last word, and file_statistics.txt counts exactly those (a reader asked for every word,
    # the cut skipped, would count words the list never reaches). When the words left cannot reach the target, the
    # cut takes the whole list and every word is asked: the count is then every word left off
    every = list(_columns(run.results))             # the same library at release 2, no target, *Only i+1* off
    with open(os.path.join(run.results, "file_statistics.json"), encoding="utf-8") as f:
        stats = json.load(f)
    total, known = sum(s["Total Words"] for s in stats), sum(s["Known Count"] for s in stats)
    now = known / total * 100
    clean = _generated(run.language, tmp_path / "clean", extra_args=["--only-i-plus-one"])     # no target
    with open(os.path.join(clean, "results", "priority_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        uses = [int(r["Occurrences"]) for r in csv.DictReader(f)]
    # a target the cut reaches inside the list *Only i+1* keeps, about a third of the way down where a whole percent
    # allows (above today's coverage: else no list at all); else one the words left cannot reach
    n = len(uses)
    reach = [int((known + sum(uses[:i])) / total * 100) for i in list(range(max(1, n // 3), n)) + list(range(1, n // 3))]
    target = next((t for t in reach if t > now), None) or int(now) + 1
    root = str(tmp_path / "root")
    cases.build(root, run.case)
    out = cases.generate(root, run.case, extra_env=LEVEL_2,
                         extra_args=["--only-i-plus-one", f"--target-coverage={target}"])
    inside = "Successfully reached" in out          # the cut ends inside the list (else it took every word left)
    assert inside or "Could only reach" in out, out[-1500:]
    results = os.path.join(root, "results")
    shown = _columns(results)
    listed = list(shown)
    assert listed and len(listed) < len(every), (target, len(listed), len(every))
    assert all(cols and cols[0] for cols in shown.values()), "every word left on shows a sentence"
    last = every.index(listed[-1])
    assert [k for k in every[:last + 1] if k in shown] == listed, "the words above the list's last, less those left off"
    left_off = last + 1 - len(listed) if inside else len(every) - len(listed)
    assert _skipped(results) == left_off, (_skipped(results), left_off, target, inside)
    print(f"Only i+1 + {target}% ({run.language}, the cut {'inside the list' if inside else 'took every word'}): "
          f"{len(listed)} listed, {left_off} left off, of {len(every)}")


def test_the_redraw_marker_names_its_day(moved):
    # why: SPEC § 7 row 36 — the redraw marker says the day it was drawn for (the local date), at level 2
    assert analyzer.redrawn_for(moved.results)["day"] == analyzer.drawn_day()


@pytest.mark.parametrize("level, day, state", [(2, "today", "drawn"), (2, "2000-01-01", "owed"),
                                               (0, "2000-01-01", "drawn"), (2, None, "owed")])
def test_a_journey_drawn_on_another_day_is_owed_again_at_release_2(monkeypatch, level, day, state):
    # why: decision 6 — a card weighs how well each episode is remembered, which fades by the day: a journey drawn
    # for this very order on another day (or by a marker with no day) is redrawn; below release 2 the day is not asked
    from app import library_store, plan_rules as rules
    from app.services import journey as J, moves

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(rules, "SENTENCE_TABLE", level)
    monkeypatch.setattr(plan_engine, "read_header", lambda path: {"run_signature": "plan"})
    monkeypatch.setattr(library_store, "open_store", lambda *a, **k: Store())
    monkeypatch.setattr(moves, "plan_inputs", lambda *a: (None, None, "parts"))
    monkeypatch.setattr(rules, "signature_digest", lambda parts: "moved")
    monkeypatch.setattr(plan_engine, "only_order", lambda header, language, *inputs: True)
    marker = {"plan": "plan", "run": "moved"}
    if day is not None:
        marker["day"] = analyzer.drawn_day() if day == "today" else day
    monkeypatch.setattr(analyzer, "redrawn_for", lambda results: marker)
    assert J.moved_state({}, "ja", "plan.json.gz") == state


@pytest.mark.parametrize("level, fmt", [("0", 4), ("1", 4), ("2", 5)])
def test_the_plan_format_follows_the_switch_and_only_release_2_moves_it(level, fmt):
    # why: inert — below level 2 the plan file is today's format, byte for byte (SPEC § 10.1)
    env = cases.child_env(os.environ.get("SURASURA_TEST_ROOT", cases.REPO))
    env["SURASURA_SENTENCE_TABLE"] = level
    p = subprocess.run([sys.executable, "-c", "from app import analyzer, plan_engine; "
                        "print(plan_engine.FORMAT, analyzer.PLAN_FORMAT)"], cwd=cases.REPO, env=env,
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-1500:]
    assert p.stdout.split() == [str(fmt), str(fmt)]


def test_all_asks_the_reader_for_todays_ceiling():
    # why: SPEC § 5.2's *All* row — Sentences per word 0 gives a row the first 87 the reader returns, today's
    # ceiling, so the page's weight does not change
    assert analyzer.ListSentences("ja", 0).n == plan_rules.context_limit(0) == 87
    assert analyzer.ListSentences("ja", 3).n == 3


# --- The lead's ruling 4 (2026-11-23): a journey with no redraw marker (Generated before this build) counts as not
# today's, and is redrawn once; this build's level-2 Generate names its own day, so its journey is today's ---

_DRAWN = r"""
import sys
from app import analyzer
results = sys.argv[1]
print(analyzer.drawn_for(results) == analyzer.read_run_stamp(results) and bool(analyzer.read_run_stamp(results)))
"""


def _current(root):
    """Whether the outputs in `root`'s results/ are the run stamp's (`drawn_for`, the one question every "is the
    journey current" asks), read at level 2 in a child."""
    p = subprocess.run([sys.executable, "-c", _DRAWN, os.path.join(root, "results")], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-1500:]
    return p.stdout.strip().splitlines()[-1] == "True"


def test_a_release_2_generate_names_its_own_day_so_its_journey_is_todays(run):
    # why: ruling 4 tells a journey Generated before this build by its missing marker — so this build's Generate
    # writes one (its own run, today) and is never redrawn just after it
    stamp = analyzer.read_run_stamp(run.results)
    assert analyzer.redrawn_for(run.results) == {"plan": stamp, "run": stamp, "day": analyzer.drawn_day()}
    assert _current(run.root)


def test_a_journey_with_no_redraw_marker_is_not_todays_and_is_redrawn_once(run):
    # why: ruling 4 — a journey Generated before this build has no marker: at level 2 it is not today's (its
    # sentences weighed no episode's fading), so the keeper redraws it from the plan once; after that it is current
    root = _generated(run.language, run.tmp.mktemp(f"unmarked-{run.language}"))
    os.remove(os.path.join(root, "results", analyzer.REDRAW_FILE))
    assert not _current(root)
    out = _redraw(root, run.language)
    assert "Redrew the journey" in out, out[-1500:]
    assert analyzer.redrawn_for(os.path.join(root, "results"))["day"] == analyzer.drawn_day()
    assert _current(root)


@pytest.mark.parametrize("level, current", [(2, False), (1, True), (0, True)])
def test_no_marker_is_current_only_below_release_2(tmp_path, monkeypatch, level, current):
    # why: inert — below level 2 a journey with no marker is the run stamp's, as today (`drawn_for`)
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", level)
    monkeypatch.setattr(analyzer, "read_run_stamp", lambda results: "stamp")
    assert (analyzer.drawn_for(str(tmp_path)) == "stamp") is current


@pytest.mark.parametrize("level, fmt_ok, state", [(2, True, "owed"), (2, False, None), (0, True, None)])
def test_with_no_marker_and_nothing_moved_release_2_owes_a_redraw(monkeypatch, level, fmt_ok, state):
    # why: ruling 4 — nothing moved and no marker: at level 2 the redraw is owed (seconds, from the plan) when the
    # plan is this build's (`only_order`: a format-4 plan at level 2 reads Generate first, so a Generate); below
    # level 2 nothing is owed, as today
    from app import library_store, plan_rules as rules
    from app.services import journey as J, moves

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(rules, "SENTENCE_TABLE", level)
    monkeypatch.setattr(plan_engine, "read_header", lambda path: {"run_signature": "plan"})
    monkeypatch.setattr(library_store, "open_store", lambda *a, **k: Store())
    monkeypatch.setattr(moves, "plan_inputs", lambda *a: (None, None, "parts"))
    monkeypatch.setattr(rules, "signature_digest", lambda parts: "plan")
    monkeypatch.setattr(plan_engine, "only_order", lambda header, language, *inputs: fmt_ok)
    monkeypatch.setattr(analyzer, "redrawn_for", lambda results: None)
    assert J.moved_state({}, "ja", "plan.json.gz") == state


# --- Part 2: the level-2 Generate takes its list's sentences from the one reader (SPEC § 10.3), and the journey is
# redrawn once a day (the lead's ruling on Left 2, 2026-11-23; SPEC § 7 rows 14, 36) ---

_PICK_TABLES = (b'{"sentences":', b'{"cowords":', b'{"pools":', b'{"firsts":')


def _progressive_columns(results):
    """{(Word, Reading): [Context 1, Src 1, …]} of the progressive list (each word's first row)."""
    with open(os.path.join(results, "progressive_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    n = sum(1 for c in (rows[0] if rows else {}) if c.startswith("Context "))
    out = {}
    for r in rows:
        cols = [v for i in range(1, n + 1) for v in (r[f"Context {i}"], r[f"Src {i}"])]
        while cols and not cols[-1] and not cols[-2]:
            del cols[-2:]
        out.setdefault((r["Word"], r["Reading"]), cols)
    return out


def test_a_release_2_generates_list_sentences_are_the_one_readers_for_its_own_order(run):
    # why: SPEC § 10.3 / § 5.2 — at release 2 no shortlist is kept: the list's own Context / Src columns are the one
    # reader's over the table the walk packed, weighed by the list's own order (the table's `places`) — the call the
    # redraw makes, so a Generate (minutes) and a redraw (seconds) can never disagree; the progressive list and
    # word_stats.json carry the same sentences, and each Src is a path the report's source table joins on
    listed = _columns(run.results)
    assert listed and sum(1 for cols in listed.values() if cols) == len(listed), "every word shows a sentence"
    want = _reader(run.root, run.language, list(listed))
    differ = [k for k in listed if listed[k] != want.get(k)]
    assert not differ, (len(differ), [(k, listed[k], want.get(k)) for k in differ[:3]])
    progressive = _progressive_columns(run.results)
    assert {k: progressive[k] for k in listed if k in progressive} == {k: listed[k] for k in listed if k in progressive}
    with open(os.path.join(run.results, "word_stats.json"), encoding="utf-8") as f:
        stats = json.load(f)
    assert all(stats[f"{k[0]}|{k[1]}"]["final_context_1"] == cols[0] for k, cols in listed.items())
    with open(os.path.join(run.results, "sources.json"), encoding="utf-8") as f:
        sources = json.load(f)
    srcs = {src for cols in listed.values() for src in cols[1::2] if src}
    assert srcs and srcs <= set(sources), sorted(srcs - set(sources))[:3]


def test_a_release_2_generate_writes_no_shortlist_and_no_first_sentence_table(run):
    # why: SPEC § 3.6 — at release 2 the plan keeps what the fast re-plan needs and nothing of the old pick: no
    # sentences, co-words, pools or first sentences (`firsts`, each file's `fs`) — they are the table's
    with gzip.open(run.plan_path, "rb") as f:
        lines = f.read().split(b"\n")
    assert json.loads(lines[0])["format"] == 5
    assert not [line[:20] for line in lines if line.startswith(_PICK_TABLES)]
    per_file = [json.loads(line) for line in lines if line.startswith(b'{"f":')]
    assert per_file and not [line["f"] for line in per_file if "fs" in line]
    assert any(line.startswith(b'{"rows":') for line in lines) and any(line.startswith(b'{"files":') for line in lines)


def test_a_release_2_generate_keeps_the_text_of_the_lines_it_shows(run):
    # why: SPEC § 5.3 — the text of the lines the list shows is kept by the Generate's own run, so the first redraw
    # after a move reads only lines that are new
    kept = analyzer._read_shown(run.results, analyzer.read_run_stamp(run.results))
    assert kept, "the Generate kept the shown lines' text"
    srcs = {src for cols in _columns(run.results).values() for src in cols[1::2] if src}
    assert srcs <= {rel for rel, _n in kept}


def test_a_release_2_generate_and_its_redraw_with_nothing_moved_show_the_same_sentences(run):
    # why: parity at rest (SPEC § 10.3, (1)) — the journey redrawn from the Generate's own plan, nothing moved, shows
    # every word's sentences as the Generate wrote them, in both lists
    root = _generated(run.language, run.tmp.mktemp(f"rest-{run.language}"))
    results = os.path.join(root, "results")
    listed, progressive = _columns(results), _progressive_columns(results)
    os.remove(os.path.join(results, analyzer.REDRAW_FILE))      # (ruling 4: not today's, so the keeper redraws it)
    out = _redraw(root, run.language)
    assert "Redrew the journey" in out, out[-1500:]
    assert _columns(results) == listed
    assert _progressive_columns(results) == progressive


def _mark_day(results, day):
    """The redraw marker's day set to `day` (as if drawn then)."""
    path = os.path.join(results, analyzer.REDRAW_FILE)
    with open(path, encoding="utf-8") as f:
        marker = json.load(f)
    marker["day"] = day
    with open(path, "w", encoding="utf-8") as f:
        json.dump(marker, f)


def test_a_journey_drawn_on_an_earlier_day_and_not_moved_since_is_not_current_and_is_redrawn_once(run):
    # why: decision 6 (the lead's ruling on Left 2) — a card weighs how well each episode is remembered, which fades
    # by the day: a journey drawn yesterday is not today's even if nothing moved; the keeper redraws it from the plan
    # once, and then it is current for the rest of the day
    root = _generated(run.language, run.tmp.mktemp(f"yesterday-{run.language}"))
    results = os.path.join(root, "results")
    assert _current(root)
    _mark_day(results, "2000-01-01")
    assert not _current(root), "drawn on another day: not current"
    out = _redraw(root, run.language)
    assert "Redrew the journey" in out, out[-1500:]
    assert analyzer.redrawn_for(results)["day"] == analyzer.drawn_day()
    assert _current(root)


@pytest.mark.parametrize("marker", ["yesterday", "none"])
def test_generate_pressed_on_a_new_day_with_nothing_changed_redraws_the_journey_from_the_plan(run, marker):
    # why: SPEC § 7 row 14 (step 2) — Generate with nothing changed reuses the run; at release 2 the journey is
    # redrawn when the day changes what it would show: seconds from the plan, never a whole Generate (and the same
    # for a journey with no marker, ruling 4)
    root = _generated(run.language, run.tmp.mktemp(f"press-{marker}-{run.language}"))
    results = os.path.join(root, "results")
    if marker == "yesterday":
        _mark_day(results, "2000-01-01")
    else:
        os.remove(os.path.join(results, analyzer.REDRAW_FILE))
    out = cases.generate(root, run.case, extra_env=LEVEL_2)
    assert "Redrew the journey" in out and "Saved the sentence table" not in out, out[-1500:]
    assert analyzer.redrawn_for(results)["day"] == analyzer.drawn_day()
    out = cases.generate(root, run.case, extra_env=LEVEL_2)
    assert "reusing existing results" in out, "the same day: reused, as today"


@pytest.mark.parametrize("level, current", [(2, False), (1, True), (0, True)])
def test_a_marker_of_another_day_is_not_current_only_at_release_2(tmp_path, monkeypatch, level, current):
    # why: inert — below level 2 the marker's day is never read (`drawn_for`: today's answer)
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", level)
    monkeypatch.setattr(analyzer, "read_run_stamp", lambda results: "stamp")
    monkeypatch.setattr(analyzer, "redrawn_for", lambda results: {"plan": "stamp", "run": "order",
                                                                  "day": "2000-01-01"})
    assert (analyzer.drawn_for(str(tmp_path)) == "order") is current
    monkeypatch.setattr(analyzer, "redrawn_for", lambda results: {"plan": "stamp", "run": "order",
                                                                  "day": analyzer.drawn_day()})
    assert analyzer.drawn_for(str(tmp_path)) == "order"


@pytest.mark.parametrize("marker", ["yesterday", "none"])
def test_generate_force_on_a_new_day_runs_whole_never_the_plans_redraw(run, marker):
    # why: the lead's ruling 3 — `generate --force` stays whole. The new day's press (above) redraws from the plan;
    # a forced Generate on that same new day, nothing changed, reads every file again as ever (the lens pass found
    # the press's redraw taken ahead of the force)
    root = _generated(run.language, run.tmp.mktemp(f"force-{marker}-{run.language}"))
    results = os.path.join(root, "results")
    if marker == "yesterday":
        _mark_day(results, "2000-01-01")
    else:
        os.remove(os.path.join(results, analyzer.REDRAW_FILE))
    out = cases.generate(root, run.case, extra_env=dict(LEVEL_2, SURASURA_FORCE_RUN="1"))
    assert "Saved the sentence table" in out and "Redrew the journey" not in out, out[-1500:]
    assert analyzer.redrawn_for(results)["day"] == analyzer.drawn_day(), "a Generate's own marker: today's"


_UNRECORD = r"""
import sys
from app import token_index
store = token_index.open_store(sys.argv[1])
store.set_meta("last_run_signature", "an earlier run")
store.close()
"""


def test_a_journey_drawn_today_whose_run_the_token_store_does_not_record_runs_whole_then_is_reused(run):
    # why: the day clause of `_drawn_another_day` (mutant X10) — with today's marker in place the reuse gate still
    # declines when the token store's record of the last run is behind the run stamp (a Generate's last write, which
    # never fails the run, did not land). The press then runs whole, which records the run, and the next press
    # reuses; a redraw from the plan would leave the record behind and redraw at every press, never reusing
    root = _generated(run.language, run.tmp.mktemp(f"unrecorded-{run.language}"))
    results = os.path.join(root, "results")
    p = subprocess.run([sys.executable, "-c", _UNRECORD, run.language], cwd=cases.REPO, env=_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]
    assert analyzer.redrawn_for(results)["day"] == analyzer.drawn_day(), "drawn today"
    out = cases.generate(root, run.case, extra_env=LEVEL_2)
    assert "Saved the sentence table" in out and "Redrew the journey" not in out, out[-1500:]
    out = cases.generate(root, run.case, extra_env=LEVEL_2)
    assert "reusing existing results" in out, out[-1500:]


_STAMP = re.compile(rb'"stamp":"\d+"')
_WRITTEN = ("priority_learning_list.csv", "progressive_learning_list.csv", "reading_list_static.html")


def _written(results):
    """The two lists' bytes and the journey page's (its render stamp blanked: two renders of one page differ there
    alone)."""
    out = {}
    for name in _WRITTEN:
        with open(os.path.join(results, name), "rb") as f:
            out[name] = _STAMP.sub(b'"stamp":""', f.read(), count=1)
    return out


def test_a_new_days_press_writes_what_a_whole_generate_writes_that_day(run):
    # why: the lead's ruling 3 — a Generate pressed on a new day with nothing changed may redraw from the plan only
    # if the redraw writes the same journey sentences and list bytes as a whole Generate on that same day (same
    # library, same clock: RP-2's libraries hold no watched date, so the score's moment reads no time)
    root = _generated(run.language, run.tmp.mktemp(f"newday-{run.language}"))
    results = os.path.join(root, "results")
    _mark_day(results, "2000-01-01")
    out = cases.generate(root, run.case, extra_env=LEVEL_2)
    assert "Redrew the journey" in out, out[-1500:]
    pressed = _written(results)
    out = cases.generate(root, run.case, extra_env=dict(LEVEL_2, SURASURA_FORCE_RUN="1"))
    assert "Saved the sentence table" in out, out[-1500:]
    whole = _written(results)
    assert [name for name in _WRITTEN if pressed[name] != whole[name]] == []


_NO_ANSWER = {
    "none": "from app import sentence_score\nsentence_score.choose = lambda *a, **k: None\n",
    "raises": ("from app import sentence_score\n\n\ndef _boom(*a, **k):\n"
               "    raise RuntimeError('a moment it cannot read')\n\n\nsentence_score.choose = _boom\n"),
    # the first round answers (Only i+1 leaves off the words with no clean line), the second gives none: the words
    # left off come back
    "second": ("from app import sentence_score\n_real, _calls = sentence_score.choose, []\n\n\n"
               "def _second(*a, **k):\n    _calls.append(1)\n    return _real(*a, **k) if len(_calls) == 1 else None\n"
               "\n\nsentence_score.choose = _second\n"),
}


@pytest.mark.parametrize("how", ["none", "raises", "second"])
def test_a_reader_with_no_answer_shows_no_sentences_and_leaves_no_word_off_with_only_i_plus_one(run, tmp_path, how):
    # why: the lens pass (failures) — the score answers None when it can't read (a table damaged inside its blocks, a
    # moment it can't read), and *Only i+1* took that for "no clean line" for every word: an empty list. A reader that
    # raised stopped the Generate. Now the list keeps every word, with no sentences this time, and says so
    spy = tmp_path / "no-answer"
    spy.mkdir()
    (spy / "sitecustomize.py").write_text(_NO_ANSWER[how], encoding="utf-8")
    root = str(tmp_path / "root")
    cases.build(root, run.case)
    out = cases.generate(root, run.case, extra_args=["--only-i-plus-one"],
                         extra_env=dict(LEVEL_2, PYTHONPATH=str(spy) + os.pathsep + cases.REPO))
    assert "the list shows no sentences this time" in out, out[-1500:]
    results = os.path.join(root, "results")
    listed = _columns(results)
    assert list(listed) == list(_columns(run.results)), "every word, as with Only i+1 off"
    assert not any(listed.values()), "no sentences this time"
    assert _skipped(results) == 0
