"""A book about to be mined with no audiobook paired asks first — Kura-AB2 (Mattias's 3.0.0 field report, issue 3:
"It's mining my book now. I didn't get to tell it I have an audiobook it can use with Anki Miner … It's just creating a
bunch of text-only cards (no audio)"). Lean (PROVISIONAL): ONE *Needs you* question a book — *Do you have 「…」's
audiobook?* · *Pick its audiobook…* / *Mine without audio* — remembered per book; never a book already paired, never
when the speech model was declined or Anki Miner can't line books up.

What a wrong answer would cost: a book mined before the question is hundreds of cards without sentence audio that
never get it later (a word Connect made is never made again); a question per part floods *Needs you* (a book is dozens
of parts); a question asked again after *Mine without audio* nags; a question for a book already paired, or with no way
to use the answer (no `sync`, the model declined), holds the learner's cards back for nothing.

Real data: a real EPUB (吾輩は猫である, the suite's Japanese sentences) and a real folder of tagged chapter MP3s whose
album names the book another way (an English title: Hon's look leaves it alone, as a learner's own rip often is), read
by a real look into a real store; Anki Miner is the suite's fake, taught 3.11's `sync`.
"""
import os

import pytest

from app.connect import actions, lineup, runner
from app.connect.ledger import Ledger
from app.services import needs
from tests.connect.test_lineup import LINE_UP_311, NEKO, _job, _record_miner, _until, no_child_left  # noqa: F401
from tests.test_audiobook_items import _audio_folder, _audio_items, _epub, _fit, _record
from tests.test_sources_scan import _drive, _empty, _look


@pytest.fixture
def lone(tmp_path, fake_miner, monkeypatch):
    """A real EPUB in the library and, in another folder, its audiobook under an English album name — the look
    leaves the audiobook alone (no title in common: neither sure nor asked). Connect's Steps over that store, Anki
    Miner the fake (3.11, `sync`), plugged in, the speech model there."""
    store, _data_dir = _empty("ja")
    src = _drive("driveB")
    book = _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, "ja")
    files = _audio_folder(os.path.join(src, "Audio", "I Am a Cat"), "I Am a Cat", _fit("ja"))
    with store:
        _look(store, "ja", store.add_source(src))
        [item] = _audio_items(store)
        rec = _record(store, item["id"])
        parts = sorted(i for (i,) in store.conn.execute("SELECT id FROM items WHERE source_type != 'audio'"))
    assert rec["book"] is None and rec["ask"] is None, "the look left it alone"
    _record_miner()
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    steps = runner.Steps({"connect_anki_miner_path": fake_miner.path})
    monkeypatch.setattr(steps, "_miner_profile", lambda lang, job: (fake_miner.path, "p-surasura"))
    monkeypatch.setattr(steps, "on_battery", lambda: False)
    return {"steps": steps, "book": os.path.abspath(book), "files": files, "audio": item["id"], "parts": parts}




def _asks(ledger):
    """The book questions still open (dismissed ones too)."""
    return [n for n in ledger.needs("ja", listed=False) if n["kind"] == runner.BOOK_AUDIO_NEED]


def _every_ask(ledger):
    """Every book question ever raised, open or fixed: (item, open)."""
    return [(r[0], r[1] is None) for r in ledger.conn.execute(
        "SELECT item_id, fixed_at FROM needs WHERE kind = ? ORDER BY id", (runner.BOOK_AUDIO_NEED,))]


def _got(item=11, key="sha256:aa", epub="b.epub", title=NEKO):
    return {"book_ask": runner.BOOK_AUDIO_ASK.format(title=title), "item_id": item, "key": key,
            "epub": os.path.abspath(epub)}


class _AskSteps:
    """`Steps.line_up` as the run sees it: what each look answers (the book's question for every part, a Wait…)."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def line_up(self, lang, job, epub):
        self.calls.append(job["item_id"])
        got = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(got, Exception):
            raise got
        return got


def _hold(steps, ledger, jid, item, epub="b.epub"):
    """One look's `_line_up` for a part -> the Wait it raised (recorded as the run records it), or what it returned."""
    try:
        got = runner._line_up(steps, ledger, "ja", {"id": jid, "item_id": item}, (epub, epub))
    except runner.Wait as w:
        runner._wait(ledger, ledger.job_by_id(jid), w, {"waiting": {}})
        return w
    return got


