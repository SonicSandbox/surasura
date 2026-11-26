"""DSA-START (3.0.19): the window's start and a move, each read against the textbook choice, on RP-2's real library.

- **A move's numbers walk only what moved.** `Numbers.after_move` copied every file's *N new* and compared all of
  them after `Engine.move` (20,000 pairs a press at 20k), though the engine changes a file's *N new* only where a
  word's first file moved — it knows those files. Now it hands them over (`Engine.move(..., n_new_was=)`), and the
  numbers publish exactly those rows: the same rows, the same figures, nothing else walked.
- **G3: the redraw's check hashes in one call.** The keeper's redraw (`analyzer.py --from-plan`) asked
  `plan_engine.check` with the chunked digest meant for a worker beside the window (0.45 s at 20k against 0.03 s);
  the redraw is a process of its own, with no thread waiting beside it.

What a wrong answer would cost: a row that keeps an old *N new* after a drop (the learner sees a stale count until
the next start), or a row told it changed when it didn't (a rebuilt row: waste, never a wrong figure).
"""
import os
import subprocess
import sys
import types

import pytest

from app import analyzer, plan_engine
from tests import plan_file_cases as cases


def _generated(language, root):
    root = str(root)
    case = f"rp2-{language}"
    cases.build(root, case)
    cases.generate(root, case, extra_env={"SURASURA_SENTENCE_TABLE": "2"})
    return root


@pytest.fixture(scope="module", params=["ja", "zh"])
def run(request, tmp_path_factory):
    """RP-2's real library of one language, Generated at level 2 (the shipped level)."""
    language = request.param
    root = _generated(language, tmp_path_factory.mktemp(f"dsa-start-{language}"))
    return types.SimpleNamespace(language=language, root=root, results=os.path.join(root, "results"),
                                 plan_path=os.path.join(root, "results", analyzer.PLAN_FILE), tmp=tmp_path_factory)


def _in_root(monkeypatch, root):
    """This process reads the module's root, as the window's own process reads its library."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", root)
    monkeypatch.setenv("APPDATA", os.path.join(root, "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", os.path.join(root, "localappdata"))


class _Walked(list):
    """A list that counts the items an iteration hands out (`list(x)`, `zip(x, …)`, a for loop): the files walked."""
    walked = 0

    def __iter__(self):
        for value in list.__iter__(self):
            _Walked.walked += 1
            yield value


def _loaded_numbers(run, monkeypatch):
    from app.services import moves
    _in_root(monkeypatch, run.root)
    numbers = moves.Numbers(moves.store_opener(run.language), run.language, plan_file=run.plan_path)
    numbers.load()
    assert numbers.idle(60) and numbers.why() is None, numbers.why()
    return numbers


def _referee(run, eng):
    """A fresh engine over the moved engine's order now (`_numbers` from scratch): the figures a move must leave."""
    plan = plan_engine.load(run.plan_path, pools=False)
    referee = plan_engine.Engine(plan, list(eng._ids), numbers_only=True)
    referee._numbers([(eng._ids[f], plan_engine.TIERS[eng._tier[f]]) for f in eng._order])
    return referee


def test_a_moves_numbers_walk_only_the_files_the_engine_changed_and_equal_a_fresh_count(run, monkeypatch):
    """Two drops (a Soon title to NOW's top, then 6+ Months' last before Soon's last): each publishes exactly the
    rows whose figures moved — the moved title's and every title whose *N new* the engine changed — with a fresh
    count's figures, and walks none of the other files' *N new* (the counter: before, 2 × every file a press)."""
    numbers = _loaded_numbers(run, monkeypatch)
    try:
        eng = numbers._engine
        n_files = len(eng._n_new)
        assert n_files >= 6, n_files
        eng._n_new = _Walked(eng._n_new)
        tiers = {t: [eng._ids[f] for f in eng._order if plan_engine.TIERS[eng._tier[f]] == t]
                 for t in plan_engine.TIERS}
        assert tiers["soon"] and tiers["goal"], {t: len(v) for t, v in tiers.items()}
        drops = [([tiers["soon"][-1]], "now", {"before_id": tiers["now"][0]}),
                 ([tiers["goal"][-1]], "soon", {"before_id": tiers["soon"][0]})]
        for ids, tier, where in drops:
            before_version, before_table = numbers()
            before_table = dict(before_table)
            _Walked.walked = 0
            touched = numbers.after_move(ids, tier, **where)
            walked = _Walked.walked
            assert touched and ids[0] in touched, touched
            _v, table = numbers()
            referee = _referee(run, eng)
            for item, (_known, _counted, n_new) in table.items():
                f = referee._f_of.get(item)
                if f is not None:
                    assert n_new == referee._n_new[f], (item, n_new, referee._n_new[f])
            moved = {item for item in table if table[item] != before_table.get(item)}
            assert set(touched) == moved | {ids[0]}, (sorted(touched), sorted(moved))
            assert numbers.changed(before_version) == set(touched)
            assert walked == 0, f"{walked} of {n_files} files' N new walked for one move"
    finally:
        numbers.close()


_DIGESTS = """
import runpy, sys
from app import plan_rules
calls, digest = [], plan_rules.signature_digest
def counted(parts, order_free=False, chunked=True, *a, **k):
    calls.append(chunked)
    return digest(parts, order_free, chunked, *a, **k)
plan_rules.signature_digest = counted
sys.argv = [sys.argv[1]] + sys.argv[2:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    sys.stderr.write("\\nDIGESTS-CHUNKED %d of %d\\n" % (sum(1 for c in calls if c), len(calls)))
"""


def test_the_redraw_hashes_the_library_with_the_one_fast_call(run):
    """A show moved to the top, then the keeper's redraw (`--from-plan`), in a root of its own: it redraws, and no
    digest in its process takes the chunked path (before: `plan_engine.check`'s, at the window's default)."""
    from tests.test_e_redraw import _move
    root = _generated(run.language, run.tmp.mktemp(f"dsa-start-redraw-{run.language}"))
    _move(root, run.language, "top")
    env = cases.child_env(root)
    env["SURASURA_SENTENCE_TABLE"] = "2"
    p = subprocess.run([sys.executable, "-c", _DIGESTS, os.path.join(cases.REPO, "app", "analyzer.py"),
                        f"--language={run.language}", "--static", "--no-open", "--from-plan"],
                       cwd=cases.REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    assert p.returncode == 0 and "Redrew the journey" in out, out[-3000:]
    line = [x for x in p.stderr.splitlines() if x.startswith("DIGESTS-CHUNKED ")][-1]
    chunked, total = int(line.split()[1]), int(line.split()[3])
    assert total >= 1, line
    assert chunked == 0, line
