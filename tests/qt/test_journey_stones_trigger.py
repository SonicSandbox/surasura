"""JS-1's scenario tests, part 2: the window's trigger on a real library and real Generates (Sonic 2026-10-23: with
*Keep studying watched episodes* on, a mark or its Undo re-renders the journey at once, a quiet run with no
re-analysis — "This is a tricky one to double test that it doesn't conflict with other decisions"). Part 1
(tests/test_journey_stones_quiet.py) holds the quiet run itself; here the trigger starts it, wired as the window wires
it: the window's writer on the library store (`Writer.on_stone`, beside `on_counted`) -> `shell.Services._stone_marked`
-> `replan_host.Replan.stone_marked` -> the real `JourneyKeeper.changed("stone")`, whose real `_is_pending` asks both
halves (`analyzer.journey_is_current`, `analyzer.report_is_current`). The keeper's Generate is recorded (`_Launches`)
and run by the test as the window would start it (part 1's `_generate`: the analyzer in its own process), then ended
on the controller; the re-order host is a recorder (`_Opener`), so "Anki moved" is a host call.

  D1  (PROVISIONAL) Finish acts after its Generate: with the option on, a Finish (and its Undo) never takes the stone's
      path; a stone set before that Generate wakes the keeper, whose run is a full Generate (never a quiet re-render
      first), with nothing sent to Anki and the re-plan verdict generate-first "reference" until it lands; a mark on a
      Finished item asks the keeper once and runs nothing.
  D4  (the button half) after a mark with the option on the keeper is pending (the report half) until the quiet run,
      then not; a second press reopens and a second look runs nothing; the quiet run hands no new plan, so Anki isn't
      re-ordered for a stone. With the option off a mark takes the counting path only (no stone call beside it): one
      Generate, a re-analysis.

The keeper asks with the argv the test's Generates run (`--min-freq 1`: six short episodes; `run_args.analyzer_args`
stands in), so its two questions are the window's about the very run the test made. In tests/qt because the trigger is
`app.qt.shell`'s (PyQt6 imported; the harness keeps it offscreen), beside Mado's tests/qt/test_shell_stones.py.

Mutants M1-M6 on the trigger (JS1-tests2.md, js1-mutants.log) are killed here and by Mado's two files.
"""
import os
import time
from types import SimpleNamespace

import pytest

from app import analyzer, plan_engine, replan_preview, run_args
from app import library_store as ls
from app.qt import shell
from app.qt.strings import MOVE_WORDS as WORDS
from app.services import moves as M
from app.services import replan_host as R
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h
from tests.test_journey_stones import REUSED, _files, _library, _settings, _stones, _words
from tests.test_journey_stones_quiet import (RE_RENDER, UP_TO_DATE, _argv, _csvs, _current, _generate,  # noqa: F401
                                             _kept_on, _the_childs_token_store)  # (an autouse fixture)
from tests.test_library_store_support import LANGUAGES, roots
from tests.test_services_moves import Heard
from tests.test_services_replan_host import _Launches, _Opener, _replans, _Settings, fired, gate, landed  # noqa: F401


class _Window:
    """One language's window as `shell.Services` wires it: the writer on the library store, the Replan (its real
    keeper), every `changed` reason and `on_counted` call recorded."""

    def __init__(self, language):
        self.language = language
        self.registry = JobRegistry()
        self.controller = GenerateController(self.registry, settle=0)
        self.launches = _Launches()
        self.opener = _Opener()
        settings = _Settings(target_language=language, junban_replan_language=language)
        self.replan = R.Replan(self.registry, self.controller, settings, language, opener=self.opener,
                               pending=lambda language: False,
                               keeper_options={"launcher": self.launches, "battery": lambda: False})
        self.keeper = self.replan.keeper
        self.reasons = []
        real = self.keeper.changed
        self.keeper.changed = lambda reason="move": self.reasons.append(reason) or real(reason)
        self.heard = Heard()
        data_dir, user_files_dir = roots(language)
        self.writer = M.Writer(ls.StoreOpener(language, data_dir, user_files_dir, role="window"), language,
                               journal_file=M.journal_path(language), words=WORDS, retry=0.05, **self.heard.kw())
        self.writer.start()
        self.services = shell.Services(writer=self.writer, replan=self.replan)
        self.counted = []
        real_counted = self.writer.on_counted
        self.writer.on_counted = lambda: self.counted.append(1) or real_counted()

    def saved(self, n):
        assert h.until(lambda: len(self.heard.saved) == n) and self.writer.idle(5), self.heard.notes
        return self.heard.saved[-1][0]

    def undone(self, n):
        assert h.until(lambda: len(self.heard.undone) == n) and self.writer.idle(5), self.heard.notes

    def host_calls(self):
        """What the re-order host was asked (Anki's order): [] while none was opened."""
        assert self.replan.host.worker.idle(5)
        return [call for host in self.opener.hosts for call in host.calls]

    def generate_asked(self, root, n):
        """The keeper's n-th run (asked: recorded), run as the window starts it and ended on the controller ->
        (report data, what it printed)."""
        assert h.until(lambda: self.launches.count() == n, seconds=5), f"{self.launches.count()} Generates, not {n}"
        data, said = _generate(root, self.language)
        self.launches.runs[n - 1].ended(0)
        return data, said

    def close(self):
        self.writer.finish(time.monotonic() + 5)
        self.replan.finish(time.monotonic() + 1)


