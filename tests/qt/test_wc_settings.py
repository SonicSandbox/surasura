"""Work counts on Settings (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work
counts*): what each press of the page costs — paints and where they land, layout passes (the hints this app answers in
Python, against one forced pass of the page), widgets made — counted, never timed.

What a wrong answer would cost a learner: Settings that lag on every click (a9.1's try: the page laid out 30–120×
per click, a search keystroke 253 ms at 250 %), a wheel notch that repaints the whole page in view, a switch that
flickers rows it never touched. The page is built once for the file (`work_counts.kept`); every test puts back what
it changed, unmeasured.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app import settings_manager
from app.qt import bridge, motion, windows
from app.qt import settings_controls as sc
from tests.qt import work_counts as wc
from tests.qt.test_settings_page import ALL_ON, NEW_FOLDER, _at_third, change, make_page, shown_views


@pytest.fixture(scope="module")
def page(qapp, tmp_path_factory):
    """The Settings page (every row's `when` met, Japanese), built once for the file, at rest."""
    with wc.module_env(tmp_path_factory, "settings"):
        mode = motion.clock().mode
        was = mode.setting
        mode.set_setting("full")
        p, store = make_page(ALL_ON, "ja")
        wc.kept(p)
        wc.settle()
        p.store_ = store
        yield p
        wc.close_kept(p)
        mode.set_setting(was)


@pytest.fixture(autouse=True)
def _at_rest(page, monkeypatch):
    wc.home(monkeypatch, "settings")
    """Each test from the same place: the search empty, the page at its top, no write pending; the page never saves
    settings.json itself (the service does)."""
    def refused(*_a, **_k):
        raise AssertionError("the page saved settings.json itself: only the settings service may")
    monkeypatch.setattr(settings_manager, "save_settings", refused)
    monkeypatch.setattr(settings_manager, "save_keys", refused)
    if page.search.edit.text():
        page.search.edit.setText("")
    page.store_.land()
    page.scroll.verticalScrollBar().setValue(0)
    wc.settle()
    yield
    page.store_.land()
    wc.settle()


QUIET = "anki_sync_auto"            # a switch whose change shows and hides no other row


def _in_view(page, widget):
    """`widget` scrolled into the page's view (unmeasured), the page settled."""
    page.scroll.ensureWidgetVisible(widget, 0, 150)
    wc.settle()
    vp, r = wc.rect_in_window(page.scroll.viewport()), wc.rect_in_window(widget)
    assert vp.top() <= r.top() and r.bottom() <= vp.bottom(), (vp, r)
    return widget


def _quiet_toggle(page):
    view = page.rows[QUIET]
    assert isinstance(view.controls[0], sc.Toggle)
    return _in_view(page, view)


def _click(widget):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


def _wheel(vp, notches=1):
    pos = QPointF(vp.width() / 2, vp.height() / 2)
    QApplication.sendEvent(vp, QWheelEvent(pos, QPointF(vp.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                           QPoint(0, -120 * notches), Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))


# --- R0: a press that changes nothing paints nothing ------------------------------------------------------------- #
def test_r0_a_write_landing_with_the_values_already_shown_paints_nothing(page):
    """Another window's write of the values the page already shows (its listeners told, its rows read again)."""
    store = page.store_
    view = _quiet_toggle(page)
    key = view.row.keys[0]
    same = dict(store.get()).get(key, view.controls[0].value())
    with wc.measure(page) as w:
        store.outside({key: same})
    assert w.painted == 0, w.report()
    assert w.hints == 0 and w.created == 0, w.report()


# --- R4: a switch repaints its row, and only what it reveals ----------------------------------------------------- #
def test_r4_a_switch_that_reveals_nothing_repaints_only_inside_its_own_row(page):
    """A switch's click: its own row repainted, nothing else on the page, no layout pass, no widget made."""
    view = _quiet_toggle(page)
    toggle = view.controls[0]
    with wc.measure(page) as w:
        _click(toggle)
    try:
        assert w.painted > 0, w.report()                                  # (the switch did show its new value)
        assert w.paints_outside(view) == [], w.report()
        assert w.union <= wc.rect_in_window(view).width() * wc.rect_in_window(view).height(), w.report()
        assert w.hints <= wc.one_pass(page.body, page) * wc.PASS_SLACK, w.report()
        assert w.created == 0, w.report()
    finally:
        _click(toggle)                                                     # put back, unmeasured
        wc.settle()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="WC found.md F1: the whole page in view repaints (rows above the switch too)")
def test_r4_r1_a_sections_switch_repaints_nothing_above_itself_and_lays_the_page_out_once(page):
    """*Junban* off hides its section's rows (on brings them back): the page below the switch repaints, nothing
    above it; one layout pass at most; no widget made or deleted (rows are hidden, never rebuilt)."""
    view = _in_view(page, page.rows["enable_junban"])
    toggle = view.controls[0]
    unit = wc.one_pass(page.body, page)
    top = wc.rect_in_window(view).top()
    below = QRect(0, top, page.width(), page.height() - top)
    try:
        for _ in range(2):                                                 # off, then on again: both measured
            with wc.measure(page) as w:
                change(toggle, not toggle.value())
            assert w.paints_outside_rect(below) == [], w.report()
            assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()
            assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
            assert w.created == 0 and w.deleted == 0, w.report()
    finally:
        if not toggle.value():
            change(toggle, True)
        wc.settle()


# --- R1: More options and the search: one layout pass ------------------------------------------------------------ #
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="WC found.md F2: rows above the button repaint")
def test_r1_r4_more_options_lays_the_page_out_once_and_repaints_nothing_above_its_button(page):
    """*More options*: the section's other rows open in place below its button — one layout pass of the page at most,
    nothing above the button repainted, nothing made. *Fewer options* the same."""
    section = next(s for s, slab in page.slabs.items() if not slab.more_row.isHidden() and s not in page.folds())
    more = _in_view(page, page.slabs[section].more)
    unit = wc.one_pass(page.body, page)
    try:
        for _ in range(2):                                                 # open, then close: both measured
            top = wc.rect_in_window(more).top()
            below = QRect(0, top, page.width(), page.height() - top)
            with wc.measure(page) as w:
                page.fold(section)
            assert w.paints_outside_rect(below) == [], w.report()
            assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
            assert w.created == 0 and w.deleted == 0, w.report()
    finally:
        if section in page.folds():
            page.fold(section)
        wc.settle()


