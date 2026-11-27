"""A book's line-up for its earlier cards — Connect's half (Kura-AB3 A2, cut down by AUDIO-FILL 3.0.21: the write is
Card sound's, `app/connect/card_sound.py`; PROVISIONAL): a book paired with its audiobook after Connect made cards from
it, not lined up yet, asks ONE standing *Needs you* line (`ADD_AUDIO_WAIT`), once; its press (`actions.add_audio` /
`actions.line_up`) asks *Mine now* on its first part, whose job lines it up. Once lined up — by a job or found by the
pass — nothing is asked: its line goes and Card sound's day memo is dropped (`card_sound.forget`), so *Add sound*'s
count holds those cards; the press on a line lined up meanwhile is Card sound's *Add sound*.

What a wrong answer would cost Mattias: no way to line the book up (his text-only cards stay silent), a line asked
again at every look or for every part, a line on a book none of whose cards need it, a line left after the book lined
up (a press for nothing), or Card sound's count that never sees the book's cards until tomorrow.

Real data: the add-audio suite's book (a real EPUB, its M4B and `.srt` paired and trusted in a real store, five
text-only cards Connect made), the fake Anki Miner as a child, the writer's fake Anki.
"""
import json
import os

import pytest

from app import library_store
from app.connect import actions, anki_miner, card_sound, library, runner
from app.connect import undo as undoing
from app.connect.ledger import Ledger
from tests.connect.test_add_audio import MAPPING, _act_book, book  # noqa: F401 (the fixture)
from tests.connect.test_lineup_own_subtitle import STAR

SEEN = card_sound.SEEN + "ja"
PRESSED = {"ok": True, "id": "r1", "real": 2, "not_cut": 0, "say": None}


def _lined(book, ledger):  # noqa: F811
    """The pick step's line-up of the book's first part (`runner._line_up`, trusted: no sync)."""
    return runner._line_up(book["steps"], ledger, "ja", {"id": 1, "item_id": 999, "language": "ja", "asked_at": None},
                           (None, book["book"]))


def _offers(ledger):
    return [n for n in ledger.needs("ja") if n["kind"] == runner.ADD_AUDIO_NEED]


def _seen(ledger):
    """Card sound's day memo as a pass of today left it (`recount`'s), beside its count."""
    card_sound._put_meta(ledger, SEEN, {"day": card_sound._today(), "kinds": {"100": card_sound.SILENT}})
    card_sound._put_meta(ledger, card_sound.COUNT + "ja", {"cards": 1, "real": 0, "ai": 0, "silent": 1, "at": "x"})


def _has_seen(ledger):
    return ledger.conn.execute("SELECT 1 FROM meta WHERE key = ?", (SEEN,)).fetchone() is not None


def _rows(ledger):
    return ledger.conn.execute("SELECT * FROM needs").fetchall(), ledger.conn.execute("SELECT * FROM meta").fetchall()


def _record(book, ledger):  # noqa: F811
    _title, _notes, sha = book["steps"].made_before("ja", book["book"])
    return json.loads(runner._meta(ledger, f"{runner.ADD_AUDIO_ASKED}ja:{runner.book_key(book['book'], sha)}")
                      or "null")


def _pressed(monkeypatch):
    """Card sound's *Add sound* stubbed: the calls it got (never Anki here)."""
    calls = []
    monkeypatch.setattr(card_sound, "press", lambda language, settings, **k: calls.append(language) or dict(PRESSED))
    return calls


def test_a_book_lined_up_by_its_job_asks_nothing_and_drops_card_sounds_day_memo_once(book, tmp_path):  # noqa: F811
    """The first line-up: no line (Card sound gives the cards their sound), the record kept `lined`, and today's day
    memo dropped so the pass's end counts the book's cards; a second part's line-up asks nothing and writes nothing —
    a memo made since stays."""
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _seen(ledger)
        assert _lined(book, ledger) is not None
        assert _offers(ledger) == [] and not _has_seen(ledger)
        assert card_sound._meta_json(ledger, card_sound.COUNT + "ja", {})["silent"] == 1, "the count kept"
        assert _record(book, ledger)["stage"] == runner.ADD_AUDIO_LINED
        _seen(ledger)
        before = _rows(ledger)
        _lined(book, ledger)
        assert _rows(ledger) == before


