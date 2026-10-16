"""The Settings page: the page adversary's fixes (W3.3 FX-page; `tracks/window/reviews/W3.3-page-adversary.md`).

What a wrong answer would cost: one hand-edited value in settings.json leaving half the page unbuilt and `ready` never
said (B2); a control cut off at the window's right edge at text size L, band names printed over each other (B4); a door
row that is a label and nothing (S1); "Anki & mining" shown as "Anki mining" with a shortcut nobody named (S2); a
text-size click that freezes the window for most of a second (S5); ✦ ⚖ 📖 that never say what they are (S8); a
reveal that drags the page back after Tab moved it (H7); a row above the reader growing and sliding the page (`hold`).
"""
import pytest

pytest.importorskip("PyQt6")
from types import SimpleNamespace

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QKeySequence, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import logos, strings, style, windows
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_live as live
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import ALL_ON, EVERYTHING, Recorder, _no_direct_save, make_page  # noqa: F401
from tests.qt.test_settings_live import fakes, make  # noqa: F401 (the live rows' fake reads)


# --- B1: the logo's tile from the theme ------------------------------------------------------------------------------ #
def test_anki_miners_tile_is_the_themes_logo_tile_token(qapp):
    # the colour lives in app/theme.py (no literal under app/qt/): the tile behind the black logo is that token
    assert logos.BEHIND == {"anki_miner": "logo-tile"}
    image = logos._decode("anki_miner", 32, 1.0)
    edge = image.pixelColor(0, image.height() // 2)
    assert edge == QColor(theme.colours()["logo-tile"]) and edge.alpha() == 255


# --- B2: a hand-edited value never stops the build ------------------------------------------------------------------- #
@pytest.mark.parametrize("bad, row_id, shown", [
    ({"logic": {"selection": {"band": "ultra_rare"}}}, "level", None),             # a band no build names
    ({"split_length": "500"}, "split_length", 500),                                # a number written as text: as held
    ({"logic": {"context": {"min_chars": "10"}}}, "sentence_length", (10, None)),  # one end of a range as text
    ({"split_length": [5]}, "split_length", None),                                 # nothing a number field can take
    ({"connect_backlog_cap": "lots"}, "connect_backlog_cap", None),
])
def test_one_hand_edited_value_never_stops_the_page_and_writes_nothing(qapp, bad, row_id, shown):
    store = Recorder(dict(ALL_ON, target_language="ja", **bad))
    page = sp.SettingsPage(SimpleNamespace(settings=store), "ja", found=EVERYTHING)
    readied = []
    page.ready.connect(lambda: readied.append(True))
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    assert readied == [True]                                  # `ready` said: P8's attach, the Tab chain
    assert set(page.rows) == {row.id for row in catalog.ROWS}  # every row built, the bad one too
    view = page.rows[row_id]
    assert view.controls, row_id                              # its control is there (the default, or as held)
    if isinstance(shown, int):
        assert view.controls[0].value() == shown
    elif isinstance(shown, tuple):
        assert view.controls[0].value()[0] == shown[0]
    assert store.calls == []                                  # showing it writes nothing


def test_a_row_that_cant_be_built_is_left_out_and_the_rest_build(qapp, monkeypatch):
    real = sp.SettingsPage._build_row

    def broken(self, index, row, settings):
        if row.id == "split_length":
            raise RuntimeError("a row's own fault")
        return real(self, index, row, settings)
    monkeypatch.setattr(sp.SettingsPage, "_build_row", broken)
    page, store = make_page(ALL_ON, "ja")
    assert page.built and "split_length" not in page.rows
    assert set(page.rows) == {row.id for row in catalog.ROWS} - {"split_length"}


def test_numberfield_shows_a_number_held_as_text_and_refuses_what_isnt_one(qapp):
    field = sc.NumberField(1, 1000, "500", tooltip="t", name="n")
    assert field.value() == 500
    with pytest.raises((ValueError, TypeError)):
        sc.NumberField(1, 1000, "lots")


# --- S1: a door row shows only with a door ---------------------------------------------------------------------------- #
def test_a_door_row_with_no_door_there_never_shows_and_comes_when_its_door_does(qapp, monkeypatch):
    monkeypatch.setattr(windows, "OPENERS", [op for op in windows.OPENERS if op.name != "put-back"])
    page, store = make_page(ALL_ON, "ja")
    for row in catalog.ROWS:
        view = page.rows[row.id]
        if row.kind == "door" and view.isVisibleTo(page):
            assert any(d.isVisibleTo(page) for d in view.doors.values()), row.id      # never a bare label
    assert not page.rows["put_back"].isVisibleTo(page)
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [
        windows.Opener("put-back", "Put Anki back", "tip", windows.always, lambda shell: None)])
    page.refresh()                                            # as `windows._found` tells every page
    assert page.rows["put_back"].isVisibleTo(page) and page.rows["put_back"].doors["put-back"].isVisibleTo(page)
    assert store.calls == []


