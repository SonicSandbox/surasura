"""The Settings page (W3.3 P3; the RUNBOOK's P3 row, the register's B3 / B4 / S1 / S5 / S7 / S8, the lead's decisions).

What a wrong answer would cost: a control that writes a key it doesn't own, or a whole block (another window's change
reverted: CLAUDE.md §6's `save_keys` rule); a write at load, on a search or a fold (a full Generate for nothing); a
per-language value that flips back while its write is on its way, or loses the other language (S1, D31); a choice that
scrolls the page under the hand (brief §2: "It shouldn't move"); a search that loses the folds the user opened; a reveal
that lands on a closed fold; a refresh that repaints the whole page (S19); a door to a window that isn't there; a page
built in one long pass on the GUI thread (B4); grey text under the floor on either slab (S5: "Readability is critical").

The settings service is a recorder with the service's API (`Recorder`: an in-memory file, every `set` kept, `land()`
writes what is pending the way the writer does — the updates run on the file then — and tells the listeners), and
`settings_manager.save_settings` / `save_keys` fail the test if the page calls them.
"""
import copy
import json
import os
import statistics
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QWidget

from app import settings_manager, theme
from app.qt import bridge, freeze, motion, style, windows
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from app.services import settings as settings_service
from tests.qt.conftest import wait_until
from tests.test_settings_catalog import WITH_MODULES

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVERYTHING = frozenset(catalog.MODULES) | {"koe_revealed"}
# Every row's `when` met (Connect on, Junban on, the Coverage road, decks for both languages, Speech revealed)
ALL_ON = {
    "connect_enabled": True, "enable_junban": True, "strategy": "coverage", "enable_koe": True,
    "anki_sync_decks": {"ja": ["日本語::コア2k"], "zh": ["中文::HSK"]},
    "connect_backlog_cap": {"ja": 40, "zh": 25},
    "connect_video_folders": {"ja": ["E:\\アニメ\\ぼっち・ざ・ろっく！"], "zh": ["D:\\视频\\中文"]},
}
NEW_FOLDER = "D:\\動画\\日本語"


class Recorder:
    """The settings service's API over an in-memory settings.json. `calls`: every `set` as (changes, update)."""

    def __init__(self, data=None):
        self.file = copy.deepcopy(data or {})
        self.calls = []
        self._pending = {}
        self._updates = []
        self._subscribers = []

    def get(self):
        settings = copy.deepcopy(self.file)
        for key, value in self._pending.items():
            settings_service.put(settings, key, value)
        return settings_service.freeze(settings)

    def set(self, changes, update=None, now=False):
        self.calls.append((dict(changes), update))
        for key, value in changes.items():
            self._pending[key] = copy.deepcopy(value)
        if update is not None:
            self._updates.append(update)

    def pending(self):
        return sorted(self._pending)

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def automation(self):
        return True

    def land(self, updates=True):
        """The writer's turn: the pending changes onto the file, then (with `updates`) the merges; the listeners told
        the keys the write carried (as the service: an update's keys aren't named)."""
        keys = sorted(self._pending)
        for key, value in self._pending.items():
            settings_service.put(self.file, key, value)
        self._pending = {}
        if updates:
            for update in self._updates:
                update(self.file)
            self._updates = []
        for callback in self._subscribers:
            callback(keys)

    def outside(self, changes):
        """Another window's write, landed at once."""
        for key, value in changes.items():
            settings_service.put(self.file, key, value)
        for callback in self._subscribers:
            callback(sorted(changes))


@pytest.fixture(autouse=True)
def _full_motion():
    """*Full* motion, whatever Windows' own switch says (*Follow* reads it: off on GitHub's runner, which is reduced
    motion there): the page's tests run frozen on one mode; a reduced-motion test sets its own."""
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("full")
    yield
    mode.set_setting(was)


@pytest.fixture(autouse=True)
def _no_direct_save(monkeypatch):
    def refused(*_a, **_k):
        raise AssertionError("the page saved settings.json itself: only the settings service may")
    monkeypatch.setattr(settings_manager, "save_settings", refused)
    monkeypatch.setattr(settings_manager, "save_keys", refused)


def make_page(data=None, language="ja", found=EVERYTHING, size=(1100, 700), wait=True):
    store = Recorder(dict({"target_language": language}, **(data or {})))
    page = sp.SettingsPage(SimpleNamespace(settings=store), language, found=found)
    page.resize(*size)
    page.show()
    if wait:
        assert wait_until(lambda: page.built, 20)
        QApplication.processEvents()
    return page, store


def open_all_folds(page):
    for section_id, slab in page.slabs.items():
        if not slab.more_row.isHidden() and section_id not in page.folds():
            page.fold(section_id)


def shown_views(page):
    """The built rows a person can see now, in page order."""
    return [page.rows[row.id] for row in catalog.ROWS if row.id in page.rows and page.rows[row.id].isVisibleTo(page)]


