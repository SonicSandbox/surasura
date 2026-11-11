"""A part Anki Miner failed on is offered again (field report on 3.0.0, Mattias #5; Sonic's rule: nothing silently
refused). Connect's feed gives such a file a FAILED stone (`tests/connect/test_rm_failed_part_again.py`); here, what
the window makes of it: its status a *Try again* button that asks the store's `ask_mining` for that file — the one way
to ask (C2), its toast with Undo —, the same on the episode's ⋯, Finished's and the rows' *Mine* no longer passing it
by as a file in Anki or one whose cards were deleted, *Needs you*'s line its own *Try again*, and the pill turning
from the press on (`press_ids`).

What a wrong answer would cost: a learner pressing every button on a part whose words are on no card, and each saying
there is nothing to do (3.0.0); or a *Try again* that asks for files that never failed.

On the window's seed (Japanese titles) through a recording writer (`test_p41_actions`'s), and on statuses built as
`view_rows` builds them.
"""
import pytest

pytest.importorskip("PyQt6")

from app.connect import feed, runner
from app.qt import rows, strings
from app.services import needs as service
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_drag import settle
from tests.qt.test_p41_actions import act, asks  # noqa: F401  (act: a fixture)

FAILED = feed.Item(kind=feed.FAILED, words=feed.WORDS[feed.FAILED], tip=runner.MINE_FAILED, job=4, made=2, total=5)


def _ep(st, n=3, cards=0, deleted=False):
    return view_rows.Episode(id=n, label=f"第{n}章", number=n, title="銀河鉄道の夜", watched=False, cards=cards,
                             mining=False, missing=False, removed=False, in_top=True, pct=0, n_new=0, status=st,
                             mark=None, rel_path=f"HighPriority/銀河鉄道の夜/銀河鉄道の夜 第{n}章.epub",
                             play_tip="", can_play=True, deleted=deleted)


def _retry(cards=2):
    return view_rows._connected(view_rows.Status("in_anki", str(cards), "", "ok"), FAILED, "book")


def test_a_failed_parts_status_is_a_try_again_button_for_that_file_with_its_click_said():
    st = _retry()
    ep = _ep(st, cards=2)
    name, tip, ask = rows.action_of(st, (ep,), None, "book")
    assert name == "try-again" and ask.ids == (3,)
    assert tip == strings.ROWS_TRY_AGAIN_TIP[True].format(tip=st.tip)
    assert name in rows.ASKS and rows.asks_connect(name, "video") and not rows.asks_connect(name, "book")
    assert rows.STATUS_ICON["retry"] and strings.ROWS_ACTION_NAMES["try-again"] == "Try again"


def test_try_again_and_mine_count_a_failed_file_whatever_it_made_and_nothing_else_in_anki():
    retry = _retry()
    in_anki = view_rows.Status("in_anki", "4", "", "ok")
    deleted = view_rows.Status("deleted", "", "", "faint")
    eps = [_ep(retry, 1, cards=2), _ep(_retry(0), 2, deleted=True), _ep(in_anki, 3, cards=4),
           _ep(deleted, 4, deleted=True), _ep(view_rows.Status("mine", "Mine", "", "ink"), 5)]
    assert [e.id for e in rows.asked_files("retry", eps)] == [1, 2]
    assert [e.id for e in rows.asked_files("mine", eps)] == [1, 2, 5], "never one in Anki or deleted, a failed one yes"
    assert [e.id for e in rows.asked_files("waiting", eps)] == [5], "a failed one waits on no turn: its own button"


def test_connect_off_a_try_again_on_a_video_asks_nothing_and_says_why():
    st = view_rows._connected(view_rows.Status("in_anki", "2", "", "ok"), FAILED, "video")
    name, tip, _ask = rows.action_of(st, (_ep(st, cards=2),), feed.OFF_CONNECT, "video")
    assert name == "try-again" and tip == strings.ROWS_ACTION_OFF.format(tip=st.tip, why=feed.OFF_CONNECT)


def test_the_episodes_menu_offers_try_again_where_its_pill_is_try_again(act):
    _seed, win, writer = act()
    lst = win.page_widgets["current"].list
    row = next(e[1] for e in lst.model().entries if e[0] == rows.ROW and e[1].episodes)
    st = _retry()
    ep = row.episodes[0]._replace(status=st, cards=2)
    entries = win.mine.episode_entries(row, ep)
    assert [e.name for e in entries] == ["ep-try-again"]
    assert entries[0].label == strings.ROWS_ACTION_NAMES["try-again"]
    entries[0].payload()
    settle(50)
    assert asks(writer) and asks(writer)[-1][1] == [ep.id]


def test_needs_yous_try_again_is_the_rows_own_ask_for_that_file(act, monkeypatch):
    """The *Needs you* line Connect writes when Anki Miner stopped twice: *Try again* (hooked by the window's mine
    routing, hidden until then) asks the store for that one file, through the writer, with the toast; its card stays
    until the new try ends (fixed by itself, or a new line). Connect off: nothing asked, said."""
    _seed, win, writer = act()
    ny = win.needs_you
    assert ny.available("try_again")
    rec = {"needs": [{"id": 11, "kind": "mine-failed", "say": runner.MINE_FAILED_SAY.format(title="銀河鉄道の夜 第3章"),
                      "item": 3, "title": None, "at": "2026-11-11T05:00:00Z", "seen_at": None}]}
    entry = next(e for e in service.entries(None, connect=rec) if e.kind == "mine-failed")
    assert entry.actions[0] == "try_again"
    ny.act("try_again", entry, None)
    assert wait_until(lambda: asks(writer), 5)
    assert asks(writer) == [("ask_mining", [3], {"on": True})]
    assert win.toasts.card.isVisible() and win.toasts.card.base == strings.MINE_ASKED_ONE
    del writer.calls[:]
    win.mine._off_read(feed.OFF_AUTOMATION)
    ny.act("try_again", entry, None)
    settle(100)
    assert asks(writer) == [] and win.bar_line.full() == feed.OFF_AUTOMATION
