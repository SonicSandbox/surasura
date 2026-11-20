"""Kantan-B2: a first run makes no card before the learner's yes (a new tester's report, 2026-11-18).

The tester's story, as his report's ledger tells it: setup's page 5 left *Make cards for me as I watch* on, the
sorting offered *Needs you*'s *Make cards for your first 20 episodes?* — and before he answered it, arranging Current
logged episodes entering the top 20, Connect queued them, the battery gate held them, and they were mined the moment
he plugged in. The rule now: while that line is offered and unanswered, and Connect never queued from the placement
log in this language, nothing that enters the top 20 makes a job (nor a gap's *Make their cards*); *Make cards* logs
the top 20 itself (and its answer is kept first, so a Connect already looking never passes them by); *Not now* is no
yes (Kantan-B2b, Sonic 2026-11-19: what comes later waits too); an ask (*Mine now*) is a yes of its own; a profile
that already finished an episode from the log, with cards, is never held.

What a wrong answer would cost: cards written into the learner's Anki that he never agreed to — or, the other way, a
learner who said yes and never gets a card. Real subtitles from tests/Test Resources (the suite's library), ja + zh,
a small mine line (2).
"""
import os

import pytest

from app.connect import inbox, library
from app.connect.ledger import Ledger
from app.services import needs, setup_wizard
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _library(lang, line=2):
    c.library(lang)
    with c.store(lang) as s:
        s.bookkeeping({"mine_line": line}, copy_carries=True)


def _consume(lang):
    with c.store(lang) as s, Ledger() as ledger:
        return inbox.consume(s, lang, ledger)


def _jobs(lang):
    with Ledger() as ledger:
        return ledger.jobs(lang)


def _enter_one(lang):
    """The learner arranges Current: the last NOW item dragged to the top, into the mine line -> its id."""
    with c.store(lang) as s:
        moved = s.ids("now")[-1]
        library.place(s, moved, "now", before_id=s.ids("now")[0], source="user")
    return moved


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_while_the_first_cards_line_waits_an_episode_entering_the_top_makes_no_job(lang):
    # why: the tester's case — Connect on from setup's page 5, the line offered, not answered: his own arranging
    # must not start mining behind the question
    _library(lang)
    needs.offer(lang, needs.FIRST_CARDS)
    _consume(lang)                                           # Connect's first look: its watermark
    moved = _enter_one(lang)
    out = _consume(lang)
    assert out["queued"] == [] and out["read"] >= 1, "the entry was read, and made no job"
    assert _jobs(lang) == []
    assert _consume(lang)["queued"] == [], "read once: the held entry is never queued later by itself"
    with c.store(lang) as s:
        assert moved in library.mine_line(s)                 # nothing moved: only no job


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_make_cards_queues_the_whole_top_including_what_entered_while_it_waited(lang):
    # why: the yes covers the top 20 as it is when pressed — the episode the learner arranged in meanwhile too
    _library(lang)
    needs.offer(lang, needs.FIRST_CARDS)
    _consume(lang)
    moved = _enter_one(lang)
    _consume(lang)
    ids = setup_wizard.first_cards(lang, {"connect_enabled": True}, c.dirs(lang)[0])
    assert moved in ids and needs.FIRST_CARDS in needs.read_answered(lang)
    out = _consume(lang)
    assert sorted(out["queued"]) == sorted(ids)


def test_make_cards_keeps_its_answer_before_its_log_so_a_running_connect_never_holds_them(monkeypatch):
    # why: Connect may look between the log and the answer; it read the line as still waiting and passed the 20 by
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    _consume("ja")
    from app import library_store
    real = library_store.Store.enter_mine_line
    seen = []

    def looked_meanwhile(self, by="user"):
        seen.append(needs.FIRST_CARDS in needs.read_answered("ja"))
        return real(self, by)
    monkeypatch.setattr(library_store.Store, "enter_mine_line", looked_meanwhile)
    setup_wizard.first_cards("ja", {"connect_enabled": True}, c.dirs("ja")[0])
    assert seen == [True]


def test_make_cards_whose_log_fails_takes_its_answer_back_and_the_line_asks_again(monkeypatch):
    # why: a failed press must leave the question standing, never a line gone with no card made
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    from app import library_store

    def busy(self, by="user"):
        raise library_store.StoreBusy("the window holds the store")
    monkeypatch.setattr(library_store.Store, "enter_mine_line", busy)
    with pytest.raises(library_store.StoreBusy):
        setup_wizard.first_cards("ja", {"connect_enabled": True}, c.dirs("ja")[0])
    assert needs.FIRST_CARDS not in needs.read_answered("ja")
    assert needs.FIRST_CARDS in needs.read_offers("ja")


