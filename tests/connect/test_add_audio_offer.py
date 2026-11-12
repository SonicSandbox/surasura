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
    monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", [], None))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        assert _offers(ledger) == []
        monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", [100, 101, 102], None))
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


# --- the lead's MUST (2026-11-12): Mattias's books were all mined text-only before this ships ---------------------- #
def _mined_out(book, tmp_path):  # noqa: F811
    """The book fully mined: no part waits, no job open — only its earlier cards (the store's made words)."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        assert ledger.jobs("ja") == []
    return path


def test_a_fully_mined_book_lined_up_later_is_offered_without_any_part_being_mined(book, tmp_path):  # noqa: F811
    """Red first: no part is picked again (every one was mined), yet the book is lined up (its own subtitle trusted,
    or a sync finished, or paired since) — Connect's pass offers its cards the narrator's voice, once."""
    path = _mined_out(book, tmp_path)
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        [offer] = _offers(ledger)
        title = book["steps"].made_before("ja", book["book"])[0]
        assert offer["item_id"] == book["item"] and offer["say"] == runner.ADD_AUDIO_ASK.format(title=title)
        before = ledger.conn.execute("SELECT * FROM needs").fetchall(), ledger.conn.execute("SELECT * FROM meta").fetchall()
        runner._add_audio_offers(book["steps"], ledger, "ja")               # the next pass: asked once, nothing written
        assert (ledger.conn.execute("SELECT * FROM needs").fetchall(),
                ledger.conn.execute("SELECT * FROM meta").fetchall()) == before


def _quiet_run(book, monkeypatch):  # noqa: F811
    """Connect's real loop (`runner.run`) on the book's steps, everything but the offer kept still."""
    monkeypatch.setattr(runner, "_blocked", lambda steps, lang, job, asked=False: "held")
    monkeypatch.setattr(runner, "_after_mining", lambda *a, **k: False)
    monkeypatch.setattr(runner, "_finish_undos", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_consume", lambda *a, **k: False)
    monkeypatch.setattr(book["steps"], "update_staged", lambda: False)
    monkeypatch.setattr(book["steps"], "enabled", lambda: True)


def test_connects_run_offers_it_with_an_empty_queue(book, tmp_path, monkeypatch):  # noqa: F811
    """r2 B1, through the real loop (`runner.run`): no job open at all — Mattias's case after the update — and the
    line is raised at its first look."""
    path = _mined_out(book, tmp_path)
    _quiet_run(book, monkeypatch)
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=book["steps"], ledger=ledger, sleep=lambda s: None, looks=1)
        assert len(_offers(ledger)) == 1


def test_a_book_not_lined_up_yet_is_asked_once_it_is(book, tmp_path, monkeypatch):  # noqa: F811
    """Paired but not lined up (the speech model still downloading): nothing asked and nothing kept — the pass after
    it lines up asks."""
    path = _mined_out(book, tmp_path)
    real = book["steps"].lined_up
    monkeypatch.setattr(book["steps"], "lined_up", lambda lang, epub: None)
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and not ledger.conn.execute(
            "SELECT 1 FROM meta WHERE key LIKE ?", (runner.ADD_AUDIO_ASKED + "%",)).fetchone()
        monkeypatch.setattr(book["steps"], "lined_up", real)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert len(_offers(ledger)) == 1


def test_a_busy_library_or_a_failing_look_never_stops_the_pass(book, tmp_path, monkeypatch):  # noqa: F811
    path = _mined_out(book, tmp_path)

    def busy(lang, epub):
        raise runner.Wait(runner.LIBRARY_BUSY)
    monkeypatch.setattr(book["steps"], "lined_up", busy)
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == []


def test_a_poor_line_up_offers_nothing(book, tmp_path, monkeypatch):  # noqa: F811
    """Mutant R3: a line-up that can't cut cards (grade C, the line kept) is no offer."""
    monkeypatch.setattr(book["steps"], "line_up", lambda lang, job, epub: {"lineup": None, "line": "x",
                                                                           "item_id": book["item"]})
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        assert _offers(ledger) == []


