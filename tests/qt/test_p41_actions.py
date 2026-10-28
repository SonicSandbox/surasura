"""P4.1 L2, package W2 (the P4.1 RUNBOOK's rows 4.1.11 and 4.1.12's two hidden hooks; C2, C3, C6, IK S3, S7): the
statuses' buttons on Current's rows — *Mine now* (Waiting's icon), *Mine this* (Mine), *No video*'s *Link…* · *Mine
text* — by the hand and by the keyboard, routed by the window (`app/qt/mine_actions.py`) to the writer's `ask_mining` /
`link_video` and to Anki Miner's own window; Finished's *Mine* / *Mine it too*, the arrivals' *Mine them too* and Needs
you's *Mine the text only* set; the writer's after-commit look that kicks Connect. On the window's seed (Japanese titles)
through a recording writer, and on a real migrated store with the real writer where the store's own write matters.

What a wrong answer would cost a learner:
  * a *Mine now* that asks twice, or for the wrong files (a file already in Anki, one he deleted the cards of), or a
    click that does nothing and says nothing;
  * the keyboard not reaching what the hand reaches, or a focus tip that says something else than the hover;
  * a button that acts while Connect is off — cards made he switched off — or one that says nothing about why;
  * a book's *Mine this* queued for Anki Miner's video API (it can only fail), instead of Anki Miner's own window;
  * an ask that commits but never wakes Connect, so its cards wait for the next unrelated move.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QRectF, Qt
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.connect import feed
from app.services import moves
from app.qt import mine_actions, rows, shell, strings
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, open_window, real, settle   # noqa: F401  (real: a fixture)


class _NoSettings:
    """The settings service's one call the after-commit hook makes: an empty settings.json."""
    def get(self):
        return {}


class P41Writer(FakeWriter):
    def ask_mining(self, ids, asked=True, label=None):
        return self._put("ask_mining", ids, label, on=asked)

    def link_video(self, item_id, video_path, label=None):
        return self._put("link_video", [item_id], label, path=video_path)


@pytest.fixture
def act(qapp, monkeypatch):
    """A window with a recording writer; `off[0]` is what Connect's switch reads as (None: on), read through the
    routing's own worker read as the window opens."""
    made = []
    off = [None]
    reads = []
    monkeypatch.setattr(mine_actions, "connect_off", lambda _s: (reads.append(1), off[0])[1])

    def make(connect_off=None):
        from tests.fixtures import window_seed
        off[0] = connect_off
        seed = window_seed.build()
        writer = P41Writer(seed.library, apply=False)
        win, services = open_window(qapp, seed, writer, size=(1280, 1100))
        assert wait_until(lambda: reads, 5)
        settle()
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def lst_of(win):
    return win.page_widgets["current"].list


def parts_of(lst, i):
    return lst.delegate.parts(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0)))


def row_with(lst, kind, media_word="video"):
    """A closed Current row (not Up Next) whose status is `kind`, scrolled to the top: its index."""
    entries = lst.model().entries
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].status is not None and
             e[1].status.kind == kind and (media_word is None or e[1].media_word == media_word))
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    return i


def action(lst, i):
    return next(p for p in parts_of(lst, i) if p[0] in rows.ACTION_NAMES)


def click(lst, p):
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=p[1].center())
    QApplication.processEvents()


def asks(writer):
    return [c for c in writer.calls if c[0] == "ask_mining"]


# --- the buttons and their words -------------------------------------------------------------------------------------- #
def test_each_status_that_is_a_button_names_its_click_and_its_hover_tip_comes_through_the_bubble(act):
    """4.1.11: Waiting's icon is *Mine now*, Mine is *Mine this*, No video offers *Link…* · *Mine text* — each tip its
    status's own words, then its action on a line of its own; the hover shows it in the window's bubble."""
    _seed, win, _writer = act()
    lst = lst_of(win)
    for kind, name, words in (("waiting", "mine-now", strings.ROWS_MINE_NOW_TIP),
                              ("mine", "mine-this", strings.ROWS_MINE_THIS_TIP),
                              ("no_media", "no-media", strings.ROWS_NO_MEDIA_TIP)):
        i = row_with(lst, kind, None)
        row = lst.model().entries[i][1]
        p = action(lst, i)
        if isinstance(words, dict):                     # a mining ask counts its files when more than one (AD-2)
            n = len(p[3].ids)
            words = words[n == 1].replace("{n}", str(n))
        assert p[0] == name and p[2] == words.format(tip=rows.status_tip(row.status)), kind   # row 38
        ev = QHelpEvent(QEvent.Type.ToolTip, p[1].center(), lst.viewport().mapToGlobal(p[1].center()))
        lst.viewportEvent(ev)
        assert wait_until(lambda: win.tooltips.showing() == p[2]), kind
        win.tooltips.hide()


def test_a_click_on_mine_now_asks_once_for_the_waiting_files_with_a_toast_and_undo(act):
    """C2: *Mine now* is the store's `ask_mining` through the window's writer — one ask, for the row's files that wait
    in the top (never one in Anki), its toast naming the title with Undo; the row stays closed."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "waiting")
    row = lst.model().entries[i][1]
    p = action(lst, i)
    click(lst, p)
    want = [e.id for e in row.episodes if e.in_top and not (e.cards or e.mining or e.missing)]
    assert want and asks(writer) == [("ask_mining", want, {"on": True})]
    assert lst.model().open_key is None
    assert win.toasts.card.isVisible() and strings.MINE_ASKED.format(title=row.title) == win.toasts.card.base


def test_mine_this_below_the_line_asks_for_every_file_that_can_be_mined(act):
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "mine")
    row = lst.model().entries[i][1]
    click(lst, action(lst, i))
    assert asks(writer) == [("ask_mining", [e.id for e in row.episodes if not e.missing], {"on": True})]


def test_a_book_row_waits_quietly_for_anki_miner_its_status_no_button_and_nothing_opened(act, monkeypatch):
    """Alpha 4 M1 (was K67's *Mine text*; Sonic 2026-10-27: "I honestly don't want to ever have to open anki miner.
    Ever."): a book's row says *Waits for Anki Miner*, quietly — no *Mine this* to press, no ask, and nothing opens
    Anki Miner's window."""
    from app.connect import anki_miner
    from app.services import view_rows
    _seed, win, writer = act()
    lst = lst_of(win)
    opened = []
    monkeypatch.setattr(anki_miner, "find", lambda _s: opened.append("looked"))
    entries = lst.model().entries
    books = [e[1] for e in entries if e[0] == rows.ROW and e[1].episodes and all(ep.text for ep in e[1].episodes)]
    assert books, "the seed holds a book or a text"
    for row in books:
        assert row.status.kind == "books" and row.status.label == view_rows.STRINGS["books_wait"]
        assert row.status.tone == "faint"
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1] is books[0])
    assert not any(p[0] in rows.ACTION_NAMES for p in parts_of(lst, i)), "nothing to press"
    assert asks(writer) == [] and opened == []


