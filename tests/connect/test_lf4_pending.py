"""Laptop round 8 #45 — a press shows at once (doctrine: architecture.md, Controls, first row). Sonic: "on press there
is ALWAYS an immediate reaction, even if that reaction is just that it is waiting to start".

Connect's side of two presses that used to show nothing until Connect or a sync got to them:
  * *Mine now*: the window writes the ask; the stone read Connect's record, which moves only once Connect reads its
    inbox. `feed.with_asks` lays *Asked* on every asked item Connect doesn't show yet, from the press itself.
  * *Mark them known*: the answer waits on the known-words lock while a sync writes; `accept_offer(on_wait=)` says so
    once, before it waits, naming what it waits for.
And #47's Stop: each item says whether its job can still be stopped (`Item.stoppable`).

What a wrong answer costs: a press that seems to do nothing (Sonic pressed again), or a stone promising cards Connect
won't make (Connect off). Real Japanese words; the known-words lock taken for real by a second thread.
"""
import threading
import time

from app import anki_sync
from app.connect import feed, known_signal, runner
from tests.connect.test_fix_b_offer_rechecked import SETTINGS, URL, anki, known_file  # noqa: F401  (fixtures)


def _record(*jobs):
    return {"running": True, "languages": {"ja": {"jobs": list(jobs), "line": "Making cards", "state": "busy"}}}


def test_an_ask_connect_hasnt_read_shows_asked_at_once_and_connects_own_stone_wins():
    got = feed.build(_record({"job": 7, "item": 2, "state": "mining", "reason": None, "kind": "mine"}), "ja")
    shown = feed.with_asks(got, [5, 2, 5])
    assert shown.items[5].kind == feed.ASKED and shown.items[5].words == feed.WORDS[feed.ASKED]
    assert shown.items[2] is got.items[2], "an item Connect shows keeps Connect's stone"
    assert feed.with_asks(got, [2]) is got and feed.with_asks(got, []) is got, "nothing new: the same Feed (S19)"


def test_with_connect_off_an_ask_promises_nothing():
    off = feed._off({"connect_enabled": False})
    assert feed.with_asks(off, [5]) is off


def test_each_item_says_whether_its_job_can_still_be_stopped():
    got = feed.build(_record(
        {"job": 1, "item": 1, "state": "mining", "reason": None},
        {"job": 2, "item": 2, "state": "filling", "reason": None},
        {"job": 3, "item": 3, "state": "waiting", "reason": runner.STOPPED_BY_YOU},
        {"job": 4, "item": 4, "state": "queued", "reason": None}), "ja")
    assert {i: got.items[i].stoppable for i in got.items} == {1: True, 2: None, 3: None, 4: True}
    assert got.items[3].tip == runner.STOPPED_BY_YOU, "a stopped episode's hover says why and what goes on"


def test_mark_them_known_says_at_once_what_it_waits_for_then_does_it(anki, known_file):  # noqa: F811
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    taken, release = threading.Event(), threading.Event()

    def sync():                                     # another writer of the known words, holding them for a moment
        held, _refused = anki_sync.hold_known_words("ja", "Anki known-words sync")
        taken.set()
        release.wait(10)
        held.release()
    holder = threading.Thread(target=sync)
    holder.start()
    assert taken.wait(10)
    said = []

    def on_wait(who):
        said.append((who, time.monotonic()))
        release.set()                               # the sync ends a moment after the notice
    added = known_signal.accept_offer("ja", URL, on_wait=on_wait)
    holder.join(10)
    assert [w for w, _t in said] == ["Anki known-words sync"], "told once, before the wait, naming the writer"
    assert sorted(added) == ["一生懸命", "上層部"]


def test_mark_them_known_with_nothing_in_the_way_says_nothing(anki, known_file):  # noqa: F811
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    said = []
    assert sorted(known_signal.accept_offer("ja", URL, on_wait=said.append)) == ["一生懸命", "上層部"]
    assert said == []


def test_mine_now_on_a_stopped_episode_shows_at_once():
    # review A11: the press the stopped stone asks for shows before Connect reads it
    got = feed.build(_record({"job": 3, "item": 3, "state": "waiting", "reason": runner.STOPPED_BY_YOU}), "ja")
    assert feed.with_asks(got, [3]).items[3].kind == feed.ASKED
    waiting = feed.build(_record({"job": 4, "item": 4, "state": "waiting", "reason": runner.ANKI_CLOSED}), "ja")
    assert feed.with_asks(waiting, [4]) is waiting, "Connect's own wait keeps its reason"
