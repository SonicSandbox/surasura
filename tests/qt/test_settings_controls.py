"""The Settings page's controls (W3.3 P2; the foundation brief §7, §8; RUNBOOK P2's row and the intent keeper's B3, N7,
S5, S6).

What a wrong answer would cost: a saved value loaded as if it were a click (a write at load, an animation on every
open); a typed number that commits "3" on the way to "300" (Connect would shelve cards the user never meant to: B3); a
wheel that changes a field the page was only scrolling past; a vein or a gem that moves when motion is reduced or the
captures are frozen; a toggle whose light blinks off as fast as it came; a slider gem that lands between two levels, or
rises back after it lands; grey text under the contrast floor on either slab (Sonic: "Readability is critical here").
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QFocusEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app import theme, word_selection
from app.qt import freeze, motion, style
from app.qt import settings_controls as sc
from tests.qt.pixels import count, rgb_array

BANDS = [(b, word_selection.band_label(b)) for b in word_selection.BANDS_ORDER]
ROAD = [("anki", "Anki"), ("import", "Import a list")]
MINE = [("list", "Your list", "the words on your list, in its order"),
        ("unknown", "Every unknown word", "any word you don't know yet"),
        ("i1", "Only i+1", "a word whose sentence holds no other unknown")]
KNOWN_FROM = [("suspended", "suspended"), ("marked", "marked"), ("flag1", "flag 1"), ("flag2", "flag 2")]
FOLDERS = ["E:\\アニメ\\ぼっち・ざ・ろっく！", "D:\\動画\\日本語"]
LOOKS = [("dark", "Dark"), ("paper", "Paper"), ("sepia", "Sepia"), ("night", "Night"), ("contrast", "High contrast")]
TIP, NAME = "Where your known words come from", "Known words source"


@pytest.fixture
def clock(qapp):
    """The clock on test time, motion unfrozen and Full; put back afterwards (as test_motion's)."""
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


def shown(w, width=None):
    hint = w.sizeHint()
    w.resize(width or hint.width(), hint.height() if not w.hasHeightForWidth() else w.heightForWidth(width or
                                                                                                     hint.width()))
    w.show()
    QApplication.processEvents()
    return w


def spy(w):
    got = []
    w.changed.connect(got.append)
    return got


def click(w, point):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPointF(point).toPoint())


def mouse(w, kind, x, y, buttons=Qt.MouseButton.LeftButton):
    pos = QPointF(x, y)
    button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    QApplication.sendEvent(w, QMouseEvent(kind, pos, QPointF(w.mapToGlobal(pos.toPoint())), button, buttons,
                                          Qt.KeyboardModifier.NoModifier))


def key(w, k):
    QTest.keyClick(w, k)


# --- every control: its tooltip, its name, its focus --------------------------------------------------------------- #
FACTORIES = {
    "choice": lambda: sc.Choice(ROAD, tooltip=TIP, name=NAME),
    "cards": lambda: sc.Cards(MINE, tooltip=TIP, name=NAME),
    "toggle": lambda: sc.Toggle(tooltip=TIP, name=NAME),
    "tablets": lambda: sc.Tablets(KNOWN_FROM, tooltip=TIP, name=NAME),
    "list": lambda: sc.Tablets(value=FOLDERS, on_add=lambda: None, tooltip=TIP, name=NAME),
    "slider": lambda: sc.LevelSlider(BANDS, tooltip=TIP, name=NAME),
    "select": lambda: sc.Select(LOOKS, tooltip=TIP, name=NAME),
}


@pytest.mark.parametrize("kind", sorted(FACTORIES))
def test_a_painted_control_carries_its_tooltip_and_name_and_is_one_tab_stop(qapp, kind):
    w = FACTORIES[kind]()
    assert w.toolTip() == TIP and w.accessibleName() == NAME
    assert w.focusPolicy() == Qt.FocusPolicy.TabFocus        # a click leaves no ring and never scrolls the page


