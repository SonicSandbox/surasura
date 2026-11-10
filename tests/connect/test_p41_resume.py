"""P4.1 row 4.1.9R (the intent keeper's B2, ✅ G1.1-2): Connect turned on again by any writer — its own switch
(`connect_enabled`) or D29's automation (`logic.automation`) — is one rule, `resume.turned_on(before, after,
languages)`: every language's placement watermark at its log's end, the list Connect last looked at forgotten, and the
asks watermark (`ledger.ASKS_FROM + lang`) set now.

What a wrong answer would cost: the automation off for a week while automatic rarity raised the level, and two
*Mine this* asks made meanwhile — turned back on, Connect would queue level jobs across the library and mine both asks
and every episode placed in the top 20 meanwhile: cards for things the user did while saying "nothing automatic".
Or, the other way, a turn-on that ran when nothing turned on would forget a level raise made while Connect was on.

The suite's real subtitles in a store built from folders (`connect_helpers.library`); real Japanese lemmas; the list
is handed in (no Generate), as `test_level.py` hands it.
"""
import os
import sqlite3

import pytest

from app import library_store
from app.connect import inbox, level, library, resume
from app.connect import ledger as book
from app.connect.ledger import LEVEL, Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

BEFORE = {("冒険", "ボウケン"), ("散歩", "サンポ"), ("図書館", "トショカン")}
RAISED = BEFORE | {("眼鏡", "メガネ"), ("老婆", "ロウバ")}
AGAIN = RAISED | {("駐車場", "チュウシャジョウ")}
ON = {"connect_enabled": True}
AUTOMATION_OFF = {"connect_enabled": True, "logic": {"automation": False}}
CONNECT_OFF = {"connect_enabled": False}


def _line(lang="ja", n=2):
    """A library whose top `n` items are the mine line -> ([(id, file name)] of the line, [ids below it])."""
    c.library(lang)
    with c.store(lang) as s:
        s.bookkeeping({"mine_line": n}, copy_carries=True)
        library.switch_on(s)                      # Connect on from here: its watermark set
        line = library.mine_line(s)
        below = [i for i in s.ids("now") if i not in line]
        return [(i, os.path.basename(s.item(i)["rel_path"])) for i in line], below


def _check(listed, signature, files, lang="ja"):
    with c.store(lang) as s:
        return level.check(s, lang, listed, signature, files)


def _level_jobs(lang="ja"):
    with Ledger() as ledger:
        return [j["item_id"] for j in ledger.jobs(lang) if j["kind"] == LEVEL]


def _asks_from(lang="ja"):
    with Ledger() as ledger:
        row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (book.ASKS_FROM + lang,)).fetchone()
    return row[0] if row else None


def _asked(item_id, lang="ja"):
    with c.store(lang) as s:
        return s.item(item_id)["mine_asked"]


def _a_week_off(line, below, lang="ja"):
    """While Connect is off: two asks made (*Mine this* below the line) and an item placed into the top 20 — the
    level raise is the caller's (a look only happens with Connect on)."""
    with c.store(lang) as s:
        s.ask_mining([below[0]])
        s.ask_mining([below[1]])
        library.place(s, below[2], "now", before_id=line[0][0])
        rows, _gap = s.read_events(library.READER)
    assert any(r[2] == "entered_mine_line" for r in rows), "the placement is in the log, unread"


def test_the_constant_is_the_one_package_a_reads():
    # package A (4.1.3) reads the asks watermark under this key: the two must never drift apart
    assert book.ASKS_FROM == "asks_from:"


@pytest.mark.parametrize("off", [AUTOMATION_OFF, CONNECT_OFF], ids=["automation", "connect_enabled"])
def test_a_week_off_then_on_mines_nothing_of_the_week_and_the_next_raise_mines(off):
    line, below = _line()
    (a, fa), _b = line
    with c.store() as s:
        s.receipt(a, "2026-10-07T09:00:00Z")            # a mined before the week off
    files = {fa: ["眼鏡", "老婆", "駐車場"]}
    assert _check(BEFORE, "run-1", files)["first"] is True      # Connect on: the list recorded
    h.write_settings(**off)
    _a_week_off(line, below)                            # meanwhile automatic rarity raised the level: RAISED
    h.write_settings(**ON)
    assert resume.turned_on(off, ON) is None
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [], "nothing placed while off is read"
    assert _check(RAISED, "run-2", files)["first"] is True, "the week's raise is a first look: recorded, not mined"
    assert _level_jobs() == []
    watermark = _asks_from()
    assert watermark is not None
    assert _asked(below[0]) < watermark and _asked(below[1]) < watermark, "both asks are older: never mined"
    with c.store() as s:
        s.ask_mining([below[3]])
    assert _asked(below[3]) > watermark, "an ask made now is newer: Connect mines it"
    out = _check(AGAIN, "run-3", files)
    assert out["queued"] == [a] and _level_jobs() == [a], "the next raise mines, its new word only"


