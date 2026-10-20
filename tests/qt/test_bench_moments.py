"""What every bench reports per moment (M4.1 row 4, package A: `tests/qt/bench_moments.py`'s `Moments.summary`).

What a wrong answer would cost: a moment judged on another moment's work. A GUI-thread step runs from the loop's waking
to its next wait, and the timer that ends one repetition goes on into the next one's begin and action in that one
stretch: hold 1 gave menu-open the menu move's whole cost (130–180 ms at 20,000 files; menu-open's slowest equal to
menu-goal's to the hundredth), and the bar's "typical worst" at 10 repetitions is the slowest (nearest-rank p95), so one
such stretch decided the line. The median of the repetitions' worsts is reported beside it; the bar is Sonic's and
stays as it is.
"""
import pytest

pytest.importorskip("PyQt6")

from tests.qt import bench_moments


class _Hud:
    """The HUD's side `Moments.summary` reads: no frames, the step log given."""

    def __init__(self, steps):
        self.keep = 0
        self.tag = None
        self.step_log = list(steps)
        self.ignore_before = 0.0

    def explain_frames(self):
        return []


def _moments(steps, reps):
    m = bench_moments.Moments(_Hud(steps), tag=False)
    for name, t0, t1 in reps:
        if name not in m.order:
            m.order.append(name)
        m.reps.append([name, t0, t1])
    return m


def test_a_stretch_over_one_repetitions_end_and_the_next_ones_begin_counts_for_the_next_only():
    # menu-open's repetition ends at 10.350 by a timer whose stretch (from 10.349, 170 ms) goes on to begin menu-goal at
    # 10.351 and to apply its move: that stretch is menu-goal's, never menu-open's
    steps = [(10.010, 2.5), (10.349, 170.0), (10.600, 3.0)]
    out = _moments(steps, [("menu-open", 10.000, 10.350), ("menu-goal", 10.351, 11.150)]).summary()
    assert out["menu-open"]["step_slowest_ms"] == 2.5
    assert out["menu-goal"]["step_slowest_ms"] == 170.0
    assert out["menu-open"]["steps_over_4ms"] == 0


def test_the_step_holding_a_repetitions_own_begin_still_counts_for_it():
    # the click's stretch began just before its repetition did (the begin and the press in one stretch): it is that
    # repetition's own, and stays so
    steps = [(9.999, 30.0), (10.200, 1.0)]
    out = _moments(steps, [("pickup", 10.000, 10.300), ("slide", 10.400, 10.900)]).summary()
    assert out["pickup"]["step_slowest_ms"] == 30.0
    assert out["slide"]["step_slowest_ms"] == 0.0


def test_a_stretch_over_a_repetitions_end_that_holds_no_later_begin_stays_with_it():
    # the drop's stretch runs past its repetition's end (10.120 → 10.150) but the next moment begins only after it
    # (10.200): it is the drop's, and never the next one's
    steps = [(10.100, 50.0)]
    out = _moments(steps, [("drop", 10.000, 10.120), ("drop-top20", 10.200, 10.500)]).summary()
    assert out["drop"]["step_slowest_ms"] == 50.0
    assert out["drop-top20"]["step_slowest_ms"] == 0.0


def test_the_median_of_the_repetitions_worsts_is_reported_beside_the_p95():
    # 10 repetitions: the nearest-rank p95 is the slowest (round(0.95 * 9) = 9), so one stretch decides it; the median
    # of the worsts is the typical repetition's
    worsts = [1.0, 2.0, 3.0, 3.0, 3.5, 4.5, 5.0, 6.0, 7.0, 90.0]
    steps, reps = [], []
    for k, ms in enumerate(worsts):
        t0 = 100.0 + k
        reps.append(("menu-goal", t0, t0 + 0.5))
        steps.append((t0 + 0.1, ms))
    m = _moments(steps, reps).summary()["menu-goal"]
    assert m["step_worst_p95_ms"] == 90.0 == m["step_slowest_ms"]
    assert m["step_worst_median_ms"] == 4.0


def test_the_markdown_carries_the_median_column_and_the_bar_as_it_was():
    moment = {"reps": 10, "frames_n": 12, "frames_p95_ms": 2.1, "frames_max_ms": 3.0, "windows": {"main": 12},
              "slow_n": 0, "slow_causes": {}, "step_worst_p95_ms": 90.0, "step_worst_median_ms": 4.0,
              "step_slowest_ms": 90.0, "steps_over_4ms": 3, "wakes_after": 0}
    md = bench_moments.markdown({"bench": "bench_drag", "results": [{"scale": 150, "run": 1, "dpr": 1.5,
                                                                    "moments": {"menu-goal": moment}}]})
    assert ("Bar here: frame p95 <= 3.2 ms; a frame over 6.4 ms needs a cause; the steps' typical worst <= 4.0 ms; "
            "0 clock wake-ups once still.") in md
    assert "| step typ. worst | median worst | slowest |" in md
    assert "| 90.0 | 4.0 | 90.0 | 3 | 0 |" in md