def test_no_video_offers_link_alone_and_link_hands_the_chosen_video_to_the_writer(act):
    """4.1.9L: *No video*'s button opens *Link…* (alpha 4 M1: *Mine text*, Anki Miner's own window, is gone); *Link…*
    picks a video (the picker's filter: the videos Connect makes cards from) and the writer links it to that episode."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "no_media", None)
    row = lst.model().entries[i][1]
    p = action(lst, i)
    click(lst, p)
    menu = lst.action_menu
    assert menu is not None and [a.text() for a in menu.actions()] == [strings.ROWS_LINK]
    assert all(a.toolTip() for a in menu.actions())
    asked = []
    win.mine.pick_file = lambda title, folder, patterns: asked.append((title, patterns)) or r"D:\Videos\第1話.mkv"
    menu.actions()[0].trigger()
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "link_video"], 5)
    assert [c for c in writer.calls if c[0] == "link_video"] == [("link_video", [p[3].episode.id],
                                                                   {"path": r"D:\Videos\第1話.mkv"})]
    assert asked[0][0] == strings.LINK_TITLE.format(label=p[3].episode.label) and "*.mkv" in asked[0][1]
    menu.close()
    assert asks(writer) == [] and row.key == lst.model().entries[i][1].key


def test_a_button_never_asks_for_a_file_in_anki_being_mined_or_whose_cards_were_deleted(act):
    """C3 / N15: *Mine now* never re-makes a word whose note is gone — a file whose cards the learner deleted is never
    in its ask; nor one already in Anki or being mined. *Mine this* skips a file not on disk."""
    _seed, win, _writer = act()
    lst = lst_of(win)
    row = next(e[1] for e in lst.model().entries if e[0] == rows.ROW and len(e[1].episodes) >= 4)
    eps = [e._replace(in_top=True, missing=False, cards=0, mining=False, deleted=False) for e in row.episodes]
    changed = {eps[0].id: eps[0]._replace(cards=4), eps[1].id: eps[1]._replace(mining=True),
               eps[2].id: eps[2]._replace(deleted=True)}
    episodes = [changed.get(e.id, e) for e in eps]
    got = [e.id for e in rows.asked_files("waiting", episodes)]
    assert got == [e.id for e in eps[3:]]
    gone = eps[3]._replace(missing=True)
    assert [e.id for e in rows.asked_files("mine", episodes[:3] + [gone] + eps[4:])] == [e.id for e in eps[4:]]


# --- the keyboard ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Space])
def test_the_keyboard_reaches_the_button_with_the_same_tip_and_enter_or_space_presses_it(act, key):
    """RS-6: the same text and action on keyboard focus — → takes the keyboard to the row's button and shows the hover's
    tip; Enter / Space press it (one ask, the row not opened); ← lets it go (Enter then opens the row as before)."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "waiting")
    p = action(lst, i)
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    QTest.keyClick(lst, Qt.Key.Key_Right)
    assert lst.action_focus == (lst.model().entries[i][1].key, "mine-now")
    assert wait_until(lambda: win.tooltips.showing() == p[2])
    QTest.keyClick(lst, key)
    assert len(asks(writer)) == 1 and asks(writer)[0][1] == list(p[3].ids)
    assert lst.model().open_key is None and lst.action_focus is None
    QTest.keyClick(lst, Qt.Key.Key_Right)
    QTest.keyClick(lst, Qt.Key.Key_Left)
    assert lst.action_focus is None
    QTest.keyClick(lst, Qt.Key.Key_Return)                     # the row's own Enter again: it opens, nothing asked
    assert lst.model().open_key == lst.model().entries[i][1].key and len(asks(writer)) == 1


def test_a_rows_accessible_text_names_its_status_and_how_the_keyboard_presses_its_button(act):
    """RS-6: a row's status read out as words (`view_rows.spoken`), and its button's name and key in its description."""
    _seed, win, _writer = act()
    lst = lst_of(win)
    for kind, name in (("waiting", "mine-now"), ("mine", "mine-this"), ("no_media", "no-media")):
        i = row_with(lst, kind, None)
        row = lst.model().entries[i][1]
        idx = lst.model().index(i, 0)
        assert row.status.label in lst.model().data(idx, Qt.ItemDataRole.AccessibleTextRole), kind
        assert lst.model().data(idx, Qt.ItemDataRole.AccessibleDescriptionRole).endswith(
            strings.ROWS_ACTION_KEY.format(action=strings.ROWS_ACTION_NAMES[name])), kind


# --- Connect off --------------------------------------------------------------------------------------------------------- #
def test_while_connect_is_off_the_buttons_ask_nothing_and_say_why(act):
    """IK S7: off (Make cards for me off, or D29's automation off), a click or a key asks nothing; the tip says why in
    the feed's own words, and the description names no key."""
    _seed, win, writer = act(connect_off=feed.OFF_CONNECT)
    lst = lst_of(win)
    assert lst.connect_off == feed.OFF_CONNECT
    i = row_with(lst, "waiting")
    row = lst.model().entries[i][1]
    p = action(lst, i)
    assert p[2] == strings.ROWS_ACTION_OFF.format(tip=rows.status_tip(row.status), why=feed.OFF_CONNECT)
    click(lst, p)
    assert wait_until(lambda: win.tooltips.showing() == p[2])
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    QTest.keyClick(lst, Qt.Key.Key_Right)
    QTest.keyClick(lst, Qt.Key.Key_Return)
    k = row_with(lst, "no_media", None)
    click(lst, action(lst, k))
    # P4.1 WF (IK N2): *Link…* · *Mine text* need no Connect — the menu opens while it is off (was: no menu)
    assert lst.action_menu is not None and lst.action_menu.isVisible()
    lst.action_menu.close()
    assert asks(writer) == [] and [c for c in writer.calls if c[0] == "link_video"] == []
    desc = lst.model().data(lst.model().index(i, 0), Qt.ItemDataRole.AccessibleDescriptionRole)
    assert "Enter" not in desc
    win.mine.mine_ids([row.episodes[0].id])                   # the arrivals' Mine them too: refused, said in the bar
    assert asks(writer) == [] and win.bar_line.full() == feed.OFF_CONNECT
    # P4.1 L2 mutants (W10): Finished's *Mine* goes through the same ask, refused while off (no row button gates it)
    win.bar_line.set_full("")
    win.mine.mine_row(row, [e.id for e in row.episodes])
    assert asks(writer) == [] and win.bar_line.full() == feed.OFF_CONNECT


def test_the_switch_is_read_again_when_connect_or_automation_is_written(act):
    _seed, win, _writer = act(connect_off=feed.OFF_AUTOMATION)
    lst = lst_of(win)
    assert lst.connect_off == feed.OFF_AUTOMATION
    seen = []
    real_off = mine_actions.connect_off
    mine_actions.connect_off = lambda s: (seen.append(1), None)[1]
    try:
        win.mine._settings_written({"covers_download"})        # anything else: not read again
        settle(100)
        assert seen == [] and lst.connect_off == feed.OFF_AUTOMATION
        win.mine._settings_written({"logic.automation"})
        assert wait_until(lambda: lst.connect_off is None and seen, 5)
    finally:
        mine_actions.connect_off = real_off


def test_connect_off_reads_both_switches_in_the_feeds_words():
    assert mine_actions.connect_off({"connect_enabled": True, "logic": {"automation": True}}) is None
    assert mine_actions.connect_off({"connect_enabled": False, "logic": {"automation": True}}) == feed.OFF_CONNECT
    assert mine_actions.connect_off({"connect_enabled": True, "logic": {"automation": False}}) == feed.OFF_AUTOMATION
    assert mine_actions.connect_off(None) == feed.OFF_CONNECT


