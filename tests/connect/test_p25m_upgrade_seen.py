"""An upgraded ledger keeps what the user already saw on screen: a need that was shown in *Needs you* before the
SCHEMA 3 -> 4 upgrade is still marked seen after it, and one never shown stays unseen (P2.5 mutant M12; ledger
`_needs_v4`, the `UPDATE needs SET seen_at = at WHERE seen = 1` run when the `seen_at` column is added).

The rule: opening a SCHEMA 3 file stamps `seen_at` with the need's own `at` for every need with `seen = 1`, and leaves
`seen_at` empty for `seen = 0`. The two needs have different kinds, so neither is closed as a duplicate of the other.

What a wrong answer would cost: a need the user already saw would count again on the *Needs you* badge after an
upgrade (the user is asked to look at the same failure twice), or an unseen need would be marked seen and the badge
would go quiet for a failure nobody has looked at.

The ledger is a real SQLite file in `tmp_path`; the SCHEMA 3 file is built by hand with `sqlite3`, the same tables an
old file had. No network, no sleeps.
"""
import sqlite3

import pytest

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

# SCHEMA 3's *needs*: no seen_at / dismissed_at / fixed_at yet.
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

_SEEN_AT = "2026-09-01T10:00:00"       # the shown need's own time (its `at`)
_UNSEEN_AT = "2026-09-02T10:00:00"


@pytest.fixture
def schema_3_path(tmp_path):
    """A SCHEMA 3 ledger file with two open needs of different kinds: one the user has seen (seen=1), one not yet
    (seen=0)."""
    path = tmp_path / "ledger.sqlite"
    con = sqlite3.connect(str(path), isolation_level=None)
    try:
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta VALUES ('schema', '3')")
        con.execute(_SCHEMA_2_JOBS)
        con.execute(_SCHEMA_3_NEEDS)
        con.execute(_SCHEMA_3_ONE_NEED)
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', 7, 3, 'mine-failed', '上層部の字幕が読めませんでした', ?, 1)", (_SEEN_AT,))
        con.execute("INSERT INTO needs (language, item_id, job_id, kind, say, at, seen) VALUES "
                    "('ja', 8, 3, 'no-video', '気配の動画が見つかりませんでした', ?, 0)", (_UNSEEN_AT,))
    finally:
        con.close()
    return str(path)


def test_upgrade_keeps_a_shown_need_shown_and_an_unseen_one_unseen(schema_3_path):
    """Opening the SCHEMA 3 file: the need the user had seen still has its seen time (its own `at`), the unseen
    need has none, and the badge's unseen list holds only the unseen one."""
    with Ledger(schema_3_path) as ledger:
        open_needs = {row["kind"]: row for row in ledger.needs("ja")}
        assert set(open_needs) == {"mine-failed", "no-video"}   # both stay open after the upgrade

        assert open_needs["mine-failed"]["seen_at"] == _SEEN_AT   # shown before the upgrade: still shown
        assert open_needs["no-video"]["seen_at"] is None          # never shown: still unseen

        unseen = ledger.needs("ja", unseen=True)
        assert [row["kind"] for row in unseen] == ["no-video"]    # the badge counts only the unseen one