def other_value(page, view, control, settings):
    """A value `control` doesn't show now, and the payload the page hands the catalog for it."""
    row = view.row
    current = control.value()
    if isinstance(control, sc.Toggle):
        new = not current
        return new, ({row.keys[1]: new} if row.kind == "slider" else new)
    if isinstance(control, (sc.Choice, sc.Select)):
        values = control.values() if hasattr(control, "values") else [v for v, _l, _t in control._options]
        new = next(v for v in values if v != current)
        return new, new
    if isinstance(control, sc.LevelSlider):
        new = next(b for b, _n in control._bands if b != current)
        return new, new
    if isinstance(control, sc.Tablets):
        if control.is_list:
            new = current + [NEW_FOLDER]
            return new, new
        first = control._options[0][0]
        new = [v for v, _l, _t in control._options if (v in current) != (v == first)]
        return new, new
    if isinstance(control, sc.Range):
        lo, hi = current
        new = (lo + 1, hi + 1)
        return new, new
    if isinstance(control, sc.NumberField):
        new = current + 1 if current + 1 <= control.maximum else current - 1
        return new, new
    if isinstance(control, sc.TextField):
        new = (current or "") + "日本"
        return new, new
    raise AssertionError(f"no way to change {type(control).__name__} of {row.id}")


def change(control, new):
    """What a person's change does: the control shows the new value and says so, once."""
    control.set_value(new)
    control.changed.emit(new)


# --- saving: every control writes exactly its key(s), through the service only -------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_every_visible_control_writes_exactly_its_keys_and_a_per_language_one_keeps_the_other_language(qapp, language):
    page, store = make_page(ALL_ON, language)
    open_all_folds(page)
    walked = set()
    # backwards: a row's switch comes before the rows it shows, so the rows are walked while they show
    for view in reversed(shown_views(page)):
        if view.row.id == "target_language" or not view.isVisibleTo(page):
            continue
        for control in view.controls:
            if not control.isVisibleTo(page):
                continue
            row = view.row
            settings = page._settings()
            new, payload = other_value(page, view, control, settings)
            expected, update = catalog.change(row, settings, language, payload)
            store.calls.clear()
            change(control, new)
            walked.add(row.id)
            if row.id == "known_road":
                assert store.calls == [], "the road is the page's state, never a key"
                continue
            assert len(store.calls) == 1, (row.id, store.calls)
            changes, given_update = store.calls[0]
            if row.keys[0] in catalog.PER_LANGUAGE:
                key = row.keys[0]
                assert changes == {} and given_update is not None, row.id       # merged at write time (S1)
                other = "zh" if language == "ja" else "ja"
                on_file = {key: {other: "the other language's", language: None}}
                given_update(on_file)
                assert set(on_file) == {key} and on_file[key][other] == "the other language's", row.id
                assert catalog.value(row, on_file, language) == control.value(), row.id
            else:
                assert given_update is None
                assert set(changes) == set(expected) and set(changes) <= set(row.keys), (row.id, changes)
                assert changes == expected
            store.land()
    shown_with_controls = {v.row.id for v in shown_views(page) if v.controls} | walked
    assert walked >= shown_with_controls - {"target_language"}
    assert len(walked) > 60, walked
    # the language last: one key, and the page follows it once it lands
    view = page.rows["target_language"]
    store.calls.clear()
    other = "zh" if language == "ja" else "ja"
    change(view.controls[0], other)
    assert store.calls == [({"target_language": other}, None)]
    store.land()
    assert page.language == other


def test_a_row_its_owner_takes_is_never_written_by_the_page_too(qapp):
    """`takes` (the live rows' owner, P4): a change its owner handled is written once, by the owner — the page writes
    nothing beside it; one the owner declines the page writes as any row."""
    page, store = make_page(ALL_ON)
    open_all_folds(page)
    view = page.rows["app_motion"]
    control = view.controls[0]
    taken = []
    page.takes["app_motion"] = lambda value: taken.append(value) or True
    new, _payload = other_value(page, view, control, page._settings())
    store.calls.clear()
    change(control, new)
    assert taken == [new] and store.calls == []
    page.takes["app_motion"] = lambda value: False
    held = catalog.value(view.row, page._settings(), "ja")
    newer = next(v for v in ("follow", "full", "reduced") if v not in (new, held))
    change(control, newer)
    assert store.calls == [({"app_motion": newer}, None)]


def test_a_per_language_value_never_flips_back_while_its_write_is_on_its_way(qapp):
    page, store = make_page(ALL_ON, "ja")
    cap = page.rows["connect_backlog_cap"].controls[0]
    assert cap.value() == 40
    change(cap, 300)
    assert store.calls[-1][0] == {} and store.calls[-1][1] is not None
    # another window's write lands first (Chinese's cap), its keys naming the cap: the field keeps 300
    store.outside({"connect_backlog_cap": {"ja": 40, "zh": 30}})
    assert cap.value() == 300
    store.land()                                          # the merge: onto the file's own value at write time
    assert store.file["connect_backlog_cap"] == {"ja": 300, "zh": 30}
    assert cap.value() == 300 and "connect_backlog_cap" not in page._overlay


