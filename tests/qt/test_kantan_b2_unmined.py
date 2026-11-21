"""Kantan-B2: a mined episode's ⋯ *Mine again* and the window *Words Surasura won't mine again* with *Allow again*
(a new tester, 2026-11-18: "is there a way to reset the episode to unmined?", "where does it keep a record of that?";
every word PROVISIONAL).

What a wrong answer would cost a learner:
  * an episode whose cards he deleted that no press in the window can mine again (only `surasura-cli undo --job N`);
  * words he deleted for a bad sentence, kept out for good with no list and no way back;
  * *Allow again* without an Undo, or a list that still shows a word he freed (or hides one still blocked).

The menu on the window's seed through a recording writer (`test_p41_actions`'s); the window on a real store
(`test_removed`'s), real ja / zh words.
"""
import pytest

pytest.importorskip("PyQt6")

from app.connect import feed, library
from app.qt import strings, unmined_words, windows
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_drag import rows_of, settle
from tests.qt.test_p41_actions import act, asks  # noqa: F401  (act: a fixture)
from tests.qt.test_removed import _saved, _undo, real  # noqa: F401  (real: a fixture)
from app.qt import rows

WORDS = {"ja": ("ほっ", "残念"), "zh": ("哎呀", "遗憾")}


def _row_ep(win):
    lst = win.page_widgets["current"].list
    row = next(e[1] for e in lst.model().entries if e[0] == rows.ROW and e[1].episodes)
    return row, row.episodes[0]


# --- the episode's ⋯ ------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("kind", ["in_anki", "deleted"])
def test_a_mined_episodes_menu_offers_mine_again_and_its_words_and_mine_again_asks_for_it(act, kind):
    # why: the tester's way to "reset the episode to unmined" — one entry on its ⋯, an ask with its toast's Undo
    _seed, win, writer = act()
    row, ep = _row_ep(win)
    ep = ep._replace(status=view_rows.Status(kind, "2", "", "ok"), cards=2 if kind == "in_anki" else 0,
                     deleted=kind == "deleted", mining=False)
    entries = win.mine.episode_entries(row, ep)
    assert [e.name for e in entries] == ["ep-mine-again", "ep-unmined-words"]
    assert entries[0].label == strings.MINE_AGAIN and entries[0].tip == strings.MINE_AGAIN_TIP and entries[0].writes
    assert entries[1].label == strings.UNMINED_ENTRY and entries[1].tip
    entries[0].payload()
    settle(50)
    assert asks(writer) and asks(writer)[-1][1] == [ep.id]
    assert win.toasts.card.base == strings.MINE_AGAIN_ASKED.format(label=ep.label)


def test_an_unmined_episode_offers_no_mine_again(act):
    # why: *Mine again* is for a mined episode only; one waiting keeps its own *Mine now*
    _seed, win, _writer = act()
    row, ep = _row_ep(win)
    for st in (view_rows.Status("mine", "Mine", "", "ink"), view_rows.Status("waiting", "", "", "faint")):
        assert "ep-mine-again" not in [e.name for e in win.mine.episode_entries(row, ep._replace(status=st))]


def test_with_connect_off_mine_again_says_why_and_asks_nothing(act):
    _seed, win, writer = act(connect_off=feed.OFF_CONNECT)
    row, ep = _row_ep(win)
    ep = ep._replace(status=view_rows.Status("deleted", "", "", "faint"), deleted=True, mining=False)
    entry = win.mine.episode_entries(row, ep)[0]
    assert entry.tip == strings.ROWS_ACTION_OFF.format(tip=strings.MINE_AGAIN_TIP, why=feed.OFF_CONNECT)
    entry.payload()
    settle(50)
    assert asks(writer) == [] and win.bar_line.full() == feed.OFF_CONNECT


# --- the window ---------------------------------------------------------------------------------------------------- #
def _deleted_cards(language):
    """`before(store)`: the first two NOW items mined (WORDS), then both cards deleted in Anki -> the hook."""
    def before(store):
        a, b = store.ids("now")[:2]
        w = WORDS[language]
        library.record_batch(store, a, {w[0]: [101]}, "2026-11-18T10:00:00Z", batch="t-1")
        library.record_batch(store, b, {w[1]: [201]}, "2026-11-18T11:00:00Z", batch="t-2")
        store.notes_gone([101, 201])
        before.ids = (a, b)
    return before


def _open(win, **kw):
    w = unmined_words.open_window(win, **kw)
    assert wait_until(lambda: not w._reading and w.reads, 10)
    settle()
    return w


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_list_shows_the_deleted_cards_words_and_allow_again_frees_one_with_an_undo(real, language):
    before = _deleted_cards(language)
    store, win, writer = real(language, before=before)
    w = _open(win)
    words = WORDS[language]
    assert w.order == [words[1], words[0]] and w.none.isHidden()          # the newest made first
    line = w.lines[words[0]]
    assert line.allow.toolTip() == strings.UNMINED_ALLOW_TIP.format(word=words[0])
    assert line.detail.text().startswith("from ") and len(line.detail.text()) > len("from ")
    line.allow.click()
    assert words[0] not in w.lines                                          # it leaves the list at the press
    assert wait_until(lambda: words[0] not in library.made_words_all(store), 10)
    _saved(win, writer)
    assert win.toasts.card.base == strings.UNMINED_ALLOWED.format(word=words[0])
    assert wait_until(lambda: not w._reading and w.order == [words[1]], 10)
    _undo(win)                                                              # the toast's one Undo: kept out again
    assert wait_until(lambda: words[0] in library.made_words_all(store), 10)
    assert wait_until(lambda: not w._reading and w.order == [words[1], words[0]], 10)


def test_from_an_episode_only_its_words_and_an_empty_list_says_so(real):
    before = _deleted_cards("ja")
    store, win, _writer = real("ja", before=before)
    a, _b = before.ids
    w = _open(win, item_ids=(a,), label="第1話")
    assert w.order == [WORDS["ja"][0]]
    other = store.ids("now")[3]
    w2 = _open(win, item_ids=(other,), label="第4話")
    assert w2 is not w and w2.order == [] and w2.none.text() == strings.UNMINED_NONE_OF


def test_settings_door_opens_the_window(real):
    _store, win, _writer = real("ja")
    op = next(op for op in windows.OPENERS if op.name == "unmined-words")
    got = windows.launch(win, op)
    assert isinstance(got, unmined_words.UnminedWindow)
    assert wait_until(lambda: not got._reading and got.reads, 10)
    assert got.none.text() == strings.UNMINED_NONE