def test_a_book_with_no_audiobook_paired_asks_before_its_first_card_one_question_for_the_book(lone, fake_miner):
    """Mattias's cause: `Steps.line_up` found no audiobook for the book and the part went straight to the pick —
    text-only cards, nothing asked. Now the part's line-up is the book's question (its first part names it, so every
    part asks the same one, keyed by the EPUB's sha256), and nothing was started."""
    from app.library_store import sha256_of
    sha = sha256_of(lone["book"])
    got = lone["steps"].line_up("ja", _job(), lone["book"])
    assert got == {"book_ask": runner.BOOK_AUDIO_ASK.format(title=NEKO), "item_id": lone["parts"][0],
                   "key": f"sha256:{sha}", "epub": lone["book"]}
    assert lone["steps"].line_up("ja", dict(_job(), id=2, item_id=lone["parts"][-1]), lone["book"]) == got
    assert "sync" not in fake_miner.commands()


def test_every_part_waits_on_one_question_that_stays_seen_and_mine_without_audio_lets_them_all_go(tmp_path):
    """Two parts of one book: ONE standing *Needs you* question (the first part's), each part held by its words (the
    row's amber *Waiting for you*), looked at again at each look — once seen it stays seen and nothing is written
    again (review B1); *Mine without audio* keeps the answer for the book, fixes the question and queues every part it
    held — once (a second press answers nothing); the next looks mine them as the book."""
    from app.connect import feed
    ledger_path = str(tmp_path / "ledger.db")
    got = _got()
    with Ledger(ledger_path) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        b = ledger.queue("ja", 12, "mine", None, "store-1")
        steps = _AskSteps(got)
        for jid, item in ((a, 11), (b, 12)):
            w = _hold(steps, ledger, jid, item)
            assert isinstance(w, runner.Wait) and w.reason == got["book_ask"] and w.look is True
        [need] = _asks(ledger)
        assert need["item_id"] == 11 and need["say"] == got["book_ask"]
        ledger.mark_seen([need["id"]])
        before = ledger.conn.execute("SELECT * FROM needs").fetchall()
        _hold(steps, ledger, a, 11)
        assert ledger.conn.execute("SELECT * FROM needs").fetchall() == before, "seen stays seen; nothing written"
        rec = {"running": True, "languages": {"ja": {"needs": [{"id": need["id"], "kind": need["kind"],
                                                                "say": got["book_ask"], "item": 11}],
                                                     "jobs": [{"item": 12, "state": "waiting",
                                                               "reason": got["book_ask"]}]}}}
        assert feed.build(rec, "ja").items[12].kind == feed.HELD
    entry = [e for e in needs.entries(None, (), {"needs": rec["languages"]["ja"]["needs"]}, set())
             if e.kind == runner.BOOK_AUDIO_NEED]
    # Iro-AA: *Make AI audio (beta)* between the two — the window shows it only while the AI voice's beta is on
    assert entry and entry[0].actions == ("pick_audiobook", "ai_audio", "no_audiobook", "dismiss") and \
        entry[0].title == got["book_ask"]
    assert actions.book_audiobook("ja", need["id"], path=ledger_path) is True
    with Ledger(ledger_path) as ledger:
        assert [ledger.job_by_id(j)["state"] for j in (a, b)] == ["queued", "queued"]
        assert not _asks(ledger)
        assert _hold(steps, ledger, a, 11) is None and _hold(steps, ledger, b, 12) is None
        assert not _asks(ledger), "never asked again"
    assert actions.book_audiobook("ja", need["id"], path=ledger_path) is False, "answered already"