def test_a_book_with_no_cards_yet_is_never_offered_and_never_asked_later(book, tmp_path, monkeypatch):  # noqa: F811
    """Nothing made before its line-up (its cards will carry the narrator from the start): no line, and none later
    either — the book was looked at once."""
    monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", [], None))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        assert _offers(ledger) == []
        monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", [100, 101, 102], None))
        _lined(book, ledger)
        assert _offers(ledger) == []


def test_a_book_not_lined_up_offers_nothing(book, tmp_path, monkeypatch):  # noqa: F811
    """*Keep them together* (no sentence audio, as you said): no line-up, no line, Card sound's memo left alone."""
    from tests import connect_helpers as c
    with c.store("ja") as s:
        assert s.mark_audiobook_lineup(book["item"], book["rec"]["book"]["key"], "none") is True
        assert s.audiobook_keep_together(book["item"], book["rec"]["book"]["key"]) is True
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _seen(ledger)
        assert _lined(book, ledger) is None and _offers(ledger) == [] and _has_seen(ledger)


def test_a_count_that_fails_never_stops_the_mine(book, tmp_path, monkeypatch):  # noqa: F811
    def broken(lang, epub):
        raise OSError("the library is busy")
    monkeypatch.setattr(book["steps"], "made_before", broken)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert _lined(book, ledger) is not None and _offers(ledger) == []


# --- the lead's MUST: Mattias's books were all mined text-only before this ships ---------------------- #
def _mined_out(book, tmp_path):  # noqa: F811
    """The book fully mined: no part waits, no job open — only its earlier cards (the store's made words)."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        assert ledger.jobs("ja") == []
    return path


def test_a_fully_mined_book_lined_up_later_drops_the_memo_without_any_part_being_mined(book, tmp_path):  # noqa: F811
    """Red first: no part is picked again (every one was mined), yet the book is lined up (its own subtitle trusted,
    or a sync finished, or paired since) — Connect's pass asks nothing and drops Card sound's day memo, once."""
    path = _mined_out(book, tmp_path)
    with Ledger(path) as ledger:
        _seen(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and not _has_seen(ledger)
        assert _record(book, ledger)["stage"] == runner.ADD_AUDIO_LINED
        _seen(ledger)
        before = _rows(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")               # the next pass: once, nothing written
        assert _rows(ledger) == before


def _quiet_run(book, monkeypatch):  # noqa: F811
    """Connect's real loop (`runner.run`) on the book's steps, everything but the look kept still."""
    monkeypatch.setattr(runner, "_blocked", lambda steps, lang, job, asked=False: "held")
    monkeypatch.setattr(runner, "_after_mining", lambda *a, **k: False)
    monkeypatch.setattr(runner, "_finish_undos", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_consume", lambda *a, **k: False)
    monkeypatch.setattr(book["steps"], "update_staged", lambda: False)
    monkeypatch.setattr(book["steps"], "enabled", lambda: True)


def test_connects_run_looks_at_it_with_an_empty_queue(book, tmp_path, monkeypatch):  # noqa: F811
    """r2 B1, through the real loop (`runner.run`): no job open at all — Mattias's case after the update — and the
    lined-up book is looked at on the first look: Card sound's memo dropped, no line."""
    path = _mined_out(book, tmp_path)
    _quiet_run(book, monkeypatch)
    with Ledger(path) as ledger:
        _seen(ledger)
        runner.run({}, ["ja"], steps=book["steps"], ledger=ledger, sleep=lambda s: None, looks=1)
        assert _offers(ledger) == [] and not _has_seen(ledger)
        assert _record(book, ledger)["stage"] == runner.ADD_AUDIO_LINED