def test_a_section_whose_rows_are_all_doorless_door_rows_leaves_the_page_and_the_nav(qapp, monkeypatch):
    monkeypatch.setattr(windows, "OPENERS", [])
    page, store = make_page(ALL_ON, "ja")
    # Export without a door: only its actions remain (P11's), so it stays; its door rows go
    assert not page.rows["sentence_dictionary"].isVisibleTo(page)
    assert not page.rows["words_to_leave_out"].isVisibleTo(page)


# --- S2: "&" is shown, never a mnemonic ------------------------------------------------------------------------------- #
def test_an_ampersand_in_a_nav_name_or_a_door_is_shown_and_makes_no_alt_shortcut(qapp):
    page, store = make_page(ALL_ON, "ja")
    nav = page.nav["anki"]
    assert "&" in S.SECTIONS["anki"]
    assert nav.text() == S.SECTIONS["anki"].replace("&", "&&")
    assert QKeySequence.mnemonic(nav.text()).isEmpty()
    assert nav.accessibleName() == S.SECTIONS["anki"]
    for b in page.nav.values():
        assert QKeySequence.mnemonic(b.text()).isEmpty(), b.text()
    door = sc.Door("Q&A…", tooltip="tip")
    assert QKeySequence.mnemonic(door.text()).isEmpty() and door.accessibleName() == "Q&A…"


# --- S5: text size saves and says Restart to apply ------------------------------------------------------------------- #
def test_text_size_is_saved_by_the_page_and_says_restart_never_applied_live(qapp, fakes):  # noqa: F811
    assert live.LIVE_TEXT_SIZE is False
    page, store, shell = make(fakes)
    looks = []
    shell.set_look = lambda text_size=None: looks.append(text_size)
    page.row("text_size").controls[0].changed.emit("L")
    assert store.calls == [({"text_size": "L"}, None)]          # the page saves that key alone
    assert shell.sizes == [] and looks == []                    # the shell's live switch is never called
    assert shell.bar_line.lines == [strings.RESTART_TO_APPLY]
    assert page.row("text_size").help.text() == S.ROWS["text_size"][1]


# --- B4 / S7: nothing cut at the right edge; the level stacked ------------------------------------------------------- #
def _cut(page):
    vp = page.scroll.viewport()
    out = []
    for row_id, view in page.rows.items():
        if not view.isVisibleTo(page):
            continue
        for c in view.findChildren((sc._Control, sc.Door, sc._Field)):
            if c.isVisibleTo(view) and c.mapTo(vp, QPoint(c.width(), 0)).x() > vp.width() + 1:
                out.append(row_id)
    return out


