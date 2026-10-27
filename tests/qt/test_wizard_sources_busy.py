"""K4 (alpha 4, Mattias's note 5): setup's page 3 waits on a busy library and goes on by itself —
`setup_wizard.read_folders(waiting=)` and the page's *Waiting for your library…* line.

What a wrong answer would cost a learner: page 3 said "couldn't be read: the library is busy (another window's save)"
and dropped the folder he picked while a big scan held the library — he had to notice, pick it again and press Next
again, maybe many times. Now a busy library is waited for (the page says so, *Stop* still works) and the read goes on;
*Stop* while waiting keeps the folder listed and fails nothing.

A real empty library under the test's root and a real source folder of Japanese texts (`test_wizard_sources`'
helpers); the library made busy by another handle holding its write lock (another window's save, its 5 s wait cut to
0.2 s) or by another look marked running on it.
"""
import os
import threading

from app import library_store as ls
from app import sources
from app.services import setup_wizard
from tests.test_services_moves import LockHolder, short_lock_wait  # noqa: F401 (a fixture)
from tests.qt.test_wizard_sources import SHOWS, _folder, _fresh_look_state, empty_library  # noqa: F401 (fixtures)


def _db():
    from app import path_utils
    return ls.library_db_path("ja", path_utils.get_data_path("ja"))


def _released_after(seconds, release):
    t = threading.Timer(seconds, release)
    t.start()
    return t


def test_a_save_holding_the_library_is_waited_for_and_the_folder_is_read(empty_library, short_lock_wait,
                                                                         monkeypatch):
    monkeypatch.setattr(setup_wizard, "BUSY_WAIT_S", 0.05)
    told = []
    holder = LockHolder(_db())
    timer = _released_after(1.0, holder.release)
    try:
        got = setup_wizard.read_folders("ja", [_folder("anime", SHOWS)], waiting=told.append)
    finally:
        timer.join(5)
    assert got["failed"] == [] and not got["busy"] and got["added"] == 5
    assert told[0] is True and told[-1] is False                      # the page said it waited, then went on


def test_another_look_reading_the_library_is_waited_for_then_the_folder_is_read(empty_library, monkeypatch):
    monkeypatch.setattr(setup_wizard, "BUSY_WAIT_S", 0.05)
    key = ls.path_key(os.path.abspath(_db()))
    with sources._GUARD:
        sources._RUNNING.add(key)                                     # the window's own look, running
    timer = _released_after(0.5, lambda: sources._RUNNING.discard(key))
    told = []
    try:
        got = setup_wizard.read_folders("ja", [_folder("anime", SHOWS)], waiting=told.append)
    finally:
        timer.join(5)
    assert got["added"] == 5 and got["failed"] == [] and not got["stopped"]
    assert told == [True, False]


def test_stop_while_waiting_keeps_the_folder_listed_and_fails_nothing(empty_library, short_lock_wait, monkeypatch):
    monkeypatch.setattr(setup_wizard, "BUSY_WAIT_S", 0.05)
    folder = _folder("anime", SHOWS)
    holder = LockHolder(_db())
    stop = threading.Event()
    told = []

    def waiting(on):
        told.append(on)
        if on:
            stop.set()                                                 # he presses Stop on the waiting line
    try:
        got = setup_wizard.read_folders("ja", [folder], stop=stop.is_set, waiting=waiting)
    finally:
        holder.release()
    assert got["stopped"] and got["failed"] == [] and folder not in got["read"]     # still listed, to read later
    assert told == [True, False]


def test_a_quiet_library_never_says_it_waits(empty_library):
    told = []
    got = setup_wizard.read_folders("ja", [_folder("anime", SHOWS)], waiting=told.append)
    assert got["added"] == 5 and told == []
