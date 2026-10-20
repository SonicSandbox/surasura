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
from PyQt6.QtCore import QEvent, Qt
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
        assert p[0] == name and p[2] == words.format(tip=row.status.tip), kind
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
    assert win.toasts.card.isVisible() and strings.MINE_ASKED.format(title=row.title) == win.toasts.card.message


def test_mine_this_below_the_line_asks_for_every_file_that_can_be_mined(act):
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "mine")
    row = lst.model().entries[i][1]
    click(lst, action(lst, i))
    assert asks(writer) == [("ask_mining", [e.id for e in row.episodes if not e.missing], {"on": True})]


def test_a_books_mine_this_makes_no_ask_and_opens_anki_miner_with_its_path_copied(act, monkeypatch):
    """K67 / IK S3: Anki Miner's API mines video only — a book's *Mine this* is *Mine text*: no ask, Anki Miner's own
    window, the file's path on the clipboard, a toast saying so."""
    from app.connect import anki_miner
    from app.qt import windows
    _seed, win, writer = act()
    lst = lst_of(win)
    opened = []
    monkeypatch.setattr(anki_miner, "find", lambda _s: r"C:\Programs\AnkiMiner\Anki Miner.exe")
    monkeypatch.setattr(windows, "open_url", lambda url: opened.append(url) or True)
    entries = lst.model().entries
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].media_word != "video" and
             any(p[0] == "mine-this" for p in parts_of(lst, n)))
    row = entries[i][1]
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    click(lst, action(lst, i))
    assert wait_until(lambda: opened, 5)
    assert asks(writer) == [] and opened == [r"C:\Programs\AnkiMiner\Anki Miner.exe"]
    ep = row.episodes[0]
    from app import path_utils
    assert QApplication.clipboard().text() == os.path.join(path_utils.get_data_path("ja"), *ep.rel_path.split("/"))
    assert strings.MINE_TEXT_COPIED.format(name=ep.label) == win.toasts.card.message


def test_no_video_offers_link_and_mine_text_and_link_hands_the_chosen_video_to_the_writer(act, monkeypatch):
    """4.1.9L / C6: *No video*'s button opens *Link…* · *Mine text*; *Link…* picks a video (the picker's filter: the
    videos Connect makes cards from) and the writer links it to that episode; with no Anki Miner, *Mine text* says so."""
    from app.connect import anki_miner
    _seed, win, writer = act()
    lst = lst_of(win)
    i = row_with(lst, "no_media", None)
    row = lst.model().entries[i][1]
    p = action(lst, i)
    click(lst, p)
    menu = lst.action_menu
    assert menu is not None and [a.text() for a in menu.actions()] == [strings.ROWS_LINK, strings.ROWS_MINE_TEXT]
    assert all(a.toolTip() for a in menu.actions())
    asked = []
    win.mine.pick_file = lambda title, folder, patterns: asked.append((title, patterns)) or r"D:\Videos\第1話.mkv"
    menu.actions()[0].trigger()
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "link_video"], 5)
    assert [c for c in writer.calls if c[0] == "link_video"] == [("link_video", [p[3].episode.id],
                                                                   {"path": r"D:\Videos\第1話.mkv"})]
    assert asked[0][0] == strings.LINK_TITLE.format(label=p[3].episode.label) and "*.mkv" in asked[0][1]
    menu.close()
    monkeypatch.setattr(anki_miner, "find", lambda _s: None)
    click(lst, action(lst, i))
    lst.action_menu.actions()[1].trigger()
    assert wait_until(lambda: win.bar_line.full() == strings.MINE_TEXT_NO_MINER, 5)
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
    assert p[2] == strings.ROWS_ACTION_OFF.format(tip=row.status.tip, why=feed.OFF_CONNECT)
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


def test_needs_you_mine_the_text_only_is_set_and_opens_anki_miner_with_the_lines_file(act, monkeypatch):
    """4.1.12: Needs you's *Mine the text only* is C6."""
    from app.connect import anki_miner
    from app.qt import windows
    from app.services import needs as service
    _seed, win, _writer = act()
    ny = win.needs_you
    assert "mine_text_only" in ny.hooks and ny.available("mine_text_only")
    opened = []
    monkeypatch.setattr(anki_miner, "find", lambda _s: r"C:\AnkiMiner.exe")
    monkeypatch.setattr(windows, "open_url", lambda url: opened.append(url) or True)
    line = service.NeedLine(key="item:1", text="第3話 · no video", item_id=1, label="第3話", number=3,
                            rel_path="HighPriority/葬送のフリーレン/葬送のフリーレン 第3話.srt", actions=())
    entry = service.Entry(key="video:x", kind=service.NO_VIDEO, title="葬送のフリーレン", lines=(line,), actions=(),
                          unseen=False)
    ny.act("mine_text_only", entry, None)                      # the card's own button: its first file
    assert wait_until(lambda: opened, 5)
    assert QApplication.clipboard().text().endswith(os.path.join("葬送のフリーレン", "葬送のフリーレン 第3話.srt"))


