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
    assert win.words._grace.isActive()
    assert wait_until(lambda: not win.words._grace.isActive(), 3)      # the grace ran out with the pointer on it
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


# --- Kotoba-K: Known / Ignore on the kept card ------------------------------------------------------------------- #
class Marks:
    """The window's writer for the card's marks (`PeekHost.mark` / `undo`, a worker's): records each call and answers
    as `word_marks` would — or with `error`."""

    def __init__(self, error=None):
        self.calls, self.undos, self.error, self.undo_ids = [], 0, error, []

    def mark(self, marks):
        from app.services.word_marks import Marked
        self.calls.append(list(marks))
        if self.error:
            return Marked(error=self.error, busy=True)
        return Marked(done=[(w, None, m) for w, m in marks], undo_id=len(self.calls))

    def undo(self, undo_id=None):
        from app.services.word_marks import Marked
        self.undos += 1
        self.undo_ids.append(undo_id)
        return Marked(done=[("x", "known", None)])


def _kept_with_marks(peek, error=None):
    win, lst, i, provider = peek
    marks = Marks(error)
    said = []
    win.words.mark, win.words.undo, win.words.say = marks.mark, marks.undo, said.append
    part = _new_part(lst, i)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=part[1].center())
    card = win.words.card
    assert wait_until(lambda: card.isVisible() and card.kept and card.card is not None, 3)
    return win, card, marks, said, provider


def _word_item(card, text):
    return next(it for it in card.sheet.items if it.text == text and it.word is not None)