# --- the hooks P4.1 sets ---------------------------------------------------------------------------------------------- #
def test_finished_mine_and_mine_it_too_and_the_arrivals_mine_them_too_ask_through_the_writer(act):
    """C2: Finished's *Mine* (no cards: every file) and *Mine it too* (the files with none), and the arrivals' *Mine
    them too*: the same one ask."""
    _seed, win, writer = act()
    fa = win.finished
    page = win.page_widgets["finished"]
    win.show_tab("finished")
    assert wait_until(lambda: page.view_model is not None and page.view_model.finished, 10)
    fin_rows = [r for m in page.view_model.finished for r in m.rows if r.media_word == "video"]
    mined = next(r for r in fin_rows if len(r.episodes) > 1 and all(e.cards for e in r.episodes))
    some = mined._replace(episodes=(mined.episodes[0]._replace(cards=0),) + mined.episodes[1:])   # one not mined
    fa.menu_pick(some, "mine-too")
    assert asks(writer) == [("ask_mining", [some.episodes[0].id], {"on": True})]
    fa.menu_pick(mined, "mine-too")                            # every file in Anki: nothing to ask
    assert len(asks(writer)) == 1
    none = mined._replace(episodes=tuple(e._replace(cards=0) for e in mined.episodes))
    assert "mine" in [e[0] for e in fa.menu_entries(none)]
    fa.menu_pick(none, "mine")
    assert asks(writer)[-1][1] == [e.id for e in none.episodes]
    # P4.1 WF (S5): the arrivals' *Mine them too* asks by the rows' rule, told by the tray's own rows (was: any ids)
    tray = win.arrivals_tray
    assert wait_until(lambda: tray.watched(), 10)
    want = [e.id for a in tray.watched() for e in rows.asked_files("mine", a.episodes)]
    assert want, "the seed's watched arrivals hold a file still to mine"
    n = len(asks(writer))
    tray.mine_too([i for a in tray.watched() for i in a.item_ids] + [want[0], 999999])   # 999999: no tray row has it
    assert len(asks(writer)) == n + 1 and asks(writer)[-1][1] == want


def test_needs_you_has_no_mine_the_text_only_any_more(act):
    """Alpha 4 M1: *Needs you*'s *Mine the text only* (Anki Miner's own window) is gone — no hook, nothing offered."""
    _seed, win, _writer = act()
    ny = win.needs_you
    assert "mine_text_only" not in ny.hooks


def test_needs_you_make_their_cards_is_connects_ordinary_work_in_the_gaps_language_then_answers_the_entry(
        act, monkeypatch):
    """4.1.12, moved to P4.1 WF (IK D-1 lean (a); adversary S3, S4): a gap's *Make their cards* is no ask (was: one
    `ask_mining`) — `actions.make_cards` in the entry's own language (here Chinese, while the window's writer is the
    Japanese one), Connect kicked once it queued any, and only then the entry answered as *Leave them* answers it; the
    bar counts the episodes, no title pasted. What a wrong answer would cost: deleted cards made again in bulk, a
    gap answered with no cards coming, or Japanese titles mined for a Chinese gap. While Connect is off, or when the
    gap is gone, nothing is answered."""
    from app.services import needs as service
    from app.services import press as press_service
    monkeypatch.setattr(press_service, "LINGER_S", 0.0)         # (the card stays here: pressed again at once)
    _seed, win, writer = act()
    ny = win.needs_you
    assert ny.available("make_cards")
    order = []
    monkeypatch.setattr(service, "answer", lambda lang, keys: order.append(("answer", lang, list(keys))) or len(keys))
    ny.connect_calls["kick"] = lambda settings: order.append(("kick",)) or object()
    made = [2]
    win.mine.make_cards = lambda lang, gap_id: order.append(("make", lang, gap_id)) or made[0]
    ny.language = "zh"                                       # the gap came from Chinese; the writer is Japanese
    entry = service._gap_entry({"id": 3, "since": "2026-10-10T08:00:00Z", "until": "2026-10-12T21:00:00Z",
                                "items": [11, 12, 12]}, set())
    ny.act("make_cards", entry, None)
    assert wait_until(lambda: len(order) == 3, 5), order
    assert order == [("make", "zh", 3), ("kick",), ("answer", "zh", service.answer_keys(entry))]
    assert asks(writer) == [] and writer.calls == [], "no store ask, nothing to undo"
    assert wait_until(lambda: win.bar_line.full() == strings.MAKE_CARDS_QUEUED[False].format(n=2), 5)
    assert entry.title not in win.bar_line.full()
    del order[:]
    made[0] = 0                                              # every episode has its job already: answered, no kick
    ny.act("make_cards", entry, None)
    assert wait_until(lambda: win.bar_line.full() == strings.MAKE_CARDS_NONE, 5)
    assert [o[0] for o in order] == ["make", "answer"]
    del order[:]
    made[0] = False                                          # no ledger, or the gap gone: nothing answered
    ny.act("make_cards", entry, None)
    assert wait_until(lambda: win.bar_line.full() == strings.MAKE_CARDS_GONE, 5)
    assert order == [("make", "zh", 3)]
    del order[:]
    win.mine._off_read(feed.OFF_AUTOMATION)
    ny.act("make_cards", entry, None)
    settle(100)
    assert order == [] and win.bar_line.full() == feed.OFF_AUTOMATION


# --- the kick after a commit ------------------------------------------------------------------------------------------ #
def test_the_after_commit_hook_looks_once_per_commit_and_never_stops_the_writer(monkeypatch):
    from app.connect import window_link
    looked = []
    monkeypatch.setattr(window_link.Link, "after_change", lambda self, *a, **k: looked.append(self.language))
    hook = shell.connect_after_commit("ja", _NoSettings())       # W1's hook: the one kept at the L2 merge
    hook(object(), "ask_mining")
    hook(object(), "move")
    assert looked == ["ja", "ja"]
    monkeypatch.setattr(window_link.Link, "after_change", lambda self, *a, **k: 1 / 0)
    moves.Writer._call(None, hook, object(), "undo")           # a look that fails: the writer prints it, never raises


def test_library_for_hangs_the_kick_on_the_writer(qapp, monkeypatch):
    from app.services import settings as settings_service
    reader, writer = shell.library_for("ja", settings_service.SettingsService())
    try:
        assert writer.after_commit.__qualname__.startswith("connect_after_commit")
    finally:                                                 # P4.1 WF (adversary N8): nothing of it left open
        reader.stop()
        writer.opener.close()


def test_a_click_on_mine_this_on_a_real_store_asks_once_and_kicks_connect_once(real, monkeypatch):
    """C2 end to end: the real writer commits the store's `mine_asked`, then its after-commit look runs once (on the
    writer's thread) — the kick that wakes Connect (`window_link.Link.after_change`, a spy here: no process started)."""
    from app.connect import window_link
    looked = []
    monkeypatch.setattr(window_link.Link, "after_change", lambda self, *a, **k: looked.append(self.language))
    store, win, writer = real()
    writer.after_commit = shell.connect_after_commit("ja", _NoSettings())
    win.mine._off_read(None)
    lst = lst_of(win)
    entries = lst.model().entries
    i = next((n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].media_word == "video" and
              any(p[0] in ("mine-now", "mine-this") for p in parts_of(lst, n))), None)
    assert i is not None, [(e[1].status.kind if e[1].status else None) for e in entries if e[0] == rows.ROW]
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    p = action(lst, i)
    click(lst, p)
    assert wait_until(lambda: all(store.item(k).get("mine_asked") for k in p[3].ids) and looked, 10)
    settle(200)
    assert looked == ["ja"]


