"""The journey's stones, the window's trigger (JS-1, Sonic 2026-10-23: the lean, "double test it doesn't conflict with
other decisions"): with *Keep studying watched episodes* on, a watched mark moves no run input — no `order_version`,
so the library reader's moves never tell the journey keeper — yet the report shows the stone. The window's writer
says so itself (`Writer.on_stone`, after a mark or its undo that moved nothing that counts), the window passes it on
(`shell.Services._stone_marked` → `replan_host.Replan.stone_marked` → `keeper.changed("stone")`), and the keeper's
check asks the report half too (`tests/test_services_journey_stones.py`).

What a wrong answer would cost a learner: a stone he set that the journey doesn't show until something else runs a
Generate (or a stone still showing after its Undo); or, the other way, every counted mark asking the keeper twice (its
own `order_version` path already does), each a needless look at the library.

The writes run on a real `library_store` (`test_services_moves`' migrated library, Japanese and Chinese), the keeper
is the real `JourneyKeeper` inside a real `Replan`, its `changed` recorded.
"""
import time

from app.qt import shell
from tests import services_helpers as h
from tests.test_services_moves import Recorder, lib, make_writer  # noqa: F401 (fixtures)
from tests.test_services_replan_host import _Settings, _replan, gate  # noqa: F401 (a fixture)


def _wired(lib, make_writer):
    """The window's writer, its replan and its services as the window wires them (`Services._wire_writer`). -> (writer,
    heard, the keeper's `changed` reasons, the writer's `on_counted` calls, replan)."""
    replan, _registry, _controller, _launches, _opener = _replan(_Settings(target_language=lib.language),
                                                                 language=lib.language, journey=lambda: False)
    reasons = []
    real = replan.keeper.changed
    replan.keeper.changed = lambda reason="move": reasons.append(reason) or real(reason)
    w, heard = make_writer(numbers=Recorder())
    services = shell.Services(writer=w, replan=replan)
    counted = []
    real_counted = w.on_counted
    w.on_counted = lambda: counted.append(1) or real_counted()
    assert services.writer is w
    return w, heard, reasons, counted, replan


def test_with_keep_studying_on_a_mark_and_its_undo_each_tell_the_journey_keeper_once(lib, make_writer, gate):
    # why: the option on, a stone is a status write (no `order_version`): only the writer can say the report moved
    w, heard, reasons, counted, replan = _wired(lib, make_writer)
    lib.store.set_library_options(keep_watched=True)
    now = lib.ids("now")
    w.set_watched([now[0]], True)
    assert h.until(lambda: len(heard.saved) == 1)
    assert w.idle(5)
    assert lib.store.item(now[0])["watched"] == 1
    assert reasons == ["stone"] and counted == [], "one look for the stone, the counting path never"
    w.undo()
    assert h.until(lambda: len(heard.undone) == 1)
    assert w.idle(5)
    assert lib.store.item(now[0])["watched"] == 0
    assert reasons == ["stone", "stone"] and counted == [], "its undo: one look more"
    replan.finish(time.monotonic() + 1)


def test_with_keep_studying_off_a_mark_takes_the_counting_path_and_never_the_stones(lib, make_writer, gate):
    # why: the option off, a stone moves `order_version` (the reader's moves tell the keeper): a second look is waste
    w, heard, reasons, counted, replan = _wired(lib, make_writer)
    now = lib.ids("now")
    w.set_watched([now[0]], True)
    assert h.until(lambda: len(heard.saved) == 1)
    assert w.idle(5)
    assert counted == [1] and reasons == [], "counted: the order_version path, no stone call"
    w.undo()
    assert h.until(lambda: len(heard.undone) == 1)
    assert w.idle(5)
    assert counted == [1, 1] and reasons == []
    replan.finish(time.monotonic() + 1)


def test_a_stone_tells_only_the_keeper_of_its_own_language_and_nothing_once_the_quit_began(lib, make_writer, gate):
    # why: a language switch leaves the old writer finishing its queue: its stone is never the new journey's; at quit,
    # nothing more is asked
    w, heard, reasons, counted, replan = _wired(lib, make_writer)
    other = "zh" if lib.language == "ja" else "ja"
    replan.stone_marked(other)
    assert reasons == []
    replan.stone_marked(lib.language)
    assert reasons == ["stone"]
    services = shell.Services(writer=w, replan=replan)
    services.closing.set()
    services._stone_marked(lib.language)
    assert reasons == ["stone"]
    replan.finish(time.monotonic() + 1)