def test_a_per_language_change_back_before_it_lands_is_still_written(qapp):
    # the page compares with what it shows (its overlay), not with the file: 40 → 300 → 40 writes twice
    page, store = make_page(ALL_ON, "ja")
    cap = page.rows["connect_backlog_cap"].controls[0]
    change(cap, 300)
    change(cap, 40)
    assert len(store.calls) == 2
    store.land()
    assert store.file["connect_backlog_cap"]["ja"] == 40


@WITH_MODULES
def test_nothing_is_written_at_build_search_fold_reveal_or_for_the_same_value(qapp):
    page, store = make_page(ALL_ON, "ja")
    page.search.edit.setText("kanji")
    page.search.edit.setText("")
    for section_id in list(page.slabs):
        if not page.slabs[section_id].more_row.isHidden():
            page.fold(section_id)
            page.fold(section_id)
    for target in ("known", "mine_line", "soon_line", "logic.selection.min_count", "app"):
        page.reveal(target)
    for view in shown_views(page):
        for control in view.controls:
            control.changed.emit(control.value())             # the same value: nothing to write
    store.land()
    assert store.calls == []


def test_a_typed_number_writes_once_on_enter_never_while_typing(qapp):
    # B3: typing 3, 30, 300 commits once — never "3" on the way
    page, store = make_page(ALL_ON, "ja")
    field = page.rows["split_length"].controls[0]
    field.edit.setFocus()
    field.edit.selectAll()
    QTest.keyClicks(field.edit, "300")
    assert store.calls == []
    QTest.keyClick(field.edit, Qt.Key.Key_Return)
    assert store.calls == [({"split_length": 300}, None)]


def test_the_level_slider_writes_band_and_automatic_off_and_automatic_alone_writes_its_key(qapp):
    page, store = make_page(dict(ALL_ON, logic={"selection": {"band": "core", "auto": True}}), "ja")
    view = page.rows["level"]
    slider, auto = view.controls
    other = next(b for b, _n in slider._bands if b != slider.value())
    change(slider, other)
    assert store.calls[-1] == ({"logic.selection.band": other, "logic.selection.auto": False}, None)
    store.land()
    assert auto.value() is False                          # the landed write repainted the row's other control
    change(auto, True)
    assert store.calls[-1] == ({"logic.selection.auto": True}, None)


def test_gap2_a_level_dragged_by_hand_is_saved_at_the_release_not_after_the_gems_settle(qapp):
    """Gap 2 (M4.1 P3): the band's write waited for the gem's glide and fall (up to ~205 ms after the release). Now
    the service has it at the release; the gem settles after, a look only."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent
    page, store = make_page(dict(ALL_ON, logic={"selection": {"band": "core", "auto": False}}), "ja")
    slider = page.rows["level"].controls[0]
    clock = motion.clock()
    freeze.set_frozen(False)
    clock.use_test_time()
    try:
        def send(kind, x, buttons):
            pos = QPointF(x, slider.chamber(0).y())
            button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
            QApplication.sendEvent(slider, QMouseEvent(kind, pos, QPointF(slider.mapToGlobal(pos.toPoint())), button,
                                                       buttons, Qt.KeyboardModifier.NoModifier))
        a, b = slider.chamber(2), slider.chamber(3)
        x = a.x() + 0.35 * (b.x() - a.x())
        send(QEvent.Type.MouseButtonPress, slider.chamber(0).x(), Qt.MouseButton.LeftButton)
        clock.advance(200)
        send(QEvent.Type.MouseMove, x, Qt.MouseButton.LeftButton)
        clock.advance(300)
        calls = len(store.calls)
        send(QEvent.Type.MouseButtonRelease, x, Qt.MouseButton.NoButton)
        band = slider.value()
        assert band != "core" and slider.busy()                        # chosen, the gem still settling
        assert store.calls[calls:] == [({"logic.selection.band": band}, None)]     # (Automatic already off)
        clock.advance(400)
        assert len(store.calls) == calls + 1                           # the settle writes nothing more
    finally:
        clock.use_real_time()
        freeze.set_frozen(None)


# --- a choice never moves the page (brief §2; S7: 100 %, 150 %, 175 %, text size L, a language switch) --------------- #
def never_moves(text_size="M", language="ja"):
    """Every visible control changed with the page scrolled to put it in the middle: its y in the viewport and the
    scroll value, before and after (at once, and after the loop's own turn and the write landing). -> problems."""
    app = QApplication.instance()
    if style.current()[1] != text_size:
        style.apply(app, "night", text_size, language)
    page, store = make_page(ALL_ON, language)
    open_all_folds(page)
    QApplication.processEvents()
    vp, bar = page.scroll.viewport(), page.scroll.verticalScrollBar()
    problems, checked = [], 0
    views = [v for v in reversed(shown_views(page)) if v.row.id != "target_language"]
    views.append(page.rows["target_language"])            # the language last: rows above it change (Parsing's)
    for view in views:
        if not view.isVisibleTo(page):
            continue
        for control in view.controls:
            if not control.isVisibleTo(page):
                continue
            middle = control.mapTo(page.body, QPoint(0, 0)).y() - vp.height() // 2
            bar.setValue(max(0, min(bar.maximum(), middle)))
            QApplication.processEvents()
            v0, y0 = bar.value(), control.mapTo(vp, QPoint(0, 0)).y()
            new, _payload = other_value(page, view, control, page._settings())
            change(control, new)
            y1 = control.mapTo(vp, QPoint(0, 0)).y()
            QApplication.processEvents()
            store.land()
            QApplication.processEvents()
            y2, v2 = control.mapTo(vp, QPoint(0, 0)).y(), bar.value()
            checked += 1
            if (y1, y2) != (y0, y0):
                problems.append(f"{view.row.id}: y {y0} -> {y1} -> {y2}")
            if view.row.id != "target_language" and v2 != v0:
                problems.append(f"{view.row.id}: scroll {v0} -> {v2}")
    page.close()
    return problems, checked


def test_a_choice_never_moves_the_page_at_100_percent(qapp):
    problems, checked = never_moves("M")
    assert checked > 60 and problems == []


def test_a_choice_never_moves_the_page_at_text_size_large(qapp):
    problems, checked = never_moves("L")
    assert checked > 60 and problems == []


def test_a_choice_never_moves_the_page_in_chinese(qapp):
    problems, checked = never_moves("M", "zh")
    assert checked > 60 and problems == []


@pytest.mark.parametrize("scale", ["1.5", "1.75"])
def test_a_choice_never_moves_the_page_at_150_and_175_percent(scale, tmp_path):
    # Windows' scaling stood in for by QT_SCALE_FACTOR, each scale in its own process (tests/qt/capture.py's way)
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM="offscreen", SURASURA_FREEZE_MOTION="1",
               SURASURA_TEST_ROOT=str(tmp_path), PYTHONIOENCODING="utf-8")
    code = ("import json, sys\n"
            "from PyQt6.QtWidgets import QApplication\n"
            "app = QApplication(['settings-page-scale'])\n"
            "from app.qt import style\n"
            "style.apply(app, 'night', 'M', 'ja')\n"
            "from tests.qt import test_settings_page as t\n"
            "settings_manager = t.settings_manager\n"
            "settings_manager.save_settings = settings_manager.save_keys = None\n"
            "problems, checked = t.never_moves('M')\n"
            "from app.qt import bridge\n"
            "bridge.wait_for_workers(10000)\n"     # as the app's quit: a live row's read (P4) ends before the exit
            "dpr = app.primaryScreen().devicePixelRatio()\n"
            "print('RESULT ' + json.dumps([problems, checked, dpr]))\n")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=240)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line is not None, done.stdout[-2000:] + done.stderr[-4000:]
    problems, checked, dpr = json.loads(line[len("RESULT "):])
    assert abs(dpr - float(scale)) < 0.01
    assert checked > 60 and problems == []


