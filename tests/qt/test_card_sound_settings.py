"""Settings › Anki & mining › *Card sound*'s two presses (AUDIO-FILL, 3.0.21; Sonic § 106 decisions 9 + 10; PROVISIONAL
words): *Add sound* with its count beside it (`card_sound.counted`, the row Connect's pass kept, read on a worker),
the press running the real writer (`card_sound.press` → `act` → `sentence_audio.fill`) on a worker, then its toast
with *Undo*; *Remove all AI audio…* — the count first (nothing written), then the sheet (No by default, painted as a
danger, the AI voice's still-on line while it is on), the removal on a worker, a toast whose *Undo* puts the clips
back. Japanese and Chinese for *Add sound* (real sound needs no AI voice); *Remove all AI audio* is Japanese only (the
voice reads only Japanese).

Stand-ins only where the world outside the app is: Anki (the writer's fake), Anki Miner's field mapping, the cut, the
plan of each card's line (AUDIO-FIND's own suite), the window's toast (a recorder with its *Undo*).

What a wrong answer would cost: a row that writes on the window's thread (a freeze while clips are cut); a removal
before the yes, or with Yes under Enter; the learner's own audio taken; an Undo that says sound went when it came back.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import card_sound as cs, sentence_audio as sa, sound_source
from app.connect.ledger import Ledger
from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from app.qt import strings
from tests.connect.test_add_audio import MAPPING
from tests.connect.test_card_sound import Anki, _clip
from tests.qt.conftest import wait_until

LINES = {"ja": {1700000000601: ("今日は朝から雨が降っている。", "雨"), 1700000000602: ("駅まで歩いて十分かかる。", "駅")},
         "zh": {1700000000601: ("今天早上一直在下雨。", "下雨"), 1700000000602: ("走到车站要十分钟。", "车站")}}
OWN = 1700000000609                                   # the learner's own audio: never touched


class Toasts:
    """The window's toast: its line and its *Undo* kept, the Undo pressed by the test."""

    def __init__(self):
        self.shown = []

    def show(self, text, undo=None, **_):
        self.shown.append((text, undo))


@pytest.fixture
def world(qapp, monkeypatch, tmp_path):
    from app.cli import verbs
    from app.connect import undo as undoing
    from tests.qt.test_settings_live import Fakes
    anki, main, cut, voice = Anki(), threading.main_thread(), [], [False]

    def plan(language, notes, mapping, steps, ledger_path=None):
        return {int(n["noteId"]): sound_source.Source(sound_source.LINE, 7, 0, 1000, f"7:{int(n['noteId'])}")
                for n in notes}

    def cut_line(language, line_id, settings, steps):
        cut.append(threading.current_thread() is not main)
        return _clip(tmp_path, "line-" + line_id.replace(":", "_") + ".mp3")
    monkeypatch.setattr(sound_source, "plan", plan)
    monkeypatch.setattr(cs, "Anki", lambda url: anki)
    monkeypatch.setattr(cs, "_mapping", lambda s, l: (str(tmp_path / "run"), MAPPING))
    monkeypatch.setattr(cs, "_cut_line", cut_line)
    monkeypatch.setattr(cs, "_voice_on", lambda s, l: voice[0])
    monkeypatch.setattr(cs, "_kick", lambda s: None)
    monkeypatch.setattr(cs, "_keep_dir", lambda: str(tmp_path / "kept"))
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(undoing, "owe_sync", lambda s: None)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    return {"anki": anki, "cut": cut, "voice": voice, "fakes": Fakes(monkeypatch), "tmp": tmp_path}


def _page(world, language, toasts=True):
    from tests.qt.test_settings_live import make
    page, store, shell = make(world["fakes"], data={"connect_enabled": True}, language=language)
    if toasts:
        shell.toasts = Toasts()
    return page, store, shell


def _seed(world, language):
    anki = world["anki"]
    for n, (sentence, word) in LINES[language].items():
        anki.add(n, sentence, word)
    anki.add(OWN, LINES[language][1700000000601][0], "own", audio="[sound:mine.mp3]")
    with Ledger() as ledger:                            # Connect's pass kept the count (its own process)
        assert cs.recount(anki, ledger, language, MAPPING, None)["real"] == 2