@pytest.mark.parametrize("extra", [0, 40])
def test_at_text_size_large_no_control_runs_past_the_page_and_narrow_rows_stack(qapp, extra):
    # Offscreen has no real fonts (guidelines §5): the page is made just wide enough for its widest control, whatever
    # the fonts make it, and every row must then fit — the narrow ones stacked, none cut (real fonts at 1000 × 620 · L
    # and 200 % · L · 1024: FXP.md's probe figures).
    style.apply(qapp, style.current()[0], "L", "ja")
    page, store = make_page(ALL_ON, "ja", size=(1000, 620))
    open_all = [s for s, slab in page.slabs.items() if not slab.more_row.isHidden()]
    for section_id in open_all:
        page.fold(section_id)
    page._settle()
    widest = max(v.minimumSizeHint().width() for v in page.rows.values() if v.isVisibleTo(page))
    m = page.body.layout().contentsMargins()
    width = page.nav_panel.width() + 1 + m.left() + m.right() + widest + extra + 4
    page.resize(width, 620)
    QApplication.processEvents()
    page._settle()
    QApplication.processEvents()
    assert page.body.width() <= page.scroll.viewport().width()
    assert any(v.stacked for v in page.rows.values() if v.isVisibleTo(page) and v.row.kind != "slider")
    assert _cut(page) == []
    for view in page.rows.values():                          # a row side by side never squeezes its words
        if view.isVisibleTo(page) and view.stacked is False:
            assert view.label.width() >= view._words_min() - 1, view.row.id
    assert store.calls == []


def test_a_row_stacks_its_words_above_its_control_when_narrow_and_goes_back_when_wide(qapp):
    page, store = make_page(ALL_ON, "ja", size=(1400, 700))
    view = page.rows["known_from_anki"]
    assert view.stacked is False
    view.arrange(view.side_by_side() - 10)
    assert view.stacked is True
    page._settle()
    view.arrange(view.side_by_side() + 10)
    assert view.stacked is False


def test_the_level_row_is_words_above_the_slider_full_width_and_the_readout_under_it(qapp):
    page, store = make_page(ALL_ON, "ja", size=(1100, 700))
    page.reveal("level")
    view = page.rows["level"]
    view.set_words(view.label.text(), "≈850 words · 96.0% of your content")      # the readout P4 sets
    page._settle()
    QApplication.processEvents()
    slider = view.controls[0]
    assert view.label.geometry().bottom() <= view.slot.geometry().top()
    assert view.slot.geometry().bottom() <= view.help.geometry().top()      # the readout's line under the slider
    assert slider.width() >= view.width() * 0.8                              # the row's full width
    auto = view.controls[1]
    assert auto.mapTo(view, QPoint(0, 0)).y() < view.slot.geometry().top()    # Automatic beside the words, above


def test_the_level_sliders_names_go_on_two_lines_when_narrow_and_never_meet(qapp):
    bands = [("core", "Core"), ("common", "Common"), ("occasional", "Occasional"), ("uncommon", "Uncommon"),
             ("rare", "Rare"), ("very_rare", "Very Rare"), ("native", "Native")]
    slider = sc.LevelSlider(bands, "rare", tooltip="t", name="Level")
    wide, least = slider.sizeHint().width(), slider.minimumSizeHint().width()
    assert least < wide
    assert not slider.staggered(wide) and slider.staggered(wide - 20)
    assert slider.heightForWidth(wide - 20) > slider.heightForWidth(wide)
    assert slider.heightForWidth(least) == slider.minimumSizeHint().height()


# --- S8: each option's own tip, the picks in words ------------------------------------------------------------------- #
def _move(widget, pos):
    QApplication.sendEvent(widget, QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                               Qt.KeyboardModifier.NoModifier))


def test_tablets_show_the_tip_of_the_tablet_under_the_pointer_and_name_their_picks(qapp):
    tips = S.OPTION_TIPS["junban_only_markers"]
    opts = [(v, S.OPTIONS["junban_only_markers"][v], tips[v]) for v in ("star", "lopsided", "reading")]
    t = sc.Tablets(opts, multi=True, value=["star", "reading"], tooltip="Only words marked", name="Only words marked")
    t.resize(t.sizeHint())
    t.show()
    assert t.hasMouseTracking()
    assert t.accessibleDescription() == "High leverage, Reading"            # ✦ 📖 named in words
    for i, v in enumerate(("star", "lopsided", "reading")):
        _move(t, t._parts()[i][3].center().toPoint())
        assert t.toolTip() == tips[v]
    QApplication.sendEvent(t, QEvent(QEvent.Type.Leave))
    assert t.toolTip() == "Only words marked"
    t.set_value([])
    assert t.accessibleDescription() == S.PICKED_NONE


