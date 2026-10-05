"""The Anki-write lock in core (E1.4 §W): `anki_connect.writer` / `take_writer` and the read list.

What a wrong answer would cost, in order:
  * a write that races another writer — every action off `READ_ACTIONS` is refused unless the calling
    thread holds the lock (failing closed, before a socket opens): one per family here, alone and
    inside a `multi`, and from a second thread while the first holds it;
  * a write that starts as an update begins — refused while an update waits, before the take and again
    right after it (a writer that waited minutes);
  * a delayed write landing mid-review, or a Restore of a snapshot replaced while it waited;
  * an update that exits mid-write — the dashboard's wait names the writer, once.

The writers themselves (順, Backfill, the automatic step, the windows, two processes): Junban's suite,
`modules/junban/tests/test_anki_writer_lock.py`.
"""
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app import anki_connect, locks, updater
from tests.test_anki_sync_wiring import _DashboardHarness

URL = anki_connect.DEFAULT_URL

# One write action per family Anki has: positions, fields, suspension, tags, notes, decks.
WRITES = [
    ("setSpecificValueOfCard", {"card": 1789712080047, "keys": ["due"], "newValues": [2944]}),
    ("updateNoteFields", {"note": {"id": 1789712000000, "fields": {"Patterns": "〜に 34%"}}}),
    ("suspend", {"cards": [1789712080047]}),
    ("addTags", {"notes": [1789712000000], "tags": "Surasura::later"}),
    ("deleteNotes", {"notes": [1789712000000]}),
    ("deleteDecks", {"decks": ["TheBank"], "cardsToo": True}),
]


class _Anki:
    """A patched `urlopen`: answers like a healthy AnkiConnect, records each action it was sent."""

    def __init__(self, reviewing=False):
        self.actions = []
        self.reviewing = reviewing

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        self.actions.append(payload["action"])
        result = {"guiReviewActive": self.reviewing, "multi": []}.get(payload["action"])
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"result": result, "error": None}).encode()
        return response


@pytest.fixture(autouse=True)
def _no_update_waiting():
    yield
    updater.release_children(start=False)


def _holder(verb="Backfill"):
    """Another thread holding the lock until the returned Event is set."""
    taken, done = threading.Event(), threading.Event()

    def hold():
        with anki_connect.writer(verb):
            taken.set()
            done.wait(10)
    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert taken.wait(5)
    return done, thread


# --- the read list ------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("action, params", WRITES)
def test_a_write_action_without_the_lock_is_refused_before_a_socket_opens(action, params):
    fake = _Anki()
    with patch("urllib.request.urlopen", fake):
        with pytest.raises(anki_connect.AnkiError) as caught:
            anki_connect.invoke(action, URL, **params)
        assert caught.value.kind == "refused"
        with pytest.raises(anki_connect.AnkiError):         # smuggled inside a batch, nested too
            anki_connect.multi([{"action": "findCards", "params": {"query": "deck:TheBank"}},
                                {"action": "multi", "params": {"actions": [{"action": action, "params": params}]}}],
                               URL)
    assert fake.actions == []


@pytest.mark.parametrize("action, params", WRITES)
def test_a_write_action_from_a_second_thread_is_refused_while_the_first_holds_the_lock(action, params):
    fake, refused = _Anki(), []
    with patch("urllib.request.urlopen", fake), anki_connect.writer("順 reorder"):
        def other():
            try:
                anki_connect.invoke(action, URL, **params)
            except anki_connect.AnkiError as e:
                refused.append(e.kind)
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(5)
        anki_connect.invoke(action, URL, **params)          # the holder's own thread sends it
    assert refused == ["refused"] and fake.actions == [action]


def test_every_read_is_sent_without_the_lock():
    fake = _Anki()
    with patch("urllib.request.urlopen", fake):
        for action in sorted(anki_connect.READ_ACTIONS):
            anki_connect.invoke(action, URL)
        anki_connect.multi([{"action": "findCards", "params": {"query": "deck:TheBank is:new"}},
                            {"action": "notesInfo", "params": {"notes": [1789712000000]}}], URL)
    assert fake.actions == sorted(anki_connect.READ_ACTIONS) + ["multi"]


def test_the_forbidden_two_stay_refused_even_with_the_lock():
    with patch("urllib.request.urlopen", _Anki()) as fake, anki_connect.writer("順 reorder"):
        for action in sorted(anki_connect.FORBIDDEN_ACTIONS):
            with pytest.raises(anki_connect.AnkiError):
                anki_connect.invoke(action, URL)
    assert fake.actions == []


# --- the update's wait --------------------------------------------------------------------------------- #
def test_an_update_waiting_refuses_a_new_writer_before_the_take():
    updater.hold_children()
    with pytest.raises(locks.Busy) as caught:
        anki_connect.writer("順 reorder")
    assert caught.value.holder == {"verb": "an update"}
    assert locks.read_holder(anki_connect.WRITER_LOCK) is None, "the lock was never taken"
    assert anki_connect.busy_message(caught.value).startswith("An update is waiting")


