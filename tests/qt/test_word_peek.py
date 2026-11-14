"""Hover-W: the word card over a Current row's *N new* (app/qt/word_peek.py, the rows' `new` part, the shell's host).

Sonic's yes to the look (2026-11-14, "It's good for hover"); the leans PROVISIONAL (TheForge hover-w-register.md).
What these prove, on the seeded window with real Japanese words in the card:
  - resting on a row's *N new* shows the card (the bubble's timing; frozen here: at once), its words asked at once;
    leaving it takes the hover card away after a short grace, never while the pointer is on the card;
  - the hover: New here three across and four down (twelve words, the list's order across the rows), the other parts
    one line each with *+N more*; a click keeps it open and expands every part; *+N more* opens its part at the top;
  - the longest real words drop the grid to two columns and are never cut;
  - Waiting to update is a band in the head; Esc closes the kept card; the card is built once; every button wired;
  - kept open, a word's sentence shows on one line with the word marked, its part named; a word without one: nothing.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import rows, word_peek
from app.services import title_words as TW
from tests.qt.conftest import wait_until
from tests.qt.test_drag import lst_of, world  # noqa: F401 (a fixture)
from tests.qt.test_wiring import problems

# Real words (RP-2's 注文の多い料理店 and the titles before it, through today's engine: Hover-W's shows.json)
NEW = ("どうも 何か 紳士 鉄砲 がた ごとん がたがたがた 白熊 二疋 木の葉 かさかさ 西洋 大歓迎 かぎ穴 わん 料理店 どこか "
       "じゃないか えらいひと 横っ腹 損害 山鳥 瀬戸 ブラシ カフスボタン 瓶 振りかける 酢 もみ込む 西洋料理").split()
BEFORE = (("喫茶店の朝", "という どういう ちょうどいい それに 遠慮 ことになる まで".split()),
          ("蜘蛛の糸", "気がつく どうか られる とする それでも どこまでも 善い事 ものがある".split()))
LONGEST = ("ありがとうございました ありがとうございます しばらくすると チンチロリン カフスボタン いつの間にか がたがたがた "
           "モカブレンド かも知れない ちょうどいい 手っ取り早い ネクタイピン").split()


def _w(label, at="ep1"):
    return TW.CardWord(label, label, "", False, at, 0)


def _card(row, new=NEW, before=BEFORE, anki=None, kept=False):
    groups = tuple(TW.Group(t, tuple(_w(x) for x in ws)) for t, ws in before)
    return TW.Card(key=row.key, title=row.title, tier="Soon", n_files=len(row.episodes), n_new=len(new),
                   today=len(new) + sum(len(g.words) for g in groups), new=tuple(_w(x) for x in new), anki=anki,
                   before=groups, kept=kept, episode=row.episodes[0] if row.episodes else None,
                   items=tuple(e.id for e in row.episodes))


class Provider:
    """The window's provider, answering at once with a card for any row (sentences when asked)."""

    def __init__(self, **kw):
        self.kw, self.asked, self.sentences_asked = kw, [], []
        self.found = {}

    def ask(self, row, view, done):
        self.asked.append(row.key)
        done(_card(row, **self.kw))

    def sentences(self, row, done):
        self.sentences_asked.append(row.key)
        done(self.found)

    def refresh_anki(self, force=False):
        pass


@pytest.fixture
def peek(world):     # noqa: F811
    seed, win, _writer = world()
    provider = Provider()
    win.services.title_words = provider
    lst = lst_of(win)
    i = next(i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and e[1].n_new is not None)
    return win, lst, i, provider


def _new_part(lst, i):
    entry = lst.model().entries[i]
    for part in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))):
        if part[0] == rows.NEW_PART:
            return part
    raise AssertionError("no N new part")


def _rest_on(lst, i):
    part = _new_part(lst, i)
    pos = part[1].center()
    QTest.mouseMove(lst.viewport(), pos)
    ev = QHelpEvent(QEvent.Type.ToolTip, pos, lst.viewport().mapToGlobal(pos))
    QApplication.sendEvent(lst.viewport(), ev)
    QApplication.processEvents()
    return part