def test_the_answer_lands_on_the_key_it_was_asked_with_and_a_new_edition_asks_once_again(tmp_path):
    """Review B2: the book re-extracted (a new sha256, the same parts) — its old question goes, ONE card stands for
    the new edition, and *Mine without audio* answers the edition it asked about (never the old key: else it would
    be asked forever)."""
    ledger_path = str(tmp_path / "ledger.db")
    with Ledger(ledger_path) as ledger:
        jid = ledger.queue("ja", 11, "mine", None, "store-1")
        _hold(_AskSteps(_got(key="sha256:old")), ledger, jid, 11)
        _hold(_AskSteps(_got(key="sha256:new")), ledger, jid, 11)
        [need] = _asks(ledger)
        assert need["fixed_at"] is None
    assert actions.book_audiobook("ja", need["id"], path=ledger_path) is True
    with Ledger(ledger_path) as ledger:
        assert _hold(_AskSteps(_got(key="sha256:new")), ledger, jid, 11) is None
        assert isinstance(_hold(_AskSteps(_got(key="sha256:old")), ledger, jid, 11), runner.Wait), \
            "the other edition was never answered"


def test_a_question_asked_by_a_part_that_left_gives_way_to_one_card_for_the_book(tmp_path):
    """Review S5: the book's first part left the library — the next part asks, the old part's card goes (never an
    orphan whose *Mine without audio* answers nothing)."""
    ledger_path = str(tmp_path / "ledger.db")
    with Ledger(ledger_path) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        b = ledger.queue("ja", 12, "mine", None, "store-1")
        _hold(_AskSteps(_got(item=11)), ledger, a, 11)
        _hold(_AskSteps(_got(item=12)), ledger, b, 12)
        assert _every_ask(ledger) == [(11, False), (12, True)]
        [need] = _asks(ledger)
    assert actions.book_audiobook("ja", need["id"], path=ledger_path) is True


def test_a_busy_library_never_takes_the_question_away(tmp_path):
    """Review S3: a look that finds the library busy is no answer — the card stays the same card (its id, seen)."""
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", 11, "mine", None, "store-1")
        _hold(_AskSteps(_got()), ledger, jid, 11)
        [need] = _asks(ledger)
        w = _hold(_AskSteps(runner.Wait(runner.LIBRARY_BUSY)), ledger, jid, 11)
        assert w.reason == runner.LIBRARY_BUSY
        assert [(n["id"], n["fixed_at"]) for n in _asks(ledger)] == [(need["id"], None)]


def test_a_dismissed_question_lets_the_book_go_for_good_even_after_its_asking_part_is_done(tmp_path):
    """*Dismiss* (every Connect card has it): the book is mined as the book, never held on a question nobody sees —
    and kept: once the asking part's job ends (its needs go with it, `runner._fixed`), the next part never asks
    again (review S4)."""
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        b = ledger.queue("ja", 12, "mine", None, "store-1")
        steps = _AskSteps(_got())
        _hold(steps, ledger, a, 11)
        [need] = _asks(ledger)
        assert ledger.dismiss(need["id"])
        assert _hold(steps, ledger, a, 11) is None
        runner._fixed(ledger, "ja", item_id=11)             # part 1 mined: its job ended, its needs with it
        assert _hold(steps, ledger, b, 12) is None
        assert _every_ask(ledger) == [(11, False)], "no second question"


def test_mine_without_audio_is_kept_for_the_real_book_and_it_is_never_asked_again(lone, fake_miner, tmp_path):
    steps = lone["steps"]
    ledger_path = str(tmp_path / "ledger.db")
    with Ledger(ledger_path) as ledger:
        jobs = [ledger.queue("ja", p, "mine", None, "store-1") for p in lone["parts"]]
        assert isinstance(_hold(steps, ledger, jobs[0], lone["parts"][0], lone["book"]), runner.Wait)
        [need] = _asks(ledger)
    assert actions.book_audiobook("ja", need["id"], path=ledger_path) is True
    with Ledger(ledger_path) as ledger:
        for jid, part in zip(jobs, lone["parts"]):
            assert _hold(steps, ledger, jid, part, lone["book"]) is None
    assert "sync" not in fake_miner.commands()


