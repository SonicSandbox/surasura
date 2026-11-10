"""Alpha 6 (Minato, recording the README demo, 2026-10-29): after Generate ended, Current's rows kept *not analysed yet*
(no *% known*, no *N new*) until the next change to the library. The numbers (`moves.Numbers`) re-read the plan only
when the store's order moved (`moves.open_library`'s `subscribe_moves`) or the window's own drop asked; a Generate
writes a new plan and moves no order, so nothing asked. Not the demo root's: a fresh root's first Generate does it, with
automatic Generate on and off. Now `shell.Services` hears the Generate controller's end (`on_end`) and asks the numbers
again after every run that finished.

What a wrong answer would cost a learner: their very first Generate seems to have done nothing — every row still says
*not analysed yet* — until they happen to drag something; or (the other way) the plan read again after a run that
failed, stopped or never started.

The scenario half is the real window on a fresh test root (tests/test_journey_stones' Show A and Show B in Now, cut from
the bundled samples' real Japanese), its own Generate (the controller's real launch, the analyzer in its own process).
"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from app import path_utils, run_args
from app.qt import bridge, shell
from tests.qt.conftest import wait_until
from tests.test_journey_stones import _library
from tests.test_journey_stones_quiet import _argv, _the_childs_token_store  # noqa: F401  (an autouse fixture)


# --- the rule --------------------------------------------------------------------------------------------------------- #
class _Controller:
    def __init__(self):
        self.ends = []

    def on_end(self, callback):
        self.ends.append(callback)

    def end(self, outcome):
        for callback in self.ends:
            callback(SimpleNamespace(language="ja"), outcome)


class _Numbers:
    def __init__(self, fails=False):
        self.asked, self.fails = 0, fails

    def resync(self):
        self.asked += 1
        if self.fails:
            raise RuntimeError("its worker is closed")


def _services(numbers):
    controller = _Controller()
    services = shell.Services(controller=controller, updates=SimpleNamespace(failure=lambda: None),
                              writer=SimpleNamespace(numbers=numbers, language="ja"))
    services._provide()                               # (the duties' wiring, as `make_duties` ends it)
    return services, controller


@pytest.mark.parametrize("outcome, asked", [("current", 1), ("failed", 0), ("stale", 0), ("dropped", 0)])
def test_only_a_generate_that_finished_asks_the_numbers_again(outcome, asked):
    # why: "current" is the one end that wrote a new plan; a failed, stopped or never-started run left the old one
    numbers = _Numbers()
    services, controller = _services(numbers)
    services._provide()                               # wired again (a second call): heard once, never twice
    assert len(controller.ends) == 1
    controller.end(outcome)
    assert numbers.asked == asked


def test_after_the_quit_began_or_with_no_writer_a_finished_generate_asks_nothing_and_never_raises():
    numbers = _Numbers()
    services, controller = _services(numbers)
    services.closing.set()                            # the quit: the numbers' worker is going
    controller.end("current")
    assert numbers.asked == 0
    services.closing.clear()
    services.writer = None                            # a library that couldn't be opened
    controller.end("current")
    failing = _Numbers(fails=True)
    services.writer = SimpleNamespace(numbers=failing)
    controller.end("current")                         # said in the log, never raised into the run's thread
    assert failing.asked == 1


# --- the scenario: a fresh root, the window's own Generate -------------------------------------------------------- #
@pytest.mark.parametrize("automatic", [True, False])
def test_a_fresh_roots_first_generate_shows_every_rows_numbers_without_another_change(qapp, monkeypatch, automatic):
    # why: the learner's first start — the library placed, no plan yet, so every row says *not analysed yet* — then
    # Generate. Its end must bring each episode's *% known* by itself, automatic Generate on or off
    monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **k: _argv(language))
    with open(path_utils.get_user_file("settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": "ja", "logic": {"automation": automatic}}, f)
    store, _ids, _names = _library("ja")
    services = shell.open_services()
    win = shell.open_window(qapp, services)
    win.first_frame.connect(win.start_duties)         # as main() connects them
    win.first_frame.connect(services.load_numbers)
    win.resize(1280, 900)
    win.show_first()
    try:
        page = win.page_widgets["current"]
        numbers = services.writer.numbers

        def pcts():
            return [e.pct for row in page.view_model.rows for e in row.episodes]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 20)
        assert wait_until(lambda: numbers.why() == "no plan: Generate first", 20)
        assert len(pcts()) == 6 and set(pcts()) == {None}, "before: every episode not analysed yet"
        assert wait_until(lambda: services.has_duties() and win.duties is not None, 20)
        bridge.run_in_worker(services.generate)
        assert wait_until(lambda: services.controller.state().state == "current", 180), services.controller.state()
        assert wait_until(lambda: None not in pcts(), 20), (numbers.why(), pcts())
        assert numbers.why() is None, "N new follows the new plan"
        assert all(0 < p < 100 for p in pcts())
    finally:
        win.close()
        services.shutdown(2.0)
        store.close()
