"""VOICE-SETUP's *Some cards need the AI voice: set it up* on the Needs-you page, in the real window (`app/qt/needs.py`'s
`ai_waiting_in`, `_voice_offered`, `_do_voice_setup` / `_do_voice_not_now`), and the whole flow a learner walks: the
card's *Set it up* → the AI voice's own guide (the private module's `qt_setup`) → its 4 steps by Enter → *Done*, with a
stand-in install and trial (never the 4.9 GB download).

What a wrong answer would cost a learner: a card whose explainer stands as a line under its title, buttons with no tip,
a card shown for a Chinese library or with the module absent (a press that opens nothing), a card that comes back after
*Not now*, a guide that can't be walked to its end by Enter, a card still asking once the voice is installed, and a
page gathered again at every count that didn't change.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from app.qt import needs as qneeds
from app.qt import strings, windows
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_gone_folder import world  # noqa: F401 — the window, ja and zh
from tests.qt.test_onb_more_card import gather, view
from tests.test_library_store_support import LANGUAGES


def opened(world, language, monkeypatch, waiting=18, offered=None):
    seed, win, _writer, ny = world(language)
    ny.read_settings = lambda: {}
    ny.read_connect = lambda _lang: {"needs": [], "jobs": [], "gaps": []}
    ny.find_offline = lambda _lang, _rels, _data: []
    if offered is not None:
        monkeypatch.setattr(qneeds, "_voice_offered", lambda lang: offered)
    said = []
    monkeypatch.setattr(win, "say", lambda text, hold=None: said.append(text))
    ny.ai_waiting = waiting
    gather(ny, view(language))
    win.show_tab("needs")
    return win, ny, said


def card_of(ny):
    return next((e for e in ny.entries if e.kind == service.VOICE_SETUP), None)


def button(ny, name):
    return next(b for b in ny.cards.buttons(service.VOICE_SETUP) if b.property("action") == name)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_card_asks_with_two_tipped_buttons_and_its_explainer_behind_a_mark(world, language, monkeypatch):
    win, ny, _said = opened(world, language, monkeypatch, offered=True)
    e = card_of(ny)
    assert e is not None and e.title == "Some cards need the AI voice: set it up"
    assert [b.text() for b in ny.cards.buttons(e.key)] == ["Set it up", "Not now"]
    assert all(b.toolTip() for b in ny.cards.buttons(e.key))
    card = ny.cards.card(e.key)
    assert getattr(card, "about", None) is not None, "its line stands behind a ?, never under the title"
    assert getattr(card, "more", None) is None, "its two answers end it: no ⋯"


@pytest.mark.parametrize("language", LANGUAGES)
def test_not_now_takes_the_card_off_for_good(world, language, monkeypatch):
    win, ny, said = opened(world, language, monkeypatch, offered=True)
    button(ny, "voice_not_now").click()
    assert wait_until(lambda: service.VOICE_SETUP in service.read_answered(language), 10)
    gather(ny)
    assert card_of(ny) is None and strings.NEEDS_VOICE_NOT_NOW in said
    ny.ai_waiting_in(40)
    gather(ny)
    assert card_of(ny) is None


def test_a_chinese_library_and_an_absent_module_never_show_it(world, monkeypatch):
    # why: the voice reads Japanese only; without the module *Set it up* would open nothing
    win, ny, _said = opened(world, "zh", monkeypatch)
    assert card_of(ny) is None
    import sys
    import modules
    monkeypatch.delattr(modules, "irodori", raising=False)            # the folder gone (a public build)
    monkeypatch.setitem(sys.modules, "modules.irodori", None)
    assert qneeds._voice_offered("ja") is False
    ny._do_voice_setup(service.Entry(key=service.VOICE_SETUP, kind=service.VOICE_SETUP, title="", lines=(),
                                     actions=(), unseen=False, say="", data={"n": 3}), None)   # opens nothing, no raise


def test_the_count_gathers_again_only_when_it_changes(world, monkeypatch):
    # why: the count comes with Card sound's every look — a gather each time it says the same is waste
    win, ny, _said = opened(world, "ja", monkeypatch, waiting=None, offered=True)
    assert card_of(ny) is None
    n = ny.gathers
    ny.ai_waiting_in(None)
    ny.ai_waiting_in(0)
    assert ny.gathers == n and not ny._running, "nothing waiting either way: nothing gathered"
    ny.ai_waiting_in(18)
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    assert card_of(ny) is not None and card_of(ny).data == {"n": 18}
    n = ny.gathers
    ny.ai_waiting_in(18)
    assert ny.gathers == n and not ny._running
    ny.ai_waiting_in(25)                                 # more cards wait: the card says the new count
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    assert card_of(ny).data == {"n": 25}
    n = ny.gathers
    ny.ai_waiting_in(0)
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    assert card_of(ny) is None


def test_a_language_switch_forgets_the_left_languages_count(world, monkeypatch):
    win, ny, _said = opened(world, "ja", monkeypatch, offered=True)
    assert card_of(ny) is not None
    ny._switched()
    assert ny.ai_waiting is None
    gather(ny)
    assert card_of(ny) is None


# --- the whole flow (the private module's guide; skipped where it is absent) --------------------------------------- #
@pytest.fixture
def voice_module(monkeypatch):
    """The AI voice's guide with a stand-in install (the files a finished install leaves) and trial — no download, no
    nvidia-smi, no Anki Miner."""
    qt_setup = pytest.importorskip("modules.irodori.qt_setup")
    import json
    import os
    from modules.irodori import runtime, setup
    calls = {"install": 0, "test": 0}

    def install(say, cancel):
        calls["install"] += 1
        for i, what in enumerate(runtime.STEPS, 1):
            say(i, len(runtime.STEPS), what)
        base = runtime.home()
        for path in (runtime.env_python(base), runtime.model_path(base), runtime.codec_path(base)):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()
        open(os.path.join(base, runtime.MARKER), "w").close()
        with open(os.path.join(base, "installed.json"), "w", encoding="utf-8") as f:
            json.dump({"version": runtime.RUNTIME_VERSION, "backend": "cpu", "size_bytes": 4_900_000_000}, f)

    def trial(settings):
        calls["test"] += 1
        record = {"start_s": 19.0, "sentence_s": 24.0, "backend": "cpu", "at": "2026-11-26T22:00:00", "file": None,
                  "voice": settings.get("irodori_card_voice")}
        with open(os.path.join(runtime.home(), setup.TESTED), "w", encoding="utf-8") as f:
            json.dump(record, f)
        return record
    job = setup.Job(install=install, test=trial)
    job.calls = calls
    monkeypatch.setattr(setup, "JOB", job)
    monkeypatch.setattr(runtime, "gpu", lambda run=None: None)
    monkeypatch.setattr(setup, "listen_look", lambda settings, language="ja": setup.LISTEN_NO_MINER)
    return qt_setup, setup, job


def _enter(guide):
    """Enter, as a learner presses it once the step has been read (a double click's time after it came: AD-1)."""
    assert wait_until(lambda: guide.settled(), 3)
    guide.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()


def test_the_whole_flow_needs_you_to_the_guides_four_steps_to_done(world, monkeypatch, voice_module):
    qt_setup, setup, job = voice_module
    win, ny, said = opened(world, "ja", monkeypatch)
    e = card_of(ny)
    assert e is not None, "Japanese, the module here, the voice not installed, 18 cards waiting: the card"
    button(ny, "voice_setup").click()
    assert wait_until(lambda: windows.opened(win, qt_setup.NAME) is not None, 5)
    guide = windows.opened(win, qt_setup.NAME)
    assert wait_until(lambda: guide.facts is not None, 10)
    assert guide.what_line.text().startswith("18 of your cards") and guide.btn_not_now.isVisible()
    _enter(guide)                                                       # 1 What it is: Install
    assert guide.i == 1 and win.services.settings.get().get("enable_irodori") is True
    assert wait_until(lambda: job.state.get("phase") == setup.DONE, 10) and job.calls["install"] == 1
    _enter(guide)                                                       # 2 The voices
    assert guide.i == 2
    guide.days.choose("1", user=True)
    assert win.services.settings.get().get("card_sound_days") == 1
    _enter(guide)                                                       # 3 Your choices
    assert guide.i == 3
    assert wait_until(lambda: guide.try_big.text() == "24 s a sentence on your processor", 10)
    _enter(guide)                                                       # 4 Try it here: Done
    assert wait_until(lambda: windows.opened(win, qt_setup.NAME) is None, 5)
    assert job.calls == {"install": 1, "test": 1}
    gather(ny)
    assert card_of(ny) is None, "installed: the card has nothing left to ask"
    assert service.VOICE_SETUP not in service.read_answered("ja")


def test_the_guides_not_now_from_the_card_answers_the_card(world, monkeypatch, voice_module):
    qt_setup, setup, job = voice_module
    win, ny, said = opened(world, "ja", monkeypatch)
    button(ny, "voice_setup").click()
    assert wait_until(lambda: windows.opened(win, qt_setup.NAME) is not None, 5)
    guide = windows.opened(win, qt_setup.NAME)
    assert wait_until(lambda: guide.facts is not None, 10)
    guide.btn_not_now.click()
    assert wait_until(lambda: service.VOICE_SETUP in service.read_answered("ja"), 5)
    gather(ny)
    assert card_of(ny) is None and job.calls["install"] == 0


@pytest.mark.parametrize("kept, shown", [({"cards": 9, "real": 2, "ai": 7, "silent": 0, "at": "x"}, 7),
                                         ({"cards": 2, "real": 2, "ai": 0, "silent": 0, "at": "x"}, None),
                                         (None, None)])
def test_with_no_count_handed_in_the_card_reads_card_sounds_own_ai_count(world, monkeypatch, kept, shown):
    # why: AUDIO-FILL — nothing in the window hands `ai_waiting_in` a number yet; the count Connect's pass kept
    # (`card_sound.counted`, read on the gather's worker while Connect is on) says how many wait for the voice, so
    # the card shows from it — and never from a count with no AI cards, or none kept
    win, ny, _said = opened(world, "ja", monkeypatch, waiting=None, offered=True)
    ny.read_settings = lambda: {"connect_enabled": True}
    asked = []
    ny.connect_calls["sound_count"] = lambda lang: asked.append(lang) or kept
    gather(ny)
    e = card_of(ny)
    assert asked == ["ja"], "Card sound's one ledger row, read once a gather"
    assert (e is not None) is (shown is not None)
    if shown:
        assert e.data["n"] == shown
