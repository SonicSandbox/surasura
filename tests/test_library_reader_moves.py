"""The library reader's move hook (`LibraryReader.subscribe_moves`, `_moved`): what counts as a move of the order or the
pins, at the edges its end-to-end test leaves open — a store made again (a Repair, a restore) whose version numbers
happen to match, and a version read that fails.

What a wrong answer would cost a learner: after a Repair their Anki order is never brought back in line with the
library (the re-order host never hears of it), or a busy store read makes the host and the journey keeper start work
for a move nobody made. The handle is a stand-in giving the store's `versions()`.
"""
import sqlite3

from app.services.library_reader import LibraryReader
from tests.fixtures import window_seed


class _Handle:
    def __init__(self, epoch, order, pins):
        self.now = {"epoch": epoch, "order_version": order, "pins_version": pins}
        self.fails = False

    def versions(self):
        if self.fails:
            raise sqlite3.OperationalError("database is locked")
        return dict(self.now)


def _reader():
    seed = window_seed.build()
    reader = LibraryReader(seed.opener, language="ja", numbers=seed.numbers, mining=seed.mining, poll=0.02)
    heard = []
    reader.subscribe_moves(lambda language, versions: heard.append((language, versions.get("epoch"))))
    return reader, heard


def test_a_store_made_again_with_the_same_version_numbers_is_a_move():
    """A Repair makes the store again (a new epoch): its order and pins versions may start over at the very numbers
    the window last saw — that is still a new order, told once."""
    reader, heard = _reader()
    h = _Handle("epoch-1", 7, 2)
    reader._moved(h)
    assert heard == []                                   # the first look only learns the versions
    h.now["epoch"] = "epoch-2"
    reader._moved(h)
    reader._moved(h)
    assert heard == [("ja", "epoch-2")]


def test_a_version_read_that_fails_tells_nothing_and_the_next_read_tells_only_a_real_move():
    """A busy store (another program writing) makes `versions()` fail: nothing is told, and when the read works again
    with the versions unchanged nothing is told either; a real move after it is told once."""
    reader, heard = _reader()
    h = _Handle("epoch-1", 7, 2)
    reader._moved(h)
    h.fails = True
    reader._moved(h)
    h.fails = False
    reader._moved(h)
    assert heard == [], "a failed read was told as a move"
    h.now["order_version"] = 8
    reader._moved(h)
    assert heard == [("ja", "epoch-1")]