def test_the_fields_take_a_click_and_carry_their_tip_and_name_on_the_line_itself(qapp):
    for w in (sc.NumberField(0, 1000, 40, tooltip=TIP, name=NAME), sc.TextField("自分", tooltip=TIP, name=NAME)):
        assert w.edit.focusPolicy() == Qt.FocusPolicy.StrongFocus and w.focusProxy() is w.edit
        assert w.edit.toolTip() == TIP and w.edit.accessibleName() == NAME     # the bubble reads the widget under the hand
    door = sc.Door("Anki…", tooltip=TIP)
    assert door.focusPolicy() == Qt.FocusPolicy.TabFocus and door.toolTip() == TIP and door.accessibleName() == "Anki…"


# --- one or the other ----------------------------------------------------------------------------------------------- #
def test_a_choice_loads_without_a_signal_and_a_click_says_its_value_once(qapp):
    c = shown(sc.Choice(ROAD))
    got = spy(c)
    c.set_value("import")
    assert c.value() == "import" and got == [] and motion.clock().active == []
    click(c, c._rects()[0].center())
    assert got == ["anki"] and c.value() == "anki"
    click(c, c._rects()[0].center())                        # the chosen one again: nothing to say
    assert got == ["anki"]
    with pytest.raises(ValueError):
        c.set_value("neither")


def test_a_choice_arrows_move_and_space_or_enter_chooses(qapp):
    c = shown(sc.Choice([("follow", "Follow Windows"), ("full", "Full"), ("reduced", "Reduced")]))
    got = spy(c)
    key(c, Qt.Key.Key_Right)
    key(c, Qt.Key.Key_Right)
    assert got == []                                        # arrows only move
    key(c, Qt.Key.Key_Space)
    assert got == ["reduced"]
    key(c, Qt.Key.Key_Home)
    key(c, Qt.Key.Key_Return)
    assert got == ["reduced", "follow"]


def test_the_vein_travels_on_the_clock_leading_end_first(clock):
    c = shown(sc.Choice([("follow", "Follow Windows"), ("full", "Full"), ("reduced", "Reduced")]))
    start, end = c._rest(0), c._rest(2)
    click(c, c._rects()[2].center())
    assert c.vein() == start                                # nothing moves before the clock's frame
    clock.advance(48)
    a, b = c.vein()
    lead, trail = (b - start[1]) / (end[1] - start[1]), (a - start[0]) / (end[0] - start[0])
    assert 0 < trail < lead < 1                             # moving right: the right end there first
    clock.advance(theme.SETTINGS_MOTION["vein-travel"])
    assert c.vein() == end and c._vein.span is None and clock.active == []


@pytest.mark.parametrize("how", ["reduced", "frozen"])
def test_the_vein_jumps_under_reduced_motion_and_the_freeze_switch(clock, how):
    if how == "reduced":
        clock.mode.set_setting("reduced")
    else:
        freeze.set_frozen(True)
    c = shown(sc.Choice(ROAD))
    click(c, c._rects()[1].center())
    assert c.vein() == c._rest(1) and c._vein.span is None and clock.active == []


def test_the_chosen_option_wears_the_vein_and_the_rest_sit_in_the_cut(qapp):
    c = shown(sc.Choice(ROAD))
    arr = rgb_array(c.grab())
    assert count(arr, theme.colours()["cut"]) > 0.25 * arr.shape[0] * arr.shape[1]
    row = round(c._vein_rect(c.vein()).center().y())
    lit = arr[row, round(c._rects()[0].center().x())]
    dark = arr[row, round(c._rects()[1].center().x())]
    assert max(lit) > 120 and max(dark) < 40                 # the iris under the chosen one only


def test_cards_choose_by_click_and_keyboard_and_their_vein_runs_down_the_left(clock):
    c = shown(sc.Cards(MINE, value="list"))
    got = spy(c)
    key(c, Qt.Key.Key_Down)
    key(c, Qt.Key.Key_Down)
    key(c, Qt.Key.Key_Enter)
    assert got == ["i1"]
    clock.advance(theme.SETTINGS_MOTION["vein-travel"])
    r = c._rects()[2]
    assert r.top() < c.vein()[0] < c.vein()[1] < r.bottom()
    click(c, c._rects()[1].center())
    assert got == ["i1", "unknown"]
    c.set_value("list")
    assert got == ["i1", "unknown"]


