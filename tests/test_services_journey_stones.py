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
import os

import pytest

from app import analyzer, run_args
from app.services import journey as J
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


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