# --- P4.1 WF: the reviews' fixes ------------------------------------------------------------------------------------ #
def _ep(st, n=5):
    from app.services import view_rows
    return view_rows.Episode(id=n, label=f"第{n}話", number=n, title="葬送のフリーレン", watched=False, cards=0,
                             mining=False, missing=False, removed=False, in_top=True, pct=0, n_new=0, status=st,
                             mark=None, rel_path=f"HighPriority/葬送のフリーレン/葬送のフリーレン 第{n}話.srt",
                             play_tip="", can_play=True)


def test_not_timed_is_no_mine_now_button_and_a_wait_on_anki_or_battery_is():
    """WF fix 3 (adversary S2 / IK S1), as amended by Sonic 2026-10-22 (laptop round 5, M-3 A): *Not timed* is a warn
    *Waiting* with no *Mine now* (its way on is *Mine anyway* in Needs you) — its tip the wait's own, never "Click to
    mine it now". A wait on the battery or on Anki is *Mine now* as every *Waiting* is: on battery the press is the
    yes for that one episode, waiting for Anki it goes first once Anki answers, and the tip says which. A *Waiting* for
    its turn stays the *Mine now* button."""
    from app.connect import runner
    from app.services import view_rows
    plain = view_rows.Status("waiting", "Waiting", "In your top 20: it mines by itself, in turn", "dim")
    st = view_rows._connected(plain, feed.Item(feed.NOT_TIMED, feed.WORDS[feed.NOT_TIMED], "not timed to its video",
                                               1, 0, 0), "video")
    assert (st.kind, st.tone) == ("waiting", "warn")
    name, tip, ask = rows.action_of(st, (_ep(st),))
    assert (name, ask) == ("status", None) and tip == st.tip and "Click to mine it now" not in tip
    for kind, reason, says in ((feed.ANKI, runner.ANKI_CLOSED, "goes first once Anki answers"),
                               (feed.BATTERY, runner.ON_BATTERY, "mine this one now, on battery")):
        st = view_rows._connected(plain, feed.Item(kind, feed.WORDS[kind], reason, 1, 0, 0), "video")
        # A3W-5 (Sonic, 2026-10-24 night): on battery is a plain wait (a still arc), amber only a wait on you
        assert (st.kind, st.tone) == ("waiting", "dim" if kind == feed.BATTERY else "warn"), kind
        name, tip, ask = rows.action_of(st, (_ep(st),))
        assert name == "mine-now" and ask is not None, kind
        assert tip.startswith(st.label + "\n" + reason) and says in tip, kind     # row 38: the icon's name first
    turn = view_rows._connected(plain, feed.Item(feed.WAITING, feed.WORDS[feed.WAITING], "", 1, 0, 0), "video")
    assert turn.tone == "dim" and rows.action_of(turn, (_ep(turn),))[0] == "mine-now"


def test_a_non_video_mine_this_tip_never_names_anki_miners_window_and_needs_no_connect():
    """WF fixes 6 and 7 (IK S5, N2), alpha 4 M1: a non-video file's *Mine this* tip is its status's own (never "mine it
    now", never Anki Miner's window), the same while Connect is off — it asks nothing; a video's *Mine this* is
    refused while Connect is off."""
    from app.services import view_rows
    st = view_rows.Status("mine", "Mine", "Not in your top 20: it isn't mined yet", "ink")
    name, tip, _ask = rows.action_of(st, (_ep(st),), None, "text")
    assert name == "mine-this" and tip == st.tip and "Anki Miner" not in tip
    assert rows.action_of(st, (_ep(st),), feed.OFF_CONNECT, "text")[1] == tip
    assert rows.action_of(st, (_ep(st),), feed.OFF_CONNECT, "video")[1] == strings.ROWS_ACTION_OFF.format(
        tip=st.tip, why=feed.OFF_CONNECT)
    assert not rows.asks_connect("no-media") and not rows.asks_connect("mine-this", "text")
    assert rows.asks_connect("mine-now") and rows.asks_connect("mine-this", "video")


def test_while_connect_is_off_link_still_links_and_a_video_ask_is_still_refused(act):
    """WF fix 7 (IK N2): *Link…* needs no Connect — chosen while Connect is off, the writer links the video; *Mine
    now* on a video stays refused (nothing asked)."""
    _seed, win, writer = act(connect_off=feed.OFF_CONNECT)
    lst = lst_of(win)
    i = row_with(lst, "no_media", None)
    p = action(lst, i)
    click(lst, p)
    assert lst.action_menu is not None
    win.mine.pick_file = lambda title, folder, patterns: r"D:\Videos\第1話.mkv"
    lst.action_menu.actions()[0].trigger()
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "link_video"], 5)
    lst.action_menu.close()
    click(lst, action(lst, row_with(lst, "waiting")))
    assert asks(writer) == []


def test_one_file_is_said_as_one(act):
    """WF fix 6 (IK S5; the N1 disposition): "1 file", never "1 files"."""
    assert strings.MINE_ASKED_ONE == "1 file: its cards come next"
    _seed, win, writer = act()
    tray = win.arrivals_tray
    assert wait_until(lambda: tray.watched(), 10)
    open_ = [e for a in tray.watched() for e in rows.asked_files("mine", a.episodes)]
    assert open_, "the seed's watched arrivals hold a file still to mine"
    win.mine.mine_ids([open_[0].id])
    assert asks(writer)[-1][1] == [open_[0].id] and win.toasts.card.base == strings.MINE_ASKED_ONE


def test_the_bulk_asks_never_name_a_file_in_anki_being_mined_or_whose_cards_were_deleted(act):
    """WF fix 5 (adversary S5; C3 / N15): Finished's *Mine* / *Mine it too* and the arrivals' *Mine them too* ask by
    the rows' rule — an ask makes a job that re-makes every word whose note is gone, so a file whose cards the learner
    deleted is never in it, nor one in Anki or being mined. Nothing left: nothing asked, and the bar says so."""
    _seed, win, writer = act()
    page = win.page_widgets["finished"]
    win.show_tab("finished")
    assert wait_until(lambda: page.view_model is not None and page.view_model.finished, 10)
    row = next(r for m in page.view_model.finished for r in m.rows if r.media_word == "video" and len(r.episodes) >= 4)
    eps = [e._replace(cards=0, mining=False, deleted=False, missing=False) for e in row.episodes]
    eps[0], eps[1], eps[2] = eps[0]._replace(cards=3), eps[1]._replace(deleted=True), eps[2]._replace(mining=True)
    some = row._replace(episodes=tuple(eps))
    win.finished.on_mine_too(some)
    assert asks(writer) == [("ask_mining", [e.id for e in eps[3:]], {"on": True})]
    win.mine.settle([e.id for e in eps[3:]])                # (round 8: asked again only once the first press ended)
    win.finished.on_mine(some)
    assert asks(writer)[-1][1] == [e.id for e in eps[3:]]
    gone = row._replace(episodes=tuple(eps[:3]))             # in Anki, deleted, being mined: nothing to ask
    win.finished.on_mine_too(gone)
    assert len(asks(writer)) == 2 and win.bar_line.full() == strings.MINE_NOTHING
    tray = win.arrivals_tray
    assert wait_until(lambda: tray.watched(), 10)
    arrival = tray.watched()[0]
    held = [e._replace(cards=0, mining=False, deleted=False, missing=False) for e in arrival.episodes]
    held[0] = held[0]._replace(deleted=True)
    tray.groups = tuple(g._replace(rows=(arrival._replace(episodes=tuple(held)),)) if g.kind == "watched" else g
                        for g in tray.groups)
    tray.mine_them_too()
    assert asks(writer)[-1][1] == [e.id for e in held[1:]] and held[0].id not in asks(writer)[-1][1]
    n = len(asks(writer))
    win.mine.mine_ids([held[0].id])                          # only the deleted one: nothing asked, said in the bar
    assert len(asks(writer)) == n and win.bar_line.full() == strings.MINE_NOTHING