def test_a_click_never_scrolls_a_field_into_view_but_tab_may(qapp):
    page, store = make_page(ALL_ON, "ja", size=(1100, 600))
    vp, bar = page.scroll.viewport(), page.scroll.verticalScrollBar()
    field = page.rows["split_length"].controls[0]
    # the field half out of view at the viewport's foot
    bar.setValue(field.mapTo(page.body, QPoint(0, 0)).y() - vp.height() + field.height() // 2)
    QApplication.processEvents()
    before = bar.value()
    QTest.mouseClick(field.edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(4, 4))
    QApplication.processEvents()
    assert field.edit.hasFocus() and bar.value() == before
    # Tab moves focus on to the next control, below the fold: Qt's focus scroll brings it into view
    page.activateWindow()
    tabs = page.scroll.tab_scrolls
    QTest.keyClick(field.edit, Qt.Key.Key_Tab)
    QApplication.processEvents()
    assert page.scroll.tab_scrolls == tabs + 1


# --- search ------------------------------------------------------------------------------------------------------------ #
def test_search_filters_rows_by_label_help_and_key_words_and_hides_group_names(qapp):
    page, store = make_page(ALL_ON, "ja")
    names = page.rows["names_katakana"].group
    assert names.isVisibleTo(page)
    page.search.edit.setText("telemetry")                 # a search word, not in the label
    assert page.rows["telemetry_enabled"].isVisibleTo(page)
    assert not page.rows["names_katakana"].isVisibleTo(page)
    assert not page.slabs["parsing"].isVisibleTo(page) and page.slabs["app"].isVisibleTo(page)
    page.search.edit.setText("katakana")
    assert page.rows["names_katakana"].isVisibleTo(page) and not names.isVisibleTo(page)
    page.search.edit.setText("Particles and endings")     # the help line
    assert page.rows["connect_send_grammar"].isVisibleTo(page)
    assert store.calls == []


def test_search_reads_japanese_words_and_opens_a_fold_where_a_row_matches_then_restores_the_folds(qapp):
    page, store = make_page(ALL_ON, "ja")
    page.fold("level")                                    # the user opened Level's More options
    assert page.folds() == {"level"}
    page.search.edit.setText("例文")                       # a choice's label in Japanese: Backfill's fills
    assert page.rows["junban_backfill_fills"].isVisibleTo(page)
    page.search.edit.setText("suspended")                 # Known words' + row, its fold closed by the user
    assert page.rows["anki_sync_include_suspended"].isVisibleTo(page)
    assert page.slabs["known"].adv.isVisibleTo(page)
    page.search.edit.setText("")
    assert not page.slabs["known"].adv.isVisibleTo(page)  # closed again: as the user left it
    assert page.slabs["level"].adv.isVisibleTo(page) and page.folds() == {"level"}
    assert page.rows["names_katakana"].group.isVisibleTo(page)


def test_search_says_when_nothing_matches_and_hides_every_slab(qapp):
    page, store = make_page(ALL_ON, "ja")
    page.search.edit.setText("xyzzy")
    assert page.nothing.isVisibleTo(page)
    assert page.nothing.text() == S.SEARCH_NONE.format(q="xyzzy")
    assert not any(slab.isVisibleTo(page) for slab in page.slabs.values())
    page.search.edit.setText("")
    assert not page.nothing.isVisibleTo(page) and page.slabs["setup"].isVisibleTo(page)


def test_slash_focuses_the_search_and_esc_in_it_clears_it_first(qapp):
    page, store = make_page(ALL_ON, "ja")
    page.scroll.verticalScrollBar().setValue(600)
    page.setFocus()
    QTest.keyClick(page, Qt.Key.Key_Slash)
    assert page.search.edit.hasFocus()
    assert page.scroll.verticalScrollBar().value() == 0   # the search stands first: brought into view
    QTest.keyClicks(page.search.edit, "names")
    QTest.keyClick(page.search.edit, Qt.Key.Key_Escape)
    assert page.search.edit.text() == ""
    # empty, Esc isn't the search's: it goes on (the shell's router; never bound here)
    assert page.search.eventFilter(page.search.edit, _key(Qt.Key.Key_Escape)) is False


def _key(k):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier)


