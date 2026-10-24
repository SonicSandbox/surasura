"""The journey keeper's check asks the report half too (JS-1; `app/services/journey.py` `JourneyKeeper._is_pending`,
`app/analyzer.py` `report_is_current` — the one helper surasura-cli's `_nothing_changed` asks as well).

A stone with *Keep studying watched episodes* on changes no run input: `journey_is_current` stays True by contract
(presentation is left out of it), so a keeper that asked only that would never re-render the report for the stone.
Pending is now: the analysis isn't current OR the report isn't (it is missing, or was drawn from something else than
it would be drawn from now: `last_render_sig` against `compute_render_signature`).

What a wrong answer would cost a learner: a stone (or its Undo) the journey shows only after some unrelated Generate;
or, if the report half were asked wrongly, a quiet Generate after every move that changes nothing.
Real Generates (the command line's), Japanese and Chinese, under the per-test SURASURA_TEST_ROOT.
"""
import json
import os
import time

import pytest

from app import analyzer, run_args
from app.services import journey as J
from app.services import replan_host as R
from tests import cli_helpers as h
from tests import services_helpers as sh
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.test_services_replan_host import _replan, fired, gate  # noqa: F401  (fixtures)


class _Controller:
    """What the keeper holds of the controller here: its listener (the check itself asks no run)."""

    def on_end(self, _listener):
        pass

    def unsubscribe(self, _listener):
        pass

    def withdraw(self, _run):
        pass


def _keeper(language, settings):
    return J.JourneyKeeper(_Controller(), language, settings=lambda: dict(settings))


def test_pending_is_either_half_never_the_analysis_alone(monkeypatch):
    # why: the two halves are asked of the keeper's own argv; either one moved is a run (a re-render alone when only
    # the report's moved — the analyzer's reuse path decides that)
    answers = {"analysis": True, "report": True}
    monkeypatch.setattr(analyzer, "journey_is_current", lambda args, language: answers["analysis"])
    monkeypatch.setattr(analyzer, "report_is_current", lambda args, language: answers["report"])
    keeper = _keeper("ja", {"target_language": "ja"})
    assert keeper._is_pending() is False
    answers["report"] = False
    assert keeper._is_pending() is True, "only the report half moved: pending"
    answers.update(analysis=None, report=True)
    assert keeper._is_pending() is True, "the analysis can't tell: pending, as before"
    answers.update(analysis=False)
    assert keeper._is_pending() is True


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_after_a_generate_a_render_only_change_makes_the_keeper_pending_and_the_analysis_stays_current(language):
    # why: the real halves after a real Generate — current, then a change only the report shows (words a day here; a
    # stone with Keep studying on moves the same half), then the report gone
    h.seed_library(language)
    settings = h.write_settings(target_language=language)
    code, _lines = h.run_cli("generate", "--lang", language)
    assert code == 0
    args = run_args.analyzer_args(settings, language)
    keeper = _keeper(language, settings)
    assert analyzer.journey_is_current(args, language) is True
    assert analyzer.report_is_current(args, language) is True
    assert keeper._is_pending() is False, "nothing moved: nothing to run"
    settings = h.write_settings(target_language=language, words_per_day=12)
    keeper = _keeper(language, settings)
    args = run_args.analyzer_args(settings, language)
    assert analyzer.journey_is_current(args, language) is True, "a render-only change: the analysis stays current"
    assert analyzer.report_is_current(args, language) is False
    assert keeper._is_pending() is True, "only the render signature moved: the keeper re-renders"
    code, lines = h.run_cli("generate", "--lang", language)
    assert code == 0 and lines[-1]["ran"] is False, "the run it asks re-renders and analyses nothing"
    assert keeper._is_pending() is False, "re-rendered: current again"
    os.remove(os.path.join(h.root(), "results", "reading_list_static.html"))
    assert analyzer.report_is_current(args, language) is False and keeper._is_pending() is True, "no report: pending"