SEARCH_LAYERS = 12                  # today's most: ~9 viewports of paint summed over the nested layers (body, slab,
#                                     row, label…) when a keystroke changes every row in view
SEARCH_MOVES = 9                    # today's most: a row moved 7–8 times by one keystroke (found.md F3) — the rule is
#                                     `wc.MOVES_PER_PASS`; lower this to it when F3's fix lands. Unpaused (a9.1's lag): 38


@pytest.mark.parametrize("typed", ["a", "an", "", "zzzz", "片仮名"])
def test_r1_a_search_keystroke_lays_the_page_out_once_whatever_it_shows_or_hides(page, typed):
    """A keystroke hides and shows rows (a search cleared shows ~126 again): laid out once as the pass ends, never once
    a row shown (a9.1: 100 ms at 250 %). The page's paint is the viewport's worth at most each layer, never a widget
    made. `typed` follows a keystroke that matched most rows."""
    unit = wc.one_pass(page.body, page)
    page.search.edit.setText("ann" if typed != "an" else "a")
    wc.settle()
    with wc.measure(page) as w:
        page.search.edit.setText(typed)
    assert w.most_moved()[0] <= SEARCH_MOVES, w.report()
    assert w.hints <= unit * wc.PASS_SLACK, (unit, w.report())
    vp = page.scroll.viewport()
    assert w.area <= SEARCH_LAYERS * vp.width() * vp.height(), w.report()
    assert w.created == 0 and w.deleted == 0, w.report()


# --- R2: a wheel notch paints the strip it uncovers --------------------------------------------------------------- #
def test_r2_a_wheel_notch_paints_only_the_strip_it_uncovers_and_the_scroll_bar(page):
    """A notch moves what is on screen and paints only the strip that comes in (the body is opaque, a9.1) — plus
    the scroll bar, whose handle moved."""
    vp = page.scroll.viewport()
    bar = page.scroll.verticalScrollBar()
    view = wc.rect_in_window(vp)
    for _ in range(3):
        v0 = bar.value()
        with wc.measure(page) as w:
            _wheel(vp)
        moved = wc.exposed(v0, bar.value())
        assert moved > 0
        in_view = w.union_in(view)
        assert in_view <= (moved + wc.STRIP_SLACK_PX) * vp.width(), (moved, in_view, w.report())
        assert w.paints_outside(vp, bar) == [], w.report()
        assert w.hints == 0 and w.created == 0, w.report()


