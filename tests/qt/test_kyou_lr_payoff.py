"""Kyou-LR — the review loop's payoff in the window (the WL mocks' 03-payoff-toast; words PROVISIONAL).

After a known-words sync that read the learner's moves in Anki, the window says once *From your phone: 3 known · 2 to
swap · 1 ignored* with *Undo* (that sync's moves, through the automation's worker), its tooltip that a synced card may
be deleted; the same sync's state again shows nothing new; another language's sync isn't shown here. The service side:
a sync's result with moves publishes them (`AutoSync.ended`), one without publishes none.

What a wrong answer would cost: a toast every five minutes for the same moves, an Undo that undoes another sync, or a
learner never told what their phone did. A stand-in automation (tests/qt/test_jobs_bar.py's World), never a live sync.
"""
import pytest

pytest.importorskip("PyQt6")

from app import anki_sync
from app.qt import strings
from app.services import automation as A
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import World


@pytest.fixture
def world(qapp, tmp_path):
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    yield w
    w.close()


def _state(payoff, seq=1):
    return A.State(A.SYNCED, "ja", 0, 1200, None, None, seq, None, payoff)


def test_the_payoff_toasts_once_with_undo_for_that_sync_and_its_tooltip(world):
    asked = []
    world.automation.undo_payoff = lambda language, sync_id, then=None: asked.append((language, sync_id))
    win = world.win
    win._show_automation(_state(("ja", "1732000000000", 3, 2, 1)))
    assert win.toasts.text == "From your phone: 3 known · 2 to swap · 1 ignored"
    assert win.toasts.card.toolTip() == strings.LOOP_PAYOFF_TIP
    win.toasts.card._press(0)                                         # its one button: Undo
    assert asked == [("ja", "1732000000000")]
    win.toasts.show("something else")
    win._show_automation(_state(("ja", "1732000000000", 3, 2, 1), seq=2))   # the same sync again: nothing new
    assert win.toasts.text == "something else" and win.toasts.card.toolTip() == ""


def test_the_undos_answer_is_said_and_another_languages_sync_is_not_shown_here(world):
    world.automation.undo_payoff = lambda language, sync_id, then=None: then({"undone": True})
    win = world.win
    win._show_automation(_state(("zh", "1", 1, 0, 0)))
    assert win.toasts.text != strings.LOOP_PAYOFF.format(known=1, swap=0, ignored=0)
    win._show_automation(_state(("ja", "2", 0, 0, 4), seq=2))
    win.toasts.card._press(0)
    assert wait_until(lambda: win.toasts.text == strings.LOOP_UNDONE)


class _Owner:
    """AutoSync's owner, as far as `ended` reads it."""

    def __init__(self):
        self.language, self.published = "ja", []
        self.worker = type("W", (), {"put": lambda self, *a: True})()

    def clock(self):
        return 0.0

    def publish(self, **changes):
        self.published.append(changes)


def test_a_sync_with_moves_publishes_them_and_one_without_publishes_none():
    owner = _Owner()
    sync = A.AutoSync(owner)
    moved = anki_sync.SyncResult(added=3, total_known=40)
    moved.loop = {"sync": "9", "known": 3, "swap": 2, "ignored": 1, "unknown": 0}
    sync.ended(moved, "ja")
    assert {"payoff": ("ja", "9", 3, 2, 1)} in owner.published
    owner.published.clear()
    sync.ended(anki_sync.SyncResult(added=0, total_known=40), "ja")
    assert not [p for p in owner.published if "payoff" in p]