def test_picking_its_audiobook_lines_the_book_up_and_its_question_goes_by_itself(lone, fake_miner, tmp_path):
    """*Pick its audiobook…*: the store's own pick (`pick_audiobook_book`, one Undo) pairs the audiobook with the book;
    the part's next look lines them up (Anki Miner's `sync`), and the book's question is fixed by itself."""
    from tests import connect_helpers as c
    steps = lone["steps"]
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", lone["parts"][0], "mine", None, "store-1")
        assert isinstance(_hold(steps, ledger, jid, lone["parts"][0], lone["book"]), runner.Wait)
        assert [n["fixed_at"] for n in _asks(ledger)] == [None]
        with c.store("ja") as s:
            assert s.pick_audiobook_book(lone["audio"], lone["book"]) is not None
        w = _hold(steps, ledger, jid, lone["parts"][0], lone["book"])
        assert runner.lining_up(w.reason)
        assert ledger.needs("ja") == [], "the book's question went by itself"
    _until(lambda: "sync" in fake_miner.commands())        # the sync is a child of Connect's
    assert fake_miner.commands().count("sync") == 1


def test_no_question_once_the_speech_model_was_declined_or_without_anki_miners_sync(lone, fake_miner):
    """Nothing the answer could change: the speech model declined (*Not now*: every book's cards without sentence
    audio) or an Anki Miner that can't line books up — mined as the book, as before, nothing asked."""
    steps = lone["steps"]
    lineup.set_answer(False)
    assert steps.line_up("ja", _job(), lone["book"]) is None
    lineup.clear_answer()
    _record_miner([f for f in LINE_UP_311 if f != "sync"])
    assert steps.line_up("ja", _job(), lone["book"]) is None


def test_hons_own_question_about_the_book_stands_beside_it_and_its_audiobook_is_offered_first(lone):
    """Review S6: Hon unsure (H-8: *Is this audiobook 「…」 the book 「…」?*) — the book still asks its own question (a
    hidden H-8 card never holds it with nothing shown), and *Pick its audiobook…* offers that audiobook first."""
    from tests import connect_helpers as c
    other = _drive("driveA2")
    _audio_folder(os.path.join(other, "Audio", "A Cat Story"), "A Cat Story", _fit("ja"))
    with c.store("ja") as s:
        _look(s, "ja", s.add_source(other))
        assert s.pair_audiobook(lone["audio"], ask={"item": lone["parts"][0], "epub": lone["book"], "sha256": None,
                                                    "key": "k-ask", "title": NEKO})
        listed = [a["item_id"] for a in s.book_audiobooks(lone["parts"][0])["audiobooks"]]
        assert len(listed) == 2 and listed[0] == lone["audio"], "the one Hon asks about first, before A… by title"
        assert s.pick_audiobook_book(lone["audio"], lone["book"]) is not None, "the pick pairs an asked one too"
    with pytest.raises(runner.Wait) as w:
        lone["steps"].line_up("ja", _job(), lone["book"])
    assert runner.lining_up(w.value.reason)


def test_the_pick_lists_the_librarys_audiobooks_with_no_book_and_none_once_paired(lone):
    """`Store.book_audiobooks` (the window's *Pick its audiobook…*, on a worker): the part's book (its EPUB, its
    title) and the audiobooks with no book — the lone one here; a part of no EPUB is no book. Once picked (paired) it
    is no longer offered, to this book or another."""
    from tests import connect_helpers as c
    with c.store("ja") as s:
        got = s.book_audiobooks(lone["parts"][1])
        assert got["epub"] == lone["book"] and got["title"] == NEKO
        assert [(a["item_id"], a["title"], a["n"]) for a in got["audiobooks"]] == [(lone["audio"], "I Am a Cat", 3)]
        assert s.book_audiobooks(lone["audio"]) is None, "an audiobook's own item is no book"
        assert s.pick_audiobook_book(lone["audio"], lone["book"]) is not None
        assert s.book_audiobooks(lone["parts"][1])["audiobooks"] == []