def test_a_book_not_lined_up_yet_is_asked_once_and_its_line_goes_once_it_is(book, tmp_path,
                                                                          monkeypatch):  # noqa: F811
    """r4: paired, able to be lined up, not yet (the speech model still downloading): one line now, worded so (its
    press lines it up), and a second look asks nothing more; once it is lined up the line is fixed and Card sound's
    memo dropped — and a look after writes nothing."""
    path = _mined_out(book, tmp_path)
    real = book["steps"].lined_up
    monkeypatch.setattr(book["steps"], "lined_up", lambda lang, epub: None)
    title = book["steps"].made_before("ja", book["book"])[0]
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        [offer] = _offers(ledger)
        assert offer["say"] == runner.ADD_AUDIO_WAIT.format(title=title) and offer["item_id"] == book["item"]
        assert _record(book, ledger)["stage"] == runner.ADD_AUDIO_WAITING
        before = _rows(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _rows(ledger) == before, "asked once"
        _seen(ledger)
        monkeypatch.setattr(book["steps"], "lined_up", real)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and not _has_seen(ledger)
        assert _record(book, ledger)["stage"] == runner.ADD_AUDIO_LINED
        before = _rows(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _rows(ledger) == before


def test_a_busy_library_or_a_failing_look_never_stops_the_pass(book, tmp_path, monkeypatch):  # noqa: F811
    path = _mined_out(book, tmp_path)

    def busy(lang, epub):
        raise runner.Wait(runner.LIBRARY_BUSY)
    monkeypatch.setattr(book["steps"], "lined_up", busy)
    with Ledger(path) as ledger:
        _seen(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and _has_seen(ledger)


def test_a_poor_line_up_drops_nothing(book, tmp_path, monkeypatch):  # noqa: F811
    """Mutant R3: a line-up that can't cut cards (grade C, the line kept) is no line-up: Card sound's memo stays."""
    monkeypatch.setattr(book["steps"], "line_up", lambda lang, job, epub: {"lineup": None, "line": "x",
                                                                           "item_id": book["item"]})
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _seen(ledger)
        _lined(book, ledger)
        assert _offers(ledger) == [] and _has_seen(ledger)


# --- the line's press (`actions.add_audio` -> `line_up`; lined up meanwhile: Card sound's *Add sound*) ----------- #
def _waiting_line(book, ledger, monkeypatch):  # noqa: F811
    """The book's waiting line asked (its line-up read as not yet), then the line-up back as it is (lined up since,
    the pass not looked again) -> the line."""
    real = book["steps"].lined_up
    monkeypatch.setattr(book["steps"], "lined_up", lambda lang, epub: None)
    runner._add_audio_offers(book["steps"], ledger, "ja")
    monkeypatch.setattr(book["steps"], "lined_up", real)
    [offer] = [n for n in _offers(ledger) if n["item_id"] == book["item"]]
    return offer


def test_the_press_on_a_book_lined_up_meanwhile_fixes_its_line_and_is_card_sounds_add_sound(
        book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Lined up since its line came: the press fixes the line, drops Card sound's memo, and is Card sound's *Add
    sound* (its answer, `sound` marked, the book's title) — Connect writes nothing in Anki itself."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    calls = _pressed(monkeypatch)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        offer = _waiting_line(book, ledger, monkeypatch)
        _seen(ledger)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=path)
    assert got == dict(PRESSED, sound=True, title=book["steps"].made_before("ja", book["book"])[0])
    assert calls == ["ja"]
    with Ledger(path) as ledger:
        assert _offers(ledger) == [] and not _has_seen(ledger)
    assert not [c for c in book["anki"].calls if c[0] in ("store", "update", "tag")]
    assert fake_miner.commands() == []


def test_two_books_asked_each_press_fixes_its_own_line(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A1: another book's line open beside this one — this line's press never fixes the other book's."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    _pressed(monkeypatch)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (
            f"{runner.ADD_AUDIO_ASKED}ja:zzz:other", json.dumps({"epub": "D:/Books/other.epub", "item": 77,
                                                                  "title": "other", "stage": "waiting"})))
        ledger.need("ja", runner.ADD_AUDIO_NEED, "other", item_id=77, standing=True)
        offer = _waiting_line(book, ledger, monkeypatch)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=path)
    assert got["ok"] and got["sound"]
    with Ledger(path) as ledger:
        assert [n["item_id"] for n in _offers(ledger)] == [77]


@pytest.mark.parametrize("which", ["fixed", "another language", "another kind", "no ledger"])
def test_a_press_on_a_line_no_longer_open_does_nothing(book, fake_miner, tmp_path, monkeypatch, which):  # noqa: F811
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    calls = _pressed(monkeypatch)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        offer = _waiting_line(book, ledger, monkeypatch)
        if which == "fixed":
            ledger.conn.execute("UPDATE needs SET fixed_at = 'x' WHERE id = ?", (offer["id"],))
        elif which == "another kind":
            ledger.conn.execute("UPDATE needs SET kind = 'not-timed' WHERE id = ?", (offer["id"],))
    got = actions.add_audio("zh" if which == "another language" else "ja", offer["id"], {"connect_enabled": True},
                            path=str(tmp_path / "none.sqlite") if which == "no ledger" else path)
    assert got == {"ok": False, "say": None}
    assert calls == [] and not [c for c in book["anki"].calls if c[0] in ("store", "update", "tag")]


def test_connect_off_says_so_and_keeps_the_line(book, fake_miner, tmp_path, monkeypatch):  # noqa: F811
    """Mutant A3: Connect switched off since the line came: its words, nothing written, the line and the memo stay."""
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    calls = _pressed(monkeypatch)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        offer = _waiting_line(book, ledger, monkeypatch)
        _seen(ledger)
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": False}, path=path)
    assert got == {"ok": False, "say": undoing.PREVIEW_OFF} and calls == []
    with Ledger(path) as ledger:
        assert len(_offers(ledger)) == 1 and _has_seen(ledger)


def test_the_books_line_stays_when_its_audiobooks_own_job_ends(book, tmp_path, monkeypatch):  # noqa: F811
    """r1 S6: the line sits on the audiobook's item; that item's own job ending (an audiobook mined from its own
    transcript) fixes its needs — never this line, which is asked only once."""
    path = _mined_out(book, tmp_path)
    _waiting(book, monkeypatch)
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
    _waiting(book, monkeypatch)
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


# --- review A2 round 4 B1: the pass starts nothing; the press lines a book up through its first part's Mine now -- #
def test_a_mined_out_book_not_lined_up_starts_nothing_and_is_offered(book, tmp_path, monkeypatch,
                                                                     fake_miner):  # noqa: F811
    """No trust, no job: the pass never listens and never syncs (only a job does, seen and stoppable on its row) — and
    the book's line comes all the same, worded for a book its press lines up."""
    from tests.connect.test_lineup_own_subtitle import _trust
    _trust(monkeypatch, book, on=False)
    monkeypatch.setattr(anki_miner, "_SPEECH", {})   # (its answers are kept for a Connect run: never another test's)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    with Ledger(_mined_out(book, tmp_path)) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        [offer] = _offers(ledger)
        assert offer["say"] == runner.ADD_AUDIO_WAIT.format(title=book["steps"].made_before("ja", book["book"])[0])
        assert [n["kind"] for n in ledger.needs("ja")] == [runner.ADD_AUDIO_NEED]
    assert fake_miner.commands() == []


def test_the_press_on_a_book_not_lined_up_asks_its_first_parts_mine_now_and_writes_nothing(book, fake_miner,
                                                                                           tmp_path,
                                                                                           monkeypatch):  # noqa: F811
    """Its line's press and the command line's `line_up` alike: the first part to mine (its job lines the book up),
    in words; the line stays, nothing in Anki, Card sound not asked, nothing started."""
    from tests.connect.test_lineup_own_subtitle import _trust
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    calls = _pressed(monkeypatch)
    _trust(monkeypatch, book, on=False)
    monkeypatch.setattr(anki_miner, "_SPEECH", {})
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        [offer] = _offers(ledger)
        _seen(ledger)
    first = book["steps"].first_part("ja", book["book"])
    got = actions.add_audio("ja", offer["id"], {"connect_enabled": True}, path=path)
    assert got["ok"] is False and got["line_up"] == first and first is not None
    assert got["say"] == actions.LINE_UP_FIRST.format(title=got["title"])
    direct = actions.line_up("ja", book["book"], {"connect_enabled": True}, path=path)    # (the command line's)
    assert direct["ok"] is False and direct["line_up"] == first
    assert direct["say"] == actions.LINE_UP_FIRST.format(title=direct["title"])
    with Ledger(path) as ledger:
        assert [n["id"] for n in _offers(ledger)] == [offer["id"]] and _has_seen(ledger)
    assert calls == [] and not [c for c in book["anki"].calls if c[0] in ("store", "update", "tag")]
    assert fake_miner.commands() == []


def test_a_book_kept_together_or_never_found_in_its_audio_is_never_offered(book, fake_miner, tmp_path,
                                                                           monkeypatch):  # noqa: F811
    """*Keep them together* (no sentence audio, as you said), or a sync that found nothing: no line, and `line_up`
    has nothing to line up."""
    from tests import connect_helpers as c
    from tests.connect.test_lineup_own_subtitle import _trust
    _act_book(book, fake_miner, monkeypatch, tmp_path)
    _trust(monkeypatch, book, on=False)
    with c.store("ja") as s:
        assert s.mark_audiobook_lineup(book["item"], book["rec"]["book"]["key"], "none") is True
    path = _mined_out(book, tmp_path)
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == []
    assert actions.line_up("ja", book["book"], {"connect_enabled": True}, path=path) == {"ok": False, "say": None}


def test_a_mined_out_book_with_no_cards_is_never_offered(book, tmp_path, monkeypatch, fake_miner):  # noqa: F811
    """Nothing Connect made from it: no line (its cards will come with the narrator), nothing written, nothing
    started."""
    from tests.connect.test_lineup_own_subtitle import _trust
    _trust(monkeypatch, book, on=False)
    monkeypatch.setattr(book["steps"], "made_before", lambda lang, epub: ("星屑", [], None))
    with Ledger(_mined_out(book, tmp_path)) as ledger:
        before = _rows(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and _rows(ledger) == before
    assert fake_miner.commands() == []


# --- review A2 round 5 --------------------------------------------------------------------------------------------- #
def _waiting(book, monkeypatch):  # noqa: F811
    """Not lined up yet (no trust, nothing heard): a part's job would line it up."""
    from tests.connect.test_lineup_own_subtitle import _trust
    _trust(monkeypatch, book, on=False)
    monkeypatch.setattr(anki_miner, "_SPEECH", {})


@pytest.mark.parametrize("why", ["poor sync", "speech no", "audio away", "no books"])
def test_a_book_its_job_wouldnt_line_up_is_never_offered(book, tmp_path, monkeypatch, why):  # noqa: F811
    """r5 S1: the cases where a part's job gives up quietly — a sync kept at grade C, *Not now* to the speech model,
    the audio not on this computer, an Anki Miner that doesn't mine books — offer nothing (never a press that asks
    *Mine now* for ever)."""
    from app.connect import lineup
    _waiting(book, monkeypatch)
    key = book["rec"]["book"]["key"]
    if why == "poor sync":
        lineup.write(key, {"status": lineup.DONE, "grade": "C", "files": []})
    elif why == "speech no":
        lineup.set_answer(False)
    elif why == "audio away":
        monkeypatch.setattr(runner, "_on_disk", lambda path: not str(path).lower().endswith(".m4b"))
    else:
        monkeypatch.setattr(book["steps"], "mines", lambda lang, kind: kind != "books")
    try:
        assert book["steps"].lineable("ja", book["book"]) is False
        with Ledger(_mined_out(book, tmp_path)) as ledger:
            runner._add_audio_offers(book["steps"], ledger, "ja")
            assert _offers(ledger) == []
    finally:
        lineup.clear_answer()


def test_a_waiting_line_goes_once_the_book_cant_be_lined_up(book, tmp_path, monkeypatch):  # noqa: F811
    """r5 S2: offered while it could be lined up; then *Keep them together* — the line goes (never "line it up" for
    good) and isn't asked again."""
    from tests import connect_helpers as c
    _waiting(book, monkeypatch)
    with Ledger(_mined_out(book, tmp_path)) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert len(_offers(ledger)) == 1
        with c.store("ja") as s:
            assert s.mark_audiobook_lineup(book["item"], book["rec"]["book"]["key"], "none") is True
            assert s.audiobook_keep_together(book["item"], book["rec"]["book"]["key"]) is True
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and _record(book, ledger)["stage"] == runner.ADD_AUDIO_GONE
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == []


def test_cards_made_while_it_waited_are_kept_and_a_jobs_line_up_fixes_its_line(book, tmp_path,
                                                                             monkeypatch):  # noqa: F811
    """r5 S3 + the job's path: asked while waiting; a part mined meanwhile (as the book: text-only) adds its card;
    then a part's job lines it up (`_line_up`) — the line is fixed, Card sound's memo dropped, and the record holds
    every card made before, the new one too."""
    from app.connect import add_audio, library
    from tests.connect.test_lineup_own_subtitle import _trust
    _waiting(book, monkeypatch)
    path = _mined_out(book, tmp_path)
    with Ledger(path) as ledger:
        runner._add_audio_offers(book["steps"], ledger, "ja")
        [_offer] = _offers(ledger)
        _seen(ledger)
    with book["steps"]._open("ja") as store:
        parts = add_audio.book_items(store, book["book"])
        library.record_batch(store, parts[0], {"meanwhile": [500]}, "2026-11-10T00:00:00Z")
    _trust(monkeypatch, book)
    with Ledger(path) as ledger:
        assert runner._line_up(book["steps"], ledger, "ja", {"id": 1, "item_id": parts[0], "language": "ja",
                                                             "asked_at": None}, (None, book["book"])) is not None
        assert _offers(ledger) == [] and not _has_seen(ledger)
        rec = _record(book, ledger)
        assert 500 in rec["notes"] and rec["stage"] == runner.ADD_AUDIO_LINED


def test_a_line_up_given_up_is_never_offered(book, tmp_path, monkeypatch):  # noqa: F811
    """Mutant W8: Anki Miner failed TRIES times running on it — given up, not offered (its press would ask for ever)."""
    from app.connect import lineup
    _waiting(book, monkeypatch)
    lineup.write(book["rec"]["book"]["key"], {"status": lineup.FAILED, "tries": lineup.TRIES})
    assert book["steps"].lineable("ja", book["book"]) is False
    lineup.write(book["rec"]["book"]["key"], {"status": lineup.FAILED, "tries": lineup.TRIES - 1})
    assert book["steps"].lineable("ja", book["book"]) is True


# --- Kura-AB5: an earlier copy's cards (based on the diagnosis in #431 by Mattias, a 3.0.8 preview; PROVISIONAL) ---- #
# His カラフル: 40 cards made from the book's 2.x `.txt` parts; the parts removed, the book added again as its
# EPUB — every word carded already, so the EPUB made none; the record counted the live parts only and froze with no
# card. Now Card sound gives those cards their sound: a record from then is looked at once more (Card sound's memo
# dropped), never asked as a line.

def _removed_parts(book, name, notes, folder="old 2x"):  # noqa: F811
    """A 2.x split copy `<name>_01.txt`, `<name>_02.txt` (the book's own sentences) read by a look, its first
    part's cards `notes` made by Connect (text-only, each a sentence of the book), then removed -> (its item ids, trash
    ids)."""
    from tests.test_audiobook_items import _settle
    from tests.test_sources_scan import _book_text, _drive, _look, _write
    top = _drive(folder)
    paths = [_write(os.path.join(top, name, f"{name}_{n:02d}.txt"),        # (a part worth reading: T2-B4's length)
                    "\n".join([name] + book["lines"][n * 4:n * 4 + 4] + [_book_text("ja")])) for n in (1, 2)]
    _settle(*paths)
    with book["steps"]._open("ja") as store:
        _look(store, "ja", store.add_source(top))
        keys = {library_store.origin_key(os.path.abspath(p)) for p in paths}
        ids = sorted({i for k, i in store.conn.execute("SELECT content_key, item_id FROM pairings") if k in keys})
        assert len(ids) == 2
        for k, note in enumerate(notes):
            line = book["lines"][4 + k]
            book["anki"].add(note, f"<b>{line[:2]}</b>" + line[2:], line[:2])
        library.record_batch(store, ids[0], {f"old{k}": [n] for k, n in enumerate(notes)}, "2026-10-01T00:00:00Z")
        store.remove(ids)
        trash = [r[0] for r in store.conn.execute("SELECT id FROM trash WHERE item_id IN (?, ?)", ids)]
    return ids, trash


def _asked(book, ledger):  # noqa: F811
    _title, _notes, sha = book["steps"].made_before("ja", book["book"])
    key = f"{runner.ADD_AUDIO_ASKED}ja:{runner.book_key(book['book'], sha)}"
    return key, json.loads(runner._meta(ledger, key) or "null")


def test_a_book_asked_with_no_card_is_looked_at_once_more_for_its_earlier_copys_cards(book, tmp_path):  # noqa: F811
    """#431, his state: the record 3.0.8 froze — lined up, no card. The next pass looks ONCE more: the earlier copy's
    cards kept in the record, Card sound's memo dropped (its count plans them), no line asked; a pass after writes
    nothing; the book's line-up places those cards by their sentences."""
    from app.connect import add_audio
    _removed_parts(book, STAR, [400, 401, 402])
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        key, _none = _asked(book, ledger)
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(
            {"epub": book["book"], "item": book["item"], "title": STAR, "notes": [], "stage": runner.ADD_AUDIO_LINED})))
        ledger.conn.commit()
        _seen(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and not _has_seen(ledger)
        _key, rec = _asked(book, ledger)
        assert {400, 401, 402} <= set(rec["notes"]) and rec["stage"] == runner.ADD_AUDIO_LINED and rec["earlier"]
        _seen(ledger)
        before = _rows(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _rows(ledger) == before, "looked at once"
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert {400, 401, 402} <= set(got["can"]), "placed in the book's line-up by their sentences"


def test_a_book_asked_with_no_card_and_no_earlier_copy_is_never_looked_at_again(book, tmp_path):  # noqa: F811
    """No earlier copy's card either: the once-more look writes the record (`earlier`), raises no line, and the
    record is never looked at again — an earlier copy removed after drops nothing."""
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        key, _none = _asked(book, ledger)
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(
            {"epub": book["book"], "item": book["item"], "title": STAR, "notes": [], "stage": runner.ADD_AUDIO_LINED})))
        ledger.conn.commit()
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == []
        _key, rec = _asked(book, ledger)
        assert rec["earlier"] is True and rec["stage"] == runner.ADD_AUDIO_LINED
        _removed_parts(book, STAR, [400])                # removed after: the book was looked at already
        _seen(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and _has_seen(ledger)


def test_the_first_look_counts_an_earlier_copys_cards_with_the_books_own(book, tmp_path):  # noqa: F811
    """No record yet (the copy removed before the EPUB lined up): the first line-up's record names the book's cards
    and the earlier copy's, together — and asks no line."""
    _removed_parts(book, STAR, [400, 401])
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        _lined(book, ledger)
        assert _offers(ledger) == []
        _key, rec = _asked(book, ledger)
        assert {100, 400, 401} <= set(rec["notes"]) and rec["earlier"] is True


def test_earlier_copies_are_the_removed_2x_parts_of_this_book_only(book):  # noqa: F811
    """Only the book's own earlier copy: the removed `<the EPUB's name>_NN.txt` (any case, full-width alike); never a
    name that only starts alike, another book's, nor one put back (a live item: the book's own rule)."""
    from app.connect import add_audio
    mine, _t = _removed_parts(book, STAR, [400])
    alike, _t2 = _removed_parts(book, STAR + "外伝", [410], folder="gaiden")
    other, _t3 = _removed_parts(book, "銀河鉄道の夜", [420], folder="ginga")
    back, trash = _removed_parts(book, STAR.replace("！", "!"), [430], folder="halfwidth")
    with book["steps"]._open("ja") as store:
        assert add_audio.earlier_copies(store, book["book"]) == sorted(mine + back), "NFKC: ！ and ! alike"
        store.restore(trash)
        assert add_audio.earlier_copies(store, book["book"]) == sorted(mine), "put back: live, never an earlier copy"
        assert not set(alike + other) & set(add_audio.book_items(store, book["book"]))
        assert add_audio.earlier_copies(store, os.path.join(os.path.dirname(book["book"]), "nothing.epub")) == []


def test_earlier_copies_go_by_the_epubs_file_name_and_by_the_books_title(book, monkeypatch):  # noqa: F811
    """His EPUB's file name is not its title (`カラフル (文春文庫) - 森 絵都 epub.epub` holds 「カラフル」): 2.x named its
    parts by what he typed — the file's name or the title; both are this book's."""
    from app.connect import add_audio
    by_file, _t = _removed_parts(book, STAR, [400])
    by_title, _t2 = _removed_parts(book, "カラフル", [410], folder="title")
    real = library.book_of
    monkeypatch.setattr(library, "book_of", lambda store, epub: dict(real(store, epub), title="カラフル"))
    with book["steps"]._open("ja") as store:
        assert add_audio.earlier_copies(store, book["book"]) == sorted(by_file + by_title)


def test_a_book_asked_with_no_card_not_lined_up_now_is_left_as_it_was(book, tmp_path, monkeypatch):  # noqa: F811
    """Its line-up gone meanwhile (separated, a sync failed): the once-more look waits for it — the record is never
    given up for that (it would never be looked at again) and nothing is written."""
    _removed_parts(book, STAR, [400])
    monkeypatch.setattr(book["steps"], "lined_up", lambda lang, epub: None)
    monkeypatch.setattr(book["steps"], "lineable", lambda lang, epub: False)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        key, _none = _asked(book, ledger)
        was = json.dumps({"epub": book["book"], "item": book["item"], "title": STAR, "notes": [],
                          "stage": runner.ADD_AUDIO_LINED})
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, was))
        ledger.conn.commit()
        _seen(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert runner._meta(ledger, key) == was and _offers(ledger) == [] and _has_seen(ledger)


def test_a_book_asked_with_its_own_cards_is_looked_at_once_more_when_an_earlier_copy_had_more(book, tmp_path,  # noqa: F811
                                                                                              monkeypatch):
    """Review r1 S4: the EPUB made two cards before it lined up, so 3.0.8 froze the record with those — the 2.x copy's
    cards were never counted. Looked at once more: the earlier copy's are in its list, Card sound's memo dropped, no
    line; a pass after writes nothing."""
    _removed_parts(book, STAR, [400, 401])
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        key, _none = _asked(book, ledger)
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(
            {"epub": book["book"], "item": book["item"], "title": STAR, "notes": [100, 101],
             "stage": runner.ADD_AUDIO_LINED})))
        ledger.conn.commit()
        _seen(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _offers(ledger) == [] and not _has_seen(ledger)
        _key, rec = _asked(book, ledger)
        assert {100, 101, 400, 401} <= set(rec["notes"]) and rec["earlier"] is True
        before = _rows(ledger)
        runner._add_audio_offers(book["steps"], ledger, "ja")
        assert _rows(ledger) == before


def test_earlier_copies_never_count_a_part_of_this_very_epub_given_up(book):  # noqa: F811
    """Review r2 N1: the EPUB's own parts are named `<name>_NN.txt` too — one removed is no earlier copy (its cards
    were counted while it was live; those mined since its line-up carry the narrator)."""
    from app import library_store as ls
    from app.connect import add_audio
    with book["steps"]._open("ja") as store:
        parts = add_audio.book_items(store, book["book"], earlier=False)
        rel = store.conn.execute("SELECT rel_path FROM items WHERE id = ?", (parts[-1],)).fetchone()[0]
        assert ls._SPLIT_PART.fullmatch(rel.replace("\\", "/").rpartition("/")[2]), rel
        store.remove([parts[-1]])
        assert add_audio.earlier_copies(store, book["book"]) == []
