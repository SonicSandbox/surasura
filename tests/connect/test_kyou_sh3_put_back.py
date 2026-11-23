"""Kyou-SH3 part 2: *Put back…* — an earlier tidy's Undo (PROVISIONAL words; the list: the last 10 tidies).

What each test holds still:
- **the list (`tidy.past`):** a language's tidies that deleted cards, newest first, at most 10 (older backups stay on
  disk, unlisted); each says whether it can go back (`CAN`), went back already (`PUT_BACK`) or has no copy on disk
  (`GONE`); a tidy that deleted nothing, one still writing or putting back, and another language's aren't listed;
- **an older tidy goes back with Undo's own rules:** its cards in Anki again (the newer tidy's stay deleted, its Undo
  still offered), and **never twice**: a second put-back of the same tidy is refused and adds no copy.

What a wrong answer costs: a tidy put back twice (two cards for each word), the wrong tidy's cards back, or a list
that offers a tidy whose copy is gone. Anki is the Kyou-SH2 suite's fake (a real package: SQLite in a zip); the
ledger and the library store are real. ja + zh.
"""
import json
import os

import pytest

from app.connect import tidy
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_kyou_sh2_tidy import WORDS, _anki, _mined, _opener, ledger  # noqa: F401  (the fixture)


def _two_tidies(ledger, lang):
    """Two tidies of one episode's cards: the older took 104, the newer 105 -> (anki, older id, newer id)."""
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    older = tidy.run(anki, ledger, lang, [104], why=tidy.NOW, open_store=_opener(lang))
    newer = tidy.run(anki, ledger, lang, [105], why=tidy.AUTO, open_store=_opener(lang))
    assert older["deleted"] == [104] and newer["deleted"] == [105]
    return anki, older["id"], newer["id"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_older_tidy_goes_back_and_never_twice(ledger, lang):
    # why: the newest tidy's Undo is in Needs you; *Put back…* gives an older one the same Undo — and a tidy that
    # went back once is refused the second time (else every word of it would have two cards)
    anki, older, newer = _two_tidies(ledger, lang)
    assert [(p["id"], p["can"]) for p in tidy.past(ledger, lang)] == [(newer, tidy.CAN), (older, tidy.CAN)]
    back = tidy.restore(anki, ledger, older, _opener(lang), language=lang)
    assert back["back"] == 1 and WORDS[lang][3] in [n["fields"]["Word"]["value"] for n in anki.notes_.values()]
    assert WORDS[lang][4] not in [n["fields"]["Word"]["value"] for n in anki.notes_.values()], "the newer stays deleted"
    notes = len(anki.notes_)
    with pytest.raises(tidy.Refused):
        tidy.restore(anki, ledger, older, _opener(lang), language=lang)
    assert len(anki.notes_) == notes, "no second copy"
    assert [(p["id"], p["can"]) for p in tidy.past(ledger, lang)] == [(newer, tidy.CAN), (older, tidy.PUT_BACK)]
    assert tidy.restore(anki, ledger, newer, _opener(lang), language=lang)["back"] == 1, "the newer's Undo still goes"


def test_another_languages_tidy_is_neither_listed_nor_put_back(ledger):
    anki, older, newer = _two_tidies(ledger, "ja")
    assert tidy.past(ledger, "zh") == []
    with pytest.raises(tidy.Refused):
        tidy.restore(anki, ledger, older, _opener("zh"), language="zh")


def _row(ledger, lang, state, deleted, folder, why=tidy.AUTO, at="2026-11-20T09:30:00Z"):
    tidy.ensure(ledger)
    with ledger.transaction():
        return ledger.conn.execute(
            "INSERT INTO tidies (language, at, why, state, folder, notes, made, kept, deleted) "
            "VALUES (?, ?, ?, ?, ?, '{}', '[]', '[]', ?)", (lang, at, why, state, folder, json.dumps(deleted))).lastrowid


def test_the_list_is_the_last_ten_newest_first_and_says_which_can_go_back(ledger, tmp_path):
    # why: the menu lists ten; older backups stay on disk (never purged) but aren't offered; one whose copy is gone
    # is shown so, before the press
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "cards.apkg").write_bytes(b"PK")
    ids = [_row(ledger, "ja", tidy.DONE, [100 + i], str(kept)) for i in range(11)]
    gone = _row(ledger, "ja", tidy.DONE, [300], str(tmp_path / "removed"))
    undone = _row(ledger, "ja", tidy.UNDONE, [301], str(kept))
    _row(ledger, "ja", tidy.DONE, [], str(kept))                        # deleted nothing (every card kept late)
    _row(ledger, "ja", tidy.WRITING, [302], str(kept))                  # half-way: finished by the next look
    _row(ledger, "ja", tidy.RESTORING, [303], str(kept))
    _row(ledger, "ja", tidy.UNSAVED, [], str(kept))
    _row(ledger, "zh", tidy.DONE, [304], str(kept))
    listed = tidy.past(ledger, "ja")
    assert [p["id"] for p in listed] == [undone, gone] + ids[::-1][:8]
    assert [p["can"] for p in listed[:3]] == [tidy.PUT_BACK, tidy.GONE, tidy.CAN]
    assert listed[0]["cards"] == 1 and listed[0]["at"] == "2026-11-20T09:30:00Z"
    assert ids[0] not in [p["id"] for p in listed] and os.path.exists(kept / "cards.apkg"), "older: on disk, unlisted"


def test_with_no_ledger_yet_nothing_is_listed(monkeypatch, tmp_path):
    from app.connect import ledger as ledger_module
    monkeypatch.setattr(ledger_module, "path", lambda: str(tmp_path / "none" / "connect.db"))
    assert tidy.act_past("ja") == []


def test_two_undos_of_one_tidy_at_once_put_it_back_once(ledger):
    # why: *Needs you*'s Undo and *Put back…* are two presses; both may read the tidy as `done` before either takes
    # Anki's lock — the one that takes it second finds it claimed and is refused, adding no card
    anki, older, newer = _two_tidies(ledger, "ja")
    writer = anki.writer

    class _Other:
        """The other Undo ran in full between this one's read and its lock."""
        def __init__(self, verb):
            self.inner = writer(verb)

        def __enter__(self):
            anki.writer = writer
            tidy.restore(anki, ledger, older, _opener("ja"), language="ja")
            return self.inner.__enter__()

        def __exit__(self, *exc):
            return self.inner.__exit__(*exc)
    anki.writer = _Other
    notes = None
    with pytest.raises(tidy.Refused):
        notes = tidy.restore(anki, ledger, older, _opener("ja"), language="ja")
    assert notes is None and tidy.tidy_row(ledger, older)["state"] == tidy.UNDONE
    words = [n["fields"]["Word"]["value"] for n in anki.notes_.values()]
    assert words.count(WORDS["ja"][3]) == 1, "one card for its word"