def test_hover_w_resting_on_n_new_shows_the_card_and_its_words_are_asked_at_once(peek):
    win, lst, i, provider = peek
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3) and not card.kept
    assert provider.asked == [lst.model().entries[i][1].key]
    words = [it for it in card.sheet.items if it.word is not None]
    assert [it.text for it in words[:12]] == NEW[:12]                   # New here: twelve, the list's order
    grid = words[:12]
    assert len({it.rect.left() for it in grid}) == 3 and len({it.rect.top() for it in grid}) == 4
    assert grid[1].rect.top() == grid[0].rect.top() and grid[3].rect.top() > grid[0].rect.top()   # across, then down
    mores = [it for it in card.sheet.items if it.more is not None]
    assert [m.more for m in mores] == [0, 2] and mores[0].text == f"+{len(NEW) - 12} more"
    on_the_way = [it for it in card.sheet.items if it.word is not None][12:]
    assert len({it.rect.top() for it in on_the_way}) == 1                # Learned on the way: one line
    assert card.width() <= round(word_peek.HOVER_W[1] * word_peek.fz()) + 2


def test_hover_w_leaving_n_new_takes_the_hover_card_away_unless_the_pointer_is_on_it(peek):
    win, lst, i, _provider = peek
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3)
    card.pointer_in.emit(True)                                          # on the card: it stays
    win.words.left()
    QTest.qWait(word_peek.GRACE_MS + 120)
    assert card.isVisible()
    card.pointer_in.emit(False)
    assert wait_until(lambda: not card.isVisible(), 3)


def test_hover_w_a_click_keeps_it_open_expands_every_part_and_esc_closes_it(peek):
    win, lst, i, _provider = peek
    part = _new_part(lst, i)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=part[1].center())
    card = win.words.card
    assert wait_until(lambda: card.isVisible() and card.kept, 3)
    words = [it.text for it in card.sheet.items if it.word is not None]
    assert words[:len(NEW)] == NEW and words[len(NEW):] == [w for _t, ws in BEFORE for w in ws]
    assert not [it for it in card.sheet.items if it.more is not None]   # nothing held back
    assert card.close_button.isVisible() and card.journey.isVisible()
    QTest.keyClick(win, Qt.Key.Key_Escape)
    assert wait_until(lambda: not card.isVisible(), 3)


def test_hover_w_plus_n_more_opens_its_part_at_the_top_of_the_kept_card(peek):
    win, lst, i, _provider = peek
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3)
    more = next(it for it in card.sheet.items if it.more == 2)
    card.clicked(more)
    assert card.kept and card.scroll.verticalScrollBar().value() == min(
        card._part_top[2], card.scroll.verticalScrollBar().maximum())
    assert card.sheet.findChildren(QWidget)                              # the part's wash band


def test_hover_w_the_longest_real_words_are_never_cut_and_three_columns_fit_or_two(peek):
    win, lst, i, provider = peek
    provider.kw = {"new": LONGEST, "before": ()}
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3)
    words = [it for it in card.sheet.items if it.word is not None]
    lefts = sorted({it.rect.left() for it in words})
    assert len(lefts) in (2, 3) and len(words) == (12 if len(lefts) == 3 else 8)
    for it in words:
        assert it.rect.width() >= word_peek._adv(it.text, word_peek.WORD_ROLE)      # never elided
        assert it.rect.right() <= card.sheet.width()


def test_hover_w_waiting_to_update_is_a_band_in_the_head(peek):
    win, lst, i, provider = peek
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3)
    plain = card.head_h
    card.hide()
    provider.kw = {"kept": True}
    win.words._cards.clear()
    _rest_on(lst, i)
    assert wait_until(lambda: card.isVisible() and card.card is not None and card.card.kept, 3)
    assert card.head_h > plain                                           # the band: plain words, not a faint note


def test_hover_w_kept_open_a_words_sentence_shows_with_the_word_marked_and_its_part(peek):
    win, lst, i, provider = peek
    provider.found = {("紳士", ""): TW.Sentence("二人の若い紳士が、すっかりイギリスの兵隊のかたちをして、", 5, 7, "Part 1")}
    part = _new_part(lst, i)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=part[1].center())
    card = win.words.card
    assert wait_until(lambda: card.kept and card.sentences, 3)
    assert provider.sentences_asked == [card.card.key]                  # once for the card
    gentleman = next(it for it in card.sheet.items if it.text == "紳士")
    card.hovered(gentleman)
    before, mid, after, place = card.sentence_parts()
    assert mid == "紳士" and before == "二人の若い" and place.strip().endswith("Part 1")
    other = next(it for it in card.sheet.items if it.text == "鉄砲")
    card.hovered(other)
    assert card.sentence_parts() is None                                 # no sentence for it: nothing, never a guess
    card.clicked(gentleman)                                              # a click keeps it after the pointer goes
    card.hovered(None)
    assert card.sentence_parts()[1] == "紳士"