def test_mine_them_too_asks_for_an_arrivals_videos_only_and_leaves_its_epub_out_saying_so(act, monkeypatch):
    """K67 (IK S3) on New arrivals: Anki Miner mines video only, so *Mine them too* over a video show and an EPUB that
    came with it asks for the videos alone (`mine_actions.videos_of`, the rule *Mine now* uses), the toast saying the
    other files were left out; an EPUB alone asks nothing and the bar says it waits
    for Anki Miner (alpha 4 M1: never its window). Wrong, the book's file made a job
    Anki Miner can never finish."""
    _seed, win, writer = act()
    tray = win.arrivals_tray
    assert wait_until(lambda: tray.watched(), 10)
    shown = tray.watched()[0]
    videos = [e._replace(cards=0, mining=False, deleted=False, missing=False) for e in shown.episodes]
    book = next(r for r in win.page_widgets["current"].view_model.rows if r.media_word != "video" and r.episodes)
    ep = book.episodes[0]
    epub = ep._replace(id=max(e.id for e in videos) + 1000, cards=0, mining=False, deleted=False, missing=False,
                       rel_path=f"HighPriority/Hato/{book.title}/{book.title}.epub", label=f"{book.title}.epub")
    came = shown._replace(key="p-epub", work_id=book.work_id, title=book.title, media=book.media,
                          media_word=book.media_word, item_ids=(epub.id,), episodes=(epub,))
    tray.groups = tuple(g._replace(rows=(shown._replace(episodes=tuple(videos)), came)) if g.kind == "watched" else g
                        for g in tray.groups)
    tray.mine_them_too()
    assert asks(writer)[-1][1] == [e.id for e in videos] and epub.id not in asks(writer)[-1][1]
    assert win.toasts.card.base == strings.MINE_ASKED_N_VIDEOS[len(videos) == 1].format(n=len(videos))
    n = len(asks(writer))
    win.mine.mine_ids([epub.id])                             # the EPUB alone: no ask, the bar says it waits
    assert len(asks(writer)) == n and win.bar_line.full() == strings.MINE_BOOKS_WAIT


