"""A2 (Sonic 2026-11-06, "into 3.0"; the generate-speed study): *Journey ↗* never waits for a background run, and the
journey's readers ask for its catch-up (`Services.journey_brought`, `draw_journey`, `journey_for_reading`, the export).

What a wrong answer would cost a learner: *Journey ↗* frozen for up to a minute after a burst of moves (the old
`JOURNEY_DRAW_WAIT` behind a background Generate); or a press that opens the journey and never brings its sentences in;
or an export written from lists one burst behind the order the window shows.

The keeper is the real `JourneyKeeper` on a real `GenerateController` whose runs are recorded, never launched; the
analyzer's two questions are the test's (`halves`), so each case says what the analyzer would answer.
"""
import os
import threading
import time
from types import SimpleNamespace

from app import analyzer, run_args
from app.qt import settings_live, shell
from app.services import generate as G
from app.services import journey as J
from app.services.generate import GenerateController
from app.services.jobs import JobRegistry
from tests import services_helpers as h
from tests.test_services_journey import _Launches

SETTLE = {"journey_settle_s": 0.3, "journey_settle_battery_s": 0.3}


class _World:
    """The services' parts `draw_journey` and `journey_for_reading` read, the replan's three journey calls on a real
    keeper (`Replan.journey_wanted` / `journey_background` / `journey_catching_up` are the keeper's own)."""

    def __init__(self, monkeypatch, moves_only=True):
        self.halves = {"journey": False, "report": False}
        monkeypatch.setattr(run_args, "analyzer_args", lambda settings, language=None, **_k: ["analyzer.py"])
        monkeypatch.setattr(analyzer, "report_is_current", lambda _a, _l: self.halves["report"])
        monkeypatch.setattr(analyzer, "journey_is_current", lambda _a, _l: self.halves["journey"])
        self.launches = _Launches()
        self.controller = GenerateController(JobRegistry(), settle=0)
        self.keeper = J.JourneyKeeper(self.controller, "ja", settings=lambda: dict(SETTLE), battery=lambda: False,
                                      launcher=self.launches, only_moved=lambda: moves_only, catch_up=60.0,
                                      plan_path=os.path.join(h.root(), "no-plan.json.gz"))
        replan = SimpleNamespace(journey_wanted=self.keeper.want, journey_background=self.keeper.background_run,
                                 journey_catching_up=self.keeper.catching_up)
        self.asked = 0
        services = SimpleNamespace(closing=threading.Event(), controller=self.controller, language="ja",
                                   settings=SimpleNamespace(get=lambda: {"target_language": "ja"}),
                                   generate=self.generate, replan=replan)
        services.journey_brought = lambda reason: shell.Services.journey_brought(services, reason)
        services.journey_for_reading = lambda reason, wait=30: shell.Services.journey_for_reading(services, reason,
                                                                                                 wait)
        self.services = services

    def generate(self):
        self.asked += 1
        return self.controller.request("ja", argv=["analyzer.py"], launcher=self.launches)

    def draw(self, wait=30):
        started = time.monotonic()
        answer = shell.Services.draw_journey(self.services, wait=wait)
        return answer, time.monotonic() - started

    def close(self):
        self.keeper.close()


def test_after_moves_journey_opens_at_once_and_asks_the_catch_up(monkeypatch):
    # the moves' journey waits for a reader: the press opens it as it is (the ● says it catches up) and asks the run
    w = _World(monkeypatch)
    try:
        w.keeper.changed("store")
        assert h.until(w.keeper.catching_up, seconds=5)
        assert w.launches.count() == 0
        answer, took = w.draw()
        assert answer is None and took < 0.5, (answer, took)
        assert h.until(lambda: w.launches.count() == 1, seconds=3), "the press asked the catch-up"
        assert w.launches.runs[0].quiet and w.asked == 0, "the keeper's background run, not a run of the press's own"
    finally:
        w.close()


def test_journey_never_waits_for_a_background_run_in_flight(monkeypatch):
    # the old wait: up to a minute behind the keeper's Generate — now the press opens at once
    w = _World(monkeypatch, moves_only=False)
    try:
        w.keeper.changed("store")
        assert h.until(lambda: w.launches.count() == 1, seconds=5)
        assert w.controller.state().state in J.IN_FLIGHT
        answer, took = w.draw()
        assert answer is None and took < 0.5, (answer, took)
        assert w.launches.count() == 1 and w.asked == 0, "nothing more asked"
    finally:
        w.close()


