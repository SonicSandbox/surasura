"""P3.3's planted-bug pass (research/mutants JUDGED-P3.3): `_junban_auto`'s gaps the change's own tests missed — a
plan with no re-plan orders from the list, the re-plan's rows in 順's own order with their file numbers, and the order
recorded planned only after a run that finished.

What a wrong answer would cost: the re-order crashing (or writing nothing) after a level raise; Anki ordered by
content when you chose priority; spaced numbers lost (RP-10); a run Anki cut short recorded as planned, so the
window's host never finishes the order.

`_junban_auto` with Junban's automatic run (`auto`) and the store's record replaced: what it hands them is checked;
never a live Anki.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("modules.junban")

from app import analyzer, run_args  # noqa: E402
from app.cli import verbs  # noqa: E402
from modules.junban import spaced  # noqa: E402

VERSIONS = {"order_version": 7, "pins_version": 2, "planned_order_version": 7, "planned_pins_version": 2, "epoch": "e"}


@pytest.fixture
def harness(monkeypatch):
    seen = {"reorder": [], "jobs": [], "recorded": [], "report": {"ok": True, "stats": {"total": 3}, "written": []}}

    # P4.1 L2 (package T): Connect's step also asks the run to suspend and record *Take its new cards out* (`cards_out`)
    def reorder(junban_settings, list_current, positions_only, run_id, job, cards_out):
        seen["reorder"].append({"list_current": list_current, "positions_only": positions_only, "job": job,
                                "cards_out": cards_out})
        return {"outcome": "done", "report": seen["report"]}
    auto = SimpleNamespace(blocked=lambda settings, window=False: None, window_open=lambda: False, reorder=reorder)
    monkeypatch.setattr(verbs, "deck_aside", lambda settings, lang: None)
    monkeypatch.setattr(verbs, "_session", lambda settings: None)
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, lang, headless=False: ["analyzer.py"])
    monkeypatch.setattr(analyzer, "journey_is_current", lambda argv, lang: "the journey's answer")
    monkeypatch.setattr(spaced, "Job", lambda **kw: (seen["jobs"].append(kw), ("job", kw["places"]))[1])
    monkeypatch.setattr(verbs, "_record_planned", lambda lang, versions: (seen["recorded"].append(versions),
                                                                          dict(VERSIONS))[1])
    monkeypatch.setattr(verbs, "_plan_moved", lambda current, after: False)
    seen["auto"] = auto
    return seen


def _current(result=True):
    return SimpleNamespace(result=object() if result else None, places={"話1.srt": 1, "話2.srt": 2},
                           versions=dict(VERSIONS), key=("k",),
                           rows=lambda mode: [("約束", "ヤクソク", mode), ("勇気", "ユウキ", mode)])


def _run(harness, current, **settings):
    args = SimpleNamespace(wait=0.0)
    out, _stats = verbs._junban_auto(args, "ja", dict(settings), harness["auto"], job=None, current=current,
                                     positions_only=False)
    return args, out


def test_a_plan_with_no_re_plan_orders_from_the_list_as_the_journey_finds_it(harness):
    # why (P3.3 B42): a level raise ("after") or Generate first has no engine rows — Junban orders from the list, its
    # currency the journey's, never a spaced job from rows that don't exist
    _run(harness, _current(result=False))
    assert harness["jobs"] == [], "no job from a re-plan that isn't there"
    assert harness["reorder"][0]["list_current"] == "the journey's answer" and harness["reorder"][0]["job"] is None
    assert harness["recorded"] == [], "nothing recorded planned without a re-plan"


def test_the_re_plans_rows_follow_your_junban_order_and_carry_its_file_numbers(harness):
    # why (P3.3 B43 / B44): 順's own order (priority here, as you wrote it) and RP-10's file numbers go to the job
    current = _current()
    _run(harness, current, junban_order=" Priority ")
    assert harness["jobs"] == [{"automatic": True, "rows": current.rows("priority"), "places": current.places}]
    assert harness["reorder"][0]["list_current"] is True
    assert harness["reorder"][0]["cards_out"] is True, "P4.1 L2: not positions only, so the run records a take-out"


class _Store:
    """The library store as `_record_planned` reads it: its versions, and the record it raises."""

    def __init__(self, now):
        self.now, self.recorded = dict(now), []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def versions(self):
        return dict(self.now)

    def record_planned(self, order_version, pins_version):
        self.recorded.append((order_version, pins_version))
        self.now["planned_order_version"] = max(self.now["planned_order_version"], order_version)
        self.now["planned_pins_version"] = max(self.now["planned_pins_version"], pins_version)


def test_a_pins_only_advance_is_recorded_as_planned(monkeypatch):
    # why (P3.3 B54): you pinned an episode (its pins version moved, the order didn't) and Connect's run wrote that
    # order — recorded, so the window's host owes nothing for it and doesn't re-order Anki once more
    from app.connect import library
    store = _Store({"order_version": 5, "pins_version": 3, "planned_order_version": 5, "planned_pins_version": 2,
                    "epoch": "e"})
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": store)
    after = verbs._record_planned("ja", {"order_version": 5, "pins_version": 3})
    assert store.recorded == [(5, 3)]
    assert after["planned_pins_version"] == 3


class _Picked(Exception):
    """The pick stopped right after it settled its ranks (the test's)."""


def test_a_re_plan_that_lists_no_words_is_the_picks_ranking_never_the_last_generates(monkeypatch, tmp_path):
    # why (P3.3 B57): Connect hands the re-plan's ranks in; an empty ranking (every word of the list known since) is
    # the answer — the last Generate's list would mine words the engine no longer lists
    subtitle = tmp_path / "話1.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,500\n約束だよ\n", encoding="utf-8")
    read = []
    monkeypatch.setattr(verbs, "settings", lambda: {"target_language": "ja"})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_listed", lambda args, lang: read.append(lang) or {("約束", "ヤクソク"): 0})

    def settled(job, lang):
        raise _Picked()
    monkeypatch.setattr(verbs, "_level_job", settled)
    with pytest.raises(_Picked):
        verbs.pick(SimpleNamespace(lang="ja", file=str(subtitle), video=None, words="list", job="8", wait=0.0,
                                   made=set(), listed={}))
    assert read == [], "the handed-in ranking is used as is"


@pytest.mark.parametrize("report", [{"ok": True, "left": 4}, {"ok": True, "failures": [{"note": 1}]}, {"ok": False}])
def test_a_run_that_didnt_finish_never_records_its_order_as_planned(harness, report):
    # why (P3.3 B47 / B48 / B49): only a clean run (ok, nothing left, no failures) leaves Anki in the store's order —
    # a run Anki cut short recorded as planned would leave the window's host owing nothing for an order half written
    harness["report"] = dict(report, stats={"total": 3}, written=[])
    _run(harness, _current())
    assert harness["recorded"] == []
    harness["report"] = {"ok": True, "stats": {"total": 3}, "written": []}
    _run(harness, _current())
    assert harness["recorded"] == [VERSIONS], "a clean run records the versions read with its order"