def test_a_double_click_on_mine_now_asks_once(act):
    """WF fix 8 (adversary N1): a double-click on a part acts once — Qt turned the second click into a press whose
    release asked again (a second toast and Undo)."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    _seed, win, writer = act()
    lst = lst_of(win)
    p = action(lst, row_with(lst, "waiting"))
    pos = QPointF(p[1].center())
    glob = QPointF(lst.viewport().mapToGlobal(p[1].center()))
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    for kind, buttons in ((QEvent.Type.MouseButtonPress, left), (QEvent.Type.MouseButtonRelease, none),
                          (QEvent.Type.MouseButtonDblClick, left), (QEvent.Type.MouseButtonRelease, none)):
        QApplication.sendEvent(lst.viewport(), QMouseEvent(kind, pos, glob, left, buttons,
                                                           Qt.KeyboardModifier.NoModifier))
        QApplication.processEvents()
    assert len(asks(writer)) == 1


def test_two_switch_workers_asking_for_one_languages_feed_get_one_feed(monkeypatch):
    """WF fix 9 (adversary N5): `connect_feed`'s look-then-make is under a lock — two workers of a quick ja → zh → ja
    never make two Chinese feeds (the reader would read one, the line tick the other)."""
    import threading
    import time
    from app.services import settings as settings_service
    real_init = feed.Provider.__init__

    def slow(self, *a, **k):
        time.sleep(0.05)                                     # the race widened: both workers inside the look at once
        real_init(self, *a, **k)
    monkeypatch.setattr(feed.Provider, "__init__", slow)
    settings = settings_service.SettingsService()
    got, start = [], threading.Barrier(2)

    def ask():
        start.wait()
        got.append(shell.connect_feed("zh", settings))
    workers = [threading.Thread(target=ask) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(5)
    assert len(got) == 2 and got[0] is got[1]


def test_LM11b_a_groups_epub_asks_nothing_though_the_group_is_led_by_a_video(act):
    """K67 judged by the file, not the row: a group led by an anime holding a light novel's EPUB — *Mine this* on the
    EPUB asks nothing (the bar says it waits for Anki Miner; alpha 4 M1: never its window); on the anime's episode,
    the ask."""
    from app.services import view_rows as vr
    from tests import test_view_rows as tvr
    _seed, win, writer = act()
    tvr.WORKS.clear()
    tvr.work(1, "星降る街の小さな工房")
    tvr.work(3, "白銀の書庫番", media="lightnovel")
    items = tvr.items_of([("now", 1, 10, tvr.eps("星降る街の小さな工房", 1, 2), {}),
                          ("now", 3, 10, ["白銀の書庫番 01 章.epub"], {0: {"source_type": "epub"}})])
    pieces = {10: {"id": 10, "title": None, "kind": "group"}}
    row = vr.build(items, dict(tvr.WORKS), {"mine_line": 20}, pieces=pieces).rows[0]
    book = row.episodes[2]
    assert row.media_word == "video" and book.media_word == "EPUB"
    win.mine.mine_row(row, [book.id])
    assert asks(writer) == [] and win.bar_line.full() == strings.MINE_BOOKS_WAIT
    win.mine.mine_row(row, [row.episodes[0].id])
    assert [c[1] for c in asks(writer)] == [[row.episodes[0].id]]


def test_LM11b_a_groups_mine_now_asks_its_videos_alone_and_says_the_rest_are_left_out(act):
    """K67, one rule for one file and for many (`mine_actions.videos_of`): *Mine now* on a group of an anime's two
    episodes and a light novel's EPUB asks for the two videos only — Anki Miner can't mine the EPUB — and its toast
    says the others are left out; a group of videos only says its usual words."""
    from app.qt import mine_actions
    from app.services import view_rows as vr
    from tests import test_view_rows as tvr
    _seed, win, writer = act()
    tvr.WORKS.clear()
    tvr.work(1, "星降る街の小さな工房")
    tvr.work(3, "白銀の書庫番", media="lightnovel")
    items = tvr.items_of([("now", 1, 10, tvr.eps("星降る街の小さな工房", 1, 2), {}),
                          ("now", 3, 10, ["白銀の書庫番 01 章.epub"], {0: {"source_type": "epub"}})])
    row = vr.build(items, dict(tvr.WORKS), {"mine_line": 20}, pieces={10: {"id": 10, "title": None, "kind": "group"}}
                   ).rows[0]
    ids = [e.id for e in row.episodes]
    assert mine_actions.videos_of(row, ids) == (ids[:2], row.episodes[2])
    win.mine.mine_row(row, ids)
    assert [c[1] for c in asks(writer)] == [ids[:2]]
    assert win.toasts.card.base == strings.MINE_ASKED_VIDEOS.format(title=row.title)
    win.mine.settle(ids)                             # (round 8 row 45: asked again only once the first press ended)
    win.mine.mine_row(row, ids[:2])
    assert [c[1] for c in asks(writer)] == [ids[:2], ids[:2]]
    assert win.toasts.card.base == strings.MINE_ASKED.format(title=row.title)


# --- row 28 (Michi's row 24b ask): an episode's own ⋯ offers *Mine now* where its pill would be *Mine now* ----------- #
def _waiting_episode(lst):
    """A Current row and one of its episodes whose stone reads a plain (grey) *Waiting*: its turn, nothing else."""
    for kind, row, _lines in lst.model().entries:
        for ep in getattr(row, "episodes", ()) if kind in (rows.HERO, rows.ROW) else ():
            if ep.status is not None and ep.status.kind == "waiting" and ep.status.tone != "warn":
                return row, ep
    raise AssertionError("the seed holds a grey Waiting episode")


def _mine_now(entries):
    return [e for e in entries if e.name == "ep-mine-now"]


def test_row28_a_grey_waiting_episodes_menu_offers_mine_now_and_it_asks_for_that_episode_alone(act):
    """One rule with the pill (`rows.action_of`): a grey *Waiting* episode's ⋯ offers *Mine now* — its words and tip the
    pill's — and picking it is the pill's own ask (`mine_row`), for that episode's file alone, never its row's others."""
    _seed, win, writer = act()
    lst = lst_of(win)
    row, ep = _waiting_episode(lst)
    assert win.mine.episode_entries in win.items.episode_hooks
    entry = _mine_now(win.items.episode_entries(row, ep))
    tip = rows.action_of(ep.status, (ep,), None, ep.media_word or row.media_word)[1]     # the pill's own words
    assert [(e.label, e.tip, e.ok) for e in entry] == [(strings.ROWS_ACTION_NAMES["mine-now"], tip, True)]
    win.items.episode_pick(row, ep, entry[0].name, entry[0].payload)
    assert asks(writer) == [("ask_mining", [ep.id], {"on": True})]


def test_row28_the_menu_offers_mine_now_exactly_where_the_pills_rule_does(act):
    """IK-1: one rule with the pill — the episode's ⋯ offers *Mine now* exactly when `rows.action_of` says "mine-now"
    for that episode, whatever the stone's status (a grey *Waiting*, a wait on Anki or on the battery, …): asked of the
    rule itself, so a change to what the rule offers needs no change here. *Not timed*, a file in Anki, one being mined
    and no status at all are fixed cases: nothing to ask, no entry, nothing asked."""
    from app.connect import runner
    from app.services import view_rows
    _seed, win, writer = act()
    lst = lst_of(win)
    row, grey = _waiting_episode(lst)
    plain = view_rows.Status("waiting", "Waiting", "In your top 20: it mines by itself, in turn", "dim")
    waits = [view_rows._connected(plain, feed.Item(kind, feed.WORDS[kind], reason, 1, 0, 0), "video")
             for kind, reason in ((feed.ANKI, runner.ANKI_CLOSED), (feed.BATTERY, runner.ON_BATTERY))]
    for ep in [grey] + [_ep(st) for st in waits]:
        rule = rows.action_of(ep.status, (ep,), win.mine.off, ep.media_word or row.media_word)[0]
        offered = _mine_now(win.items.episode_entries(row, ep))
        assert (len(offered) == 1) == (rule == "mine-now"), (ep.status, rule)
    not_timed = view_rows._connected(plain, feed.Item(feed.NOT_TIMED, feed.WORDS[feed.NOT_TIMED],
                                                      "not timed to its video", 1, 0, 0), "video")
    in_anki = _ep(view_rows.Status("in_anki", "In Anki", "Its cards are in Anki", "ok"))._replace(cards=4)
    mining = _ep(view_rows.Status("mining", "Mining", "Being mined now", "accent"))._replace(mining=True)
    for ep in (_ep(not_timed), in_anki, mining, _ep(None)):
        assert win.mine.episode_entries(row, ep) == [], ep.status
        assert _mine_now(win.items.episode_entries(row, ep)) == [], ep.status
    assert asks(writer) == []


def test_row28_a_read_only_store_greys_the_episodes_mine_now_with_its_reason_after_a_separator(act):
    """AD-8: *Mine now* asks the store for a write — while it is read-only the menu greys it with the store's reason, as
    it greys *Mark watched* and *Split here…* (the menu's one rule, `_refused_tip`); the modules' entries stand after a
    separator."""
    _seed, win, writer = act()
    lst = lst_of(win)
    row, ep = _waiting_episode(lst)
    m = win.items.episode_menu(row, ep, win.mapToGlobal(win.rect().center()))
    acts = m.actions()
    k = next(n for n, a in enumerate(acts) if a.text() == strings.ROWS_ACTION_NAMES["mine-now"])
    assert acts[k - 1].isSeparator() and not any(a.isSeparator() for a in acts[:k - 1]), "the hooks apart, once"
    m.close()
    writer.writable, writer.why = False, "damaged"
    reason = win.items._refused_tip()
    assert reason
    entry = _mine_now(win.items.episode_entries(row, ep))
    assert [(e.ok, e.tip) for e in entry] == [(False, reason)]
    assert win.items.episode_entries(row, ep)[0].tip == reason, "as Mark watched"


def test_W1_a_hand_ask_still_mines_an_episode_marked_watched_while_the_option_is_off(act):
    """W-1 (the lead's ruling from Sonic's LF4-1, "Your own Mine this / Mine now on it still makes its cards"): a watched
    episode leaves the list, but a hand ask always mines it. Marked through the real path (its Done → the writer's
    `set_watched` → the store, read back by the reader), its pill, its ⋯ and its row's button stay as they were: one
    rule (`rows.action_of`), nothing greyed."""
    _seed, win, writer = act()
    lst = lst_of(win)
    # a grey *Waiting* episode whose row's own button asks for it too (the pill, the ⋯ and the row, all three)
    row, ep = next((r, e) for kind, r, _l in lst.model().entries if kind in (rows.HERO, rows.ROW)
                   for e in r.episodes if e.status is not None and e.status.kind == "waiting" and e.status.tone != "warn"
                   and (rows.action_of(r.status, r.episodes, None, r.media_word)[2] or rows.Ask(0, (), None)).ids
                   and e.id in rows.action_of(r.status, r.episodes, None, r.media_word)[2].ids)
    before = rows.action_of(ep.status, (ep,), None, ep.media_word or row.media_word)
    assert before[0] == "mine-now"
    row_before = rows.action_of(row.status, row.episodes, None, row.media_word)
    writer.apply = True                                       # the stand-in store takes this write
    win.moves.done(row, ep)
    assert writer.calls[-1][:2] == ("set_watched", [ep.id])

    def now():
        for r in win.page_widgets["current"].view_model.rows:
            for e in r.episodes:
                if e.id == ep.id:
                    return r, e
    assert wait_until(lambda: now()[1].watched, 3)
    assert not win.page_widgets["current"].view_model.keep_watched
    row2, ep2 = now()
    pill = rows.action_of(ep2.status, (ep2,), None, ep2.media_word or row2.media_word)
    assert pill[:2] == before[:2] and list(pill[2].ids) == [ep.id]          # the pill: Mine now, as before the mark
    entry = _mine_now(win.items.episode_entries(row2, ep2))
    assert [(e.tip, e.ok) for e in entry] == [(pill[1], True)]              # the ⋯: live, the pill's own words
    name, _tip, ask = rows.action_of(row2.status, row2.episodes, None, row2.media_word)
    assert name == row_before[0] and ep.id in ask.ids                      # the row's button: still asks for it


def test_row28_while_connect_is_off_mine_now_is_offered_saying_why_and_asks_nothing(act):
    """IK S7, as the pill: Connect off, the episode's *Mine now* is still there, its tip saying why in the feed's words;
    picked, nothing is asked and the bar says why."""
    _seed, win, writer = act(connect_off=feed.OFF_CONNECT)
    lst = lst_of(win)
    row, ep = _waiting_episode(lst)
    entry = _mine_now(win.items.episode_entries(row, ep))
    assert [e.tip for e in entry] == [strings.ROWS_ACTION_OFF.format(tip=rows.status_tip(ep.status),
                                                                    why=feed.OFF_CONNECT)]
    win.items.episode_pick(row, ep, entry[0].name, entry[0].payload)
    assert asks(writer) == [] and win.bar_line.full() == feed.OFF_CONNECT


# --- round 8 row 45 (the trial): *Mine now* turns its pill from the frame of the press ------------------------------- #
def _watch_asks(win, writer):
    """`writer.ask_mining` wrapped: at each call, whether every asked file was already marked pressed in Current's list
    and how often the list's viewport had painted since the watch began."""
    from tests.qt.test_press import Paints
    lst = lst_of(win)
    paints = Paints(lst.viewport())
    QApplication.processEvents()
    seen = []
    real = writer.ask_mining

    def ask_mining(ids, asked=True, label=None):
        seen.append((set(ids) <= lst.pressed_ids, paints.n))
        return real(ids, asked=asked, label=label)
    writer.ask_mining = ask_mining
    return seen, paints.n


def _status_moved(lst, ids, status):
    """The reader's next view, as Connect's feed would make it: the asked files' statuses now `status`."""
    entries = []
    for kind, row, lines in lst.model().entries:
        if kind in (rows.HERO, rows.ROW) and any(e.id in ids for e in row.episodes):
            row = row._replace(episodes=type(row.episodes)(e._replace(status=status) if e.id in ids else e
                                                           for e in row.episodes))
        entries.append((kind, row, lines))
    lst.set_entries(entries)


def test_round8_mine_now_turns_its_pill_painted_before_the_ask_and_stops_when_the_feed_moves(act, monkeypatch):
    """Round 8 row 45: a click on *Mine now* marks its files pressed and repaints them — the turning mark in the
    hourglass's place, its hover *Asked · starting…* — before the ask reaches the writer; a second click asks nothing;
    saved, Connect's feed is looked at now; the mark goes when the feed's status for the file changes from what it was
    at the press. Red first: before the trial nothing was marked at the ask (the pill stayed the hourglass)."""
    from app.services import view_rows
    _seed, win, writer = act()
    lst = lst_of(win)
    looked = []
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: looked.append(names))
    i = row_with(lst, "waiting")
    row = lst.model().entries[i][1]
    seen, before = _watch_asks(win, writer)
    click(lst, action(lst, i))
    assert len(seen) == 1
    marked, painted = seen[0]
    ids = asks(writer)[0][1]
    assert marked and painted > before                                 # pressed and painted before the ask
    assert set(ids) <= lst.pressed_ids and lst.turning() is None           # (frozen: the mark is still, never gone)
    assert action(lst, i)[2] == strings.ROWS_ASKED_TIP                  # the hover's intentional words
    click(lst, action(lst, i))
    assert len(asks(writer)) == 1                                       # pressed again: asked once
    assert wait_until(lambda: ("connect",) in looked)                   # saved: the feed looked at now
    lst.set_entries(list(lst.model().entries))                          # a view with nothing new of it: still pressed
    assert set(ids) <= lst.pressed_ids
    _status_moved(lst, ids, view_rows.Status("mining", "Mining", "Being mined now", "accent"))
    assert not lst.pressed_ids and lst._turn is None                        # Connect took it: the pill is its own again
    assert row.key == lst.model().entries[i][1].key


