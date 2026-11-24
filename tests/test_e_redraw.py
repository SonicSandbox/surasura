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
chooser = analyzer.ListSentences(language, int(sys.argv[4]), results_dir=results)
got = chooser([tuple(k) for k in keys], None)
print(json.dumps(None if got is None else [[list(k), v] for k, v in got.items()], ensure_ascii=False))
"""


def _reader(root, language, keys, max_contexts=3):
    """The one reader asked of `root`'s own table for the list's rows in its own order (what the level-2 Generate's
    columns are: SPEC § 5.2) -> {key: columns}."""
    p = subprocess.run([sys.executable, "-c", _READER, language, os.path.join(root, "results"),
                        json.dumps([list(k) for k in keys], ensure_ascii=False), str(max_contexts)],
                       cwd=cases.REPO, env=_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(p.stdout.strip().splitlines()[-1])
    assert got is not None, "the fresh Generate's table answers"
    return {tuple(k): v for k, v in got}


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
    kept = analyzer._read_shown(results, table.head["run_signature"])
    assert kept, "the shown lines' text is kept"
    shown = {v for cols in _columns(results).values() for v in cols[0::2] if v}
    assert len(kept) >= len(shown) > 0
    assert analyzer._read_shown(results, "another run") == {}, "another run's kept text is never read"
    with open(os.path.join(results, analyzer.SHOWN_FILE), "rb") as f:
        first = f.read()
    analyzer._write_shown(str(tmp_path), table.head["run_signature"], kept)
    with open(os.path.join(str(tmp_path), analyzer.SHOWN_FILE), "rb") as f:
        assert f.read() == first, "the same lines, the same bytes (no time inside)"


def test_a_format_5_plan_holds_its_sentences_in_the_table_and_a_move_reads_none(run, monkeypatch):
    # why: SPEC § 6.1 row 8 / § 6.3 row 14 — at release 2 the plan's pools and first sentences are never decoded,
    # and the engine's move (the window's own numbers) and the lean load open no sentence table
    with gzip.open(run.plan_path, "rb") as f:
        assert json.loads(f.readline())["format"] == 5, "a level-2 Generate writes format 5"
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 2)
    monkeypatch.setattr(plan_engine, "FORMAT", 5)
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
    # the same numbers as the plan read as format 4 below release 2: the move doesn't hang on the sentences
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 0)
    monkeypatch.setattr(plan_engine, "FORMAT", 4)
    a = plan_engine.Engine(plan_engine.load(run.plan_path, pools=False))
    b = plan_engine.Engine(plan_engine.load(run.plan_path, pools=False))
    assert a.move([soon[-1]], "now") == b.move([soon[-1]], "now")


def test_a_format_5_plan_with_no_chooser_or_no_table_is_a_generate(run, monkeypatch):
    # why: a release-2 plan's sentences are the table's alone: with none to ask, the redraw Generates, never shows
    # the plan's leftovers
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 2)
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


def test_a_format_4_plan_at_release_2_reads_generate_first(run, tmp_path, monkeypatch):
    # why: SPEC § 3.4 — an older plan's sentences are not the table's: "Generate first", never a crash or a guess
    with gzip.open(run.plan_path, "rb") as f:
        lines = f.read().split(b"\n")
    lines[0] = json.dumps(dict(json.loads(lines[0]), format=4)).encode("utf-8")
    old = str(tmp_path / analyzer.PLAN_FILE)
    with gzip.open(old, "wb") as f:
        f.write(b"\n".join(lines))
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 2)
    monkeypatch.setattr(plan_engine, "FORMAT", 5)
    assert plan_engine.read_header(old) is None
    plan = plan_engine.load(old)
    verdict = plan_engine.check(plan, run.language, plan.header["engine"], plan.header["run_signature"], None)
    assert verdict == ("generate-first", "format")
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 0)
    assert plan_engine.check(plan, run.language, plan.header["engine"], plan.header["run_signature"], None) == \
        ("generate-first", "signature"), "below release 2 the format is not asked (today's verdict)"


def test_with_only_i_plus_one_the_redraw_still_generates_and_the_reader_keeps_every_word_today_keeps(run, tmp_path):
    # why: SPEC § 6.3 row 15 — *Only i+1* skips a word with no i+1 sentence; the fast re-plan stands aside with it on
    # (`aside_reasons`: "i+1"), so a move Generates as today; the reader's `clean_only` (every line of the word, not
    # 60 + 15) never loses a word today's list keeps
    root = _generated(run.language, tmp_path / "root", extra_args=["--only-i-plus-one"])
    results = os.path.join(root, "results")
    plan = plan_engine.load(os.path.join(results, analyzer.PLAN_FILE), pools=False)
    assert "i+1" in plan_engine.aside_reasons(plan)
    kept_today = list(_columns(results))
    _move(root, run.language, "top")
    out = _redraw(root, run.language)
    assert "Redrew the journey" not in out and "generating" in out
    p = subprocess.run([sys.executable, "-c", _READER.replace("results_dir=results)", "True, results_dir=results)"),
                        run.language, results, json.dumps([list(k) for k in kept_today], ensure_ascii=False), "3"],
                       cwd=cases.REPO, env=_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]
    got = {tuple(k): v for k, v in json.loads(p.stdout.strip().splitlines()[-1])}
    lost = [k for k in kept_today if not got.get(k)]
    # Measured (part 1): ja 111 of 112 kept. The one word lost: today's ladder counts its sentence clean by the
    # priority order (words learned in earlier rows), the one reader counts "new when studied" by the study order
    # (the progressive list, the table's `places`) and finds 2 other new words in it — the score's one rule, for the
    # lead (register, *For the lead*). Never more than one word in fifty.
    assert len(lost) * 50 <= len(kept_today), (len(lost), len(kept_today), lost[:5])
    print(f"Only i+1 ({run.language}): the reader keeps {len(kept_today) - len(lost)} of today's {len(kept_today)}")


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
