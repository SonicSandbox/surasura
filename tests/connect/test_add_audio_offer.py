"""*Add audio to these cards* — Connect's half of the window's press (Kura-AB3 A2; spec TheForge `tracks/pipeline/work/
AB3/add-audio-spec.md` L2; PROVISIONAL): once a book first lines up with its audiobook, the cards Connect made from it
before are offered the narrator's voice — ONE standing *Needs you* line a book, asked once; *Add the narrator's voice*
(`actions.add_audio`) fills them through `add_audio.act` and the line goes; its toast's Undo (`actions.add_audio_undo`)
takes them back.

What a wrong answer would cost Mattias: no way to find the press (his text-only cards stay silent), a line asked again
at every look or for every part, a line on a book none of whose cards need it, a press that writes another book's
cards, or a line that goes though nothing was added (no second chance).

Real data: the add-audio suite's book (a real EPUB, its M4B and `.srt` paired and trusted in a real store, five
text-only cards Connect made), the fake Anki Miner as a child, the writer's fake Anki.
"""
import json

import pytest

from app.connect import actions, runner
from app.connect import sentence_audio as sa
from app.connect.ledger import Ledger
from tests.connect.test_add_audio import MAPPING, _act_book, book  # noqa: F401 (the fixture)


def _lined(book, ledger):  # noqa: F811
    """The pick step's line-up of the book's first part (`runner._line_up`, trusted: no sync)."""
    return runner._line_up(book["steps"], ledger, "ja", {"id": 1, "item_id": 999, "language": "ja", "asked_at": None},
                           (None, book["book"]))


def _offers(ledger):
    return [n for n in ledger.needs("ja") if n["kind"] == runner.ADD_AUDIO_NEED]


def test_a_book_lined_up_after_cards_were_made_offers_them_the_narrators_voice_once(book, tmp_path):  # noqa: F811
    """The first line-up: one line naming the book and its eight cards Connect made; a second look and a second part
    ask nothing more and write nothing."""
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert _lined(book, ledger) is not None
        [offer] = _offers(ledger)
        title = book["steps"].made_before("ja", book["book"])[0]
        assert offer["say"] == runner.ADD_AUDIO_ASK.format(title=title, n=8)
        assert offer["item_id"] == book["item"]
        before = ledger.conn.execute("SELECT * FROM needs").fetchall(), ledger.conn.execute("SELECT * FROM meta").fetchall()
        _lined(book, ledger)
        assert (ledger.conn.execute("SELECT * FROM needs").fetchall(),
                ledger.conn.execute("SELECT * FROM meta").fetchall()) == before


def test_a_book_with_no_cards_yet_is_never_offered_and_never_asked_later(book, tmp_path, monkeypatch):  # noqa: F811
    """Nothing made before its line-up (its cards will carry the narrator from the start): no line, and none later
    either — the book was asked once."""
    monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", 0))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        assert _offers(ledger) == []
        monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", 3))
        _lined(book, ledger)
        assert _offers(ledger) == []


def test_a_book_not_lined_up_offers_nothing(book, tmp_path, monkeypatch):  # noqa: F811
    """*Keep them together* (no sentence audio, as you said): no line-up, no offer."""
    from tests import connect_helpers as c
    with c.store("ja") as s:
        assert s.mark_audiobook_lineup(book["item"], book["rec"]["book"]["key"], "none") is True
        assert s.audiobook_keep_together(book["item"], book["rec"]["book"]["key"]) is True
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert _lined(book, ledger) is None and _offers(ledger) == []


def test_a_count_that_fails_never_stops_the_mine(book, tmp_path, monkeypatch):  # noqa: F811
    def broken(lang, epub):
        raise OSError("the library is busy")
    monkeypatch.setattr(book["steps"], "made_before", broken)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert _lined(book, ledger) is not None and _offers(ledger) == []


def test_the_press_fills_that_books_cards_and_the_line_goes_and_its_undo_takes_them_back(
        book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    owed = _act_book(book, fake_miner, monkeypatch, tmp_path)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        [offer] = _offers(ledger)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=str(tmp_path / "ledger.sqlite"))
    assert got["ok"] and got["filled"] == 5 and got["id"] and owed
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert _offers(ledger) == []
    assert all(book["anki"].value(100 + k).startswith("[sound:") for k in range(5))
    back = actions.add_audio_undo("ja", got["id"], {"connect_enabled": True})
    assert back == {"ok": True, "emptied": 5, "kept": 0, "say": None}
    assert all(book["anki"].value(100 + k) == "" for k in range(5))


def test_a_press_that_couldnt_keeps_the_line_and_says_why(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """You're reviewing in Anki: nothing written, the line stays (pressed again later, it asks again)."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    book["anki"].reviewing_ = True
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        [offer] = _offers(ledger)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=str(tmp_path / "ledger.sqlite"))
    assert got["ok"] is False and got["say"] == "You're reviewing in Anki. Add audio again when you're done."
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert [n["id"] for n in _offers(ledger)] == [offer["id"]]
    assert all(book["anki"].value(100 + k) == "" for k in range(5))


@pytest.mark.parametrize("which", ["fixed", "another language", "another kind", "no ledger"])
def test_a_press_on_a_line_no_longer_open_writes_nothing(book, fake_miner, tmp_path, monkeypatch, which):  # noqa: F811
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _lined(book, ledger)
        [offer] = _offers(ledger)
        if which == "fixed":
            ledger.conn.execute("UPDATE needs SET fixed_at = 'x' WHERE id = ?", (offer["id"],))
        elif which == "another kind":
            ledger.conn.execute("UPDATE needs SET kind = 'not-timed' WHERE id = ?", (offer["id"],))
    got = actions.add_audio("zh" if which == "another language" else "ja", offer["id"], {"connect_enabled": True},
                            path=str(tmp_path / "none.sqlite") if which == "no ledger" else path)
    assert got == {"ok": False, "say": None}
    assert not [c for c in book["anki"].calls if c[0] in ("store", "update", "tag")]


def test_the_toasts_undo_of_a_record_no_longer_there_says_so(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    got = actions.add_audio_undo("ja", "17-none", {"connect_enabled": True})
    assert got["ok"] is False and got["say"]
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert sa.record(ledger, "17-none") is None
    assert json.dumps(got)
