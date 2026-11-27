"""ONE-READ 3 (the DSA audit's G10, counted again): a known-words sync parses KnownWord.json once in EVERY module, its
review loop's Undo parses and writes it once, and a word the window marks known keeps the next sync a delta.

DSA-SYNC (3.0.19) handed one parse down the sync (`anki_sync.KnownFile`) and pinned it through anki_sync's own parser;
this counts every parse of the file in the process — the window's word marks, the review loop's states, Known from
Anki, the swap queue — so a reader that parses it again on its own, in any module, shows. Counted at ONE-READ 3's base:
a quiet sync 1, a sync with every move from the phone 1, its Undo 1 (one write, one dated copy), the window's mark 1.

What a wrong answer would cost: ~50 ms a parse at a 3 MB file (9,000 words) at every sync, and a full sync (every note
in scope read from Anki) after every word the window marks. Real words (ja + zh, tests/Test Resources' sentences);
every file in the test's temp root; the stand-in Anki of Kyou-LR, never a live one.
"""
import json
import os

import pytest

from app import anki_sync, path_utils
from app.connect import review_loop
from app.path_utils import get_user_files_path
from app.services import word_marks
from tests.connect.test_kyou_lr_review_loop import (GREEN, RED, WORDS, LoopAnki, _known, _sync,  # noqa: F401
                                                     connect_on)


@pytest.fixture
def anki(monkeypatch):
    return LoopAnki(monkeypatch)


class Parses:
    """Every parse of KnownWord.json's text in any module (`json.loads` of a text holding its entries; the sync's own
    state and records hold none), every write of the file and every dated copy of it, while counting."""

    def __init__(self, monkeypatch, language):
        self.path = os.path.normcase(os.path.abspath(os.path.join(get_user_files_path(language), "KnownWord.json")))
        self.on, self.parses, self.writes, self.backups = False, 0, 0, 0
        real_loads, real_bytes, real_backup = json.loads, anki_sync._atomic_write_bytes, path_utils.backup_to_trash
        me = self

        def loads(text, *a, **k):
            if me.on and isinstance(text, str) and '"dictForm"' in text[:20000]:
                me.parses += 1
            return real_loads(text, *a, **k)

        def write(p, data):
            me.writes += me.on and os.path.normcase(os.path.abspath(p)) == me.path
            return real_bytes(p, data)

        def backup(p, *a, **k):
            me.backups += me.on and os.path.normcase(os.path.abspath(p)) == me.path
            return real_backup(p, *a, **k)
        monkeypatch.setattr(json, "loads", loads)
        monkeypatch.setattr(anki_sync, "_atomic_write_bytes", write)
        monkeypatch.setattr(path_utils, "backup_to_trash", backup)

    def __enter__(self):
        self.parses = self.writes = self.backups = 0
        self.on = True
        return self

    def __exit__(self, *exc):
        self.on = False


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_every_module_parses_the_known_words_once_a_sync_and_once_an_undo(anki, monkeypatch, language):
    # why: the audit counted 6–9 parses a sync across the sync, Known, the loop's states, apply and read-back
    known, ignore, swap, studied, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)
    count = Parses(monkeypatch, language)
    with count:
        _sync(language)
    assert count.parses == 1 and count.writes == 0, "a quiet sync: its own parse, no write"
    anki.add(1, known, suspended=True, tags=["marked"])
    anki.add(2, ignore, suspended=True, flag=RED)
    anki.add(3, swap, suspended=True, flag=GREEN)
    with count:
        result, _ = _sync(language)
    assert result.loop["known"] == 1 and result.loop["ignored"] == 1 and result.loop["swap"] == 1
    assert count.parses == 1, f"every move from the phone, one parse: {count.parses}"
    with count:
        review_loop.undo(language, result.loop["sync"])
    assert count.parses == 1 and count.writes == 1 and count.backups == 1, (count.parses, count.writes,
                                                                           count.backups)
    assert _known(language) == {studied}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_word_the_window_marks_known_keeps_the_next_sync_a_delta(anki, monkeypatch, language):
    # why: a write that only adds follows the sync's record (`follow_known_write`); else the next sync reads every note
    # in scope again
    studied, word = WORDS[language][3], WORDS[language][0]
    anki.add(4, studied)
    _sync(language)
    count = Parses(monkeypatch, language)
    with count:
        marked = word_marks.apply(language, [(word, "known")])
    assert not marked.error and count.parses == 1 and count.writes == 1
    result, _ = _sync(language)
    assert result.mode == "delta", result.mode
    assert _known(language) == {studied, word}