def test_two_copies_of_one_epub_are_two_books_whose_questions_never_take_each_others_place(tmp_path):
    """Round 2 S1: the same bytes in two library folders (one key, two EPUBs): each its own card, standing — a look of
    one never fixes the other's (else each look would raise it anew, unseen); one answer counts for both (the key)."""
    ledger_path = str(tmp_path / "ledger.db")
    with Ledger(ledger_path) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        b = ledger.queue("ja", 21, "mine", None, "store-1")
        one, two = _got(item=11, epub="b.epub"), _got(item=21, epub="copy/b.epub")
        _hold(_AskSteps(one), ledger, a, 11, "b.epub")
        _hold(_AskSteps(two), ledger, b, 21, "copy/b.epub")
        before = ledger.conn.execute("SELECT * FROM needs ORDER BY id").fetchall()
        assert len(before) == 2
        for _ in range(2):
            _hold(_AskSteps(one), ledger, a, 11, "b.epub")
            _hold(_AskSteps(two), ledger, b, 21, "copy/b.epub")
        assert ledger.conn.execute("SELECT * FROM needs ORDER BY id").fetchall() == before
        first = _asks(ledger)[0]["id"]
    assert actions.book_audiobook("ja", first, path=ledger_path) is True
    with Ledger(ledger_path) as ledger:
        assert _hold(_AskSteps(two), ledger, b, 21, "copy/b.epub") is None, "the same book's answer"


def test_a_question_no_waiting_part_holds_any_more_goes_when_a_job_ends(tmp_path):
    """Round 2 S2: the card is asked by the book's first part, which may have no job; once no part waits on it (their
    jobs dropped or done without an answer), a job's end takes the card away — never one nothing clears."""
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        b = ledger.queue("ja", 12, "mine", None, "store-1")
        _hold(_AskSteps(_got(item=11)), ledger, b, 12)
        runner._book_orphans(ledger, "ja")
        assert [n["item_id"] for n in _asks(ledger)] == [11], "a part still waits on it"
        ledger.set_state(b, "dropped", reason="left the top 20")
        runner._book_orphans(ledger, "ja")
        assert _asks(ledger) == []


def test_an_answer_kept_by_the_books_path_holds_once_its_sha256_is_known(tmp_path):
    """Round 2 N4: asked (and answered) while its parts had no sha256 — the path key; a later look knows the EPUB's
    sha256: still answered, never asked once more."""
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", 11, "mine", None, "store-1")
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)",
                            (f"{runner.BOOK_SAID}ja:{runner.book_key('b.epub')}", runner.NO_AUDIOBOOK))
        assert _hold(_AskSteps(_got(key="sha256:later")), ledger, jid, 11) is None
        assert _asks(ledger) == []


def test_two_books_in_one_title_are_each_named_by_their_file():
    """Round 2 S3: two volumes in one folder are one title — each card and its pick name the book by its file, so the
    two questions differ (and an answer to one never lets the other go)."""
    from app.connect import library
    store, _data_dir = _empty("ja")
    src = _drive("driveV")
    books = [_epub(os.path.join(src, "Books", "星屑の剣士", f"星屑の剣士 {n}.epub"), f"星屑の剣士 {n}", "ja",
                   repeat=19 + n) for n in (1, 2)]          # each volume its own text (the same text is one item)
    with store:
        _look(store, "ja", store.add_source(src), first=True)
        found = [library.book_of(store, b) for b in books]
        assert found[0]["item"] != found[1]["item"]
        works = [store.item(f["item"])["work_id"] for f in found]
        store.merge_works(works[0], [works[1]])             # the learner's own join: one title, two books
        found = [library.book_of(store, b) for b in books]
        assert store.item(found[0]["item"])["work_id"] == store.item(found[1]["item"])["work_id"], "one title"
        assert [f["title"] for f in found] == ["星屑の剣士 1", "星屑の剣士 2"]
        assert [store.book_audiobooks(f["item"])["title"] for f in found] == ["星屑の剣士 1", "星屑の剣士 2"]
