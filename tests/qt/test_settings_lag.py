"""Settings and the bug's press lag (alpha 9.1 try, round 1: "why does it always lag when i'm going through settings?",
report 3: "It lags when I open up the debug screen"). Measured at 250 %: a switch's step 142 ms, a search keystroke
253 ms, *More options* 74 ms; the causes, each pinned here:

- Qt lays out every ancestor of a widget it shows at once, so each row shown laid the whole page out again (clearing a
  search: 126 rows, ~100 ms) — the page's layouts are paused while rows are shown and hidden, laid out once after;
- a word-wrapped label lays its text out again on every ask, and every layout asks each of ~270 lines at two widths or
  more — a row's label and help remember their height per width and text (`Words`);
- the scrolled body wasn't opaque, so every wheel notch and glide frame painted the whole page in view (Qt's
  scroll by moving what is on screen can't be seen offscreen: its own ground is pinned here, the frames in the bench);
- each row's rule was asked twice a pass, every slab re-tinted after each section, and a landed write that can move a
  door ran the whole pass twice;
- the picture's scrub asked each of ~630 shown widgets for `shown_fit` through PyQt's own getattr (~11 µs each when the
  widget lacks it: ~7 ms of the press).
"""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from app.qt import report as report_ui
from app.qt import settings_catalog as catalog
from app.qt import settings_page as sp
from app.qt import style
from tests.qt.test_settings_page import ALL_ON, make_page, shown_views

JA_LABEL = "JPDBやJitenに載っていない片仮名の名前（ブシン、ゼーリエ）を一語として数える"
ZH_HELP = "按你自己的文本给生词排序：最常见、你最快能读懂的句子里的词排在前面"


class _Counter(QObject):
    """Events of `kind` reaching widgets of `cls`, counted while installed on the application."""

    def __init__(self, kind, cls):
        super().__init__()
        self.kind, self.cls, self.n = kind, cls, 0

    def eventFilter(self, obj, event):
        if event.type() == self.kind and isinstance(obj, self.cls):
            self.n += 1
        return False


def _laid_out_in_order(page, flush=False):
    """Every shown row of every container laid out: a height, below the one before, never overlapping it. `flush`
    (no group name shown between, as while searching): each row right under the one before, the first at its
    container's top — where the layout puts it, never where it stood before the pass."""
    for slab in page.slabs.values():
        if slab.isHidden():
            continue
        for box in (slab.main_box, slab.adv_box):
            views = [box.itemAt(i).widget() for i in range(box.count())]
            views = [v for v in views if isinstance(v, sp.RowView) and v.isVisibleTo(page)]
            if flush and views and box is slab.main_box:
                assert views[0].y() == box.contentsMargins().top(), views[0].row.id
            for above, below in zip(views, views[1:]):
                assert above.height() > 0 and below.height() > 0, below.row.id
                assert above.geometry().bottom() < below.geometry().top(), (above.row.id, below.row.id)
                if flush:
                    assert below.geometry().top() == above.geometry().bottom() + 1 + max(0, box.spacing()),                         (above.row.id, below.row.id)


def _settled(turns=5):
    for _ in range(turns):
        QApplication.processEvents()


# --- one layout for a pass, never one per row shown -------------------------------------------------------------- #
@pytest.mark.parametrize("query, came_back", [
    ("an", 20),          # a match in most sections: rows come back inside slabs that stayed shown
    ("zzzz", 80),        # nothing matched: every slab comes back (each slab shown re-laid the column, unpaused)
])
def test_clearing_a_search_lays_the_page_out_once_not_once_per_row(qapp, query, came_back):
    """Clearing a search shows nearly every row again. Each row shown in a shown slab moved every row under it (97
    rows: 1,526 moves), each slab shown moved every slab under it; paused, a few moves a row and a slab. Counted with
    the layout settled before and after (the adversary's SHOULD-1: one turn left the search's own work in the count)."""
    page, store = make_page(ALL_ON, "ja")
    page.search.edit.setText(query)
    _settled()
    hidden = [v for v in page.rows.values() if not v.isVisibleTo(page)]
    moves, slab_moves = _Counter(QEvent.Type.Move, sp.RowView), _Counter(QEvent.Type.Move, sp.Slab)
    qapp.installEventFilter(moves)
    qapp.installEventFilter(slab_moves)
    try:
        page.search.edit.setText("")
        _settled()
    finally:
        qapp.removeEventFilter(moves)
        qapp.removeEventFilter(slab_moves)
    shown = shown_views(page)
    assert len([v for v in hidden if v.isVisibleTo(page)]) > came_back
    assert moves.n <= 5 * len(shown), (moves.n, len(shown))
    assert slab_moves.n <= 3 * len(page.slabs), (slab_moves.n, len(page.slabs))     # the column laid out once too
    _laid_out_in_order(page)
    assert store.calls == []


def test_a_keystroke_with_the_search_in_view_lays_the_rows_out_before_the_loops_turn(qapp):
    """The one pass with nothing to settle (S3: the search in view): the paused layouts are laid out as they resume,
    so the rows left stand flush before any paint — never a frame with gaps where the hidden rows were."""
    page, _store = make_page(ALL_ON, "ja")
    page.search.edit.setText("an")                    # (no processEvents: what the next paint would show)
    _laid_out_in_order(page, flush=True)
    page.search.edit.setText("ann")
    _laid_out_in_order(page, flush=True)