# --- the trigger beside a run in flight (IK finding 2, S19) and the start / focus look (JSW-A2) -------------------- #
def test_a_stone_during_the_keepers_run_leaves_the_run_alone_and_looks_once_after_it_ends(gate, fired):
    # why: a stone moves no count, so the Generate in flight (a Finish's, or the keeper's own) is never thrown away
    # and started again for it — that put a Finish's Anki step off by a whole Generate. The run may have drawn the marks
    # before the stone (it signs the ones it drew), so the keeper looks once more after it ends; that look asks a run
    # only if the report still isn't current (here the check always says pending: the look is a second run).
    replan, _registry, _controller, launches, _opener = _replan(journey=lambda: True)
    keeper = replan.keeper
    keeper.changed("move")
    assert sh.until(lambda: launches.count() == 1, seconds=5)
    run = launches.runs[0]
    replan.stone_marked("ja")
    assert not run.cancel_event.is_set(), "the run in flight is never withdrawn for a stone"
    assert keeper.asked == 1 and launches.count() == 1
    run.ended(0)
    assert sh.until(lambda: launches.count() == 2, seconds=5), "one look after the run ended"
    assert fired.done(keeper) and keeper.asked == 2
    launches.runs[1].ended(0)
    assert fired.done(keeper) and keeper.asked == 2 and launches.count() == 2, "once: nothing more after the next run"
    replan.finish(time.monotonic() + 1)


def test_a_stone_during_a_run_that_reports_progress_still_leaves_the_run_alone(gate, fired):
    # why: a run that reports its steps is RUNNING while the stone waits; its progress line is a RUNNING delivery and
    # must not look (the look would withdraw the run). Only the run's end looks, once.
    replan, _registry, _controller, launches, _opener = _replan(journey=lambda: True)
    keeper = replan.keeper
    keeper.changed("move")
    assert sh.until(lambda: launches.count() == 1, seconds=5)
    run = launches.runs[0]
    replan.stone_marked("ja")
    run.feed(json.dumps({"type": "progress", "step": "Counting words", "done": None, "total": None}) + "\n")
    assert not sh.until(lambda: run.cancel_event.is_set(), seconds=1), "a RUNNING delivery never withdraws the run"
    assert not run.cancel_event.is_set()
    assert keeper.asked == 1 and launches.count() == 1
    run.ended(0)
    assert sh.until(lambda: launches.count() == 2, seconds=5), "one look after the run ended"
    assert fired.done(keeper) and keeper.asked == 2
    launches.runs[1].ended(0)
    assert fired.done(keeper) and keeper.asked == 2 and launches.count() == 2, "once: nothing more after the next run"
    replan.finish(time.monotonic() + 1)


def test_a_stone_with_no_run_in_flight_looks_at_once(gate, fired):
    # why: the deferral is only for a run going; with none, the stone's look is the one it always was
    replan, _registry, _controller, launches, _opener = _replan(journey=lambda: True)
    replan.stone_marked("ja")
    assert sh.until(lambda: launches.count() == 1, seconds=5) and fired.done(replan.keeper)
    assert replan.keeper.asked == 1
    replan.finish(time.monotonic() + 1)


class _Store:
    """The library store as the start's look reads it: the order hasn't moved since the last Generate."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def journey_pending(self):
        return False


def test_the_start_and_focus_look_asks_the_report_half_so_a_stone_marked_before_quit_shows(monkeypatch, gate):
    # why (JSW-A2): a stone with Keep studying on never moves `order_version`, so a stone marked in the last seconds
    # before quit (its keeper closed before the settle), or dropped before the window's services were made, left the
    # store saying "nothing pending" at the next start: the journey opened without it until some later move
    from app import library_store
    report = {"current": True}
    monkeypatch.setattr(library_store, "open_store", lambda *a, **k: _Store())
    monkeypatch.setattr(analyzer, "report_is_current", lambda args, language: report["current"])
    assert R.journey_pending("ja") is False, "nothing moved, the report current: no look"
    report["current"] = False
    assert R.journey_pending("ja") is True, "the report isn't current (the stone): the keeper looks"
    replan, _registry, _controller, _launches, _opener = _replan(pending=None, journey=lambda: False)
    heard = []
    real = replan.keeper.changed
    replan.keeper.changed = lambda reason="move": heard.append(reason) or real(reason)
    replan.start()
    assert replan.host.worker.idle(5)
    assert heard == ["start"], "the start's look (the default one) asks the report half"
    replan.activated()
    assert replan.host.worker.idle(5)
    assert heard == ["start", "start"], "...and so does a focus"
    replan.finish(time.monotonic() + 1)