def test_a_choice_with_option_tips_shows_the_one_under_the_pointer(qapp):
    c = sc.Choice([("a", "✦", "High leverage: starred"), ("b", "Plain", None)], "a", tooltip="Row tip", name="n")
    c.resize(c.sizeHint())
    c.show()
    _move(c, c._rects()[0].center().toPoint())
    assert c.toolTip() == "High leverage: starred"
    _move(c, c._rects()[1].center().toPoint())
    assert c.toolTip() == "Row tip"                            # no tip of its own: the control's
    assert c.accessibleDescription() == "High leverage"


def test_a_choice_without_option_tips_keeps_mouse_tracking_off(qapp):
    c = sc.Choice([("a", "A"), ("b", "B")], "a", tooltip="Row tip")
    assert not c.hasMouseTracking()


# --- N2: Backspace never removes a folder ---------------------------------------------------------------------------- #
def test_backspace_never_removes_a_folder_delete_does(qapp):
    t = sc.Tablets(None, value=["D:\\動画\\日本語", "E:\\アニメ"], tooltip="t", name="n")
    t.resize(t.sizeHint())
    changed = []
    t.changed.connect(changed.append)
    QTest.keyClick(t, Qt.Key.Key_Backspace)
    assert t.value() == ["D:\\動画\\日本語", "E:\\アニメ"] and changed == []
    QTest.keyClick(t, Qt.Key.Key_Delete)
    assert t.value() == ["E:\\アニメ"]


# --- H7: a scroll the page didn't make lets a held reveal go --------------------------------------------------------- #
def test_a_scroll_not_made_by_the_page_lets_the_held_reveal_go(qapp):
    page, store = make_page(ALL_ON, "ja")
    bar = page.scroll.verticalScrollBar()
    assert bar.maximum() > 200
    # a late relayout's clamp (one event-loop turn) ignores any scroll: wait it out, or a loaded run sees it
    assert wait_until(lambda: not getattr(page, "_clamp", False), 5)
    page._revealed = page.rows["max_contexts"]               # a reveal held while the build goes on
    bar.setValue(120)                                         # as Tab's ensureWidgetVisible does: not the page's own
    assert page._revealed is None
    assert store.calls == []


def test_the_pages_own_scrolls_keep_the_held_reveal(qapp):
    page, store = make_page(ALL_ON, "ja")
    marker = page.rows["split_length"]
    page._revealed = marker
    page._scroll_to(40)
    assert page._revealed is marker


# --- hold: a row above the reader growing never slides the page ------------------------------------------------------ #
def test_hold_keeps_the_reader_in_place_when_a_row_above_grows(qapp):
    page, store = make_page(ALL_ON, "ja")
    bar = page.scroll.verticalScrollBar()
    target = page.rows["max_contexts"]
    bar.setValue(page._y_in_body(target) - 50)
    page._settle()
    vp = page.scroll.viewport()
    above = page.rows["anki_connection"]
    assert above.mapTo(vp, QPoint(0, 0)).y() < 0                 # above the reader
    before = page._top_widget()
    y0 = before.mapTo(vp, QPoint(0, 0)).y()
    with page.hold(above):
        above.set_words(above.label.text(), "\n".join(["a line that grows the row"] * 6))
    assert before.mapTo(vp, QPoint(0, 0)).y() == y0
    assert store.calls == []


# --- S3: a keystroke with the search in view settles nothing on the GUI thread --------------------------------------- #
def test_a_search_keystroke_with_the_search_in_view_never_settles_the_layout_itself(qapp, monkeypatch):
    page, store = make_page(ALL_ON, "ja")
    settled = []
    monkeypatch.setattr(page, "_settle", lambda: settled.append(True))
    page.search.edit.setText("kanji")
    assert settled == []
    assert page.rows["names_kanji"].isVisibleTo(page) and not page.rows["split_length"].isVisibleTo(page)
    page.search.edit.setText("")
    assert page.rows["split_length"].isVisibleTo(page)
    assert store.calls == []


def test_the_rows_that_import_on_first_use_wait_for_the_warming_worker():
    assert sp._WARM_ROWS(catalog.ROW["level"]) and sp._WARM_ROWS(catalog.ROW["connect_video_folders"])
    assert not sp._WARM_ROWS(catalog.ROW["split_length"])