def test_not_now_is_no_yes_what_comes_later_waits_too():
    # why: Kantan-B2b (Sonic 2026-11-19: "Nothing mines until the yes"): *Not now* keeps its own answer, the line
    # stays unanswered, and an episode entering the top 20 afterwards makes no job either
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    _consume("ja")
    before = _enter_one("ja")
    _consume("ja")
    needs.answer("ja", [needs.FIRST_CARDS_NOT_NOW])         # *Not now*'s own answer, never the line's
    assert _consume("ja")["queued"] == []
    later = _enter_one("ja")
    assert later != before
    assert _consume("ja")["queued"] == [] and _jobs("ja") == []


def test_an_ask_is_a_yes_of_its_own_while_the_line_waits():
    # why: *Mine now* on an episode is the learner's own press — never held by the first run's question
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    _consume("ja")
    with c.store("ja") as s:
        item = s.ids("now")[-1]
        s.ask_mining([item])
    out = _consume("ja")
    assert out["queued"] == [item] and out["asked"] == [item]


def _mined(lang, item_id):
    """The item's log job finished with a card, as Connect's loop records it (its batch's `made` outcome)."""
    with Ledger() as ledger, ledger.transaction():
        job = ledger.job(lang, item_id)
        ledger.conn.execute("INSERT INTO outcomes (job_id, word, reading, outcome, note_id, attempt) VALUES "
                            "(?, '約束', 'ヤクソク', 'made', 1001, 1)", (job["id"],))
        ledger.set_state(job["id"], "done")


def test_a_profile_that_already_mined_from_the_log_is_never_held_by_an_old_unanswered_line():
    # why: a 3.0 learner who left the line unanswered for weeks while Connect mined must keep getting cards
    _library("ja")
    _consume("ja")
    first = _enter_one("ja")
    assert _consume("ja")["queued"] == [first]               # queued from the log once (no line offered then) …
    _mined("ja", first)                                      # … and mined, with a card
    needs.offer("ja", needs.FIRST_CARDS)
    second = _enter_one("ja")
    assert second in _consume("ja")["queued"]


def test_a_profile_whose_log_jobs_were_only_queued_is_held_by_its_unanswered_line():
    # why: Kantan-B2b — the reporter's 3.0.15 install: jobs queued from the log, none finished; that is no yes
    _library("ja")
    _consume("ja")
    first = _enter_one("ja")
    assert _consume("ja")["queued"] == [first]
    needs.offer("ja", needs.FIRST_CARDS)
    _enter_one("ja")
    assert _consume("ja")["queued"] == []


def test_no_line_offered_is_the_rule_as_before():
    # why: a library set up with no shows at setup (no line) mines what enters, as Connect always did
    _library("zh")
    _consume("zh")
    moved = _enter_one("zh")
    assert _consume("zh")["queued"] == [moved]


def test_a_gap_while_the_line_waits_names_no_episodes_of_its_own():
    # why: a log Connect can't trust (a rebuild's new epoch) offers *Make their cards* for the top 20 — the first
    # run's own line asks that already
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    _consume("ja")
    with c.store("ja") as s:
        s.bookkeeping({f"reader_epoch:{library.READER}": "an-older-epoch"}, copy_carries=True)
    out = _consume("ja")
    assert out["reconciled"] and out["missed"] == []
    with Ledger() as ledger:
        assert ledger.gaps("ja") == []


def test_a_seen_file_held_by_a_write_never_reads_as_no_line(monkeypatch):
    # why: the window replaces the seen file while Connect (another process) reads it — read as "no line", the hold
    # would lift and the held entry be mined; instead the look fails whole (the reader stays) and Connect looks again
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    _consume("ja")
    _enter_one("ja")
    with c.store("ja") as s:
        mark = s.meta()[f"reader:{library.READER}"]
    real = needs._load

    def held(language, strict=False):
        raise PermissionError("the file is being replaced")
    monkeypatch.setattr(needs, "_load", held)
    with pytest.raises(OSError):
        _consume("ja")
    with c.store("ja") as s:
        assert s.meta()[f"reader:{library.READER}"] == mark, "nothing read past: the next look reads them again"
    assert _jobs("ja") == []
    monkeypatch.setattr(needs, "_load", real)
    assert _consume("ja")["queued"] == [] and _jobs("ja") == [], "read again: still held"


def test_a_seen_file_once_held_then_readable_is_read_again_within_the_look(monkeypatch):
    # why: a replace lasts a moment — a second try in the same look reads it
    _library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    real, calls = needs._load, []

    def once(language, strict=False):
        calls.append(strict)
        if len(calls) == 1:
            raise PermissionError("the file is being replaced")
        return real(language, strict)
    monkeypatch.setattr(needs, "_load", once)
    assert needs.first_cards_waiting("ja", wait=0) is True and calls == [True, True]


def test_a_seen_file_that_isnt_json_is_no_line_as_before():
    # why: a damaged or newer file must never stop Connect for good
    _library("ja")
    os.makedirs(os.path.dirname(needs.seen_path("ja")), exist_ok=True)
    with open(needs.seen_path("ja"), "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert needs.first_cards_waiting("ja") is False
    _consume("ja")
    moved = _enter_one("ja")
    assert _consume("ja")["queued"] == [moved]