def test_an_update_that_began_during_the_wait_refuses_right_after_the_take():
    done, thread = _holder()
    answer = {}

    def waiter():
        try:
            anki_connect.writer("順 reorder", wait=None)
        except locks.Busy as e:
            answer["busy"] = e.holder
    worker = threading.Thread(target=waiter)
    worker.start()
    time.sleep(0.3)
    updater.hold_children()            # "Update now", while the 順 window waits for Backfill
    done.set()
    thread.join(5)
    worker.join(5)
    assert answer["busy"] == {"verb": "an update"}
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None, "released before refusing"


# --- after a wait ------------------------------------------------------------------------------------- #
def _after_wait(fake, changed=None):
    done, thread = _holder()
    threading.Timer(0.3, done.set).start()
    with patch("urllib.request.urlopen", fake):
        held, problem = anki_connect.take_writer("順 reorder", URL, wait=5, changed=changed)
    thread.join(5)
    return held, problem


def test_after_a_wait_the_user_reviewing_refuses():
    fake = _Anki(reviewing=True)
    held, problem = _after_wait(fake)
    assert held is None and problem == anki_connect.REVIEWING
    assert fake.actions == ["guiReviewActive"]
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


def test_after_a_wait_a_changed_snapshot_refuses():
    held, problem = _after_wait(_Anki(), changed=lambda: True)
    assert held is None and problem == anki_connect.CHANGED


def test_after_a_wait_with_nothing_changed_the_writer_holds_it():
    held, problem = _after_wait(_Anki(), changed=lambda: False)
    try:
        assert problem is None and held.waited and locks.held_here(anki_connect.WRITER_LOCK)
    finally:
        held.release()


def test_uncontended_nothing_is_asked():
    fake = _Anki(reviewing=True)
    with patch("urllib.request.urlopen", fake):
        held, problem = anki_connect.take_writer("順 reorder", URL, changed=lambda: True)
    held.release()
    assert problem is None and fake.actions == []


def test_held_elsewhere_the_refusal_names_the_writer_and_since_when():
    done, thread = _holder("the automatic 順 step")
    try:
        held, problem = anki_connect.take_writer("Backfill", URL)
    finally:
        done.set()
        thread.join(5)
    assert held is None
    assert problem.startswith("The automatic 順 step is writing to Anki (since ")
    assert problem.endswith("). Try again when it finishes.")


def test_the_waiting_line_names_the_holder():
    assert anki_connect.waiting_line({"verb": "Backfill"}) == "Waiting for Backfill to finish writing to Anki…"
    assert anki_connect.waiting_line(None) == "Waiting for another Surasura to finish writing to Anki…"


# --- the dashboard's update wait ----------------------------------------------------------------------- #
class TestTheUpdatesWait(_DashboardHarness):
    def test_a_writer_here_is_one_entry_naming_what_it_writes(self):
        self.app._junban_auto_lock = threading.Lock()
        self.app._junban_auto_lock.acquire()            # the automatic step is running…
        done, thread = _holder("the automatic 順 step")  # …and holds the Anki-write lock
        try:
            names = [entry["name"] for entry in self.MasterDashboardApp._busy_threads(self.app)]
        finally:
            done.set()
            thread.join(5)
        self.assertEqual(names, ["Writing to Anki (the automatic 順 step)"])
        names = [entry["name"] for entry in self.MasterDashboardApp._busy_threads(self.app)]
        self.assertEqual(names, ["Junban's automatic reorder"], "today's entry, the lock let go")


# --- the review's rows (E1.4-adversary #1, #6, #7) ----------------------------------------------------- #
def test_an_address_that_cannot_be_used_after_a_wait_never_leaks_the_lock():
    # A hand-edited port that isn't a number: `invoke` raises a ValueError, not an AnkiError.
    done, thread = _holder()
    threading.Timer(0.3, done.set).start()
    held, problem = anki_connect.take_writer("順 reorder", "http://127.0.0.1:abc", wait=5)
    thread.join(5)
    assert problem is None and held.waited
    held.release()
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


def test_a_check_after_the_wait_that_fails_lets_the_lock_go():
    def broken():
        raise OSError("the snapshot could not be read")
    with pytest.raises(OSError):
        _after_wait(_Anki(), changed=broken)
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


def test_a_window_closed_as_the_lock_came_free_writes_nothing():
    closed = threading.Event()
    closed.set()
    with patch("urllib.request.urlopen", _Anki()):
        held, problem = anki_connect.take_writer("順 reorder", URL, cancel=closed)
    assert held is None and problem == anki_connect.CLOSED
    assert locks.held_in_process(anki_connect.WRITER_LOCK) is None


class TestTheUpdatesWaitBesideAWindow(_DashboardHarness):
    def _names(self):
        return [entry["name"] for entry in self.MasterDashboardApp._busy_threads(self.app)]

    def test_the_automatic_steps_entry_stays_while_a_window_writes(self):
        self.app._junban_auto_lock = threading.Lock()
        self.app._junban_auto_lock.acquire()            # the automatic step is preparing…
        done, thread = _holder("Backfill")              # …while the Backfill window writes
        try:
            self.assertEqual(self._names(), ["Junban's automatic reorder", "Writing to Anki (Backfill)"])
        finally:
            done.set()
            thread.join(5)

    def test_a_writer_with_no_verb_is_still_listed(self):
        self.app._junban_auto_lock = threading.Lock()   # not running
        done, thread = _holder("")
        try:
            self.assertEqual(self._names(), ["Writing to Anki (Surasura)"])
        finally:
            done.set()
            thread.join(5)