# --- on or off ------------------------------------------------------------------------------------------------------ #
def test_a_toggle_loads_without_a_signal_or_motion_and_space_toggles(clock):
    t = shown(sc.Toggle())
    got = spy(t)
    t.set_value(True)
    assert got == [] and clock.active == [] and t.position() == (1.0, 1.0)
    key(t, Qt.Key.Key_Space)
    assert got == [False]
    click(t, t.rect().center())
    assert got == [False, True]
    assert t.size().width() >= 40 and t.size().height() >= 22             # the lead's floor at Medium


def test_the_toggles_light_comes_up_faster_than_it_leaves(clock):
    t = shown(sc.Toggle())
    click(t, t.rect().center())
    clock.advance(theme.FAST)
    k, light = t.position()
    assert light == 1.0 and 0 < k < 1                       # lit at once; the gem still sliding
    clock.advance(theme.SLOW)
    assert t.position() == (1.0, 1.0)
    click(t, t.rect().center())
    clock.advance(theme.FAST)
    assert 0 < t.position()[1] < 1                          # leaving, more slowly
    clock.advance(theme.SLOW - theme.FAST)
    assert t.position() == (0.0, 0.0) and clock.active == []


@pytest.mark.parametrize("how", ["reduced", "frozen"])
def test_the_toggles_gem_jumps_under_reduced_motion_and_the_freeze_switch(clock, how):
    if how == "reduced":
        clock.mode.set_setting("reduced")
    else:
        freeze.set_frozen(True)
    t = shown(sc.Toggle())
    click(t, t.rect().center())
    assert t.position() == (1.0, 1.0) and clock.active == []


def test_a_toggle_is_easy_to_see_at_rest_in_both_states(qapp):
    c = theme.colours()
    t = shown(sc.Toggle())
    off = rgb_array(t.grab())
    t.set_value(True)
    on = rgb_array(t.grab())
    assert count(off, c["toggle-gem-off"]) >= 20 and count(off, c["gem-sapphire"]) == 0
    assert count(on, c["gem-sapphire"]) >= 20 and count(on, c["toggle-gem-off"]) == 0
    # at a glance: off, the dark gem on the left and an unlit floor; on, the lit gem on the right and the floor lit
    third = off.shape[1] // 3
    assert count(off[:, :third], c["toggle-gem-off"]) >= 10 and count(off[:, -third:], c["toggle-gem-off"]) == 0
    assert count(on[:, -third:], c["gem-sapphire"]) >= 10 and count(on[:, :third], c["gem-sapphire"]) == 0
    assert count(on, c["toggle-lit"]) >= 10 and count(off, c["toggle-lit"]) == 0
    assert count(off, c["toggle-lip"]) >= 10                                # the hewn channel's lit lower lip
    # the gem against its channel: a component's 3:1 in both states
    assert theme.contrast(c["toggle-gem-off"], c["cut"]) >= 3 and theme.contrast(c["gem-sapphire"], c["toggle-lit"]) >= 3


# --- adding --------------------------------------------------------------------------------------------------------- #
def test_tablets_pick_any_number_by_click_and_keyboard(qapp):
    t = shown(sc.Tablets(KNOWN_FROM, value=["marked"]))
    got = spy(t)
    t.set_value(["suspended", "marked"])
    assert got == [] and t.value() == ["suspended", "marked"]
    click(t, t._parts()[2][3].center())
    assert got == [["suspended", "marked", "flag1"]]
    key(t, Qt.Key.Key_Home)
    key(t, Qt.Key.Key_Space)
    assert got[-1] == ["marked", "flag1"]


def test_one_pick_tablets_keep_exactly_one(qapp):
    t = shown(sc.Tablets([("first", "first"), ("mixed", "mixed in"), ("back", "at the back")], multi=False))
    got = spy(t)
    assert t.value() == "first"
    click(t, t._parts()[2][3].center())
    click(t, t._parts()[2][3].center())
    assert got == ["back"] and t.value() == "back"