def test_round8_a_refused_or_undone_ask_stops_the_pill_turning(act):
    """Round 8 row 45: the store refusing the ask (nothing written) or its Undo puts the pill back at once."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "waiting")
    real = writer.ask_mining
    writer.ask_mining = lambda ids, asked=True, label=None: None       # refused as it was handed over
    click(lst, action(lst, i))
    assert not lst.pressed_ids
    writer.ask_mining = real
    click(lst, action(lst, i))
    assert lst.pressed_ids
    ticket = win.moves.toasted
    win.moves.undo(ticket)                                              # the toast's Undo
    assert not lst.pressed_ids


def test_round8_the_episode_menus_mine_now_turns_that_episodes_pill_before_the_ask(act):
    """Round 8 row 45, a menu's press: the episode's ⋯ closes as *Mine now* is picked, so its pending mark is the pill of
    the episode it acts on — pressed and repainted before the ask, its hover *Asked · starting…*; no line in the bar.
    Red first: before the trial the pill stayed the hourglass until Connect's next tick."""
    _seed, win, writer = act()
    lst = lst_of(win)
    row, ep = _waiting_episode(lst)
    i = next(n for n, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == row.key)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    lst.toggle(lst.model().index(i, 0))                                  # opened: its episodes' pills show
    assert wait_until(lambda: lst.model().open_key == row.key)
    settle()
    line = win.bar_line.full()
    seen, before = _watch_asks(win, writer)
    entry = _mine_now(win.items.episode_entries(row, ep))[0]
    win.items.episode_pick(row, ep, entry.name, entry.payload)
    assert asks(writer) == [("ask_mining", [ep.id], {"on": True})]
    assert seen[0][0] and seen[0][1] > before
    assert lst.pressed_ids == {ep.id} and win.bar_line.full() == line
    j = next(n for n, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == row.key)
    pill = next(p for p in parts_of(lst, j) if p[3] is not None and getattr(p[3], "ids", None) == (ep.id,))
    assert pill[2] == strings.ROWS_ASKED_TIP