# --- R4: the level slider's release ------------------------------------------------------------------------------ #
def test_r4_the_level_sliders_release_repaints_its_own_row_and_lays_nothing_out(page):
    """A band chosen by a press and release on the slider: the slider's row repaints (its gems settle frozen), and the
    rest of the page doesn't; no layout pass, nothing made."""
    view = _in_view(page, page.rows["level"])
    slider = view.controls[0]
    before = slider.value()
    target = next(i for i, (b, _n) in enumerate(slider._bands) if b != before)

    def send(kind, x, buttons):
        pos = QPointF(x, slider.chamber(0).y())
        button = Qt.MouseButton.LeftButton
        QApplication.sendEvent(slider, QMouseEvent(kind, pos, QPointF(slider.mapToGlobal(pos.toPoint())), button,
                                                   buttons, Qt.KeyboardModifier.NoModifier))
    x = slider.chamber(target).x()
    try:
        with wc.measure(page) as w:
            send(QEvent.Type.MouseButtonPress, x, Qt.MouseButton.LeftButton)
            send(QEvent.Type.MouseButtonRelease, x, Qt.MouseButton.NoButton)
        assert slider.value() != before
        assert w.painted > 0, w.report()
        assert w.paints_outside(view) == [], w.report()
        assert w.hints <= wc.one_pass(page.body, page) * wc.PASS_SLACK, w.report()
        assert w.created == 0, w.report()
    finally:
        change(slider, before)
        wc.settle()


# --- R4: a Choice and a switch, by the mouse and the keyboard ---------------------------------------------------- #
def test_r4_a_choice_clicked_on_another_value_repaints_only_inside_its_own_row(page):
    """A Choice pressed on another of its values (the row's *split books by* choice, which reveals nothing): the
    choice shows the new value, its own row alone repaints, no layout pass, no widget made."""
    view = _in_view(page, page.rows["split_books_by"])
    choice = view.controls[0]
    assert isinstance(choice, sc.Choice)
    before = choice.value()
    target = 0 if before == "even" else 1                                 # the other value's option
    back = 1 - target
    try:
        with wc.measure(page) as w:
            QTest.mouseClick(choice, Qt.MouseButton.LeftButton, pos=choice._rects()[target].center().toPoint())
        assert choice.value() != before, w.report()
        assert w.painted > 0, w.report()
        assert w.paints_outside(view) == [], w.report()
        assert w.hints <= wc.one_pass(page.body, page) * wc.PASS_SLACK, w.report()
        assert w.created == 0, w.report()
    finally:
        QTest.mouseClick(choice, Qt.MouseButton.LeftButton, pos=choice._rects()[back].center().toPoint())   # put back, unmeasured
        wc.settle()


def test_r4_a_choice_moved_by_the_arrow_keys_repaints_only_inside_its_own_row(page):
    """An arrow key moving a Choice's cursor (nothing chosen): its own row repainted, nothing else on the page, no
    layout pass, no widget made."""
    view = _in_view(page, page.rows["app_motion"])
    assert isinstance(view.controls[0], sc.Choice), view.controls[0]
    choice = view.controls[0]
    choice.setFocus()
    wc.settle()
    try:
        QTest.keyClick(choice, Qt.Key.Key_Home)                            # the cursor to the first option, unmeasured
        wc.settle()
        with wc.measure(page) as w:
            QTest.keyClick(choice, Qt.Key.Key_Right)
        rect = wc.rect_in_window(view)
        assert w.painted > 0, w.report()                                  # (the cursor did move and paint)
        assert w.paints_outside(view) == [], w.report()
        assert w.union <= rect.width() * rect.height(), w.report()
        assert w.hints <= wc.one_pass(page.body, page) * wc.PASS_SLACK, w.report()
        assert w.created == 0, w.report()
    finally:
        QTest.keyClick(choice, Qt.Key.Key_Home)                            # the cursor back, unmeasured
        choice.clearFocus()
        wc.settle()


def test_r4_a_space_on_a_switch_repaints_only_inside_its_own_row(page):
    """A switch toggled by Space from the keyboard: its own row repainted, nothing else on the page, no layout pass,
    no widget made."""
    view = _quiet_toggle(page)
    toggle = view.controls[0]
    before = toggle.value()
    try:
        with wc.measure(page) as w:
            QTest.keyClick(toggle, Qt.Key.Key_Space)
        assert toggle.value() != before, w.report()                       # (the Space really flipped the switch)
        assert w.painted > 0, w.report()                                  # (the switch did show its new value)
        assert w.paints_outside(view) == [], w.report()
        assert w.union <= wc.rect_in_window(view).width() * wc.rect_in_window(view).height(), w.report()
        assert w.hints <= wc.one_pass(page.body, page) * wc.PASS_SLACK, w.report()
        assert w.created == 0, w.report()
    finally:
        if toggle.value() != before:
            QTest.keyClick(toggle, Qt.Key.Key_Space)                       # put back, unmeasured
        wc.settle()