def test_both_rows_sit_in_the_card_sound_group_filled_by_the_live_page():
    rows = [r.id for r in catalog.ROWS]
    assert rows.index("card_sound_add") == rows.index("ai_audio") + 1
    assert rows.index("card_sound_remove_ai") == rows.index("card_sound_add") + 1
    for row_id in ("card_sound_add", "card_sound_remove_ai"):
        row = catalog.ROW[row_id]
        assert row.group == "card_sound" and row.kind == "custom" and row.keys == ()
        assert catalog.FILLED_BY[row_id] == "app.qt.settings_live" and row.label and row.tip and row.help


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_add_sound_shows_its_count_writes_on_a_worker_and_the_toasts_undo_takes_it_off(world, lang):
    # why: the row's count is Connect's (one ledger row, read off the window's thread); the press cuts and writes off
    # it too; the learner's own audio stays; the toast's Undo empties exactly what the press wrote
    _seed(world, lang)
    page, store, shell = _page(world, lang)
    parts = page.live.parts["card_sound_add"]
    door, count = parts["add"], parts["count"]
    assert door.text() == S.SOUND_ADD and door.toolTip() and count.toolTip()
    assert wait_until(lambda: count.isVisible() and count.text() == S.SOUND_COUNT.format(n=2), 5)
    door.click()
    toasts = shell.toasts
    assert wait_until(lambda: toasts.shown, 10)
    text, undo = toasts.shown[-1]
    assert text == strings.NEEDS_SOUND_ADDED.format(n=2) and undo is not None
    anki = world["anki"]
    assert world["cut"] == [True, True], "cut on a worker, never the window's thread"
    assert all(anki.value(n).startswith("[sound:surasura-sa-") for n in LINES[lang])
    assert anki.value(OWN) == "[sound:mine.mp3]", "the learner's own audio stays"
    assert wait_until(lambda: count.text() == S.SOUND_COUNT_NONE, 5), "the count read again after the press"
    undo()
    assert wait_until(lambda: all(anki.value(n) == "" for n in LINES[lang]), 10)
    assert wait_until(lambda: shell.bar_line.lines[-1:] == [strings.NEEDS_SOUND_UNDONE.format(n=2)], 5)
    assert anki.value(OWN) == "[sound:mine.mp3]" and store.calls == [], "the press writes no setting"


def test_no_count_kept_yet_shows_no_count_line(world):
    # why: before Connect's first pass there is no count: the row never shows a 0 it didn't count
    page, _store, _shell = _page(world, "ja")
    count = page.live.parts["card_sound_add"]["count"]
    wait_until(lambda: False, 0.3)
    assert not count.isVisible() and count.text() == ""


def _ai(world, tmp_path):
    """Two AI clips the writer put on (Iro-AA's tag) and the learner's own audio."""
    anki = world["anki"]
    for n, (sentence, word) in LINES["ja"].items():
        anki.add(n, sentence, word)
    anki.add(OWN, "猫が好きだ。", "猫", audio="[sound:mine.mp3]")
    with Ledger() as ledger:
        sa.fill(anki, ledger, {n: _clip(tmp_path, f"ai-{n}.mp3") for n in LINES["ja"]}, tag=cs.AI_TAG, by="ai-audio")
    return {n: anki.value(n) for n in LINES["ja"]}


def _sheet(page):
    assert wait_until(lambda: getattr(page.live, "remove_card", None) is not None
                      and page.live.remove_card.isVisible(), 5), "the sheet opens"
    return page.live.remove_card


@pytest.mark.parametrize("voice", [False, True])
def test_remove_all_ai_audio_counts_first_asks_then_removes_and_its_undo_puts_them_back(world, qapp, voice):
    # why: the count never writes; the sheet's default is No (Enter never removes) and says a voice still on makes the
    # clips again; the yes removes only the AI's clips, off the window's thread; the toast's Undo puts them back
    world["voice"][0] = voice
    was = _ai(world, world["tmp"])
    page, store, shell = _page(world, "ja")
    door = page.live.parts["card_sound_remove_ai"]["remove"]
    assert door.text() == S.SOUND_REMOVE and door.toolTip()
    door.click()
    card = _sheet(page)
    anki = world["anki"]
    assert all(anki.value(n) == was[n] for n in LINES["ja"]), "nothing removed before the yes"
    assert card.title.text() == S.SOUND_REMOVE_ASK.format(n=2)
    assert S.SOUND_REMOVE_BODY in card.body.text()
    assert (S.SOUND_REMOVE_VOICE_ON in card.body.text()) is voice
    assert card.yes.property("kind") == "danger" and card.yes.toolTip() and card.no.toolTip()
    assert qapp.focusWidget() is not card.yes, "No by default: Enter never removes"
    card.yes.click()
    toasts = shell.toasts
    assert wait_until(lambda: toasts.shown, 10)
    text, undo = toasts.shown[-1]
    assert text == S.SOUND_REMOVED.format(n=2) and undo is not None
    assert all(anki.value(n) == "" for n in LINES["ja"]) and anki.value(OWN) == "[sound:mine.mp3]"
    undo()
    assert wait_until(lambda: all(anki.value(n) == was[n] for n in LINES["ja"]), 10)
    assert wait_until(lambda: shell.bar_line.lines[-1:] == [S.SOUND_BACK.format(n=2)], 5), "its own words: back on"
    assert store.calls == []


def test_remove_with_no_ai_audio_says_so_and_opens_no_sheet(world):
    world["anki"].add(OWN, "猫が好きだ。", "猫", audio="[sound:mine.mp3]")
    page, _store, shell = _page(world, "ja")
    page.live.parts["card_sound_remove_ai"]["remove"].click()
    assert wait_until(lambda: shell.bar_line.lines[-1:] == [S.SOUND_REMOVE_NONE], 5)
    assert getattr(page.live, "remove_card", None) is None


def test_remove_is_japanese_only_and_both_rows_need_connect(world):
    # why: the AI voice reads only Japanese, so a Chinese library has no AI audio to remove; with Connect off there is
    # no Anki Miner field mapping to write through
    from tests.qt.test_settings_live import make
    page, _store, _shell = _page(world, "zh")
    assert "card_sound_add" in page.live.parts and "card_sound_remove_ai" not in page.live.parts
    off, _s, _sh = make(world["fakes"], data={"connect_enabled": False}, language="ja")
    assert "card_sound_add" not in off.live.parts and "card_sound_remove_ai" not in off.live.parts