# --- reveal ------------------------------------------------------------------------------------------------------------ #
def _at_third(page, widget):
    vp = page.scroll.viewport()
    return abs(widget.mapTo(vp, QPoint(0, 0)).y() - vp.height() / 3) <= 1


def test_reveal_known_brings_the_known_words_section_to_the_top_third_and_washes_its_row(qapp):
    page, store = make_page(ALL_ON, "ja")
    assert page.reveal("known") is True
    first = page.rows["known_road"]
    assert _at_third(page, first)
    assert first.wash == 0.0                              # frozen motion: the wash ran to its end at once


def test_reveal_of_a_row_under_more_options_opens_its_fold(qapp):
    page, store = make_page(ALL_ON, "ja")
    assert "level" not in page.folds()
    assert page.reveal("logic.selection.min_count") is True
    view = page.rows["min_count"]
    assert "level" in page.folds() and view.isVisibleTo(page) and _at_third(page, view)
    assert store.calls == []


def test_reveal_of_a_section_id_and_the_store_lines_until_p6(qapp):
    page, store = make_page(ALL_ON, "ja")
    assert page.reveal("sentences") is True
    assert _at_third(page, page.rows["sentence_length"])
    # mine_line's slot is still empty (P6): the switch's row; soon_line: the Content section
    assert page.reveal("mine_line") is True and _at_third(page, page.rows["connect_enabled"])
    assert page.reveal("soon_line") is True and _at_third(page, page.rows["target_language"])
    assert page.reveal("no such thing") is False


def test_reveal_clears_a_search_that_would_hide_the_row(qapp):
    page, store = make_page(ALL_ON, "ja")
    page.search.edit.setText("telemetry")
    page.reveal("logic.names_kanji")
    assert page.search.edit.text() == "" and page.rows["names_kanji"].isVisibleTo(page)


@pytest.fixture
def clock(qapp):
    """The clock on test time, motion unfrozen and Full; put back afterwards (as test_settings_controls')."""
    c = motion.clock()
    for a in c.active:
        a.stop()
    freeze.set_frozen(False)
    c.use_test_time(0.0)
    before = c.mode.setting
    c.mode.set_setting("full")
    yield c
    for a in c.active:
        a.stop()
    c.use_real_time()
    c.mode.set_setting(before)
    freeze.set_frozen(None)


def test_the_reveal_glides_and_washes_on_the_clock(qapp, clock):
    page, store = make_page(ALL_ON, "ja")
    bar = page.scroll.verticalScrollBar()
    page.reveal("logic.names_kanji")
    view = page.rows["names_kanji"]
    assert bar.value() == 0 and view.wash == 1.0          # nothing jumps: both on the clock
    clock.advance(theme.SETTINGS_MOTION["page-scroll"])
    assert _at_third(page, view)
    clock.advance(theme.SETTINGS_MOTION["row-wash"] / 2 - theme.SETTINGS_MOTION["page-scroll"])
    assert 0.0 < view.wash < 1.0                          # fading
    clock.advance(theme.SETTINGS_MOTION["row-wash"])
    assert view.wash == 0.0


def test_under_reduced_motion_the_reveal_jumps_and_the_wash_is_steady_for_a_second(qapp, clock):
    clock.mode.set_setting("reduced")
    page, store = make_page(ALL_ON, "ja")
    page.reveal("logic.names_kanji")
    view = page.rows["names_kanji"]
    assert _at_third(page, view)                          # a jump
    clock.advance(theme.SETTINGS_MOTION["row-wash"])
    assert view.wash == 1.0                               # steady: not on the clock
    timer = page._wash_timer
    assert timer.isActive() and timer.interval() == theme.SETTINGS_MOTION["row-wash-steady"]
    timer.timeout.emit()
    assert view.wash == 0.0