# --- R5: an overlay opened again is built once ------------------------------------------------------------------- #
def test_r5_a_select_menu_opened_closed_and_opened_again_makes_no_widget(page):
    """A Select's menu opened by a click, closed, and opened again: the menu was built with the control, so the second
    open makes no widget."""
    select = _in_view(page, page.rows["theme"]).controls[0]
    assert isinstance(select, sc.Select)
    try:
        _click(select)
        assert select.menu.isVisible()
        select.menu.close()
        wc.settle()
        with wc.measure(page) as w:
            _click(select)
        assert select.menu.isVisible(), w.report()
        assert w.created == 0, w.report()
    finally:
        select.menu.close()
        wc.settle()


# --- R4: the level slider by an arrow key ------------------------------------------------------------------------ #
def test_r4_a_level_sliders_arrow_key_repaints_its_own_row_and_lays_nothing_out(page):
    """An arrow key moves the level slider one band: the slider's row repaints (what it shows of the new band), and
    the rest of the page doesn't; no layout pass, nothing made."""
    view = _in_view(page, page.rows["level"])
    slider = view.controls[0]
    before = slider.value()
    bands = [b for b, _n in slider._bands]
    step = Qt.Key.Key_Right if bands.index(before) < len(bands) - 1 else Qt.Key.Key_Left
    try:
        with wc.measure(page) as w:
            QTest.keyClick(slider, step)
        expected = bands.index(before) + (1 if step == Qt.Key.Key_Right else -1)
        assert bands.index(slider.value()) == expected, w.report()
        assert w.painted > 0, w.report()
        assert w.paints_outside(view) == [], w.report()
        assert w.hints <= wc.one_pass(page.body, page) * wc.PASS_SLACK, w.report()
        assert w.created == 0, w.report()
    finally:
        change(slider, before)
        wc.settle()


# --- R3: a folder taken off a list by its cross ------------------------------------------------------------------ #
def test_r3_a_folders_cross_removes_that_folder_alone_and_repaints_only_inside_its_row(page):
    """The cross on the first folder tablet of the video-folders list: that folder alone goes (the other stays), its
    row repainted, nothing above it, no widget made."""
    opened = "anki" not in page.folds()
    tablets = before = None
    try:
        if opened:
            page.fold("anki")                                              # (the folders list sits behind More options)
            wc.settle()
        view = _in_view(page, page.rows["connect_video_folders"])
        tablets = view.controls[0]
        assert isinstance(tablets, sc.Tablets) and tablets.is_list
        before = tablets.value()
        change(tablets, before + [NEW_FOLDER] if NEW_FOLDER not in before else before)
        wc.settle()
        two = tablets.value()
        assert len(two) >= 2, two
        cross = tablets._parts()[0][4]
        assert cross is not None
        with wc.measure(page) as w:
            QTest.mouseClick(tablets, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPointF(cross.center()).toPoint())
            wc.rest(150)
        assert tablets.value() == two[1:], (two, tablets.value(), w.report())
        assert w.painted > 0, w.report()
        assert w.paints_outside(view) == [], w.report()
        assert w.created == 0, w.report()
    finally:
        if tablets is not None and before is not None:
            change(tablets, before)                                        # put back, unmeasured
        if opened and "anki" in page.folds():
            page.fold("anki")
        wc.settle()


# --- R1: the slash key lays the page out at most once ------------------------------------------------------------- #
def test_r1_a_slash_focusing_the_search_lays_the_page_out_at_most_once(page):
    """`/` on a page scrolled down: the search takes focus and is brought into view, and the page is laid out at most
    one pass (no more hints than one forced pass of the body asks), no widget moved more than a pass's worth (MOVES_PER_PASS)."""
    bar = page.scroll.verticalScrollBar()
    unit = wc.one_pass(page.body, page)
    bar.setValue(min(600, bar.maximum()))
    page.setFocus()
    wc.settle()
    scrolled = bar.value()
    try:
        with wc.measure(page) as w:
            QTest.keyClick(page, Qt.Key.Key_Slash)
        assert scrolled > 0, w.report()                                   # (it really stood scrolled down)
        # the page's own focus widget (hasFocus() also needs the window active, which the file's earlier tests change)
        assert page.window().focusWidget() is page.search.edit, w.report()
        assert bar.value() == 0, w.report()                               # brought into view
        assert w.hints <= unit, (unit, w.report())                        # (one pass at most: the scroll asks no more)
        assert w.most_moved()[0] <= wc.MOVES_PER_PASS, w.report()
    finally:
        page.search.edit.clearFocus()
        bar.setValue(0)
        wc.settle()