def test_two_books_offered_each_press_fills_its_own(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A1: another book's line open beside this one — this line's press never takes the other book."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (
            f"{runner.ADD_AUDIO_ASKED}ja:zzz:other", json.dumps({"epub": "D:/Books/other.epub", "item": 77,
                                                                  "title": "other"})))
        ledger.need("ja", runner.ADD_AUDIO_NEED, "other", item_id=77, standing=True)
        _lined(book, ledger)
        offer = next(n for n in _offers(ledger) if n["item_id"] == book["item"])
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=path)
    assert got["ok"] and got["filled"] == 5


def test_nothing_filled_though_some_could_keeps_the_line(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A2: every card filled by you meanwhile (the writer skips them all): nothing was added — the line stays."""
    from app.connect import add_audio
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _lined(book, ledger)
        [offer] = _offers(ledger)
    monkeypatch.setattr(add_audio, "act", lambda *a, **k: {"can": 5, "filled": 0, "id": None, "not_cut": 0})
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=path)
    assert got["ok"] is False and got["say"]
    with Ledger(path) as ledger:
        assert [n["id"] for n in _offers(ledger)] == [offer["id"]]


def test_connect_off_says_so_and_keeps_the_line(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A3: Connect switched off since the line came: its words, nothing written, the line stays."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _lined(book, ledger)
        [offer] = _offers(ledger)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": False}, path=path)
    assert got == {"ok": False, "say": "connect preview off"}
    with Ledger(path) as ledger:
        assert len(_offers(ledger)) == 1


def test_undo_counts_a_card_you_changed_since_as_kept(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A6: you changed one card's audio after the press — Undo keeps it and says so."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _lined(book, ledger)
        [offer] = _offers(ledger)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=path)
    book["anki"].notes_[100]["fields"]["SentenceAudio"]["value"] = "[sound:mine.mp3]"
    back = actions.add_audio_undo("ja", got["id"], {"connect_enabled": True})
    assert back["emptied"] == 4 and back["kept"] == 1


# --- the book row's ⋯ (Connect's half): whenever such cards exist and a line-up is ready ------------------------- #
def test_the_rows_offer_names_the_book_and_its_cards_not_offered_yet(book, tmp_path):  # noqa: F811
    """A row of the book's parts: the book, its title, how many of its Connect cards no press has looked at yet."""
    with book["steps"]._open("ja") as store:
        from app.connect import add_audio
        parts = add_audio.book_items(store, book["book"])
    got = actions.add_audio_offer("ja", parts[:1], {"connect_enabled": True}, steps=book["steps"],
                                  path=str(tmp_path / "ledger.sqlite"))
    assert got["epub"] == book["book"] and got["n"] == 8 and got["title"]


def test_the_rows_offer_is_none_for_another_row_a_book_not_lined_up_or_connect_off(book, tmp_path,
                                                                                    monkeypatch):  # noqa: F811
    path = str(tmp_path / "ledger.sqlite")
    assert actions.add_audio_offer("ja", [book["item"] + 999], {"connect_enabled": True}, steps=book["steps"],
                                   path=path) is None
    with book["steps"]._open("ja") as store:
        from app.connect import add_audio
        parts = add_audio.book_items(store, book["book"])
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": False}, steps=book["steps"], path=path) is None
    monkeypatch.setattr(book["steps"], "lined_up", lambda lang, epub: None)
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": True}, steps=book["steps"], path=path) is None


def test_after_a_press_the_row_offers_nothing_more_until_new_cards_come(book, fake_miner, tmp_path,
                                                                         monkeypatch):  # noqa: F811
    """Never nagging: once pressed (from the row or the line), the cards it looked at are offered no more; the
    book's line is fixed too."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _lined(book, ledger)
    with book["steps"]._open("ja") as store:
        from app.connect import add_audio
        parts = add_audio.book_items(store, book["book"])
    got = actions.add_audio_book("ja", book["book"], {"connect_enabled": True}, path=path)
    assert got["ok"] and got["filled"] == 5
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": True}, steps=book["steps"], path=path) is None
    with Ledger(path) as ledger:
        assert _offers(ledger) == []


def test_the_books_line_stays_when_its_audiobooks_own_job_ends(book, tmp_path, monkeypatch):  # noqa: F811
    """r1 S6: the line sits on the audiobook's item; that item's own job ending (an audiobook mined from its own
    transcript) fixes its needs — never this line, which is asked only once."""
    path = _mined_out(book, tmp_path)
    monkeypatch.setattr(runner, "_blocked", lambda steps, lang, job, asked=False: None)
    monkeypatch.setattr(runner, "_after_mining", lambda *a, **k: False)
    for name in ("mine_line", "store_id"):
        monkeypatch.setattr(book["steps"], name, lambda lang: [])
    monkeypatch.setattr(book["steps"], "prepare", lambda lang, ledger: None)
    monkeypatch.setattr(runner, "_job", lambda steps, ledger, lang, job, *a: ledger.set_state(job["id"], "done"))
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        [offer] = _offers(ledger)
        assert ledger.queue("ja", book["item"], "look", None) is not None
        runner._language(book["steps"], ledger, "ja", set(), {}, {"needs": []})
        assert ledger.jobs("ja", states=("done",)) and [n["id"] for n in _offers(ledger)] == [offer["id"]]


def test_a_moved_book_is_the_same_book_asked_once(book, tmp_path, monkeypatch):  # noqa: F811
    """r1 S1: the book's key is its EPUB's bytes — the same book at another path is never asked again."""
    path = _mined_out(book, tmp_path)
    real = book["steps"].made_before
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert len(_offers(ledger)) == 1
        ledger.conn.execute("UPDATE needs SET fixed_at = 'x'")
        moved = book["book"].replace(".epub", " (moved).epub")
        monkeypatch.setattr(book["steps"], "paired_books", lambda lang: [(moved, book["item"], real(
            "ja", book["book"])[2])])
        monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: real(lang, book["book"]))
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == []


def test_the_seen_record_is_merged_never_replaced_and_cards_mined_since_are_never_offered(  # noqa: F811
        book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """r2 B2: a press, then a part mined after the line-up (its cards carry the narrator already), then a press that
    finds nothing to fill — the row offers nothing, for good: the record kept what each press looked at, and only the
    cards made before the line-up are ever offered."""
    from app.connect import add_audio, library
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")         # asked: the 8 cards made before it lined up
    with book["steps"]._open("ja") as store:
        parts = add_audio.book_items(store, book["book"])
    assert actions.add_audio_book("ja", book["book"], {"connect_enabled": True}, path=path)["filled"] == 5
    with book["steps"]._open("ja") as store:                          # a part mined since, with the narrator's voice
        library.record_batch(store, parts[0], {"later": [400]}, "2026-11-12T00:00:00Z")
    book["anki"].add(400, book["lines"][9], book["lines"][9][:2], audio="[sound:surasura-sa-x.mp3]")
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": True}, steps=book["steps"], path=path) is None
    got = actions.add_audio_book("ja", book["book"], {"connect_enabled": True}, path=path)
    assert got["ok"] is False and "sentence audio already" in got["say"]
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": True}, steps=book["steps"], path=path) is None


def test_a_press_stopped_part_way_answers_its_undo_in_the_windows_words(book, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A7: Anki stopped answering after some cards were written — the answer carries the Undo's id and plain
    words (never the command line's), and the book isn't marked looked at (the rest are offered again)."""
    from app.cli.contract import CliError
    from app.connect import add_audio

    def stops(*a, **k):
        raise CliError("anki-closed", "x", undo="17-ab", why="Anki isn't open")
    monkeypatch.setattr(add_audio, "act", stops)
    got = actions.add_audio_book("ja", book["book"], {"connect_enabled": True}, path=str(tmp_path / "ledger.sqlite"))
    assert got["ok"] is False and got["id"] == "17-ab" and "Undo takes them back" in got["say"]
    assert "surasura-cli" not in got["say"] and "Anki isn't open" in got["say"]


def test_a_press_with_nothing_to_fill_still_ends_the_rows_offer(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant S3: every card already has audio (you added it yourself) — the one press says so, and the row offers
    nothing more (that press looked at them all)."""
    from app.connect import add_audio
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    path = str(tmp_path / "ledger.sqlite")
    for k in range(5):
        book["anki"].notes_[100 + k]["fields"]["SentenceAudio"]["value"] = "[sound:yours.mp3]"
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
    with book["steps"]._open("ja") as store:
        parts = add_audio.book_items(store, book["book"])
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": True}, steps=book["steps"], path=path)["n"] == 8
    got = actions.add_audio_book("ja", book["book"], {"connect_enabled": True}, path=path)
    assert got["ok"] is False and "6 have sentence audio already" in got["say"]
    assert actions.add_audio_offer("ja", parts, {"connect_enabled": True}, steps=book["steps"], path=path) is None
