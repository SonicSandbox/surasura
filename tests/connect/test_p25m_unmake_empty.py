"""An undo frees a word of its own batch even when the word's row is already empty.

Rule: `library.unmake(store, item_id, gone, words)` frees each word of this undo (the words in `words`) whose made-words
row holds no note ids any more, even when the deleted-card check emptied that row between Anki's delete and the undo's
finish. A word the undo did not name, and whose row still holds a live note, is left alone.

What a wrong answer would cost: a word undone with its row already empty stays blocked, so Connect never makes it again
and the learner's next batch silently skips a word they meant to have back.
"""
import contextlib

import pytest

from app.connect import library


class FakeStore:
    """`library.unmake`'s store: a real SQLite made_words table and an items table with `mined_at`."""

    def __init__(self, path):
        import sqlite3
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("CREATE TABLE made_words (item_id INTEGER, word TEXT, note_ids TEXT, made_at TEXT, "
                          "batch TEXT, PRIMARY KEY (item_id, word))")
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, mined_at TEXT)")
        self.receipts = []
        self.mined = {}
        self.touched = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextlib.contextmanager
    def _reading(self):
        yield

    @contextlib.contextmanager
    def _command(self, kind, by="user"):
        store = self

        class Cmd:
            def touch(self):
                store.touched += 1
        self.conn.execute("BEGIN")
        yield Cmd()
        self.conn.execute("COMMIT")

    def receipt(self, item_id, mined_at):
        self.receipts.append((item_id, mined_at))
        self.mined[item_id] = mined_at

    def item(self, item_id):
        return {"id": item_id, "mined_at": self.mined.get(item_id, "2026-10-08T10:00:00Z")}


@pytest.fixture
def store(tmp_path):
    fake = FakeStore(str(tmp_path / "store.sqlite"))
    try:
        yield fake
    finally:
        fake.conn.close()


def _rows(store, item_id):
    return dict(store.conn.execute("SELECT word, note_ids FROM made_words WHERE item_id = ?", (item_id,)).fetchall())


def test_undo_frees_its_own_word_whose_row_the_deleted_card_check_already_emptied(store):
    # 上層部's card was deleted in Anki before the undo finished, so its row is already '[]'. The undo still names
    # the word, so the word is freed: its row goes and it is reported as freed. 気配 keeps a live note, so it stays.
    # 日本 also has an empty row, but the undo did not name it, so the undo leaves that row alone.
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[]', 'x', 'b')")
    store.conn.execute("INSERT INTO made_words VALUES (7, '気配', '[102]', 'x', 'b')")
    store.conn.execute("INSERT INTO made_words VALUES (7, '日本', '[]', 'x', 'b')")

    freed = library.unmake(store, 7, [101], {"上層部"})

    assert freed == ["上層部"]
    assert "上層部" not in _rows(store, 7)
    assert _rows(store, 7) == {"日本": "[]", "気配": "[102]"}
