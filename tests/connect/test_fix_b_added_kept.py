"""Review B fix: a word the Anki signal already wrote into KnownWord.json, whose record save then failed, is still
recorded as `added` when the signal marks it again, so undo takes it back out.

What a wrong answer would cost: the word stays known with no way to undo it from the window. The record of a mark
says `added: True` only for a word this run put in the file; a word the user already knew by another route must not
be undone either, so that case is pinned too.

The known-words file is written through anki_sync's own helpers, in the shape the sync writes, inside the test root
the autouse fixture in tests/conftest.py provides. Anki is never touched: _mark only reads and writes the file.
"""
import json

from app import anki_sync
from app.connect import known_signal

NOW = "2026-10-08T10:00:00"


def _write_known(words):
    anki_sync._atomic_write_json(anki_sync._known_path("ja"), anki_sync._fresh_file(words))


def _words_on_disk():
    with open(anki_sync._known_path("ja"), encoding="utf-8") as f:
        return json.load(f)["words"]


def test_word_the_signal_already_wrote_is_recorded_added_so_undo_removes_it():
    # The signal wrote 勇気 (knownBy "anki-signal") before its record save failed; the next read finds it already
    # there. It is still this signal's word, so the record must say added: True for undo to take it out again.
    entry = anki_sync._entry("勇気", 31, "ja", NOW)
    entry["knownBy"] = known_signal.KNOWN_BY
    _write_known([entry])
    state = {}

    known_signal._mark("ja", [("勇気", 301, 31)], state, NOW, "signal")

    assert len(state["marked"]) == 1
    assert state["marked"][0]["word"] == "勇気"
    assert state["marked"][0]["added"] is True
    # Nothing new is appended: the word was already in the file, and the signal writes no second copy.
    assert len(_words_on_disk()) == 1


def test_word_known_another_way_is_recorded_not_added_so_undo_leaves_it():
    # 勇気 was known before the signal ran, by the user's own sync (no knownBy). Marking it again must not record
    # it as the signal's addition, or undo would remove a word the user already had.
    entry = anki_sync._entry("勇気", 31, "ja", NOW)
    _write_known([entry])
    state = {}

    known_signal._mark("ja", [("勇気", 301, 31)], state, NOW, "signal")

    assert state["marked"][0]["added"] is False
    assert len(_words_on_disk()) == 1
