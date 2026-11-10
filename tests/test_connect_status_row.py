"""Connect's line and the *Needs you* badge (P3.1 row 3.1.4; P1.5 05-surface U1, U2; RUNBOOK-P2.5's contract).

What a wrong answer would cost: a poll that reads the ledger every 3 s whether or not anything moved spends the
laptop's battery and stalls behind a busy ledger (S19: only a changed stamp reads); a read on the screen's thread
freezes the window while Anki Miner holds the ledger; a badge that stays filled after the list was looked at nags
(P1.2-1: seen stops counting); a row left polling after the switch went off is Connect in a 2.5 window. The row is
built on a hidden root; Connect's stamp and record are stood in for; real Japanese in the record."""
import sys
import types
from tkinter import ttk

import pytest

from app.connect import status_row
from tests.connect_tk_helpers import Pump, Tips, on_main, tk_root

NEED = {"id": 1, "kind": "known-sync", "say": "Sync once from Surasura's Anki window first.", "item": None,
        "title": None, "at": "2026-10-11T09:00:00Z", "seen_at": None}


def _record(line="Up to date · 26 cards made today", needs=(), unseen=0, jobs=()):
    return {"line": line, "state": "idle", "jobs": list(jobs), "needs": list(needs), "unseen": unseen, "undo": [],
            "shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}, "made_today": 26}


class Connect:
    """Connect's stamp and record, with every call's thread."""

    def __init__(self, record=None):
        self.stamp_value, self.record, self.calls = [1, 2, False, "2026-10-11"], record or _record(), []

    def stamp(self, languages=None):
        self.calls.append(("stamp", tuple(languages), on_main()))
        return list(self.stamp_value)

    def read(self, languages=None):
        self.calls.append(("read", tuple(languages), on_main()))
        return {"languages": {languages[0]: self.record}}

    def count(self, what):
        return sum(1 for c in self.calls if c[0] == what)


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()


def _row(root, connect, language="ja", **kw):
    pump, tips = Pump(), Tips()
    footer = ttk.Frame(root)             # the bottom bar the row packs above
    footer.pack(side="bottom")
    row = status_row.StatusRow(root, lambda: language, tips, lambda: None, settings=lambda: {"connect_enabled": True},
                               below=footer, stamp=connect.stamp, read=connect.read, post=pump.put,
                               unread=lambda lang: None, **kw)
    return row, pump, tips


def _look(row, pump, root):
    """One tick, run until its worker has finished and what it posted is drawn."""
    row.tick()
    assert pump.run(root, lambda: not row._looking and not pump.jobs)


def test_an_unchanged_stamp_reads_nothing_and_redraws_nothing(root):
    connect = Connect()
    row, pump, _tips = _row(root, connect)
    _look(row, pump, root)
    assert (connect.count("read"), row.redraws) == (1, 1)
    _look(row, pump, root)
    _look(row, pump, root)
    assert connect.count("stamp") == 3
    assert (connect.count("read"), row.redraws) == (1, 1), "the same stamp: no read, no redraw (S19)"
    connect.stamp_value[0] += 1                 # the ledger moved
    connect.record = _record(line="Making cards 1 of 1 — Example Show - 06 (Anki Miner)")
    _look(row, pump, root)
    assert (connect.count("read"), row.redraws) == (2, 2)


def test_a_moved_stamp_with_the_same_line_and_badge_reads_but_never_redraws(root):
    """IK11 (S19): a Content Manager move changes the library file's stamp, not what the row shows."""
    connect = Connect(_record(needs=[NEED], unseen=1))
    row, pump, _tips = _row(root, connect)
    _look(row, pump, root)
    connect.stamp_value[0] += 1
    connect.record = _record(needs=[NEED], unseen=1)    # read again, the same line, badge and hover
    _look(row, pump, root)
    assert (connect.count("read"), row.redraws) == (2, 1), "read on a moved stamp, redrawn only on a change"


def test_a_write_between_the_stamp_and_the_read_costs_no_second_read(root):
    """W4: the look keys on the stamp the read itself took, not the one before it."""
    connect = Connect()
    plain_read = connect.read

    def read(languages=None):
        connect.stamp_value[0] += 1             # Connect wrote between the look's stamp and the read
        return dict(plain_read(languages), stamp=list(connect.stamp_value))
    row, pump, _tips = _row(root, connect)
    row._read = read
    _look(row, pump, root)
    row._read = plain_read
    _look(row, pump, root)
    assert connect.count("read") == 1, "the read's own stamp is the newest: nothing to read again"


def test_a_failed_read_is_printed_once_and_read_again_only_when_the_stamp_moves(root, capsys):
    """W5: a ledger that can't be read isn't read (and printed) every 3 s."""
    connect = Connect()
    tries = []

    def broken(languages=None):
        tries.append(1)
        raise OSError("the ledger is locked")
    row, pump, _tips = _row(root, connect)
    row._read = broken
    for _ in range(3):
        _look(row, pump, root)
    assert len(tries) == 1 and capsys.readouterr().out.count("wasn't read") == 1
    connect.stamp_value[0] += 1
    row._read = connect.read
    _look(row, pump, root)
    assert row.redraws == 1 and row.line.cget("text").startswith("Connect: Up to date")


def test_the_tk_thread_never_calls_stamp_or_read(root):
    connect = Connect()
    row, pump, _tips = _row(root, connect)
    _look(row, pump, root)
    connect.stamp_value[1] += 1
    _look(row, pump, root)
    assert connect.calls and all(not main for _what, _langs, main in connect.calls)


def test_the_line_is_the_records_for_the_dashboards_language_and_hover_names_the_step(root):
    job = {"job": 3, "item": 9, "title": "Example Show - 05", "kind": "mine", "state": "mining", "reason": None,
           "step": "Anki Miner", "words": 18, "made": 0, "not_made": {}}
    connect = Connect(_record(line="Making cards 1 of 2 — Example Show - 05 (Anki Miner)", jobs=[job]))
    row, pump, tips = _row(root, connect, language="zh")
    _look(row, pump, root)
    assert connect.calls[0][1] == ("zh",)
    assert row.line.cget("text") == "Connect: Making cards 1 of 2 — Example Show - 05 (Anki Miner)"
    hover = dict((id(w), t) for w, t in tips)[id(row.line)]
    assert "Example Show - 05: Anki Miner · 18 words" in hover()


def test_the_badge_filled_while_unseen_outlined_once_seen_gone_when_empty(root):
    connect = Connect(_record(needs=[NEED, dict(NEED, id=2, kind="error", say="上層部: Anki Miner stopped.")],
                              unseen=2))
    row, pump, tips = _row(root, connect)
    _look(row, pump, root)
    assert row.badge_shown == "filled" and row.badge.cget("text") == "Needs you (2)"
    assert row.badge.cget("bg") == status_row.ACCENT and row.badge.winfo_manager() == "pack"
    assert tips.has(row.badge)

    connect.record = _record(needs=[dict(NEED, seen_at="2026-10-11T09:05:00Z")], unseen=0)
    connect.stamp_value[0] += 1
    _look(row, pump, root)
    assert row.badge_shown == "outlined" and row.badge.cget("text") == "Needs you", "no number once all are seen"
    assert row.badge.cget("bg") == status_row.BG and int(row.badge.cget("highlightthickness")) == 1

    connect.record = _record()
    connect.stamp_value[0] += 1
    _look(row, pump, root)
    assert row.badge_shown is None and row.badge.cget("text") == "" and row.badge.cget("bg") == status_row.BG, \
        "nothing open: no badge (blank, still packed: no re-layout)"


def test_switched_off_the_row_goes_and_the_poll_stops(root, monkeypatch):
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    connect = Connect()
    row, pump, _tips = _row(root, connect)
    row.start()
    assert row._timer is not None, "polling every 3 s"
    assert pump.run(root, lambda: row.redraws == 1)
    row.stop()
    assert row._timer is None and not row.frame.winfo_exists()
    stamps = connect.count("stamp")
    row.tick()
    pump.run(root, timeout=0.2)
    assert connect.count("stamp") == stamps, "no look after the switch went off"


def test_under_the_test_switch_no_timer_is_set(root):
    connect = Connect()
    row, pump, _tips = _row(root, connect)
    row.start()
    assert row._timer is None
    assert pump.run(root, lambda: row.redraws == 1), "the first look still happens"


def test_the_dashboard_with_the_preview_off_builds_no_row_and_imports_nothing(monkeypatch):
    from app import main
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    window = types.SimpleNamespace(_current_settings={"connect_enabled": False}, _connect_row=None,
                                   footer_frame=object())
    main.MasterDashboardApp._connect_row_start(window)
    assert window._connect_row is None
    assert not [m for m in sys.modules if m.startswith("app.connect")]


# --------------------------------------------------------------------------- #
# P3.2-AMN: Anki Miner's update notice, a second line
# --------------------------------------------------------------------------- #
RELEASE_PAGE = "https://github.com/0xzerolight/anki_miner/releases/tag/v3.8.0"


class WithUpdate(Connect):
    """`read` carries the record's top-level `anki_miner_update`, as `status.read` does."""

    def __init__(self, record=None, update=None):
        super().__init__(record)
        self.update = update

    def read(self, languages=None):
        return dict(super().read(languages), anki_miner_update=self.update)


def test_anki_miners_notice_appears_opens_its_page_and_goes_once_updated(root):
    """A newer Anki Miner → *Anki Miner 3.8.0 is out*, a link with its tooltip; a click opens the releases page (the
    browser stood in for); Anki Miner caught up → the line goes."""
    connect, opened = WithUpdate(update={"version": "3.8.0", "url": RELEASE_PAGE}), []
    row, pump, tips = _row(root, connect, open_url=opened.append)
    _look(row, pump, root)
    assert row.update_label.winfo_manager() == "pack" and row.update_label.cget("text") == "Anki Miner 3.8.0 is out"
    assert ("Opens Anki Miner's releases page" in [t for w, t in tips if w is row.update_label])
    row.update_label.event_generate("<Button-1>")
    assert opened == [RELEASE_PAGE]
    connect.stamp_value[0] += 1
    connect.update = None
    _look(row, pump, root)
    assert row.update_label.winfo_manager() == "", "Anki Miner updated: the notice is gone"
    row.update_label.event_generate("<Button-1>")
    assert opened == [RELEASE_PAGE], "a hidden notice opens nothing"


def test_no_notice_no_second_line(root):
    connect = WithUpdate()
    row, pump, _tips = _row(root, connect, open_url=lambda url: pytest.fail("opened"))
    _look(row, pump, root)
    assert row.redraws == 1 and row.update_label.winfo_manager() == ""


def test_the_notice_unchanged_on_a_moved_stamp_redraws_nothing_and_a_new_one_redraws(root):
    """S19: the same notice read again is no redraw; a newer release named is one."""
    connect = WithUpdate(update={"version": "3.8.0", "url": RELEASE_PAGE})
    row, pump, _tips = _row(root, connect, open_url=lambda url: None)
    _look(row, pump, root)
    _look(row, pump, root)
    connect.stamp_value[0] += 1                 # the state file rewritten with the same release
    _look(row, pump, root)
    assert (connect.count("read"), row.redraws) == (2, 1)
    connect.stamp_value[0] += 1
    connect.update = {"version": "3.9.0", "url": RELEASE_PAGE}
    _look(row, pump, root)
    assert row.redraws == 2 and row.update_label.cget("text") == "Anki Miner 3.9.0 is out"
