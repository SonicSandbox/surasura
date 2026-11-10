"""Opening a SCHEMA 3 ledger keeps one open need per ITEM: two open needs of the same language and kind but for
different items (7 and 8) both stay open after the upgrade to SCHEMA 4. Only a true duplicate (the same item) is
closed as fixed (ledger `_needs_v4`, which groups by language, kind and item).

What a wrong answer would cost: if the upgrade grouped by language and kind alone, a user's unanswered failure on one
word (上層部) would be closed the moment another word (気配) of the same kind was in the file, and *Needs you* would
silently drop it.

The schema-3 file is built by hand with `sqlite3` in `tmp_path`, with only the tables an old file had. No network,
no sleeps.
"""
import sqlite3

from app.connect.ledger import Ledger

# The P2.2 jobs table: the columns later schemas add are not there; the ledger adds them when it opens the file.
_SCHEMA_2_JOBS = """CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  language TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  state TEXT NOT NULL,
  reason TEXT,
  source TEXT,
  event_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'mine',
  words TEXT)"""

# SCHEMA 3's *needs*: no seen_at / dismissed_at / fixed_at yet, and the index that counted only unseen entries.
_SCHEMA_3_NEEDS = """CREATE TABLE needs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  language TEXT NOT NULL,
  item_id INTEGER,
  job_id INTEGER,
  kind TEXT NOT NULL,
  say TEXT NOT NULL,
  at TEXT NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0)"""
_SCHEMA_3_ONE_NEED = ("CREATE UNIQUE INDEX one_need ON needs (language, kind, COALESCE(item_id, -1)) "
                      "WHERE seen = 0")

_KIND = "mine-failed"
_SEEN_ITEM = 7      # shown to the user already (seen=1)
_UNSEEN_ITEM = 8    # not shown yet (seen=0)


def _schema_3_ledger_two_items(path):
    """A SCHEMA 3 ledger with the same kind for two different words: 上層部 (item 7, seen) and 気配 (item 8, unseen)."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta VALUES ('schema', '3')")
        con.execute(_SCHEMA_2_JOBS)
        con.execute(_SCHEMA_3_NEEDS)
        con.execute(_SCHEMA_3_ONE_NEED)
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 3, ?, '上層部の字幕が読めませんでした', '2026-09-01T10:00:00', 1)", (_SEEN_ITEM, _KIND))
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 3, ?, '気配の字幕が読めませんでした', '2026-09-02T10:00:00', 0)", (_UNSEEN_ITEM, _KIND))
    finally:
        con.close()


def test_upgrade_keeps_open_needs_for_different_items_of_the_same_kind(tmp_path):
    """Two open needs with the same language and kind but different items both stay open after the upgrade; the
    upgrade closes nothing here, because neither is a duplicate of the other (a duplicate is the same item)."""
    path = str(tmp_path / "ledger.sqlite")
    _schema_3_ledger_two_items(path)
    ledger = Ledger(path)
    try:
        # listed=False: every open need, dismissed or not, so nothing the upgrade keeps can hide behind a filter
        open_needs = ledger.needs("ja", listed=False)
        assert sorted(row["item_id"] for row in open_needs) == [_SEEN_ITEM, _UNSEEN_ITEM], (
            "the upgrade must keep one open need per item, not one per language and kind")
    finally:
        ledger.close()


def _schema_3_ledger_with_duplicate(path):
    """A SCHEMA 3 ledger with a true duplicate: 上層部 (item 7) twice, the older row already shown (seen=1) and the
    newer one still open (seen=0), plus 気配 (item 8, unseen). The partial index allows it: it covers only seen=0 rows."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta VALUES ('schema', '3')")
        con.execute(_SCHEMA_2_JOBS)
        con.execute(_SCHEMA_3_NEEDS)
        con.execute(_SCHEMA_3_ONE_NEED)
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 3, ?, '上層部の字幕が読めませんでした', '2026-09-01T10:00:00', 1)", (_SEEN_ITEM, _KIND))
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 4, ?, '上層部の字幕が読めませんでした', '2026-09-03T10:00:00', 0)", (_SEEN_ITEM, _KIND))
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 3, ?, '気配の字幕が読めませんでした', '2026-09-02T10:00:00', 0)", (_UNSEEN_ITEM, _KIND))
    finally:
        con.close()


def test_upgrade_closes_only_the_older_true_duplicate_of_the_same_item(tmp_path):
    """Two rows for the same item (7) and kind: the older one is a true duplicate and is closed by the upgrade; the
    newer one stays open, and the other item's (8) open need stays open too. Keeping both halves of the rule means a
    migration that closes nothing, or closes by kind alone, fails here."""
    path = str(tmp_path / "ledger.sqlite")
    _schema_3_ledger_with_duplicate(path)
    ledger = Ledger(path)
    try:
        open_needs = ledger.needs("ja", listed=False)
        # the newer row of item 7 (at 2026-09-03) and item 8 stay open; the older item 7 row is closed as a duplicate
        assert sorted((row["item_id"], row["at"]) for row in open_needs) == [
            (_SEEN_ITEM, "2026-09-03T10:00:00"),
            (_UNSEEN_ITEM, "2026-09-02T10:00:00"),
        ], "only a true duplicate (same item) may be closed; one open need per item must stay open"
    finally:
        ledger.close()