def test_needs_you_make_their_cards_is_connects_ordinary_work_in_the_gaps_language_then_answers_the_entry(
        act, monkeypatch):
    """4.1.12, moved to P4.1 WF (IK D-1 lean (a); adversary S3, S4): a gap's *Make their cards* is no ask (was: one
    `ask_mining`) — `actions.make_cards` in the entry's own language (here Chinese, while the window's writer is the
    Japanese one), Connect kicked once it queued any, and only then the entry answered as *Leave them* answers it; the
    bar counts the episodes, no title pasted. What a wrong answer would cost: deleted cards made again in bulk, a
    gap answered with no cards coming, or Japanese titles mined for a Chinese gap. While Connect is off, or when the
    gap is gone, nothing is answered."""
    from app.services import needs as service
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


def test_a_wait_is_no_mine_now_button_and_its_tip_names_the_wait_not_a_click():
    """WF fix 3 (adversary S2 / IK S1, C3: an ask never overrides a wait): *Not timed* and a wait on Anki or on the
    battery are warn *Waiting* stones with no *Mine now* — the tip is the wait's own, never "Click to mine it now"
    (an ask there only stamps the job, which keeps waiting, and the toast would promise cards that don't come). A
    *Waiting* for its turn stays the *Mine now* button."""
    from app.connect import runner
    from app.services import view_rows
    plain = view_rows.Status("waiting", "Waiting", "In your top 20: it mines by itself, in turn", "dim")
    for kind, reason in ((feed.NOT_TIMED, "not timed to its video"), (feed.ANKI, runner.ANKI_CLOSED),
                         (feed.BATTERY, runner.ON_BATTERY)):
        st = view_rows._connected(plain, feed.Item(kind, feed.WORDS[kind], reason, 1, 0, 0), "video")
        assert (st.kind, st.tone) == ("waiting", "warn"), kind
        name, tip, ask = rows.action_of(st, (_ep(st),))
        assert (name, ask) == ("status", None) and tip == st.tip and "Click to mine it now" not in tip, kind
    turn = view_rows._connected(plain, feed.Item(feed.WAITING, feed.WORDS[feed.WAITING], "", 1, 0, 0), "video")
    assert turn.tone == "dim" and rows.action_of(turn, (_ep(turn),))[0] == "mine-now"


def test_a_books_button_says_it_opens_anki_miner_and_works_while_connect_is_off():
    """WF fixes 6 and 7 (IK S5, N2; K67): a book's *Mine this* opens Anki Miner — its tip says so, never "mine it now"
    — and, needing no Connect, it is no refused ask while Connect is off; a video's *Mine this* is."""
    from app.services import view_rows
    st = view_rows.Status("mine", "Mine", "Not in your top 20: it isn't mined yet", "ink")
    name, tip, _ask = rows.action_of(st, (_ep(st),), None, "text")
    assert name == "mine-this" and tip == strings.ROWS_MINE_TEXT_THIS_TIP.format(tip=st.tip)
    assert "mine it now" not in tip and "Anki Miner" in tip
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


def test_one_file_is_said_as_one_and_mine_text_says_connect_waits_while_anki_miner_is_open(act):
    """WF fix 6 (IK S5; the N1 disposition): "1 file", never "1 files"; C6's toast says Connect waits while Anki
    Miner's window is open."""
    assert strings.MINE_ASKED_ONE == "1 file: its cards come next"
    assert "Connect waits while Anki Miner's window is open" in strings.MINE_TEXT_COPIED
    _seed, win, writer = act()
    tray = win.arrivals_tray
    assert wait_until(lambda: tray.watched(), 10)
    open_ = [e for a in tray.watched() for e in rows.asked_files("mine", a.episodes)]
    assert open_, "the seed's watched arrivals hold a file still to mine"
    win.mine.mine_ids([open_[0].id])
    assert asks(writer)[-1][1] == [open_[0].id] and win.toasts.card.message == strings.MINE_ASKED_ONE


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