# --- round 8's adversary (A-3, A-4, A-6, A-7) and intent keeper (IK-3) --------------------------------------------- #
def _hero_waiting(lst):
    """Current's top card (closed), its status made a plain *Waiting* (its turn, nothing else) if the seed's isn't:
    its index and the card."""
    entries = list(lst.model().entries)
    h = next(n for n, e in enumerate(entries) if e[0] == rows.HERO)
    hero = entries[h][1]
    if hero.status is None or rows.action_of(hero.status, hero.episodes, None, hero.media_word)[0] != "mine-now":
        st = _waiting_episode(lst)[1].status
        hero = hero._replace(status=st, episodes=type(hero.episodes)(e._replace(status=st, cards=0, mining=False,
                                                                                deleted=False, missing=False)
                                                                     for e in hero.episodes))
        entries[h] = (rows.HERO, hero, entries[h][2])
        lst.set_entries(entries)
    lst.scrollTo(lst.model().index(h, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    assert lst.model().open_key != hero.key
    return h, hero


def test_round8_a3_mine_now_on_the_closed_top_card_shows_its_mark_and_says_asked(act, monkeypatch):
    """A-3: the closed top card is one cached picture; pressed, nothing painted the mark over it and its hover kept
    the old tip, so a click showed nothing (and a second one, deduped, nothing either). Now its pill turns over the
    picture and its hover says *Asked · starting…*, as a row's. Red first: no mark painted, the old tip."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    h, hero = _hero_waiting(lst)
    status = next(p for p in parts_of(lst, h) if p[0] == "mine-now")
    assert status[2] != strings.ROWS_ASKED_TIP
    marks = []
    real = rows.paint_pressed
    monkeypatch.setattr(rows, "paint_pressed", lambda p, rect, *a, **k: (marks.append(QRectF(rect)),
                                                                          real(p, rect, *a, **k)))
    lst.press_ids([e.id for e in hero.episodes])
    assert marks and any(m.intersects(QRectF(status[1])) for m in marks)    # painted over its pill, in the press
    assert next(p for p in parts_of(lst, h) if p[0] == "mine-now")[2] == strings.ROWS_ASKED_TIP


def test_round8_a4_an_ask_saved_gives_way_to_connects_own_state_when_connect_says_nothing_new(act, monkeypatch):
    """A-4: Connect switched on but not running, Anki closed with the file's wait unchanged, on battery: nothing new
    of the file ever came, so the pill turned all session and *Asked · starting…* hid the wait's own reason. Now its
    press ends `SETTLE_S` after the ask was saved: the pill is its own again, with its own hover (a wait is a state),
    and a click asks again. Red first: still pressed, for good."""
    monkeypatch.setattr(mine_actions, "SETTLE_S", 0.05)
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i = row_with(lst, "waiting")
    own_tip = action(lst, i)[2]
    click(lst, action(lst, i))
    ids = asks(writer)[0][1]
    assert set(ids) <= lst.pressed_ids
    lst.set_entries(list(lst.model().entries))                          # Connect's feed: nothing new of it
    assert wait_until(lambda: not lst.pressed_ids, 5)
    assert not win.presses.any_live() and lst._turn is None
    assert action(lst, i)[2] == own_tip
    click(lst, action(lst, i))
    assert len(asks(writer)) == 2


def test_round8_ik3_each_asked_file_is_a_press_of_the_windows_so_the_hairline_runs_with_it(act, monkeypatch):
    """IK-3: Mine now's pending was a mark of the lists' alone — no press, so no hairline, no failed state, nothing a
    check of every press could see. Now each file asked for is a press of the window's (`mine:<language>:<id>`),
    live — the hairline on — before the ask reaches the writer; Connect taking it ends it (done), a refusal fails it."""
    from app.services import press as press_service
    from app.services import view_rows
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    seen = []
    real = writer.ask_mining

    def ask_mining(ids, asked=True, label=None):
        seen.append((win.presses.any_live(), win.progress.busy))
        return real(ids, asked=asked, label=label)
    writer.ask_mining = ask_mining
    i = row_with(lst, "waiting")
    click(lst, action(lst, i))
    ids = asks(writer)[0][1]
    assert seen == [(True, True)]
    presses = [win.presses.find(f"mine:{win.language}:{n}") for n in ids]
    assert all(p is not None and p.live() for p in presses)
    _status_moved(lst, ids, view_rows.Status("mining", "Mining", "Being mined now", "accent"))   # Connect took them
    assert all(p.state == press_service.DONE for p in presses) and not lst.pressed_ids
    writer.ask_mining = lambda ids, asked=True, label=None: None       # the store refuses the next one
    j = row_with(lst, "waiting")
    click(lst, action(lst, j))
    refused = [win.presses.find(f"mine:{win.language}:{e.id}") for e in lst.model().entries[j][1].episodes]
    assert any(p is not None and p.state == press_service.FAILED for p in refused)
    assert not win.presses.any_live() and not lst.pressed_ids


def test_round8_a6_a7_the_pressed_mark_turns_on_the_clock_only_while_it_is_on_screen(act, monkeypatch):
    """A-7: the freeze switch kept every turning mark still under test, so the turning path (the clock, `turned_at`,
    a frame repainting the mark's box alone) never ran. A-6: while a press was live the clock ticked at frame rate even
    with nothing pressed on screen (the row scrolled away). Motion on here: the mark turns, each frame repaints only its
    box, and the clock stops once no mark is painted, and starts again when one is. Red first: the clock never
    stopped."""
    from PyQt6.QtCore import QRect
    from app.qt import freeze, motion
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    if motion.clock().mode.reduced:
        pytest.skip("Reduced motion is on for this session: the mark is still by design")
    i = row_with(lst, "waiting")
    freeze.set_frozen(False)                                            # (conftest puts the switch back)
    click(lst, action(lst, i))
    turn = lst._turn
    assert wait_until(lambda: turn.on_clock, 5)
    phases = set()
    assert wait_until(lambda: phases.add(lst.turning()) or len(phases - {None}) >= 3, 5)   # it turns
    assert wait_until(lambda: lst._turn_rects, 5)
    row = lst.visualRect(lst.model().index(i, 0))
    assert all(r.height() < row.height() and r.width() < 80 and row.contains(r) for r in lst._turn_rects)
    win.resize(win.width(), 520)                                        # a short window: the row can scroll away
    settle()
    last = lst.model().rowCount() - 1
    lst.scrollTo(lst.model().index(last, 0), lst.ScrollHint.PositionAtBottom)
    QApplication.processEvents()
    if lst.visualRect(lst.model().index(i, 0)).intersects(QRect(lst.viewport().rect())):
        pytest.skip("the seed's list is too short to scroll its pressed row away")
    assert wait_until(lambda: not turn.on_clock, 5)                     # nothing pressed on screen: no ticking
    assert lst.pressed_ids and lst._turn is turn
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    assert wait_until(lambda: turn.on_clock, 5)                         # on screen again: it turns again


def test_round8_the_turning_hourglass_is_a_little_smaller_than_the_still_one_in_the_same_box(qapp):
    """Round 2 (Sonic: "the spin and slightly smaller"): a pressed pill's hourglass is drawn at `TURNING_SCALE` in the
    same box (nothing around it moves), so the difference shows even still (Reduced motion). Red first: the trial drew
    it at full size."""
    from PyQt6.QtCore import QRect, QRectF
    from PyQt6.QtGui import QImage, QPainter

    def ink_height(draw):
        img = QImage(48, 48, QImage.Format.Format_ARGB32)
        img.fill(0)
        q = QPainter(img)
        draw(q)
        q.end()
        accent = rows.c("accent")
        ys = [y for y in range(48) for x in range(48) if abs(img.pixelColor(x, y).blue() - accent.blue()) < 40 and
              img.pixelColor(x, y).alpha() > 200 and img.pixelColor(x, y).green() > 100]
        return max(ys) - min(ys) + 1

    box = QRect(12, 12, 24, 24)
    full = ink_height(lambda q: rows.icon(q, "waiting", QRectF(17.5, 17.5, 13, 13), rows.c("accent")))
    turning = ink_height(lambda q: rows.paint_pressed(q, box, None))
    assert rows.TURNING_SCALE < 1 and turning < full and turning >= full * 0.75, (turning, full)