# --- R4: a placing rule picked (Connect's rules) ----------------------------------------------------------------- #
def test_r4_a_placing_rule_picked_repaints_only_inside_its_own_row(qapp, tmp_path_factory):
    """A place picked on one line of Connect's placing rules: that rule's row repaints (the new place shown) and
    nothing outside it does; only that source's rule is written, the other lines keep their places."""
    from app.qt import settings_rules as sr
    channel = "youtube:UCgx8nPpXp9c0Kv4bUk1D3ng"
    rules = {"hato": "top", channel: "soon", "bilibili": "finished"}
    with wc.module_env(tmp_path_factory, "settings_rules"):
        own, store = make_page(dict(ALL_ON, placing_rules=rules), "ja")
        try:
            rows = sr.attach(own)
            wc.settle()
            view = _in_view(own, own.rows[sr.ROW_ID])
            others = {s: line.select.value() for s, line in rows.lines.items() if s != channel}
            assert len(others) >= 2 and rows.lines[channel].select.value() == "soon"
            with wc.measure(own) as w:
                rows.lines[channel].select._pick("after-show")
                wc.rest(150)
            assert rows.lines[channel].select.value() == "after-show", w.report()
            assert {s: line.select.value() for s, line in rows.lines.items() if s != channel} == others, w.report()
            assert store.calls and store.calls[-1][0]["placing_rules"][channel] == "after-show", w.report()
            assert w.painted > 0, w.report()                              # (the line did show its new place)
            assert w.paints_outside(view) == [], w.report()
        finally:
            own.slots[sr.ROW_ID].slot_needs = None
            own.close()
            wc.settle()


# --- R5: a reveal of a row (a search link) ---------------------------------------------------------------------- #
def test_r5_a_reveal_scrolls_the_page_to_the_row_washes_it_and_makes_no_widget(page, monkeypatch):
    """A reveal of the Known words row (a search link) after an earlier reveal: the page scrolls from the top to put
    the row at its top third and washes it (the wash rises, then ends at 0); no widget is made. (Paint containment is
    not pinned here: the page itself repaints as the scroll area glides.)"""
    row = page.rows["known_road"]
    levels = []
    real_set_wash = row.set_wash
    monkeypatch.setattr(row, "set_wash", lambda v: (levels.append(v), real_set_wash(v))[1])
    try:
        assert page.reveal("known") is True                          # the first reveal, unmeasured
        wc.settle()
        page.scroll.verticalScrollBar().setValue(0)
        wc.settle()
        assert not _at_third(page, row)
        with wc.measure(page) as w:
            assert page.reveal("known") is True
            wc.rest(150)
        assert _at_third(page, row), w.report()
        assert levels and max(levels) > 0 and levels[-1] == 0.0, levels
        assert row.wash == 0.0, w.report()
        assert w.created == 0, w.report()
    finally:
        page.scroll.verticalScrollBar().setValue(0)
        wc.settle()


# --- R5: a door's window kept, opened again ---------------------------------------------------------------------- #
def test_r5_a_door_opening_its_window_closed_into_its_icon_and_opened_again_makes_no_widget(page, monkeypatch):
    """A door opens its window; the window goes into its icon (hidden, or minimised) and the door is pressed again:
    the kept window comes back, the same one, and the second open makes no widget."""
    shell = QWidget()
    shell.services = SimpleNamespace(settings=page.store_)
    shell.bridge = bridge.Bridge(settings=page.store_, parent=shell)
    made = []

    def make(owner):
        made.append(1)
        return windows.SecondaryWindow(owner, "Kept")

    monkeypatch.setattr(windows, "OPENERS", [windows.Opener("kept-door", "Kept", "tip", windows.always,
                                                            lambda sh: windows.show(sh, "kept-door", make))])
    was = page.shell
    page.shell = shell
    try:
        page.open_door("kept-door")
        first = windows.opened(shell, "kept-door")
        assert first is not None and first.isVisible() and made == [1]
        for tuck in (first.hide, first.showMinimized):
            tuck()
            wc.settle()
            if tuck == first.hide:
                assert first.tucked(), first.windowState()
            else:
                assert first.isMinimized(), first.windowState()
            with wc.measure(page) as w:
                page.open_door("kept-door")
            assert windows.opened(shell, "kept-door") is first, w.report()
            assert first.isVisible() and not first.isMinimized(), w.report()
            assert made == [1], w.report()
            assert w.created == 0, w.report()
    finally:
        page.shell = was
        shell.deleteLater()
        wc.settle()