def test_hover_w_the_card_is_built_once_and_every_button_on_it_is_wired(peek):
    win, lst, i, _provider = peek
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3)
    made = len(card.findChildren(QWidget))
    for _ in range(3):
        card.hide()
        win.words._cards.clear()
        _rest_on(lst, i)
        assert wait_until(card.isVisible, 3)
        card.keep()
        card.close()
    assert len(card.findChildren(QWidget)) <= made + 1                   # (a wash band on its way out at most)
    found, _n = problems(win)
    assert not [p for p in found if "wordpeek" in p or "Open in the journey" in p or "✕" in p]


def test_hover_w_a_row_without_n_new_has_no_word_part(peek):
    win, lst, i, _provider = peek
    for j, entry in enumerate(lst.model().entries):
        if entry[0] != rows.ROW:
            continue
        names = [p[0] for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(j, 0)))]
        assert (rows.NEW_PART in names) == (entry[1].n_new is not None)


def test_hover_w_its_words_in_the_rows_menu_opens_the_card_kept_open(peek):
    """Lean 13, the keyboard's way in: ⋯ *Its words* — shown for a row with *N new* — opens its card kept open."""
    win, lst, i, provider = peek
    row = lst.model().entries[i][1]
    names = [e[0] for e in win.moves.menu_entries(row)]
    assert names[-1] == "words"
    win.moves.menu_pick(row, "words")
    card = win.words.card
    assert wait_until(lambda: card.isVisible() and card.kept, 3) and provider.asked[-1] == row.key


def test_hover_w_up_nexts_new_words_link_shows_its_next_episodes_card_and_its_click_still_opens_the_journey(peek):
    win, lst, _i, provider = peek
    j = next(j for j, e in enumerate(lst.model().entries) if e[0] == rows.HERO)
    entry = lst.model().entries[j]
    nxt = entry[1].episodes[entry[1].next_index]
    parts = lst.delegate.parts(entry, lst.visualRect(lst.model().index(j, 0)))
    link = next((p for p in parts if p[0] == "journey"), None)
    if link is None or nxt.n_new is None:
        pytest.skip("the seed's Up Next shows no *N new words ↗*")
    pos = link[1].center()
    QApplication.sendEvent(lst.viewport(), QHelpEvent(QEvent.Type.ToolTip, pos, lst.viewport().mapToGlobal(pos)))
    card = win.words.card
    assert wait_until(card.isVisible, 3)
    assert provider.asked[-1] == (entry[1].key, nxt.id) and nxt.label in card.card.title
    asked = []
    win.page_widgets["current"].on_journey = lambda row, ep: asked.append(ep)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert wait_until(lambda: asked, 3) and asked[0] == nxt


def test_hover_w_r1_leaving_while_the_card_is_still_opening_takes_it_away(peek, monkeypatch):
    """Review r1 #1: an opening keeps the widget hidden until its motion ends — the pointer leaving *N new* then still
    starts the grace, so the card never stays up with the pointer gone."""
    win, lst, i, _provider = peek
    host = win.words
    import types
    opening = types.SimpleNamespace(cancel=lambda: None)
    monkeypatch.setattr(word_peek.motion, "opening_of", lambda w: opening if w is host.card else None)
    host.card.hide()
    host.left()
    assert host._grace.isActive()


def test_hover_w_r1_a_click_asks_for_the_words_again_even_with_the_rows_card_held(peek):
    """Review r1 #2: a move or a Generate since the last hover changes the words — the kept card is asked afresh."""
    win, lst, i, provider = peek
    _rest_on(lst, i)
    assert wait_until(win.words.card.isVisible, 3)
    n = len(provider.asked)
    part = _new_part(lst, i)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=part[1].center())
    assert wait_until(lambda: win.words.card.kept, 3) and len(provider.asked) == n + 1