def test_the_wash_keeps_every_text_on_the_row_above_its_floor():
    c = theme.colours()
    for ground in theme.SETTINGS_GROUNDS:
        washed = theme.over(c["settings-row-wash"], c[ground])
        for role in ("label", "sub-label", "help", "value", "more"):
            floor = 7.0 if role in theme.SETTINGS_CHOSEN_ROLES else 4.5
            assert theme.contrast(c[theme.SETTINGS_TEXT[role]], washed) >= floor, (role, ground)


# --- refresh: a write from elsewhere repaints only its rows -------------------------------------------------------- #
def test_a_write_from_elsewhere_repaints_only_its_row(qapp):
    page, store = make_page(ALL_ON, "ja")
    toggle = page.rows["names_kanji"].controls[0]
    assert toggle.value() is True
    page.paints.clear()
    values = {v.row.id: [c.value() for c in v.controls] for v in page.rows.values()}
    store.outside({"logic.names_kanji": False})
    assert toggle.value() is False
    assert dict(page.paints) == {"names_kanji": 1}
    after = {v.row.id: [c.value() for c in v.controls] for v in page.rows.values()}
    assert {k for k in values if values[k] != after[k]} == {"names_kanji"}
    store.outside({"logic.names_kanji": False})          # the same value again: nothing repainted
    assert dict(page.paints) == {"names_kanji": 1}
    assert store.calls == []


def test_a_write_that_turns_a_switch_shows_and_hides_its_rows(qapp, monkeypatch):
    # Put Anki back's door registered (a door row shows only with its door: FX-page S1)
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [
        windows.Opener("put-back", "Put Anki back", "tip", windows.always, lambda shell: None)])
    page, store = make_page(ALL_ON, "ja")
    assert page.rows["connect_mine_words"].isVisibleTo(page)
    store.outside({"connect_enabled": False})
    assert not page.rows["connect_mine_words"].isVisibleTo(page)
    store.outside({"enable_junban": False})
    assert not page.slabs["backfill"].isVisibleTo(page) and not page.nav["backfill"].isVisibleTo(page)
    assert page.rows["put_back"].isVisibleTo(page)        # Put Anki back stays (N3)


def test_a_language_switch_asks_every_row_again_without_rebuilding(qapp):
    page, store = make_page(ALL_ON, "ja")
    built = {row_id: id(view) for row_id, view in page.rows.items()}
    assert page.rows["names_katakana"].isVisibleTo(page) and not page.rows["zh_script"].isVisibleTo(page)
    assert page.rows["connect_backlog_cap"].controls[0].value() == 40
    store.outside({"target_language": "zh"})
    assert page.language == "zh"
    assert not page.rows["names_katakana"].isVisibleTo(page) and page.rows["zh_script"].isVisibleTo(page)
    assert page.rows["connect_backlog_cap"].controls[0].value() == 25        # Chinese's own cap
    assert {row_id: id(view) for row_id, view in page.rows.items()} == built


def test_the_known_words_road_starts_on_the_side_the_decks_say_and_shows_only_its_rows(qapp, monkeypatch):
    # an import door registered (a door row shows only with its door: FX-page S1)
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [
        windows.Opener("migaku", "Migaku", "tip", windows.always, lambda shell: None)])
    page, store = make_page(dict(ALL_ON, anki_sync_decks={"ja": [], "zh": ["中文::HSK"]}), "ja")
    road = page.rows["known_road"].controls[0]
    assert road.value() == "import"
    assert page.rows["known_import"].isVisibleTo(page) and not page.rows["anki_sync_auto"].isVisibleTo(page)
    change(road, "anki")
    assert page.rows["anki_sync_auto"].isVisibleTo(page) and not page.rows["known_import"].isVisibleTo(page)
    assert store.calls == []


# --- doors ------------------------------------------------------------------------------------------------------------- #
def test_a_door_shows_only_while_its_opener_is_registered_and_available(qapp, monkeypatch):
    opened, ok = [], [True]
    monkeypatch.setattr(windows, "OPENERS", [
        windows.Opener("anki", "Anki", "the Anki window", lambda s, l: ok[0], opened.append),
        windows.Opener("junban", "Junban", "順", windows.always, opened.append, "junban"),
        windows.Opener("word-lists", "Words", "the lists", windows.always, opened.append),
    ])
    monkeypatch.setattr(windows, "_FOUND", {})
    page, store = make_page(ALL_ON, "ja")
    anki = page.rows["anki_decks"].doors["anki"]
    junban = page.rows["junban_door"].doors["junban"]
    assert anki.isVisibleTo(page)
    assert not junban.isVisibleTo(page)                   # its module not found (yet)
    windows._found({"junban": True})                      # the look answered: every door row told
    assert junban.isVisibleTo(page)
    ok[0] = False
    page.refresh()
    assert not anki.isVisibleTo(page)
    # a door no opener holds yet (PENDING_OPENERS: W3.4's rows) doesn't show, nor does a door row with none of its
    # doors there (FX-page S1: never a bare label)
    assert "migaku" in catalog.PENDING_OPENERS
    change(page.rows["known_road"].controls[0], "import")
    view = page.rows["known_import"]
    assert not view.isVisibleTo(page)
    assert not any(d.isVisibleTo(page) for d in view.doors.values())


