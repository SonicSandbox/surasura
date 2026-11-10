"""A level job's batch that made nothing at all takes no store write lock (P2.4 row 11, S19; mutant P2.4-B14).

What a wrong answer would cost: a level batch where Anki Miner made no card still asks for the store's write lock, so
while the window holds it the job waits the store's full 5 s and fails with StoreBusy, and the run stalls on a batch
that had nothing to record. Real store in a temp library; another connection holds the write lock.
"""
import time

from app.connect import library
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_fix_l33_no_lock_when_nothing_new import _another_connection_holds_the_write_lock


def test_a_level_batch_that_made_nothing_returns_at_once_while_the_window_holds_the_write_lock():
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        before = s.versions()["state_version"]
        with _another_connection_holds_the_write_lock(s.db_path):
            for made in ({}, None):         # no word made: an empty record, or none at all
                started = time.monotonic()
                library.record_batch(s, item, made, None, batch="level-0")
                assert time.monotonic() - started < 2.0, f"{made!r}: nothing to record, so no wait for the lock"
        assert s.versions()["state_version"] == before