def _pair(card, item, mark):
    card.hovered(item)
    r = card._pair_rect(item)
    at = QPoint(r.left() + r.width() // 4, r.center().y()) if mark == "known" else \
        QPoint(r.right() - r.width() // 4, r.center().y())
    hit = card.pair_at(at)
    assert hit is not None and hit.mark == mark and hit.word is item.word
    return hit


def test_kotoba_k_a_kept_words_hover_shows_known_and_ignore_and_a_click_marks_it_at_once(peek):
    win, card, marks, _said, _provider = _kept_with_marks(peek)
    gentleman = _word_item(card, "紳士")
    hit = _pair(card, gentleman, "known")
    assert card.hot_item is gentleman
    card.hovered(hit)                                                   # the pointer on the pair keeps it up
    assert card.hot_item is gentleman and card.hot_pair is hit
    card.clicked(hit)
    assert card.marked == {"紳士": "known"}                              # painted before the write
    assert wait_until(lambda: marks.calls == [[("紳士", "known")]], 3)
    card.clicked(_pair(card, _word_item(card, "紳士"), "known"))         # the lit side again: cleared
    assert card.marked == {}
    assert wait_until(lambda: marks.calls[-1] == [("紳士", None)], 3)
    card.clicked(_pair(card, _word_item(card, "紳士"), "ignore"))
    assert card.marked == {"紳士": "ignore"}
    assert wait_until(lambda: marks.calls[-1] == [("紳士", "ignore")], 3)
    assert _word_item(card, "紳士")                                       # it stays in place, dimmed, while open


def test_kotoba_k_learned_on_the_way_words_are_marked_too_and_the_hover_card_has_no_pair(peek):
    win, lst, i, _provider = peek
    _rest_on(lst, i)
    card = win.words.card
    assert wait_until(card.isVisible, 3) and not card.kept
    card.hovered(_word_item(card, "紳士"))
    assert card.hot_item is None and card.pair_at(QPoint(0, 0)) is None   # the hover card only shows: no marks
    card.hide()
    win2, card, marks, _said, _provider = _kept_with_marks(peek)
    hit = _pair(card, _word_item(card, "遠慮"), "ignore")
    card.clicked(hit)
    assert wait_until(lambda: marks.calls == [[("遠慮", "ignore")]], 3)


def test_kotoba_k_a_mark_that_fails_puts_the_word_back_and_says_why(peek):
    from app.qt import strings
    win, card, marks, said, _provider = _kept_with_marks(peek, error="Your known words are being updated by Anki.")
    card.clicked(_pair(card, _word_item(card, "鉄砲"), "known"))
    assert card.marked == {"鉄砲": "known"}
    assert wait_until(lambda: said, 3) and card.marked == {}
    assert said == [strings.WORDS_MARK_FAILED.format(why="Your known words are being updated by Anki.")]


def test_kotoba_k_i_know_all_of_these_marks_every_new_word_in_one_write_and_its_undo_puts_them_back(peek):
    from app.qt import strings
    win, card, marks, _said, _provider = _kept_with_marks(peek)
    card.clicked(_pair(card, _word_item(card, "紳士"), "ignore"))       # one marked already: left as it is
    assert wait_until(lambda: len(marks.calls) == 1, 3)
    assert card.all_known.isVisible() and card.all_known.text() == strings.WORDS_ALL_KNOWN
    assert card.all_known.toolTip()
    card.all_known.click()
    expect = [w for w in NEW if w != "紳士"]
    assert all(card.marked[w] == "known" for w in expect)               # painted with the press
    assert wait_until(lambda: len(marks.calls) == 2 and card.all_done, 3)
    assert marks.calls[1] == [(w, "known") for w in expect]
    assert card.all_known.text() == strings.WORDS_ALL_UNDO.format(n=len(expect))
    card.all_known.click()
    assert wait_until(lambda: marks.undos == 1 and card.all_done is None, 3)
    assert marks.undo_ids == [2]                                          # the batch's own write, never the last one
    assert card.marked == {"紳士": "ignore"} and card.all_known.text() == strings.WORDS_ALL_KNOWN


def test_kotoba_k_the_words_asked_again_keep_a_marked_word_in_place_while_the_counts_follow(peek):
    win, card, marks, _said, provider = _kept_with_marks(peek)
    provider.kw = dict(new=[w for w in NEW if w != "鉄砲"])             # the numbers have left it out
    card.clicked(_pair(card, _word_item(card, "鉄砲"), "known"))
    assert wait_until(lambda: card.card.n_new == len(NEW) - 1, 3)       # asked again after the write: the count follows
    assert [w.label for w in card.card.new] == NEW                       # ... and the word stays, dimmed, in its place
    card.close()
    assert card.marked == {}                                             # the next open reads the words as they are


def test_kotoba_k_two_quick_clicks_on_one_word_land_in_their_order(peek):
    """A review's finding: a ✓ and its clear, clicked at once, are written in that order (one queue), never the clear
    first — which would leave the word Known while the card shows it cleared."""
    win, card, marks, _said, _provider = _kept_with_marks(peek)
    import threading
    slow = threading.Event()
    first = marks.mark

    def slow_mark(m):
        if not marks.calls:
            slow.wait(1.0)                                              # the first write takes its time
        return first(m)
    win.words.mark = slow_mark
    card.clicked(_pair(card, _word_item(card, "瓶"), "known"))
    card.clicked(_pair(card, _word_item(card, "瓶"), "known"))         # cleared at once, before the first answers
    slow.set()
    assert wait_until(lambda: len(marks.calls) == 2, 5)
    assert win.words._writes.idle(5)
    QApplication.processEvents()                                         # (both answers in, before the window goes)
    assert marks.calls == [[("瓶", "known")], [("瓶", None)]] and card.marked == {}


def test_kotoba_k_the_marks_follow_the_window_through_its_own_write(peek, monkeypatch):
    """The window's real path: `Services.mark_words` writes the user's lists (the test root's), and the numbers are told
    every marked word at once."""
    from app.services import word_lists, word_marks
    import types
    win, _lst, _i, _provider = peek
    left = []
    numbers = types.SimpleNamespace(language="ja", leave_out=lambda words: left.append(set(words)),
                                    idle=lambda timeout=None: True)
    monkeypatch.setattr(win.services.writer, "numbers", numbers)
    word_lists._BACKED_UP.clear()
    result = win._card_mark([("鉄砲", "ignore"), ("紳士", "known")])
    assert result.error is None and len(result.done) == 2
    assert word_marks.marks("ja").get("鉄砲") == "ignore" and word_marks.marks("ja").get("紳士") == "known"
    assert left and {"鉄砲", "紳士"} <= left[-1]
    assert win._card_undo(result.undo_id).done and "紳士" not in word_marks.marks("ja")
    word_marks._UNDO.clear()


def test_kotoba_k_keep_marked_keeps_only_the_marked_words_and_adds_new_ones():
    old = TW.Card(key="k", title="t", tier="Soon", n_files=1, n_new=3, today=4,
                  new=(_w("紳士"), _w("鉄砲"), _w("白熊")), anki=None,
                  before=(TW.Group("喫茶店の朝", (_w("遠慮"),)),), kept=False, episode=None, items=())
    new = old._replace(n_new=2, new=(_w("紳士"), _w("西洋")), before=())
    got = TW.keep_marked(old, new, {"鉄砲": "known", "遠慮": "ignore"})
    assert [w.label for w in got.new] == ["紳士", "鉄砲", "西洋"] and got.n_new == 2
    assert [(g.title, [w.label for w in g.words]) for g in got.before] == [("喫茶店の朝", ["遠慮"])]

