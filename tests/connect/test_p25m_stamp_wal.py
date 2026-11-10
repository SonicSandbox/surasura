"""The status stamp moves when either database's write-ahead log changes (status.py `stamp`).

Rule pinned: a write that lands only in a SQLite `-wal` file (not yet in the main file) must still move the stamp,
so the status window redraws. Two checks: the ledger's `-wal` and the library store's `-wal`, with the main files
left untouched. What a wrong answer would cost: a finished Connect write that the window never shows, because the
stamp looked the same while the change sat in the WAL.

The ledger is a real SQLite file in a temp folder; the library store is a plain file the test writes into. Connect's
running check is faked. No network, no sleeps.
"""
import pytest

from app.connect import status
from app.connect.ledger import Ledger


@pytest.fixture
def ledger_path(tmp_path):
    """A real ledger file, closed before the stamp is taken."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path):
        pass
    return path


@pytest.fixture
def store_path(tmp_path, monkeypatch):
    """A library store file in the temp folder, handed to the stamp in place of the real one."""
    path = str(tmp_path / "library.sqlite")
    with open(path, "wb") as handle:
        handle.write(b"store")
    monkeypatch.setattr(status, "_store_path", lambda lang: path)
    monkeypatch.setattr(status, "running", lambda: False)
    return path


def test_ledger_wal_write_moves_the_stamp_and_main_file_untouched(ledger_path, store_path):
    """A write that sits only in the ledger's `-wal` file (the main file unchanged) must change the stamp, or the
    window would keep showing the old record."""
    before = status.stamp(ledger_path, languages=["ja"])
    with open(ledger_path + "-wal", "wb") as handle:
        handle.write(b"wal-bytes")
    after = status.stamp(ledger_path, languages=["ja"])
    assert after != before
    # The WAL grows (another write lands in it): the stamp must move again, not only when the file first appears.
    with open(ledger_path + "-wal", "ab") as handle:
        handle.write(b"more-wal-bytes")
    grown = status.stamp(ledger_path, languages=["ja"])
    assert grown != after


def test_library_store_wal_write_moves_the_stamp_and_main_file_untouched(ledger_path, store_path):
    """A write that sits only in the library store's `-wal` file must change the stamp too: the titles come from that
    store, so a change there is a change to what the window shows."""
    before = status.stamp(ledger_path, languages=["ja"])
    with open(store_path + "-wal", "wb") as handle:
        handle.write(b"store-wal-bytes")
    after = status.stamp(ledger_path, languages=["ja"])
    assert after != before
    # The store's WAL grows: the stamp must move again, not only when the file first appears.
    with open(store_path + "-wal", "ab") as handle:
        handle.write(b"more-store-wal-bytes")
    grown = status.stamp(ledger_path, languages=["ja"])
    assert grown != after
