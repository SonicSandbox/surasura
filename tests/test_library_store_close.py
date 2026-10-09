"""L3.3 of the library store (Library_Store_Spec.md §6.12): closes and checks that touch only what they must.

Why these matter: SQLite checkpoints a WAL database when its last connection closes, and deletes the `-wal`. Connect
opens the store about ten times a job; with Surasura closed every one of those closes was the last, so each ran a
checkpoint outside the store's write lock (the spec allows checkpoints only under it: SQLite 3.39.4's WAL-reset bug)
and the next write paid for a new `-wal` (a receipt's hold up to 62 ms, P2.4's verifier). Now a close never
checkpoints outside the lock, Connect can hold one handle for a job (`held()`), the copy follows Connect's and the
command line's writes on its own trigger, and the Content Manager's mode check, run twice a drag, reads through the
handle it already has instead of opening a connection each time (charter S19: a check that finds nothing does nothing).
Every test runs for Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT that tests/conftest.py sets.
"""

import hashlib
import os
import sqlite3
import threading
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, migrated, roots


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _wal(store_or_path):
    """The `-wal`'s size, or None when there is none."""
    path = (store_or_path if isinstance(store_or_path, str) else store_or_path.db_path) + "-wal"
    return os.path.getsize(path) if os.path.exists(path) else None


def _until(condition, limit=5.0):
    """Poll `condition` until it holds or `limit` seconds pass; its last value."""
    deadline = time.perf_counter() + limit
    while True:
        value = condition()
        if value or time.perf_counter() >= deadline:
            return value
        time.sleep(0.02)
