"""The Level menu (W3.1b; the RUNBOOK `3.0/W3.1b-level-menu`): the header's level ▾ pop as the redesign's brief draws it
— *Level* ? and *Automatic*'s toggle, Settings' level slider (one name), words · % · how often, Generate and a gear,
*Open your journey*.

What a wrong answer would cost:
  * a band picked in the pop that writes nothing (Sonic moves the slider and his list never changes), writes twice, or
    leaves Automatic on so the next automatic look moves it straight back;
  * the pop *showing* the automatic band written into settings.json — a look that silently turns Automatic's choice into
    a hand pick (S2);
  * a readout read on every start (the token store opened for a pop nobody opened) or never again after the library grew;
  * a ? or gear that opens nothing, or leaves the pop open over Settings;
  * a pop that runs off the window at Large text, or a slider that glides under Reduced motion.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import word_selection
from app.qt import frame, settings_live, strings, style
from tests.qt.conftest import wait_until
from tests.qt.test_frame import test_clock  # noqa: F401  (the motion tests' clock on test time)

# Numbers as `word_selection.band_previews` gives them (a Japanese library of a few hundred episodes)
PREVIEWS = {
    "core": {"word_count": 310, "coverage_percent": 81.2, "hours_between": 0.4},
    "common": {"word_count": 920, "coverage_percent": 88.6, "hours_between": 1.6},
    "occasional": {"word_count": 1840, "coverage_percent": 92.3, "hours_between": 4.2},
    "uncommon": {"word_count": 3125, "coverage_percent": 94.9, "hours_between": 11.0},
    "rare": {"word_count": 5480, "coverage_percent": 96.7, "hours_between": 26.5},
    "very_rare": {"word_count": 9020, "coverage_percent": 98.1, "hours_between": 61.0},
    "native": {"word_count": 14200, "coverage_percent": 99.2, "hours_between": None},
}


@pytest.fixture
def world(qapp, tmp_path):
    from tests.qt.test_jobs_bar import World
    w = World(qapp, logs_folder=str(tmp_path / "logs"))
    yield w
    w.close()


@pytest.fixture
def reads(monkeypatch):
    """`read_previews` stood in for the token store: each call recorded, the numbers above handed back."""
    calls = []

    def read(settings, language):
        calls.append(language)
        return PREVIEWS
    monkeypatch.setattr(settings_live, "read_previews", read)
    return calls


@pytest.fixture
def writes(world, monkeypatch):
    """Every `services.settings.set` call, recorded and passed on."""
    seen = []
    real = world.services.settings.set

    def record(changes, update=None, now=False):
        seen.append(dict(changes))
        return real(changes, update=update, now=now)
    monkeypatch.setattr(world.services.settings, "set", record)
    return seen


def _selection(world):
    return (world.services.settings.get().get("logic") or {}).get("selection") or {}


def _open(world):
    world.d.level.click()
    assert wait_until(world.d.pop.isVisible)


def _rare_by_hand(world):
    world.services.settings.set({"logic.selection.band": "rare", "logic.selection.auto": False}, now=True)
    world.start()
    assert wait_until(lambda: world.d.pop.level == ("rare", False, False, None))


# --- what the pop holds --------------------------------------------------------------------------------------------- #
def test_the_pop_holds_level_automatic_the_slider_the_readout_generate_and_the_journey(world, reads):
    _rare_by_hand(world)
    pop = world.d.pop
    _open(world)
    assert pop.heading.text() == strings.LEVEL_POP_HEADING and pop.auto_word.text() == strings.LEVEL_POP_AUTO_WORD
    assert pop.slider.value() == "rare" and not pop.auto_toggle.value()
    assert pop.isAncestorOf(world.d.generate) and pop.isAncestorOf(world.d.journey) and pop.isAncestorOf(pop.gear)
    assert not hasattr(pop, "band") and not hasattr(pop, "auto")         # the eyebrow and the sentence lines went
    for w in (pop.help, pop.auto_toggle, pop.slider, pop.gear):          # GUI rules: a tooltip on every control
        assert w.toolTip()
    assert wait_until(lambda: pop.read.text() == "≈5,480 words · 96.7% · every 26 h")
    assert "of your content" in pop.read.toolTip()                       # Settings' words in its hover


def test_the_readout_reads_when_the_pop_opens_and_again_only_once_what_it_reads_moved(world, reads):
    _rare_by_hand(world)
    for _ in range(10):
        QApplication.processEvents()
    assert reads == []                                    # nobody opened it: the token store is never opened for it
    _open(world)
    assert wait_until(lambda: len(reads) == 1)
    world.d.pop.close()
    _open(world)
    for _ in range(10):
        QApplication.processEvents()
    assert len(reads) == 1                                # nothing moved: the numbers in hand (S19)
    world.win.bridge.indexed.emit("ja")                   # the index grew while it is open: read again now
    assert wait_until(lambda: len(reads) == 2)
    world.d.pop.close()
    world.services.settings.set({"exclude_single": False})   # a key the numbers read, while it is closed
    for _ in range(10):
        QApplication.processEvents()
    assert len(reads) == 2
    _open(world)
    assert wait_until(lambda: len(reads) == 3)


def test_picking_a_band_never_reads_the_numbers_again(world, reads):
    _rare_by_hand(world)
    _open(world)
    assert wait_until(lambda: len(reads) == 1)
    slider = world.d.pop.slider
    slider.setFocus()
    QTest.keyClick(slider, Qt.Key.Key_Left)
    assert wait_until(lambda: world.d.level.text() == "Uncommon")     # the write landed and the level was read
    for _ in range(10):
        QApplication.processEvents()
    assert len(reads) == 1 and world.d.pop.read.text().startswith("≈3,125 words")


def test_a_library_view_alone_never_marks_the_numbers(world, reads):
    # S19: the window's own drag views, mined cards and reorders change nothing the bands' numbers read
    _rare_by_hand(world)
    _open(world)
    assert wait_until(lambda: len(reads) == 1)
    world.d.pop.close()

    class View:                                            # a view of this language (its rows don't matter here)
        language = world.win.language
    try:
        world.win.show_library(View())
    except AttributeError:
        pass                                               # the pages want a whole view; the mark came first
    assert not world.d.previews_dirty
    _open(world)
    for _ in range(10):
        QApplication.processEvents()
    assert len(reads) == 1


def test_numbers_read_for_a_language_left_meanwhile_are_never_shown(world, monkeypatch):
    _rare_by_hand(world)

    def read(settings, language):
        world.win.language = "zh"                          # the switch lands while the read runs
        return PREVIEWS
    monkeypatch.setattr(settings_live, "read_previews", read)
    _open(world)
    for _ in range(30):
        QApplication.processEvents()
    world.win.language = "ja"
    assert world.d.pop.previews is None and world.d.pop.read.text() == ""


def test_with_no_store_the_readout_stays_empty(world, monkeypatch):
    monkeypatch.setattr(settings_live, "read_previews", lambda settings, language: None)
    _rare_by_hand(world)
    _open(world)
    for _ in range(20):
        QApplication.processEvents()
    assert world.d.pop.read.text() == "" and world.d.pop.read.isHidden()


@pytest.mark.parametrize("preview, words", [
    (PREVIEWS["occasional"], "≈1,840 words · 92.3% · every 4.2 h"),
    (PREVIEWS["core"], "≈310 words · 81.2% · every 24 min"),
    (PREVIEWS["very_rare"], "≈9,020 words · 98.1% · every 61 h"),
    (PREVIEWS["native"], "≈14,200 words · 99.2%"),
    ({"word_count": 40, "coverage_percent": 50.0, "hours_between": 0.001}, "≈40 words · 50.0% · every 1 min"),
    (None, ""),
])
def test_the_readout_says_words_percent_and_how_often(preview, words):
    assert frame.level_readout(preview) == words


# --- what it writes ------------------------------------------------------------------------------------------------- #
def test_a_band_picked_writes_the_band_and_automatic_off_once(world, reads, writes):
    _rare_by_hand(world)
    _open(world)
    before = len(writes)
    slider = world.d.pop.slider
    slider.setFocus()
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert wait_until(lambda: _selection(world).get("band") == "very_rare")
    assert writes[-1] == {"logic.selection.band": "very_rare"}        # Automatic was off already: only the band
    assert len(writes) == before + 1
    assert wait_until(lambda: world.d.level.text() == "Very Rare")     # the ▾ reads it again from the write
    assert world.d.pop.read.text().startswith("≈9,020 words")          # the numbers at the lock


def test_the_band_already_written_writes_nothing(world, writes):
    _rare_by_hand(world)
    before = len(writes)
    world.win._level_write("rare")
    world.win._level_write({"logic.selection.auto": False})
    assert len(writes) == before


def test_a_hand_pick_while_automatic_is_on_turns_it_off(world, writes):
    world.services.settings.set({"logic.selection.band": "common", "logic.selection.auto": True}, now=True)
    world.start()
    assert wait_until(lambda: world.d.pop.level is not None and world.d.pop.level[1])
    world.win._level_write("uncommon")
    assert wait_until(lambda: _selection(world).get("auto") is False)
    assert writes[-1] == {"logic.selection.band": "uncommon", "logic.selection.auto": False}
    assert wait_until(lambda: not world.d.pop.auto_toggle.value())


def test_the_toggle_turns_automatic_on_and_off(world, writes):
    _rare_by_hand(world)
    _open(world)
    toggle = world.d.pop.auto_toggle
    toggle.setFocus()
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert wait_until(lambda: _selection(world).get("auto") is True)
    assert writes[-1] == {"logic.selection.auto": True}
    assert wait_until(lambda: world.d.level.text().startswith("Auto"))
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert wait_until(lambda: _selection(world).get("auto") is False)


def test_turning_automatic_off_in_the_pop_keeps_the_band_it_was_showing(world, writes):
    # B1 (2.x's D3): Automatic showed Uncommon over a written Common; off, Uncommon is written with it in one set
    world.services.settings.set({"logic.selection.band": "common", "logic.selection.auto": True}, now=True)
    world.start()
    world.d.pop.set_level("uncommon", True)               # as `automation.level` reads it over the store
    world.win._level_automatic(False)
    assert writes[-1] == {"logic.selection.auto": False, "logic.selection.band": "uncommon"}


def test_turning_automatic_off_before_its_band_is_read_keeps_the_written_band(world, writes):
    world.services.settings.set({"logic.selection.band": "common", "logic.selection.auto": True}, now=True)
    world.start()
    assert wait_until(lambda: world.d.pop.level == ("common", True, True, None))   # waiting: no store yet
    assert world.d.pop.read.text() == strings.LEVEL_POP_AUTO_WAITING             # never the written band's numbers
    assert not world.d.pop.slider._named                                          # nor its name
    world.win._level_automatic(False)
    assert writes[-1] == {"logic.selection.auto": False}


def test_in_coverage_mode_the_slider_is_greyed_and_the_readout_names_the_target(world, reads):
    world.services.settings.set({"strategy": "coverage", "target_coverage": 95}, now=True)
    world.start()
    assert wait_until(lambda: world.d.pop.coverage == 95)
    _open(world)
    assert not world.d.pop.slider.isEnabled()
    assert world.d.pop.read.text() == strings.LEVEL_POP_COVERAGE.format(n=95)
    world.services.settings.set({"strategy": "freq"})
    assert wait_until(lambda: world.d.pop.slider.isEnabled())


def test_showing_the_automatic_band_is_never_a_pick(world, writes):
    _rare_by_hand(world)
    picked = []
    world.d.pop.picked.connect(picked.append)
    world.d.pop.automatic.connect(picked.append)
    before = len(writes)
    world.d.pop.set_level("common", True)                         # Automatic's band, as `automation.level` reads it
    assert world.d.pop.slider.value() == "common" and world.d.pop.auto_toggle.value()
    assert world.d.pop.set_level("common", True) is False           # the same again: nothing repainted
    world.d.pop.set_level(None, True)                                    # no band yet: the slider stays where it is
    assert world.d.pop.slider.value() == "common"
    for _ in range(10):
        QApplication.processEvents()
    assert picked == [] and len(writes) == before


def test_a_show_while_the_hand_holds_the_gem_never_drops_the_drag_or_picks(world, writes):
    # adversary S1: a level read landing mid-gesture (indexing, known words) must neither cancel the drag nor send a pick
    _rare_by_hand(world)
    _open(world)
    slider = world.d.pop.slider
    picked = []
    world.d.pop.picked.connect(picked.append)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=slider.chamber(4).toPoint())
    QTest.mouseMove(slider, slider.chamber(2).toPoint())
    world.d.pop.set_level("common", True)                  # a show arrives while the gem is held
    assert picked == [] and slider.busy()
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=slider.chamber(2).toPoint())
    assert wait_until(lambda: picked == ["occasional"])    # the hand's pick, once
    assert world.d.pop.level is None or world.d.pop.level[0] != "common" or slider.value() == "occasional"


def test_a_pick_with_automatic_on_shows_it_off_at_once(world):
    world.services.settings.set({"logic.selection.band": "common", "logic.selection.auto": True}, now=True)
    world.start()
    assert wait_until(lambda: world.d.pop.auto_toggle.value())
    _open(world)
    slider = world.d.pop.slider
    slider.setFocus()
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert not world.d.pop.auto_toggle.value()             # before the write lands (S2)


def test_an_older_level_answer_never_moves_the_slider(world, monkeypatch):
    # adversary S3: two reads in flight; the first (slow) answer lands last and is dropped
    import threading
    _rare_by_hand(world)
    gate = threading.Event()
    answers = iter([("core", False), ("very_rare", False)])

    def level():
        band = next(answers)
        if band[0] == "core":
            gate.wait(5)                                   # the older read is slow
        return band
    monkeypatch.setattr(world.services, "level", level)
    world.win._read_level()
    world.win._read_level()
    assert wait_until(lambda: world.d.pop.level is not None and world.d.pop.level[0] == "very_rare")
    gate.set()
    for _ in range(30):
        QApplication.processEvents()
    assert world.d.pop.slider.value() == "very_rare"


def test_automatic_with_no_numbers_yet_shows_the_written_band(world):
    # `automation.level` gives no band while there is no store: the slider shows the band settings.json holds
    world.services.settings.set({"logic.selection.band": "uncommon", "logic.selection.auto": True}, now=True)
    world.start()
    assert wait_until(lambda: world.d.pop.level == ("uncommon", True, True, None))


# --- the doors ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("door", ["help", "gear"])
def test_the_question_mark_and_the_gear_open_settings_at_the_level_and_close_the_pop(world, monkeypatch, door):
    asked = []
    monkeypatch.setattr(world.win, "open_setting", lambda target: asked.append(target) or True)
    _rare_by_hand(world)
    _open(world)
    getattr(world.d.pop, door).click()
    assert asked == ["level"] and not world.d.pop.isVisible()


def test_esc_and_a_press_outside_still_close_the_new_pop(world):
    _rare_by_hand(world)
    _open(world)
    QTest.keyClick(world.win, Qt.Key.Key_Escape)
    assert not world.d.pop.isVisible()
    _open(world)
    QTest.mouseClick(world.win.centralWidget(), Qt.MouseButton.LeftButton, pos=QPoint(20, 400))
    assert not world.d.pop.isVisible()


# --- motion and room ------------------------------------------------------------------------------------------------ #
def test_under_reduced_motion_the_slider_seats_at_once(world, test_clock):
    test_clock.mode.set_setting("reduced")
    _rare_by_hand(world)
    world.d.level.click()
    test_clock.advance(1000)                                        # the pop's opening, on the test clock
    assert wait_until(world.d.pop.isVisible)
    slider = world.d.pop.slider
    slider.setFocus()
    QTest.keyClick(slider, Qt.Key.Key_Left)
    assert slider.value() == "uncommon"
    test_clock.advance(1)
    t, lift = slider.gem()
    assert t == pytest.approx(slider._at_t(3)) and lift == 0


def test_the_slider_names_only_the_chosen_band(qapp):
    from app.qt import settings_controls as sc
    bands = [(b, word_selection.band_label(b)) for b in word_selection.BANDS_ORDER]
    one = sc.LevelSlider(bands, "rare", one_name=True)
    every = sc.LevelSlider(bands, "rare")
    assert not one.staggered(120) and one.heightForWidth(120) == one.heightForWidth(600)
    assert one.minimumSizeHint().width() < every.minimumSizeHint().width()


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_the_pop_fits_inside_a_narrow_window_at_every_text_size(world, reads, size):
    qapp = QApplication.instance()
    style.apply(qapp, "night", size, "ja")
    try:
        world.win.resize(1024, 640)
        _rare_by_hand(world)
        _open(world)
        assert wait_until(lambda: world.d.pop.read.text() != "")
        pop, parent = world.d.pop, world.win.centralWidget()
        g = pop.geometry()
        assert g.left() >= 0 and g.right() <= parent.width() and g.bottom() <= parent.height()
        assert g.height() >= pop.layout().totalMinimumSize().height()
    finally:
        style.apply(qapp, "night", "M", "ja")
