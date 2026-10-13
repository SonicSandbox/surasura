"""Connect's level batch with nothing new takes no write lock; an episode batch moves the state one step (P2.4 row 11,
L3.3, S19).

What a wrong answer would cost: a level job whose words were all made already still asks for the store's write lock,
so while the window holds that lock the job waits its full 5 s and fails, and the run that should have moved on
stalls; an episode batch that moves the state version by two (or none) makes the copy and the window read a step
that was never taken, or miss one. Real Japanese words (眼鏡, 上層部, 一生懸命), synthetic note ids, a temp library.
"""
import contextlib
import sqlite3
import time

from app.connect import library
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


@contextlib.contextmanager
def _another_connection_holds_the_write_lock(db_path):
    # A second connection takes the store's write lock with a short wait, so any write attempt fails fast instead of
    # waiting out the store's own 5 s. It is released in `finally`, so a failing assert never leaves it held.
    other = sqlite3.connect(db_path, timeout=0.1)
    try:
        other.execute("BEGIN IMMEDIATE")
        yield
    finally:
        other.rollback()
        other.close()


def test_a_level_batch_with_nothing_new_returns_at_once_even_while_the_write_lock_is_held():
    # The word is recorded first, so the level job's batch has nothing new. Taking the lock would wait the store's 5 s
    # and raise StoreBusy; the batch must return without writing and without waiting.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {"眼鏡": [1700000000031]}, None, batch="level-1")
        before = s.versions()["state_version"]
        with _another_connection_holds_the_write_lock(s.db_path):
            started = time.monotonic()
            library.record_batch(s, item, {"眼鏡": [1700000000031]}, None, batch="level-2")
            waited = time.monotonic() - started
        assert waited < 2.0
        assert s.versions()["state_version"] == before


def test_an_episode_batch_moves_the_state_version_by_exactly_one():
    # The receipt and both new words are one command, so the state takes one step, not one per word or per row.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        before = s.versions()["state_version"]
        library.record_batch(s, item, {"上層部": [1700000000051], "一生懸命": [1700000000052]},
                             "2026-10-01T09:00:00", batch="b-1")
        assert s.versions()["state_version"] == before + 1
