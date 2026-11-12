"""*Needs you*'s card for videos with no subtitles in the window (Michi-NS, 3.0.1; SPEC no-subs §3, §6): ONE card, a
line per show with its own *Make them from the audio*; the press asks Anki Miner on a worker whether it can listen,
asks once in the window before its speech model is downloaded, then makes the show's subtitles on a worker as one job.

What a wrong answer would cost: a 0.5 GB download started without a yes; the window frozen while Anki Miner listens
(minutes an episode); a second press while one runs starting a second run, or repainting and re-laying the page for
nothing (the work-count: a press that changes nothing paints nothing); a card that never offers the way that's here.
The two worker steps are stood in for: nothing is run.
"""
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, closed, entry_of, settle, world  # noqa: F401  (world: the fixture)


class _Count(QObject):
    """Paint and layout events reaching any widget while installed on the application."""

    def __init__(self):
        super().__init__()
        self.paints = self.layouts = 0

    def eventFilter(self, obj, event):
        if isinstance(obj, QWidget):
            if event.type() == QEvent.Type.Paint:
                self.paints += 1
            elif event.type() == QEvent.Type.LayoutRequest:
                self.layouts += 1
        return False


def _settled(turns=8):
    for _ in range(turns):
        QApplication.processEvents()


@pytest.fixture
def subs(monkeypatch):
    """Two of the seed's episodes waiting for a subtitle, Anki Miner able to make them; the two worker steps stood in
    for (`ready`: the answer `subs_ready` gives; `release`: lets the stand-in make end)."""
    got = {"ready": "ready", "asked": [], "made": [], "release": threading.Event()}
    main = threading.main_thread()

    def waiting(view):
        eps = [(r, e) for r in view.rows for e in r.episodes][:2]
        return eps
    monkeypatch.setattr(service, "no_subs_waiting", waiting)
    monkeypatch.setattr(service, "no_subs_offer", lambda view, settings: {"make": True, "hato": False})
    return got, main


def _wire(ny, got, main):
    def ready(lang, settings):
        got["asked"].append(threading.current_thread() is not main)
        return got["ready"]

    def make(registry, lang, ids, settings, title, install, cancel):
        got["made"].append((threading.current_thread() is not main, tuple(ids), install))
        got["release"].wait(10)
        return {"made": len(ids)}
    ny.subs_ready, ny.make_subs = ready, make


def test_one_card_its_line_offers_make_from_the_audio_with_its_tip(world, subs):
    got, main = subs
    seed, win, writer, ny = world()
    entry = entry_of(ny, service.NO_SUBS)
    assert entry.title == "2 videos have no subtitles yet" and not entry.actions
    b = button(ny, entry.key, "make_from_audio")
    assert b is not None and b.text() == "Make them from the audio" and b.toolTip()


def test_the_press_makes_them_on_a_worker_and_a_second_press_meanwhile_does_and_paints_nothing(world, subs):
    """Why: minutes an episode — never on the window's thread; and a press while one runs is the same press (A-5): no
    second run, no paint, no layout (Sonic's work-count rule: a press that changes nothing paints nothing)."""
    got, main = subs
    seed, win, writer, ny = world()
    _wire(ny, got, main)
    entry = entry_of(ny, service.NO_SUBS)
    b = button(ny, entry.key, "make_from_audio")
    first = _Count()                    # the counter itself: the first press paints its arc (it can fail)
    QApplication.instance().installEventFilter(first)
    try:
        b.click()
        assert wait_until(lambda: got["made"], 5)
        _settled()
    finally:
        QApplication.instance().removeEventFilter(first)
    assert first.paints > 0
    assert got["asked"] == [True], "asked of Anki Miner off the window's thread"
    off, ids, install = got["made"][0]
    assert off and set(ids) == set(entry.data["shows"][next(iter(entry.data["shows"]))]) and install is False
    _settled()
    count = _Count()
    QApplication.instance().installEventFilter(count)
    try:
        b = button(ny, entry.key, "make_from_audio")
        b.click()
        _settled()
    finally:
        QApplication.instance().removeEventFilter(count)
    assert len(got["made"]) == 1 and len(got["asked"]) == 1, "the press under way is the one press"
    assert count.layouts == 0, f"a press that changes nothing lays nothing out ({count.layouts})"
    assert count.paints == 0, f"a press that changes nothing paints nothing ({count.paints})"
    got["release"].set()
    assert wait_until(lambda: not ny._running, 5)


def test_no_speech_model_asks_first_and_esc_downloads_nothing(world, subs):
    """Why: the model is 0.5 GB from huggingface.co: asked in the window before any byte; Esc is *Not now*."""
    got, main = subs
    got["ready"] = "no_model"
    seed, win, writer, ny = world()
    _wire(ny, got, main)
    entry = entry_of(ny, service.NO_SUBS)
    button(ny, entry.key, "make_from_audio").click()
    assert wait_until(lambda: getattr(ny, "confirming", None) is not None and ny.confirming.isVisible(), 5)
    card = ny.confirming
    assert card.title.text() == strings.NEEDS_SUBS_MODEL_ASK
    QTest.keyClick(card, Qt.Key.Key_Escape)
    assert wait_until(lambda: closed(card), 5)
    _settled()
    assert got["made"] == [], "nothing downloaded, nothing made"


def test_yes_to_the_model_installs_it_then_makes_them(world, subs):
    got, main = subs
    got["ready"] = "no_model"
    got["release"].set()
    seed, win, writer, ny = world()
    _wire(ny, got, main)
    said = []
    real = win.say
    win.say = lambda text, hold=None: said.append(text) or real(text, hold)
    entry = entry_of(ny, service.NO_SUBS)
    button(ny, entry.key, "make_from_audio").click()
    assert wait_until(lambda: getattr(ny, "confirming", None) is not None and ny.confirming.isVisible(), 5)
    ny.confirming.yes.click()
    assert wait_until(lambda: got["made"], 5)
    assert got["made"][0][2] is True, "the model first, after the yes"
    assert wait_until(lambda: strings.NEEDS_SUBS_MADE.format(n=2) in said, 5)


@pytest.mark.parametrize("language, action, site", [("ja", "find_with_hato", "jimaku.cc"),
                                                     ("zh", "find_with_hato_zh", "assrt.net")])
def test_find_them_with_hato_keeps_its_own_librarys_yes_with_its_own_words(world, subs, monkeypatch, language, action,
                                                                           site):
    """Why (Zh-H; PROVISIONAL words): the Chinese library's card says where hato looks for Chinese subtitles
    (assrt.net, then OpenSubtitles, with the learner's own keys) and its press keeps the Chinese library's own yes — a
    Japanese yes never sends Chinese titles anywhere, nor the other way round. The Japanese card is as before."""
    from app import no_subs
    monkeypatch.setattr(service, "no_subs_offer", lambda view, settings: {"make": False, "hato": True})
    real = service._no_subs_entry
    monkeypatch.setattr(service, "_no_subs_entry",
                        lambda view, offer, seen: real(view._replace(language=language), offer, seen))
    seed, win, writer, ny = world()
    ny.language = language
    entry = entry_of(ny, service.NO_SUBS)
    assert entry.actions == (action,)
    b = button(ny, entry.key, action)
    assert b is not None and b.text() == "Find them with hato" and site in b.toolTip()
    assert ("jimaku" in b.toolTip()) is (language == "ja")
    b.click()
    mine, other = no_subs.setting(language), no_subs.setting("ja" if language == "zh" else "zh")
    assert wait_until(lambda: win.services.settings.get().get(mine) is True, 5)
    assert not win.services.settings.get().get(other)
