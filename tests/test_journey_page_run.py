"""The journey page's self-check runner retries only timing rows (TOOLS-321; JOURNEY-FLAKE's find, 2026-11-26): it kept
the best of 3 attempts, so on GitHub a real check that failed once and passed on another attempt vanished. A stand-in
Edge hands it scripted attempts; nothing is opened."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import journey_page_run as runner  # noqa: E402

TIMING_ROW = "↓ next word ≤ 16 ms"                     # (a timing row: test_journey_page's TIMING reads it as one)
REAL_ROW = "Known → next: the word marked 知っている"


def _attempt(*fails):
    rows = [["each line under its sentence names where it is from", True, ""], [TIMING_ROW, True, ""],
            [REAL_ROW, True, ""]]
    for row in rows:
        if row[0] in fails:
            row[1], row[2] = False, "雨が降る: 24 ms" if row[0] == TIMING_ROW else "未知のまま"
    return {"out": rows, "SPEED": {}, "BUDGETS": [], "pass": sum(r[1] for r in rows), "total": len(rows)}


class _Edge:
    def __init__(self, attempts):
        self.attempts, self.opened = list(attempts), 0

    def __call__(self, *_a):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def open(self, url, until=None, seconds=None):
        self.opened += "selftest=1" in url

    def evaluate(self, js):
        return json.dumps(self.attempts.pop(0)) if "__selftest" in js else None

    def errors(self):
        return []


def _run(monkeypatch, *attempts):
    edge = _Edge(attempts)
    monkeypatch.setattr(runner, "Edge", edge)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    res, errs = runner.run("C:/pages/journey-ja-2000.html")
    return res, errs, edge.opened


def test_a_real_failure_is_kept_even_when_a_later_attempt_would_pass_it(monkeypatch):
    # the first attempt misses a timing row (retried), the second fails a real check: that one is kept, no third
    res, errs, opened = _run(monkeypatch, _attempt(TIMING_ROW), _attempt(REAL_ROW), _attempt())
    assert opened == 2 and res["attempts"] == 2 and not errs
    assert [r[0] for r in res["out"] if not r[1]] == [REAL_ROW]


def test_a_real_failure_on_the_first_attempt_is_never_retried(monkeypatch):
    res, _errs, opened = _run(monkeypatch, _attempt(REAL_ROW, TIMING_ROW), _attempt(), _attempt())
    assert opened == 1 and res["attempts"] == 1
    assert {r[0] for r in res["out"] if not r[1]} == {REAL_ROW, TIMING_ROW}


def test_a_timing_row_missed_under_load_is_retried_and_the_passing_attempt_kept(monkeypatch):
    res, _errs, opened = _run(monkeypatch, _attempt(TIMING_ROW), _attempt(TIMING_ROW), _attempt())
    assert opened == 3 and res["attempts"] == 3 and res["pass"] == res["total"]
    assert res["missed"] == [[TIMING_ROW + " — 雨が降る: 24 ms"]] * 2


def test_the_runners_timing_rows_are_the_tests():
    # the runner's own copy of the pattern is test_journey_page's, whose assertion splits timing rows from real ones
    with open(os.path.join(HERE, "test_journey_page.py"), encoding="utf-8") as f:
        line = next(t for t in f if t.startswith("TIMING = re.compile("))
    assert line.strip() == 'TIMING = re.compile(r"%s")' % runner.TIMING.pattern
    assert runner.TIMING.search(TIMING_ROW) and not runner.TIMING.search(REAL_ROW)