@pytest.fixture
def window(monkeypatch):
    made = []

    def make(language):
        # the keeper's argv is the test's Generates' (see the docstring): its two questions are about the run made
        monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **k: _argv(language))
        w = _Window(language)
        made.append(w)
        return w
    yield make
    for w in made:
        w.close()


def _verdict(root, language, store):
    """The re-order host's verdict on the plan the last Generate wrote, asked as it asks it (`replan_preview.Host`'s
    `_parts` and `_verdict`, the real functions): None current, ("replan-now", ...), ("generate-first", why)."""
    me = SimpleNamespace(language=language)
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))
    parts = replan_preview.Host._parts(me, {"target_language": language}, store)
    return replan_preview.Host._verdict(me, plan, parts, store)


def _journey_names(data):
    return set(_files(data) + [f["filename"] for f in data["completed_files"]])


# --- D1 · Finish acts after its Generate (PROVISIONAL) -------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d1_with_keep_studying_on_a_finish_waits_for_its_generate_and_a_stone_before_it_never_goes_first(
        language, window, gate, fired, landed):
    # why (D1, PROVISIONAL: a Finish acts after its Generate): a Finish moves what the journey counts, so Anki and the
    # re-plan wait for its Generate. A stone set in between wakes the keeper through the trigger; that must never turn
    # the Finish into a quiet re-render (its counts unanalysed, its stone drawn first) or into an early re-order
    store, ids, names, root, first = _kept_on(language)
    w = window(language)
    show_b = [ids[k] for k in ("B1", "B2", "B3")]
    w.writer.set_finished(show_b)
    w.saved(1)
    assert w.reasons == [] and w.counted == [], "a Finish is a tier move: never the stone's path"
    assert _verdict(root, language, store) == ("generate-first", "reference"), "Finished is set aside: a Generate first"
    assert w.keeper._is_pending() is True
    w.writer.set_watched([ids["A2"]])
    w.saved(2)
    assert w.reasons == ["stone"] and w.counted == [], "the stone: one look, the counting path never"
    assert fired.done(w.keeper)
    assert w.keeper.asked == 1 and h.until(lambda: w.launches.count() == 1, seconds=5), "one Generate asked"
    assert w.host_calls() == [] and _replans(w.registry) == [], "nothing sent to Anki before the Generate"
    assert _verdict(root, language, store) == ("generate-first", "reference"), "the stone moved no verdict"
    finished, said = w.generate_asked(root, 1)
    assert REUSED not in said, "the keeper's run is the Finish's Generate, a re-analysis — never a quiet re-render"
    assert not {names[k] for k in ("B1", "B2", "B3")} & _journey_names(finished), "Show B left the journey"
    assert _stones(finished) == {names["A2"]: False}, "and the stone drawn by that same run"
    assert h.until(lambda: landed.count() == 1)
    assert w.host_calls() == ["after_generate"], "Anki re-ordered after the Generate, once"
    assert _verdict(root, language, store) is None and w.keeper._is_pending() is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_d1_a_mark_on_a_finished_item_runs_nothing_and_the_finishs_undo_waits_for_its_generate(
        language, window, gate, fired):
    # why (D1): a stone on a Finished episode is in no journey (Finished is its own view): the trigger may look once
    # (Mado's PROVISIONAL: the writer knows no tiers), but the look finds both halves current and runs nothing. The
    # Finish's Undo brings Show B back to what counts: like the Finish, a tier move that waits for its Generate
    store, ids, names, root, first = _kept_on(language)
    w = window(language)
    show_b = [ids[k] for k in ("B1", "B2", "B3")]
    w.writer.set_finished(show_b)
    finish = w.saved(1)
    _finished, said = _generate(root, language)          # the Finish's own Generate (the user's press)
    assert REUSED not in said and w.keeper._is_pending() is False
    w.writer.set_watched([ids["B2"]])
    mark = w.saved(2)
    assert store.item(ids["B2"])["watched"] == 1
    assert w.reasons == ["stone"] and w.counted == [], "one look"
    assert fired.done(w.keeper)
    assert w.launches.count() == 0 and w.keeper.asked == 0, "a stone on a Finished item: no quiet run"
    assert _current(language) == (True, True)
    w.writer.undo(mark)
    w.undone(1)
    assert w.reasons == ["stone", "stone"] and fired.done(w.keeper)
    assert w.launches.count() == 0, "nor its Undo"
    w.writer.undo(finish)
    w.undone(2)
    assert w.reasons == ["stone", "stone"] and w.counted == [], "the Finish's Undo: never the stone's path"
    verdict = _verdict(root, language, store)
    assert verdict is not None and verdict[0] == "generate-first", verdict
    assert w.keeper._is_pending() is True and _current(language)[0] is False, "the analysis waits for its Generate"
    assert w.host_calls() == [], "nothing sent to Anki"
    back, said = _generate(root, language)
    assert REUSED not in said, "a re-analysis"
    assert {names[k] for k in ("B1", "B2", "B3")} <= set(_files(back)), "Show B counted again"
    assert back == first and w.keeper._is_pending() is False, "the journey exactly as before the Finish"
    store.close()