def test_a_lists_bed_asks_the_page_and_its_items_go_by_cross_or_delete(qapp):
    asked = []
    t = shown(sc.Tablets(value=FOLDERS, on_add=lambda: asked.append(True), add_label="+ folder"), width=900)
    got = spy(t)
    bed = t._parts()[-1]
    assert bed[0] == "bed"
    click(t, bed[3].center())
    assert asked == [True] and got == []                    # the bed asks; nothing changes until the page answers
    assert t.add_item("E:\\ドラマ") and got == [FOLDERS + ["E:\\ドラマ"]]
    assert not t.add_item("E:\\ドラマ") and len(got) == 1   # already there
    click(t, t._parts()[0][4].center())                     # its ✕
    assert got[-1] == [FOLDERS[1], "E:\\ドラマ"]
    key(t, Qt.Key.Key_Home)
    key(t, Qt.Key.Key_Delete)
    assert got[-1] == ["E:\\ドラマ"]
    key(t, Qt.Key.Key_End)
    key(t, Qt.Key.Key_Return)                               # Enter on the bed asks again
    assert asked == [True, True]
    t.set_value([])
    assert len(got) == 3 and t.value() == [] and [p[0] for p in t._parts()] == ["bed"]


def test_an_empty_list_is_its_bed_alone_and_tablets_wrap_when_narrow(qapp):
    t = sc.Tablets(value=[], on_add=lambda: None)
    assert [p[0] for p in t._layout(0)] == ["bed"]
    t.set_value(FOLDERS * 3)
    one_line = t.heightForWidth(10000)
    assert t.heightForWidth(120) > one_line                 # wraps rather than running off the slab


# --- the level ------------------------------------------------------------------------------------------------------ #
def test_the_slider_loads_without_a_signal_and_keys_move_it(qapp):
    s = shown(sc.LevelSlider(BANDS, value="rare"), width=640)
    got = spy(s)
    s.set_value("common")
    assert got == [] and s.gem() == (s._at_t(1), 0.0)
    key(s, Qt.Key.Key_Right)
    key(s, Qt.Key.Key_End)
    key(s, Qt.Key.Key_End)
    key(s, Qt.Key.Key_Home)
    key(s, Qt.Key.Key_Left)
    assert got == ["occasional", "native", "core"]


def test_a_click_on_a_chamber_chooses_it(qapp):
    s = shown(sc.LevelSlider(BANDS, value="rare"), width=640)
    got = spy(s)
    click(s, s.chamber(2))
    assert got == ["occasional"] and s.gem() == (s._at_t(2), 0.0)


def test_released_between_two_the_gem_falls_into_the_nearest_and_stops_hard(clock):
    s = shown(sc.LevelSlider(BANDS, value="common"), width=640)
    got = spy(s)
    a, b = s.chamber(3), s.chamber(4)
    x = a.x() + 0.38 * (b.x() - a.x())                      # nearer 3, far enough not to be held back
    mouse(s, QEvent.Type.MouseButtonPress, s.chamber(1).x(), a.y())
    clock.advance(16)
    assert 0 < s.gem()[1] < 1                               # pressed, it lifts
    clock.advance(theme.SETTINGS_MOTION["slider-lift"])
    assert s.gem()[1] == pytest.approx(1.0)
    mouse(s, QEvent.Type.MouseMove, x, a.y())
    clock.advance(300)
    assert s.gem()[0] == pytest.approx(s._t_of(x), abs=0.01)    # held, it glides after the hand
    mouse(s, QEvent.Type.MouseButtonRelease, x, a.y(), Qt.MouseButton.NoButton)
    lifts = []
    for _ in range(30):
        clock.advance(8)
        lifts.append(s.gem()[1])
    assert all(later <= earlier for earlier, later in zip(lifts, lifts[1:]))   # never rising back
    assert s.gem() == (s._at_t(3), 0.0) and s.value() == "uncommon" and got == ["uncommon"]
    assert clock.active == []                               # stopped hard: nothing left moving


def test_gap2_the_slider_chooses_at_the_release_and_its_glide_and_fall_are_a_look_only(clock):
    """Gap 2 (M4.1 P3): the band was chosen (and saved) only once the gem had glided and fallen in, up to ~205 ms
    after the release. Now at the release: the value, its signal, its description — the gem still settling."""
    s = shown(sc.LevelSlider(BANDS, value="common"), width=640)
    got = spy(s)
    a, b = s.chamber(3), s.chamber(4)
    x = a.x() + 0.38 * (b.x() - a.x())
    mouse(s, QEvent.Type.MouseButtonPress, s.chamber(1).x(), a.y())
    clock.advance(theme.SETTINGS_MOTION["slider-lift"])
    mouse(s, QEvent.Type.MouseMove, x, a.y())
    clock.advance(300)
    mouse(s, QEvent.Type.MouseButtonRelease, x, a.y(), Qt.MouseButton.NoButton)
    assert got == ["uncommon"] and s.value() == "uncommon"           # at the release, before any frame
    assert s.accessibleDescription() == BANDS[3][1]
    assert s.busy() and s.gem() != (s._at_t(3), 0.0)                 # the gem still to settle (a shown value waits)
    clock.advance(400)
    assert s.gem() == (s._at_t(3), 0.0) and got == ["uncommon"]      # seated; chosen once
    assert clock.active == []


