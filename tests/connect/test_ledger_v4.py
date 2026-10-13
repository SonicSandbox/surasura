"""A ledger written at SCHEMA 3 (before *Needs you*) upgrades to SCHEMA 4 when it is opened, and keeps the need the
user has not yet dealt with (P2.5 row L1; ledger `_needs_v4`, and the one-open-entry-per-key index it creates).

What each test holds still:

  * the upgrade keeps the one open need: of two rows for the same language + kind + item (an older one the user
    already saw, then the newest, still unseen), the newest is the one `needs("ja")` lists and the older one is closed
    as fixed, so the user is not told twice and the open need is not lost. A wrong answer would drop an unanswered
    failure from *Needs you* or show a fixed one again;
  * after the upgrade one open entry per key holds: a new need of that same key adds nothing (it returns False) while
    the open one is still unseen. A wrong answer would make the badge count one failure twice.

The ledger is a real SQLite file in a temp folder (`tmp_path`); the schema-3 file is built by hand with `sqlite3`,
with only the tables an old file had (meta, jobs, needs). No network, no sleeps.
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
_ITEM = 7


def _schema_3_ledger(path):
    """A SCHEMA 3 ledger file with the same key twice: an older need the user has seen (seen=1), then the newest
    one, still unseen (seen=0)."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta VALUES ('schema', '3')")
        con.execute(_SCHEMA_2_JOBS)
        con.execute(_SCHEMA_3_NEEDS)
        con.execute(_SCHEMA_3_ONE_NEED)
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 3, ?, '上層部の字幕が読めませんでした', '2026-09-01T10:00:00', 1)", (_ITEM, _KIND))
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', ?, 3, ?, '一生懸命の字幕が読めませんでした', '2026-09-02T10:00:00', 0)", (_ITEM, _KIND))
    finally:
        con.close()


def test_schema_3_ledger_upgrades_to_4_and_keeps_the_newest_open_need(tmp_path):
    """Opening a SCHEMA 3 file with an open need records SCHEMA 4, keeps the newest unseen row open and closes the
    older duplicate as fixed; the need the user still has to deal with stays listed."""
    path = str(tmp_path / "ledger.sqlite")
    _schema_3_ledger(path)
    ledger = Ledger(path)
    try:
        open_needs = ledger.needs("ja")
        assert [(n["id"], n["say"]) for n in open_needs] == [(2, "一生懸命の字幕が読めませんでした")]
        assert open_needs[0]["fixed_at"] is None

        # the older duplicate is closed as fixed, not deleted: its row stays for the record
        older = ledger.conn.execute("SELECT fixed_at FROM needs WHERE id = 1").fetchone()
        assert older[0] is not None
        assert ledger.conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == "4"
    finally:
        ledger.close()


def test_schema_4_upgrade_refuses_a_second_open_need_of_the_same_key(tmp_path):
    """After the upgrade, a new need of the same language + kind + item adds no second open entry: while the open
    one is still unseen, `need` returns False and *Needs you* still lists one row (one open entry per key)."""
    path = str(tmp_path / "ledger.sqlite")
    _schema_3_ledger(path)
    ledger = Ledger(path)
    try:
        counted = ledger.need("ja", _KIND, "もう一度の字幕が読めませんでした", item_id=_ITEM, job_id=4)
        assert counted is False
        assert len(ledger.needs("ja")) == 1
    finally:
        ledger.close()