# --- D4 · Generate's "up to date", the button half ------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_d4_after_a_mark_the_keeper_is_pending_until_its_quiet_run_then_a_second_press_and_look_do_nothing(
        language, window, gate, fired, landed):
    # why (D4): the window's own check (`JourneyKeeper._is_pending`) must see the stone through the report half — the
    # analysis stays current by contract — and, once the quiet run drew it, see nothing: a second press reopens, a
    # second look runs nothing. D1's other half: the quiet run hands no new plan, so a stone never re-orders Anki
    store, ids, names, root, first = _kept_on(language)
    w = window(language)
    w.controller.request(language, argv=_argv(language), launcher=w.launches)  # the first Generate, the user's press
    assert h.until(lambda: w.launches.count() == 1, seconds=5)
    w.launches.runs[0].ended(0)
    assert h.until(lambda: landed.count() == 1) and w.host_calls() == ["after_generate"], "its plan handed on once"
    assert w.keeper._is_pending() is False, "a fresh Generate: nothing to run"
    w.writer.set_watched([ids["A2"]])
    w.saved(1)
    assert w.reasons == ["stone"] and w.counted == []
    assert _current(language) == (True, False) and w.keeper._is_pending() is True, "pending: the report half"
    assert fired.done(w.keeper) and w.keeper.asked == 1
    quiet, said = w.generate_asked(root, 2)
    assert REUSED in said and RE_RENDER in said, "the run it asked is the quiet one"
    assert _stones(quiet) == {names["A2"]: False}
    assert h.until(lambda: landed.count() == 2)
    assert w.host_calls() == ["after_generate"], "the quiet run's plan is the same plan: Anki not re-ordered"
    assert w.keeper._is_pending() is False, "drawn: not pending"
    _again, said = _generate(root, language)
    assert UP_TO_DATE in said and RE_RENDER not in said, "a second press reopens"
    w.keeper.changed("stone")
    assert fired.done(w.keeper) and w.launches.count() == 2 and w.keeper.asked == 1, "a second look runs nothing"
    w.writer.undo()
    w.undone(1)
    assert w.reasons == ["stone", "stone", "stone"] and w.keeper._is_pending() is True, "the Undo: pending again"
    assert fired.done(w.keeper) and w.keeper.asked == 2
    undone, said = w.generate_asked(root, 3)
    assert REUSED in said and RE_RENDER in said and undone == first
    assert w.keeper._is_pending() is False
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_d4_with_the_option_off_a_mark_takes_the_generate_path_and_never_the_stones(language, window, gate, fired):
    # why (D4, W-1b): the option off, a mark sets its episode aside — the counting path (`on_counted`, and the reader's
    # `order_version`, here `store_moved` as the reader calls it) — so the keeper asks one Generate, a re-analysis;
    # a stone call beside it would be a second look for the same mark
    root = os.environ["SURASURA_TEST_ROOT"]
    _settings(language)
    store, ids, names = _library(language)
    _first, said = _generate(root, language)
    w = window(language)
    w.writer.set_watched([ids["A2"]])
    w.saved(1)
    assert w.counted == [1] and w.reasons == [], "the counting path alone"
    assert _current(language)[0] is False and w.keeper._is_pending() is True, "pending: the analysis half"
    w.replan.store_moved(language, {"order_version": None})     # the reader's look sees the order_version move
    assert w.reasons == ["store"] and fired.done(w.keeper)
    marked, said = w.generate_asked(root, 1)
    assert REUSED not in said, "a re-analysis"
    assert _stones(marked) == {names["A2"]: True} and _words(marked, names["A2"]) == []
    w.writer.undo()
    w.undone(1)
    assert w.counted == [1, 1] and w.reasons == ["store"], "its Undo: the counting path again, no stone call"
    assert w.keeper.asked == 1
    store.close()