def test_held_near_a_chamber_the_gem_is_held_back(clock):
    s = shown(sc.LevelSlider(BANDS, value="core"), width=640)
    c = s.chamber(2)
    mouse(s, QEvent.Type.MouseButtonPress, s.chamber(0).x(), c.y())
    mouse(s, QEvent.Type.MouseMove, c.x() + 10, c.y())
    clock.advance(400)
    t = s.gem()[0]
    assert s._at_t(2) < t < s._t_of(c.x() + 10)             # pulled toward the chamber, short of the hand
    mouse(s, QEvent.Type.MouseButtonRelease, c.x() + 10, c.y(), Qt.MouseButton.NoButton)
    clock.advance(400)
    assert s.value() == "occasional"


@pytest.mark.parametrize("how", ["reduced", "frozen"])
def test_the_slider_gem_jumps_under_reduced_motion_and_the_freeze_switch(clock, how):
    if how == "reduced":
        clock.mode.set_setting("reduced")
    else:
        freeze.set_frozen(True)
    s = shown(sc.LevelSlider(BANDS, value="core"), width=640)
    got = spy(s)
    a, b = s.chamber(4), s.chamber(5)
    mouse(s, QEvent.Type.MouseButtonPress, s.chamber(0).x(), a.y())
    mouse(s, QEvent.Type.MouseMove, a.x() + 0.4 * (b.x() - a.x()), a.y())
    mouse(s, QEvent.Type.MouseButtonRelease, a.x() + 0.4 * (b.x() - a.x()), a.y(), Qt.MouseButton.NoButton)
    assert got == ["rare"] and s.gem() == (s._at_t(4), 0.0) and clock.active == []


def test_the_slider_names_every_band_under_its_chamber(qapp):
    s = shown(sc.LevelSlider(BANDS, value="rare"), width=640)
    assert [s._bands[i][1] for i in range(len(BANDS))] == [word_selection.band_label(b) for b in
                                                           word_selection.BANDS_ORDER]
    assert s.accessibleDescription() == "Rare"


# --- the fields (B3: commit on Enter, leaving or a spin step; never while typing; never the same value) ------------ #
def test_typing_3_30_300_then_enter_commits_once_300(qapp):
    f = shown(sc.NumberField(0, 1000, 40))
    got = spy(f)
    f.edit.selectAll()
    QTest.keyClicks(f.edit, "3")
    QTest.keyClicks(f.edit, "0")
    QTest.keyClicks(f.edit, "0")
    assert got == [] and f.value() == 40 and f.edit.text() == "300"
    key(f.edit, Qt.Key.Key_Return)
    assert got == [300] and f.value() == 300
    key(f.edit, Qt.Key.Key_Return)                          # the same value: nothing
    assert got == [300]


def test_a_number_is_clamped_and_invalid_text_reverts_silently(qapp):
    f = shown(sc.NumberField(1, 500, 40, suffix="cards"))
    got = spy(f)
    f.set_value(9999)
    assert f.value() == 500 and got == []                   # loading clamps too, silently
    f.edit.setText("abc")
    key(f.edit, Qt.Key.Key_Enter)
    assert f.edit.text() == "500" and got == []
    f.edit.setText("0")
    key(f.edit, Qt.Key.Key_Enter)
    assert f.value() == 1 and f.edit.text() == "1" and got == [1]