def test_a_switch_that_shows_a_sections_rows_lays_them_out_before_the_first_paint(qapp):
    """Junban off hides its section's rows, on brings them back: laid out in the same turn (no frame of rows piled at
    the top of their slab), and every paused layout running again."""
    page, _store = make_page(ALL_ON, "ja")
    control = page.rows["enable_junban"].controls[0]
    for on in (False, True):
        control.set_value(on)
        control.changed.emit(on)                     # the page's own path: its pass, then the write landing
        _laid_out_in_order(page)                     # (before the loop's turn: no paint has come in between)
    layouts = [page.column_box, page.body.layout()]
    for slab in page.slabs.values():
        layouts += [slab.layout(), slab.main_box, slab.adv.layout()]
    assert all(layout.isEnabled() for layout in layouts)


def test_a_pass_that_fails_midway_leaves_no_layout_paused(qapp, monkeypatch):
    page, _store = make_page(ALL_ON, "ja")
    real = page._show_section

    def broken(section_id, *a, **k):
        if section_id == "anki":
            raise RuntimeError("a rule that broke")
        return real(section_id, *a, **k)
    monkeypatch.setattr(page, "_show_section", broken)
    with pytest.raises(RuntimeError):
        page._refresh_visibility()
    assert page.column_box.isEnabled() and page.body.layout().isEnabled()
    assert all(s.main_box.isEnabled() and s.layout().isEnabled() for s in page.slabs.values())
    assert not page._pausing


# --- a row's words remember their height ---------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, then", [(JA_LABEL, ZH_HELP), (ZH_HELP, "")])
def test_a_rows_words_answer_as_qt_does_and_forget_with_their_text_font_and_style(qapp, text, then):
    words, plain = sp.Words(), QLabel()
    for label in (words, plain):
        label.setWordWrap(True)
        label.setText(text)

    def same():
        for width in (120, 240, 241, 480):
            assert words.heightForWidth(width) == plain.heightForWidth(width), width
    same()
    for label in (words, plain):
        label.setText(then)                          # new words (a live line, the picture's scrub)
    same()
    bigger = QFont(words.font())
    bigger.setPointSizeF(bigger.pointSizeF() * 1.6)
    for label in (words, plain):
        label.setFont(bigger)                        # text size L
    same()
    for label in (words, plain):
        label.setStyleSheet("QLabel { padding: 9px 14px; }")      # the stylesheet's margins
    same()
    for label in (words, plain):
        label.setContentsMargins(3, 0, 11, 0)
    same()
    for minimum in (300, 0):                         # a row stacking or not moves its words' minimum (`arrange`)
        for label in (words, plain):
            label.setMinimumWidth(minimum)
        same()


def test_a_rows_label_and_help_are_words_that_remember(qapp):
    page, _store = make_page(ALL_ON, "ja")
    view = page.rows["split_length"]
    assert isinstance(view.label, sp.Words) and isinstance(view.help, sp.Words)
    width = view.help.width()
    key = (width, view.help.minimumWidth(), view.help.text())
    assert key in view.help._heights                                 # the page's layout asked it at the width it has
    known = dict(view.help._heights)
    assert view.help.heightForWidth(width) == known[key]
    assert view.help._heights == known                               # answered from what it remembered


# --- the body is opaque: a scroll moves what is on screen ---------------------------------------------------------- #
def test_the_body_paints_its_own_ground(qapp):
    page, _store = make_page(ALL_ON, "ja")
    assert page.body.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    image = page.body.grab().toImage()
    margin = page.body.layout().contentsMargins()
    ground = image.pixelColor(max(0, margin.left() // 2), image.height() // 2)
    assert ground == style.qcolor(style.colours()["content"])


# --- one ask per row, one tint, one pass per landed write -------------------------------------------------------------- #
def test_a_pass_asks_each_rows_rule_once_and_tints_once(qapp, monkeypatch):
    page, _store = make_page(ALL_ON, "ja")
    asked, tints = [], []
    real_visible, real_tint = catalog.visible, page._tint
    monkeypatch.setattr(catalog, "visible", lambda row, *a, **k: asked.append(row.id) or real_visible(row, *a, **k))
    monkeypatch.setattr(page, "_tint", lambda: tints.append(True) or real_tint())
    page._refresh_visibility()
    assert sorted(asked) == sorted(row.id for row in catalog.ROWS)
    assert tints == [True]


def test_a_landed_write_that_can_move_a_door_is_one_pass(qapp, monkeypatch):
    page, _store = make_page(ALL_ON, "ja")
    passes = []
    real = page._refresh_visibility
    monkeypatch.setattr(page, "_refresh_visibility", lambda *a, **k: passes.append(k.get("doors")) or real(*a, **k))
    page._written(["enable_junban"])
    assert passes == [True]
    passes.clear()
    page._written(["split_length"])
    assert passes == [False]


# --- the bug's press: the scrub asks a widget's class ---------------------------------------------------------------- #
def test_picture_mode_asks_each_widgets_class_for_shown_fit_never_the_widget(qapp, monkeypatch):
    """Every `shown_fit` is a method of its class; the scrub's walk asks the class (PyQt's own getattr on a widget that
    lacks the name searched Qt's properties first: ~7 ms over Settings at 250 %), and still fits each one."""
    class Fits(QLabel):
        fitted = 0

        def shown_fit(self):
            Fits.fitted += 1

    window = QWidget()
    Fits(window)
    for _ in range(5):
        QLabel("Downloads", window)
    window.show()
    looked = []
    real = QWidget.__getattribute__

    def watch(self, name):
        if name == "shown_fit":
            looked.append(self)
        return real(self, name)
    try:
        with monkeypatch.context() as patched:
            patched.setattr(QWidget, "__getattribute__", watch, raising=False)
            with report_ui.PictureMode(window, report_ui.scrub.Identity()):
                pass
    finally:
        window.close()
    assert Fits.fitted == 2                                    # fitted scrubbed, then whole again
    assert all(isinstance(w, Fits) for w in looked)            # only the one that has it was asked on itself
