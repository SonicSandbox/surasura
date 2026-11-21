"""An episode's *Words it won't mine again…* window names the words of the episode Connect couldn't make a card for,
each with why (Kantan-MA, a tester's report 2026-11-21: *Mine again* made no card and nothing said why; PROVISIONAL
words).

What a wrong answer would cost a learner: pressing *Mine again* over and over for a word that can't be made from that
episode (a song line, a name with Ignore names on, Anki Miner finding no definition), with nothing to read anywhere.

The window on a real store (`test_removed`'s `real`), its Connect record (`ledger.left_of`) stood in for: real ja
words.
"""
import sqlite3

import pytest

pytest.importorskip("PyQt6")

from app.connect import ledger
from app.qt import strings, unmined_words
from tests.qt.conftest import wait_until
from tests.qt.test_drag import settle
from tests.qt.test_kantan_b2_unmined import _deleted_cards
from tests.qt.test_removed import real  # noqa: F401  (real: a fixture)

LEFT = [{"word": "大衆", "why": ledger.LEFT_WHY["not_found"]}, {"word": "魔物", "why": "said only in a song line"}]


def _open(win, **kw):
    w = unmined_words.open_window(win, **kw)
    assert wait_until(lambda: not w._reading and w.reads, 10)
    settle()
    return w


def test_an_episodes_window_names_its_words_with_no_card_and_why(real, monkeypatch):
    asked = []
    monkeypatch.setattr(ledger, "left_of", lambda language, ids, db_path=None: asked.append((language, ids)) or
                        {i: list(LEFT) for i in ids})
    before = _deleted_cards("ja")
    _store, win, _writer = real("ja", before=before)
    a, _b = before.ids
    w = _open(win, item_ids=(a,), label="第1話")
    assert asked == [("ja", (a,))]
    assert not w.left_title.isHidden() and w.left_title.text() == strings.UNMINED_LEFT
    assert w.left_lines.text().splitlines() == ["大衆 · " + ledger.LEFT_WHY["not_found"], "魔物 · said only in a song line"]
    assert w.order and w.none.isHidden(), "the deleted cards' words are listed as before, above it"


def test_with_nothing_left_out_the_part_is_hidden_and_the_whole_list_never_reads_it(real, monkeypatch):
    asked = []
    monkeypatch.setattr(ledger, "left_of", lambda language, ids, db_path=None: asked.append(ids) or {i: [] for i in ids})
    before = _deleted_cards("ja")
    _store, win, _writer = real("ja", before=before)
    a, _b = before.ids
    w = _open(win, item_ids=(a,), label="第1話")
    assert w.left_title.isHidden() and w.left_lines.isHidden() and w.left_lines.text() == ""
    whole = _open(win)                                  # Settings' door: every episode's deleted words, no episode's
    assert asked == [(a,)] and whole.left_title.isHidden()


def test_connects_record_unreadable_just_now_shows_no_part_and_no_error(monkeypatch):
    def busy(language, ids, db_path=None):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(ledger, "left_of", busy)
    assert unmined_words.left_out("ja", (1,)) == []
