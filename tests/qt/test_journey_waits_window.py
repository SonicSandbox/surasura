"""A plain move is never a Generate, wired as the window wires it (Sonic 2026-11-06, "into 3.0"; the generate-speed
study's A; F7: the journey redrawn from the plan instead): the window's writer on a real library store -> the reader's `Replan.store_moved` -> the re-order host (a
recorder: "Anki moved" is its `poke`) and the real `JourneyKeeper`, whose real `pending` and real `only_moved` ask the
analyzer and the plan file the last Generate wrote. The keeper's Generate is recorded (`_Launches`), never run.

The work count of the move press: a burst of drags costs zero Generates — the re-order host is still told every one
(the engine re-orders Anki without a Generate) — and one redraw of the journey from the plan once the drags stop. A
Finish, the other way, still asks its Generate — Anki re-ordered at once, the watched mark's rule (Haya-FN) — (D1's
test in tests/qt/test_journey_stones_trigger.py runs it whole).
"""
import pytest

from app.services import journey as J
from tests import services_helpers as h
from tests.qt.test_journey_stones_trigger import _verdict, window  # noqa: F401 (a fixture)
from tests.test_journey_stones_quiet import _current, _kept_on, _the_childs_token_store  # noqa: F401 (autouse)
from tests.test_library_store_support import LANGUAGES
from tests.test_services_replan_host import fired, gate  # noqa: F401 (fixtures)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_burst_of_move_presses_starts_zero_generates_and_one_redraw(language, window, gate, fired):
    store, ids, _names, root, _first = _kept_on(language)
    w = window(language)
    order = [ids[k] for k in ("A1", "A2", "A3", "B1", "B2", "B3")]
    for n, item in enumerate(order[1:], 1):                # five drags, each to the top of NOW: the order reversed
        w.writer.move([item], "now")
        w.saved(n)
        w.replan.store_moved(language, {"order_version": None})   # the reader's look sees the order move
    assert _verdict(root, language, store) is None, "the plan is the library's in all but the order"
    assert _current(language)[0] is False, "the journey is owed the moves"
    assert h.until(lambda: w.launches.count() == 1, seconds=10), "the drags stopped: one run"
    assert w.keeper.asked == 1
    assert w.launches.runs[0].quiet and J.REDRAW_ARG in w.launches.runs[0].argv, "the redraw, never a Generate"
    assert w.host_calls().count("poke") == 5, "Anki re-ordered from the engine for every drag"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES[:1])
def test_a_finish_press_re_orders_anki_at_once_and_still_asks_its_generate(language, window, gate, fired):
    store, ids, _names, root, _first = _kept_on(language)
    w = window(language)
    w.writer.set_finished([ids["B3"]])
    w.saved(1)
    w.replan.store_moved(language, {"order_version": None})
    assert _verdict(root, language, store) == ("replan-now", ("files-removed", "reference-joined"))
    assert w.host_calls().count("poke") == 1, "Anki re-ordered from the engine at once (Haya-FN)"
    assert fired.done(w.keeper)
    assert h.until(lambda: w.launches.count() == 1, seconds=10), "a Finish moves what counts: its Generate"
    assert J.REDRAW_ARG not in w.launches.runs[0].argv, "a Generate, never the redraw: the list's edge"
    assert not w.keeper.catching_up()
    store.close()
