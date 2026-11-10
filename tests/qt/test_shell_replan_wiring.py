"""The window's wiring of the re-order host (`Services` in app/qt/shell.py), the two promises its route tests leave open:
the host is wired to the update and the library reader once, however often the duties are provided, and the quit
sends the host's `stop()` before it gives up on the duties' close.

What a wrong answer would cost a learner: every move of a file re-ordering Anki twice (two pokes, two keeper changes),
or a quit that walks away from a helper still writing to Anki without ever telling it to stop.
"""
import time

from app.qt import shell
from app.services.jobs import JobRegistry
from app.services.status import StatusService
from tests.qt.test_jobs_bar import FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader


class _Replan:
    def __init__(self):
        self.calls = []
        self.deadline = None

    def start(self): self.calls.append("start")
    def activated(self): self.calls.append("activated")
    def store_moved(self, language, versions=None): self.calls.append(("store_moved", language))
    def language_changed(self, language): self.calls.append(("language_changed", language))
    def update_state(self, state): self.calls.append(("update_state", state))
    def closing(self): self.calls.append("closing")
    def line(self): return None

    def finish(self, deadline):
        self.calls.append("finish")
        self.deadline = deadline
        return True


class _Library:
    def __init__(self):
        self.moves = []

    def subscribe_moves(self, cb):
        self.moves.append(cb)

    def stop(self, timeout=None):
        pass


def _services(replan, library=None):
    log = []
    registry = JobRegistry()
    status = StatusService(registry, reader=QuietReader())
    services = shell.Services(registry=registry, status=status, controller=FakeController(log),
                              updates=FakeUpdates(log), automation=FakeAutomation(log), chores=FakeChores(log),
                              library=library, replan=replan)
    return services


def test_the_duties_provided_again_wire_the_replan_to_the_reader_once(qapp):
    """The window makes its duties (`make_duties`) on services that were given them: the library reader's moves still
    reach the re-order host once — one move of a file is one poke, never two."""
    replan, library = _Replan(), _Library()
    services = _services(replan, library)
    services.make_duties()
    services.make_duties()
    assert len(library.moves) == 1, "the reader's moves were wired more than once"
    services.start()
    for cb in library.moves:
        cb("ja", {"order_version": 4})
    assert replan.calls.count(("store_moved", "ja")) == 1
    services.shutdown(0.05)


def test_the_quit_stops_the_host_before_it_gives_up_on_the_close(qapp):
    """The host's deadline at quit falls strictly before the duties' close cap, counted from the quit's own clock: its
    `stop()` is sent while the quit still waits, so a helper still writing is told to stop rather than abandoned."""
    replan = _Replan()
    services = _services(replan)
    services.start()
    t0 = time.monotonic()
    services.shutdown(0.05)
    assert replan.deadline is not None
    assert replan.deadline < t0 + shell.QUIT_CLOSE_WAIT, "the host's stop is due only when the close is given up"