def test_journey_still_waits_for_the_users_own_generate(monkeypatch):
    # not a background run: the press waits for the user's Generate as before (a6 #5), then opens
    w = _World(monkeypatch, moves_only=False)
    try:
        user = w.controller.request("ja", argv=["analyzer.py"], launcher=w.launches)
        assert h.until(lambda: w.launches.count() == 1, seconds=5)
        done = []
        t = threading.Thread(target=lambda: done.append(w.draw()), daemon=True)
        t.start()
        time.sleep(0.5)
        assert not done, "waits for the user's run"
        w.halves.update(journey=True, report=True)
        user.ended(0)
        t.join(5)
        assert done and done[0][0] is None
    finally:
        w.close()


def test_an_export_waits_for_the_catch_up_it_asked_for(monkeypatch):
    # an export has no ● of its own: it asks the catch-up and writes once it has landed
    w = _World(monkeypatch)
    try:
        w.keeper.changed("store")
        assert h.until(w.keeper.catching_up, seconds=5)
        order = []
        monkeypatch.setattr("app.exports.frequency_list",
                            lambda language, fmt, dest: order.append(("export", w.launches.count(),
                                                                      w.controller.state().state)) or "done")
        t = threading.Thread(target=lambda: order.append(
            settings_live.run_export("frequency_list", "ja", "txt", "out.txt", w.services)), daemon=True)
        t.start()
        assert h.until(lambda: w.launches.count() == 1, seconds=3), "the export asked the catch-up"
        time.sleep(0.4)
        assert order == [], "and waits for it"
        w.halves.update(journey=True, report=True)
        w.launches.runs[0].ended(0)
        t.join(5)
        assert order and order[0][0] == "export" and order[0][2] == G.CURRENT and order[-1] == "done"
    finally:
        w.close()


def test_an_export_with_nothing_owed_runs_at_once(monkeypatch):
    w = _World(monkeypatch)
    try:
        monkeypatch.setattr("app.exports.frequency_list", lambda language, fmt, dest: "done")
        started = time.monotonic()
        assert settings_live.run_export("frequency_list", "ja", "txt", "out.txt", w.services) == "done"
        assert time.monotonic() - started < 0.5 and w.launches.count() == 0
        assert settings_live.run_export("frequency_list", "ja", "txt", "out.txt") == "done", "no services: as before"
    finally:
        w.close()


def test_before_the_duties_are_made_nothing_is_brought():
    services = SimpleNamespace(replan=None)
    assert shell.Services.journey_brought(services, "journey") is False


def test_after_moves_and_the_users_generate_journey_waits_for_that_run(monkeypatch):
    # R1: the journey was catching up, then the user pressed Generate: the press waits for that run (a6 #5), never
    # opens the old journey at once
    w = _World(monkeypatch)
    try:
        w.keeper.changed("store")
        assert h.until(w.keeper.catching_up, seconds=5)
        user = w.controller.request("ja", argv=["analyzer.py"], launcher=w.launches)
        assert h.until(lambda: w.launches.count() == 1, seconds=5)
        done = []
        t = threading.Thread(target=lambda: done.append(w.draw()), daemon=True)
        t.start()
        time.sleep(0.5)
        assert not done, "waits for the user's run"
        w.halves.update(journey=True, report=True)
        user.ended(0)
        t.join(5)
        assert done and done[0][0] is None
    finally:
        w.close()


def test_an_export_a_moment_after_a_move_waits_for_its_catch_up(monkeypatch):
    # R2: the export pressed before the keeper's first look: it still asks the catch-up and waits for it
    w = _World(monkeypatch)
    try:
        w.keeper._settings = lambda: dict(SETTLE, journey_settle_s=20.0)
        w.keeper.changed("store")
        order = []
        monkeypatch.setattr("app.exports.frequency_list",
                            lambda language, fmt, dest: order.append(w.controller.state().state) or "done")
        t = threading.Thread(target=lambda: settings_live.run_export("frequency_list", "ja", "txt", "out.txt",
                                                                     w.services), daemon=True)
        t.start()
        assert h.until(lambda: w.launches.count() == 1, seconds=8), "asked at once, not after the 20 s quiet time"
        time.sleep(0.3)
        assert order == [], "waits for the run"
        w.halves.update(journey=True, report=True)
        w.launches.runs[0].ended(0)
        t.join(5)
        assert order == [G.CURRENT]
    finally:
        w.close()