def test_leaving_the_field_commits(qapp):
    f = shown(sc.NumberField(0, 100, 20))
    got = spy(f)
    f.edit.setText("55")
    QApplication.sendEvent(f.edit, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    assert got == [55]


def test_a_spin_step_commits_and_the_wheel_moves_a_field_only_while_it_has_focus(qapp):
    host = QWidget()
    f = sc.NumberField(0, 100, 20, parent=host)
    host.resize(300, 60)
    host.show()
    host.activateWindow()
    QApplication.processEvents()
    got = spy(f)
    wheel = QWheelEvent(QPointF(5, 5), QPointF(f.edit.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    f.clearFocus()
    QApplication.sendEvent(f.edit, wheel)
    assert got == [] and f.value() == 20 and not wheel.isAccepted()     # the page under it scrolls instead
    f.edit.setFocus()
    QApplication.processEvents()
    assert f.edit.hasFocus()
    QApplication.sendEvent(f.edit, wheel)
    assert got == [21]
    key(f.edit, Qt.Key.Key_Down)
    key(f.edit, Qt.Key.Key_Down)
    assert got == [21, 20, 19]


def test_a_range_carries_its_other_end_and_says_both_once(qapp):
    r = shown(sc.Range(10, 400, (20, 120), suffix="characters"))
    got = spy(r)
    r.set_value((30, 90))
    assert got == [] and r.value() == (30, 90)
    r.low.edit.setText("150")
    key(r.low.edit, Qt.Key.Key_Return)
    assert got == [(150, 150)] and r.value() == (150, 150)
    r.high.edit.setText("40")
    key(r.high.edit, Qt.Key.Key_Return)
    assert got == [(150, 150), (40, 40)]


def test_a_text_field_commits_on_enter_or_leaving_and_only_a_change(qapp):
    t = shown(sc.TextField("自分のカード", placeholder="a tag"))
    got = spy(t)
    t.set_value("自分")
    assert got == [] and t.edit.text() == "自分"
    t.edit.selectAll()
    QTest.keyClicks(t.edit, "mine")
    assert got == []
    key(t.edit, Qt.Key.Key_Return)
    assert got == ["mine"]
    QApplication.sendEvent(t.edit, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    assert got == ["mine"]
    t.edit.setText("  mined ")
    QApplication.sendEvent(t.edit, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    assert got == ["mine", "mined"]


# --- a long one-of, the door, the status mark ----------------------------------------------------------------------- #
def test_a_select_opens_its_menu_from_the_keyboard_and_a_pick_says_it_once(qapp):
    s = shown(sc.Select(LOOKS, value="dark"))
    got = spy(s)
    s.set_value("sepia")
    assert got == [] and s.value() == "sepia" and s._actions[2].isChecked()
    key(s, Qt.Key.Key_Down)
    assert s.menu.isVisible()
    s.menu.close()
    s._actions[4].trigger()
    s._actions[4].trigger()
    assert got == ["contrast"] and s.accessibleDescription() == "High contrast"
    for action in s._actions:                               # the wiring check's rule: every action connected
        assert action.receivers(action.triggered) > 0


def test_a_door_is_the_one_plain_house_button(qapp):
    """Settings' doors are all one plain kind: never an iris-filled button (the lead's round, 2026-10-15)."""
    clicks = []
    d = shown(sc.Door("Speech settings…", tooltip="Open Speech's window"))
    d.clicked.connect(lambda: clicks.append(True))
    d.click()
    assert d.property("kind") is None and clicks == [True]
    with pytest.raises(TypeError):
        sc.Door("Anki…", kind="primary")
    arr = rgb_array(d.grab())
    assert count(arr, theme.colours()["raised"]) > 0.3 * arr.shape[0] * arr.shape[1]   # the plain button's face
    for _pos, colour in theme.IRIS["night"]:
        assert count(arr, colour, 6) == 0


def test_the_status_mark_always_shows_its_word_beside_the_emerald(qapp):
    c = theme.colours()
    m = shown(sc.StatusMark(True, "connected", name="Anki"))
    lit = rgb_array(m.grab())
    assert m.words() == "connected" and m.accessibleName() == "Anki: connected"
    assert count(lit, c["emerald"]) >= 10
    m.set_value(False, "not running")
    m.resize(m.sizeHint())
    dark = rgb_array(m.grab())
    assert m.words() == "not running" and "not running" in m.accessibleName()
    assert count(dark, c["emerald-dark"]) >= 10 and count(dark, c["emerald"]) == 0


# --- the compact sizes, × the text size ----------------------------------------------------------------------------- #
@pytest.mark.parametrize("text_size", ["S", "M", "L"])
def test_the_controls_take_the_mocks_compact_sizes_times_the_text_size(qapp, text_size):
    style.apply(qapp, "night", text_size, "ja")
    f = theme.text_factor(text_size)
    assert sc.Toggle().sizeHint() == sc.QSize(round(36 * f), round(20 * f))
    assert sc.NumberField(0, 9).edit.width() == round(64 * f)
    assert sc.Tablets(KNOWN_FROM).sizeHint().height() == round(26 * f)
    choice = sc.Choice(ROAD)
    r = choice._rects()[0]
    from PyQt6.QtGui import QFontMetricsF
    fm = QFontMetricsF(sc._font("segmented"))
    assert r.height() == pytest.approx(fm.height() + 2 * 5 * f, abs=0.01)
    assert r.width() == pytest.approx(fm.horizontalAdvance("Anki") + 2 * 11 * f, abs=1)


def test_a_live_text_size_resizes_a_field_when_the_page_restyles_it(qapp):
    n, c = sc.NumberField(0, 9), sc.Choice(ROAD)
    before = c.sizeHint()
    style.apply(qapp, "night", "L", "ja")
    n.restyle()
    c.restyle()
    assert n.edit.width() == round(64 * theme.text_factor("L")) and c.sizeHint().height() > before.height()


# --- contrast (Sonic: "Readability is critical here"): ≥ 4.5 unchosen, ≥ 7 chosen, on both slabs and in the cuts ----- #
SLABS = theme.SETTINGS_GROUNDS
FLOORS = theme.SETTINGS_FLOORS
# (control, state, text colour, the grounds it is drawn on, chosen?)
TEXTS = [
    ("choice", "unchosen", "ink-dim", FLOORS, False), ("choice", "chosen", "ink", FLOORS, True),
    ("choice", "greyed", "settings-ink-greyed", FLOORS, False),
    ("cards", "label unchosen", "ink-dim", FLOORS, False), ("cards", "label chosen", "ink", FLOORS, True),
    ("cards", "line unchosen", "ink-dim", FLOORS, False),
    ("cards", "line chosen", "settings-ink-chosen-line", FLOORS, True),
    ("tablets", "off", "ink-dim", ("settings-tablet",), False), ("tablets", "on", "ink", ("settings-tablet-on",), True),
    ("tablets", "greyed", "settings-ink-greyed", ("settings-tablet",), False),
    ("tablets", "list item", "ink", ("settings-tablet-on",), True),
    ("tablets", "its ✕", "settings-ink-chosen-line", ("settings-tablet-on",), False),
    ("tablets", "the bed", "ink-dim", FLOORS, False),
    ("slider", "a band's name", "ink-dim", SLABS, False), ("slider", "the chosen band", "ink", SLABS, True),
    ("slider", "greyed", "settings-ink-greyed", SLABS, False),
    ("number", "its value", "ink", FLOORS, True), ("number", "greyed", "settings-ink-greyed", FLOORS, False),
    ("number", "its words beside", "ink-dim", SLABS, False), ("text", "placeholder", "ink-dim", FLOORS, False),
    ("select", "its choice", "ink", FLOORS, True), ("select", "its chevron", "ink-dim", FLOORS, False),
    ("select", "a menu item", "ink", ("overlay", "overlay-hover"), True),
    ("door", "its words", "ink", ("raised",), True),
    ("status", "connected", "ink", SLABS, True), ("status", "not connected", "ink-dim", SLABS, False),
]


@pytest.mark.parametrize("control, state, ink, grounds, chosen", TEXTS, ids=[f"{t[0]}-{t[1]}" for t in TEXTS])
def test_every_text_a_control_shows_clears_the_floor(control, state, ink, grounds, chosen):
    c = theme.colours()
    floor = 7.0 if chosen else 4.5
    for ground in grounds:
        assert theme.contrast(c[ink], c[ground]) >= floor, (control, state, ground, theme.contrast(c[ink], c[ground]))


def test_the_controls_paint_their_text_in_the_proven_roles():
    # the table above proves the roles: the painters must read these, not others
    t = theme.SETTINGS_TEXT
    assert (t["chosen"], t["unchosen"], t["greyed"], t["chosen-line"], t["value"]) == (
        "ink", "ink-dim", "settings-ink-greyed", "settings-ink-chosen-line", "ink")


@pytest.mark.parametrize("role", sorted(theme.SETTINGS_TEXT))
def test_every_text_role_of_the_page_clears_the_floor_on_both_slabs(role):
    """S5: P3 proves the page's roles in place; here the colours themselves, on the slab and the tinted slab."""
    c = theme.colours()
    floor = 7.0 if role in theme.SETTINGS_CHOSEN_ROLES else 4.5
    for ground in SLABS:
        assert theme.contrast(c[theme.SETTINGS_TEXT[role]], c[ground]) >= floor, (role, ground)


def test_the_surfaces_keep_the_briefs_first_rule():
    """Nearer is lighter: the tint and a tablet lighter than the slab they lie on; a cut darker than either slab."""
    c = theme.colours()

    def lum(name):
        r, g, b, _ = theme.parse(c[name])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    assert lum("slab") < lum("settings-slab-tint") < lum("settings-tablet") < lum("settings-tablet-on")
    for floor in FLOORS:
        assert lum(floor) < lum("slab")
    assert lum("cut") < lum("toggle-lit") and lum("cut") < lum("slider-glow")


def test_the_contrast_figures():
    """The figures, pinned (the result file quotes them)."""
    c = theme.colours()
    got = {(ink, g): round(theme.contrast(c[ink], c[g]), 2)
           for ink in ("ink", "ink-dim", "settings-ink-greyed", "settings-ink-chosen-line")
           for g in ("slab", "settings-slab-tint", "cut")}
    assert got[("ink-dim", "settings-slab-tint")] == 5.17 and got[("ink", "cut")] == 16.97
    assert min(got.values()) >= 4.5


def test_at_its_size_no_two_band_names_meet(qapp):
    from PyQt6.QtGui import QFontMetricsF
    s = shown(sc.LevelSlider(BANDS, value="core"))
    fm = QFontMetricsF(sc._font("row-sub"))
    spans = []
    for i, (_k, name) in enumerate(s._bands):
        w = fm.horizontalAdvance(name)
        x = min(max(0.0, s.chamber(i).x() - w / 2), s.width() - w)
        spans.append((x, x + w))
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:]))


# --- the gems are rough cut stones: never a circle, a pearl, a regular hexagon or an octagon (brief §8) ------------- #
@pytest.mark.parametrize("cut, sides", [("toggle", 7), ("slider", 8)])
def test_a_gem_is_an_uneven_polygon_of_straight_sides(qapp, cut, sides):
    import math
    path = sc.gem_path(QPointF(50, 50), 40, 36, cut)
    kinds = {path.elementAt(i).type for i in range(path.elementCount())}
    assert kinds <= {sc.QPainterPath.ElementType.MoveToElement, sc.QPainterPath.ElementType.LineToElement}  # no curves
    pts = sc.gem_corners(QPointF(50, 50), 40, 36, cut)
    assert len(pts) == sides >= 6
    lengths = [math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in zip(pts, pts[1:] + pts[:1])]
    reach = [math.dist((p.x() / 40, p.y() / 36), (50 / 40, 50 / 36)) for p in pts]
    assert max(lengths) / min(lengths) > 1.15 and max(reach) / min(reach) > 1.1      # uneven: not regular


def test_the_sliders_gem_is_heavier_than_the_toggles(qapp):
    def area(cut, w, h):
        pts = sc.gem_corners(QPointF(0, 0), w, h, cut)
        return abs(sum(a.x() * b.y() - b.x() * a.y() for a, b in zip(pts, pts[1:] + pts[:1]))) / 2
    t = shown(sc.Toggle())
    side = t.height() - 6 - 1
    s_gem = theme.size("settings-gem")
    assert area("slider", s_gem * 1.2, s_gem * 1.05) > area("toggle", side * 1.15, side)
    assert len(sc.ROUGH["slider"]) > len(sc.ROUGH["toggle"])


def test_a_gem_shows_its_two_facet_planes(qapp):
    c = theme.colours()
    t = shown(sc.Toggle(True))
    arr = rgb_array(t.grab())
    for name in ("gem-sapphire", "gem-sapphire-facet", "gem-sapphire-shade"):
        assert count(arr, name in c and c[name], 3) >= 2, name