def test_a_door_opens_through_the_shell_or_asks(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(windows, "OPENERS", [windows.Opener("word-lists", "Words", "tip", windows.always,
                                                            opened.append)])
    page, store = make_page(ALL_ON, "ja")
    asked = []
    page.door_asked.connect(asked.append)
    page.rows["words_to_leave_out"].doors["word-lists"].click()
    assert asked == ["word-lists"] and opened == []
    store2 = Recorder(ALL_ON)
    shell = QWidget()
    shell.services = SimpleNamespace(settings=store2)
    shell.bridge = bridge.Bridge(settings=store2, parent=shell)
    page2 = sp.SettingsPage(shell, "ja", found=EVERYTHING)
    assert wait_until(lambda: page2.built, 20)
    page2.rows["words_to_leave_out"].doors["word-lists"].click()
    assert opened == [shell]
    shell.deleteLater()


def test_every_door_a_row_names_has_its_words_and_pending_doors_are_named():
    for row in catalog.ROWS:
        for name in row.door:
            assert name in S.DOORS or name in S.ROW_DOORS.get(row.id, {}), (row.id, name)
    registered = {op.name for op in windows.OPENERS}
    assert set(catalog.pending(registered)) <= set(catalog.PENDING_OPENERS)


# --- the sliced build (B4) --------------------------------------------------------------------------------------------- #
def test_the_page_is_built_in_slices_of_a_few_milliseconds_and_says_ready_once(qapp):
    store = Recorder(ALL_ON)
    page = sp.SettingsPage(SimpleNamespace(settings=store), "ja", found=EVERYTHING)
    page.resize(1100, 700)
    page.show()
    assert page.rows == {} and page.search.isVisibleTo(page) and page.nav["app"].isVisibleTo(page)   # the frame at once
    ready = []
    page.ready.connect(lambda: ready.append(1))
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    assert ready == [1] and len(page.rows) == len(catalog.ROWS)
    assert len(page.slice_ms) >= 10                       # sliced, not one pass
    # each slice stops building at BUILD_MS and shows what it built: the median under the 4 ms step (generous here:
    # the timed figures are taken off the lock, P3.md)
    assert statistics.median(page.slice_ms) <= 3 * sp.SLICE_MS, page.slice_ms
    assert page.built_order == [s.id for s in catalog.SECTIONS]                 # from the top: the view first
    assert store.calls == []


def test_a_reveal_before_the_build_ends_has_its_slab_built_first(qapp):
    store = Recorder(ALL_ON)
    page = sp.SettingsPage(SimpleNamespace(settings=store), "ja", found=EVERYTHING)
    page.resize(1100, 700)
    page.show()
    assert page.reveal("logic.context.max_contexts") is True
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    assert page.built_order[0] == "sentences"
    assert _at_third(page, page.rows["max_contexts"])     # kept in place while the slabs above it were built


@pytest.mark.parametrize("setting", ["full", "reduced"])
def test_a_user_scroll_during_the_build_lets_the_reveal_go(qapp, setting):
    # the reveal aims at its row after each slice until the build ends: a wheel / drag / key is the user's, and wins —
    # its wash ends too (reduced motion holds the wash steady for a second, and the slices kept the washed row in place)
    motion.clock().mode.set_setting(setting)
    store = Recorder(ALL_ON)
    page = sp.SettingsPage(SimpleNamespace(settings=store), "ja", found=EVERYTHING)
    page.resize(1100, 700)
    page.show()
    page.reveal("logic.context.max_contexts")
    assert wait_until(lambda: page._revealed is not None, 20)
    bar = page.scroll.verticalScrollBar()
    bar.triggerAction(bar.SliderAction.SliderToMinimum)
    assert page._revealed is None
    assert wait_until(lambda: page.built, 20)
    assert bar.value() == 0                               # never pulled back to the row
    assert store.calls == []


# --- contrast (S5), tooltips, wiring, keyboard ------------------------------------------------------------------------ #
@pytest.mark.parametrize("role", sorted(theme.SETTINGS_PAGE_GROUNDS))
def test_every_text_role_of_the_page_clears_its_floor_where_it_stands(role):
    c = theme.colours()
    floor = 7.0 if role in theme.SETTINGS_CHOSEN_ROLES else 4.5
    for ground in theme.SETTINGS_PAGE_GROUNDS[role]:
        assert theme.contrast(c[theme.SETTINGS_TEXT[role]], c[ground]) >= floor, (role, ground)


def test_the_page_paints_each_text_in_its_proven_role(qapp):
    page, store = make_page(ALL_ON, "ja")
    c = theme.colours()

    def ink(widget, role=QPalette.ColorRole.WindowText):
        widget.ensurePolished()
        return widget.palette().color(role).name()
    t = {role: c[name][:7] for role, name in theme.SETTINGS_TEXT.items()}
    assert ink(page.rows["names_kanji"].label) == t["label"]
    assert ink(page.rows["names_kanji"].help) == t["help"]
    assert ink(page.rows["anki_sync_auto"].label) == t["sub-label"]
    assert ink(page.rows["names_katakana"].group) == t["group"]
    assert ink(page.nothing) == t["hint"]
    assert ink(page.search.edit, QPalette.ColorRole.Text) == t["search"]
    assert ink(page.search.edit, QPalette.ColorRole.PlaceholderText) == t["placeholder"]
    assert ink(page.slabs["level"].more, QPalette.ColorRole.ButtonText) == t["more"]
    unlit = next(b for s, b in page.nav.items() if not b.isChecked() and b.isVisibleTo(page))
    assert ink(unlit, QPalette.ColorRole.ButtonText) == t["nav-unlit"]
    # the stylesheet names the greyed role for a disabled row's words
    sheet = style.stylesheet("night", "M")
    assert f"color: {c[theme.SETTINGS_TEXT['greyed']]}" in sheet
    view = page.rows["names_kanji"]
    view.setEnabled(False)
    assert ink(view.label, QPalette.ColorRole.WindowText) in (t["greyed"], t["label"])


def test_every_button_and_toggle_has_a_tooltip_and_the_page_is_wired(qapp):
    from tests.qt.test_wiring import problems
    page, store = make_page(ALL_ON, "ja")
    found, n = problems(page)
    assert found == [] and n > 25
    for view in page.rows.values():
        for control in view.controls:
            if isinstance(control, (sc.Toggle, sc.Choice, sc.Tablets, sc.LevelSlider, sc.Select)):
                assert control.toolTip(), view.row.id
            assert control.accessibleName() or isinstance(control, sc.Range), view.row.id


def test_tab_reaches_the_search_the_nav_and_every_control(qapp):
    page, store = make_page(ALL_ON, "ja")
    open_all_folds(page)
    chain, w = [], page.nextInFocusChain()
    while w is not page and len(chain) < 2000:
        if (w.focusPolicy() & Qt.FocusPolicy.TabFocus) and w.isVisibleTo(page) and w.isEnabled():
            chain.append(w)
        w = w.nextInFocusChain()
    reached = set(chain)
    assert page.search.edit in reached
    assert {b for b in page.nav.values() if b.isVisibleTo(page)} <= reached
    for view in shown_views(page):
        for control in view.controls:
            target = control.focusProxy() or control
            if isinstance(control, sc.Range):
                target = control.low.edit
            assert target in reached or (target.focusProxy() in reached), view.row.id


def test_a_live_text_size_restyles_the_page_and_its_controls(qapp):
    page, store = make_page(ALL_ON, "ja")
    field = page.rows["split_length"].controls[0]
    style.apply(QApplication.instance(), "night", "L", "ja")
    page.restyle()
    assert page.nav_panel.width() == round(theme.size("settings-nav", "L"))
    assert field.edit.width() == round(theme.size("settings-num-w", "L"))
    assert page.search.height() == round(theme.size("settings-search-h", "L"))
    assert store.calls == []


def test_custom_rows_lay_out_an_empty_slot_their_owner_fills(qapp):
    page, store = make_page(ALL_ON, "ja")
    for row in catalog.ROWS:
        if row.kind in sp.PLACEHOLDER_KINDS:
            slot = page.custom_row(row.id)
            assert slot.layout() is not None and slot.parentWidget() is page.rows[row.id].slot
    with pytest.raises(KeyError):
        page.custom_row("names_kanji")
    view = page.rows["version"]
    assert view.label.text() != "" and "{" not in view.label.text()        # the version filled in
    assert not page.rows["new_cards_a_day"].help.isVisibleTo(page)         # its deck: P9's to say


def test_every_other_shown_section_is_tinted(qapp):
    page, store = make_page(ALL_ON, "ja")
    shown = [page.slabs[s.id] for s in catalog.SECTIONS if page.slabs[s.id].isVisibleTo(page)]
    assert [s.property("tint") for s in shown] == ["true" if i % 2 else "false" for i in range(len(shown))]
    store.outside({"enable_junban": False})               # Backfill leaves: the tints follow what shows
    shown = [page.slabs[s.id] for s in catalog.SECTIONS if page.slabs[s.id].isVisibleTo(page)]
    assert [s.property("tint") for s in shown] == ["true" if i % 2 else "false" for i in range(len(shown))]


def test_the_nav_lights_the_section_in_view_and_a_click_goes_there(qapp):
    page, store = make_page(ALL_ON, "ja")
    assert page.nav["setup"].isChecked()
    page.nav["sentences"].click()
    assert page.nav["sentences"].isChecked()
    vp = page.scroll.viewport()
    assert abs(page.slabs["sentences"].mapTo(vp, QPoint(0, 0)).y()) <= round(theme.SPACING["settings-search-gap"] *
                                                                           theme.text_factor("M")) + 1