def test_on_to_on_and_off_to_off_and_on_to_off_do_nothing():
    line, below = _line()
    (a, fa), _b = line
    files = {fa: ["眼鏡"]}
    _check(BEFORE, "run-1", files)
    with c.store() as s:
        library.place(s, below[0], "now", before_id=a)
    for before, after in [(ON, ON), (AUTOMATION_OFF, CONNECT_OFF), (ON, AUTOMATION_OFF), (ON, CONNECT_OFF),
                          (AUTOMATION_OFF, AUTOMATION_OFF)]:
        assert resume.turned_on(before, after) is None
    assert _asks_from() is None, "no turn-on: no asks watermark"
    with c.store() as s:
        rows, _gap = s.read_events(library.READER)
    assert any(r[2] == "entered_mine_line" for r in rows), "the placement still unread: its job still comes"
    with Ledger() as ledger:
        assert ledger.recorded_list("ja")[0] == "run-1", "the list Connect looked at is kept"


def test_turned_on_reads_both_switches_from_the_dicts_as_saved():
    """Either key moving counts, a missing logic block reads the automation on, None reads off (the watermarks set
    again: never too little)."""
    _line()
    assert resume.turned_on({"connect_enabled": True, "logic": {"automation": False}},
                            {"connect_enabled": True, "logic": {}}) is None
    first = _asks_from()
    assert first is not None
    assert resume.turned_on(None, ON) is None and _asks_from() >= first


def test_no_ledger_yet_is_made_so_an_ask_from_before_connect_ever_ran_is_never_mined():
    line, below = _line()
    with c.store() as s:
        s.ask_mining([below[0]])
    assert not os.path.exists(book.path())
    assert resume.turned_on(CONNECT_OFF, ON) is None
    assert os.path.exists(book.path()) and _asked(below[0]) < _asks_from()


def test_every_language_turned_on_a_chinese_one_too():
    line, below = _line("ja")
    zline, zbelow = _line("zh", n=1)
    with c.store("zh") as s:
        s.ask_mining([zbelow[0]])
        library.place(s, zbelow[1], "now", before_id=zline[0][0])
    assert resume.turned_on(AUTOMATION_OFF, ON, ("ja", "zh")) is None
    assert _asks_from("ja") and _asked(zbelow[0], "zh") < _asks_from("zh")
    with c.store("zh") as s, Ledger() as ledger:
        assert inbox.consume(s, "zh", ledger)["queued"] == []


def test_a_language_with_no_library_gets_its_ledger_marks_only(monkeypatch):
    _line("ja")
    assert resume.turned_on(CONNECT_OFF, ON, ("ja", "zh")) is None, "no Chinese library: not a failure"
    assert _asks_from("zh") is not None


def test_a_busy_library_is_named_and_its_language_left_as_it_was(monkeypatch):
    line, below = _line()
    with c.store() as s:
        library.place(s, below[0], "now", before_id=line[0][0])
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)     # there, but won't open
    out = resume.turned_on(AUTOMATION_OFF, ON, ("ja",))
    assert out == resume.BUSY.format("Japanese")
    assert _asks_from() is None, "nothing of that language written: the writer tries again"


def test_a_ledger_newer_than_this_surasura_is_named_never_written(monkeypatch):
    _line()
    with Ledger() as ledger:
        ledger.conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(book.SCHEMA + 1),))
    out = resume.turned_on(AUTOMATION_OFF, ON, ("ja",))
    assert out is not None and out.startswith("Japanese: ")
    conn = sqlite3.connect(book.path())
    try:
        assert conn.execute("SELECT value FROM meta WHERE key = ?", (book.ASKS_FROM + "ja",)).fetchone() is None
    finally:
        conn.close()
