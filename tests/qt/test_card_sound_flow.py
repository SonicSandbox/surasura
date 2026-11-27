"""*Add sound* walked as a learner walks it (AUDIO-FILL; the lane rule for a flow a learner goes through): the real
window's *Needs you* page shows Card sound's card from the count Connect kept (`card_sound.recount` → the ledger →
`card_sound.counted`, read on the window's worker), *Add sound* runs the real press (`card_sound.press` → `act` →
`run` → the one writer, `sentence_audio.fill`) on a worker, the cards are written, the toast's *Undo* takes them off
again (`press_undo` → `undo`), and *Not now* answers the card until more cards can get sound.

Stand-ins only where the world outside the app is: Anki (the writer's fake, notesInfo's shape), Anki Miner's field
mapping, the cut (a real file on disk per line) and which line a card's sound is in (`sound_source.plan`'s answer —
its own suite is AUDIO-FIND's). Japanese: the window's world is the Japanese library (Chinese runs the same press in
tests/connect/test_card_sound.py).

What a wrong answer would cost: a card that promises sound and writes none; a press on the window's thread (a freeze:
it cuts clips); an Undo that leaves the sound on; a *Not now* that keeps asking.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import card_sound as cs, sound_source
from app.connect.ledger import Ledger
from app.qt import strings
from app.services import needs as service
from tests.connect.test_add_audio import MAPPING
from tests.connect.test_card_sound import Anki
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, settle, world  # noqa: F401 (the fixture)

LINES = {1700000000501: ("今日は朝から雨が降っている。", "雨"), 1700000000502: ("駅まで歩いて十分かかる。", "駅"),
         1700000000503: ("この本はとても面白かった。", "本")}
OWN = 1700000000504                                     # the learner's own audio card: never touched


@pytest.fixture
def flow(world, monkeypatch, tmp_path):  # noqa: F811
    from app.cli import verbs
    from app.connect import undo as undoing
    anki = Anki()
    for n, (sentence, word) in LINES.items():
        anki.add(n, sentence, word)
    anki.add(OWN, "猫が好きだ。", "猫", audio="[sound:mine.mp3]")
    main, cut = threading.main_thread(), []

    def plan(language, notes, mapping, steps, ledger_path=None):
        return {int(n["noteId"]): sound_source.Source(sound_source.LINE, 7, 0, 1000, f"7:{int(n['noteId'])}")
                for n in notes}

    def cut_line(language, line_id, settings, steps):
        cut.append((line_id, threading.current_thread() is not main))
        path = tmp_path / f"line-{line_id.replace(':', '_')}.mp3"
        path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + line_id.encode())
        return str(path)
    monkeypatch.setattr(sound_source, "plan", plan)
    monkeypatch.setattr(cs, "Anki", lambda url: anki)
    monkeypatch.setattr(cs, "_mapping", lambda s, l: (str(tmp_path / "run"), MAPPING))
    monkeypatch.setattr(cs, "_cut_line", cut_line)
    monkeypatch.setattr(cs, "_voice_on", lambda s, l: False)
    monkeypatch.setattr(cs, "_kick", lambda s: None)
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(undoing, "owe_sync", lambda s: None)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    with Ledger() as ledger:                                # Connect's pass kept the count (its own process)
        assert cs.recount(anki, ledger, "ja", MAPPING, None)["real"] == 3
    _seed, win, _writer, ny = world(connect={"jobs": [], "needs": []})
    return win, ny, anki, cut


def _card(ny):
    return next((e for e in ny.entries if e.kind == service.CARD_SOUND), None)


def test_needs_you_add_sound_writes_the_cards_and_the_toasts_undo_takes_them_off(flow):
    win, ny, anki, cut = flow
    entry = _card(ny)
    assert entry is not None and entry.title == "3 cards have no sentence audio, and your library has their lines."
    add = button(ny, entry.key, "add_sound")
    assert add.text() == "Add sound" and add.toolTip() and button(ny, entry.key, "sound_not_now").toolTip()
    add.click()
    assert wait_until(lambda: win.toasts.alive and win.toasts.text, 10)
    assert win.toasts.text == strings.NEEDS_SOUND_ADDED.format(n=3)
    assert len(cut) == 3 and all(on_worker for _line, on_worker in cut), "cut on a worker, never the window's thread"
    for n in LINES:
        assert anki.value(n).startswith("[sound:surasura-sa-"), n
    assert anki.value(OWN) == "[sound:mine.mp3]", "the learner's own audio stays"
    settle(ny)
    assert _card(ny) is None, "the press kept the new count: the card goes"
    next(b for b in win.toasts.card.buttons if b.text() == strings.TOAST_UNDO).click()
    assert wait_until(lambda: all(anki.value(n) == "" for n in LINES), 10)
    assert anki.value(OWN) == "[sound:mine.mp3]"


def test_not_now_answers_the_card_until_more_cards_can_get_sound(flow):
    win, ny, anki, _cut = flow
    entry = _card(ny)
    button(ny, entry.key, "sound_not_now").click()
    assert wait_until(lambda: _card(ny) is None, 10)
    assert anki.value(next(iter(LINES))) == "", "nothing written"
    anki.add(1700000000505, "明日は晴れるでしょう。", "晴れる")
    with Ledger() as ledger:
        cs.recount(anki, ledger, "ja", MAPPING, None)
    settle(ny)
    assert _card(ny) is not None and _card(ny).data["n"] == 4, "more cards: it asks again"
