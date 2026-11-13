"""The feature guide's path (Hoshi-S PR 2; Kantan-X's model, the 3.0 planning folder's
`tracks/window/work/experience-2026-11-12/EXPERIENCE.md` §3 — PROVISIONAL): one table of steps, done from the real
thing, the Next card's choice, the glow.

What a wrong answer would cost a learner: a step ticked by pointing at it (or never ticked after doing it); a tick
lost when its record goes; a card for a module that isn't there; *Not now* coming back every minute, or a later step
set aside coming back at all; the ✦ glowing on a first run; their answers written into settings.json.
"""
import json
import os
import sqlite3
import threading
from collections import namedtuple

import pytest

from app import path_utils
from app.services import guide, help_cards
from app.services import path as P

pytest.importorskip("app.qt.settings_catalog")
from app.qt import settings_catalog as catalog  # noqa: E402  (Qt-free: the catalog is data)
from app.qt import strings  # noqa: E402  (Qt-free: the words table)

Row = namedtuple("Row", "media n_watched")
Counts = namedtuple("Counts", "finished goal_titles")
Arrival = namedtuple("Arrival", "waiting")
View = namedtuple("View", "rows counts arrivals")
EMPTY = View((), Counts(0, 0), ())
SHOWS = View((Row("anime", 0), Row("drama", 0)), Counts(0, 0), ())


def facts(**kw):
    base = dict(has_library=True, journey_opened=False, episodes_done=0, cards_made=False, own_cards=False,
                junban=True, anki_synced=False, junban_ordered=False, backfilled=False, book_in_current=False,
                lined_up=False, video_waiting=False, hato_paired=False, piyo_round=False)
    base.update(kw)
    return P.Facts(**base)


# --- the table --------------------------------------------------------------------------------------------------- #
def test_two_chapters_three_and_five_steps_each_with_its_words_and_a_real_place():
    assert [s.id for s in P.STEPS if s.chapter == P.FIRST] == ["words", "watch", "cards"]
    assert [s.id for s in P.STEPS if s.chapter == P.READY] == ["junban", "backfill", "audiobook", "hato", "piyo"]
    for step in P.STEPS:
        assert step.id in strings.PATH_STEPS and all(strings.PATH_STEPS[step.id])
        assert guide.anchor_ok(step.where, has_card=help_cards.available, locate=catalog.locate), step.id


@pytest.mark.parametrize("step, before, after", [
    ("words", {}, {"journey_opened": True}),
    ("watch", {}, {"episodes_done": 1}),
    ("cards", {}, {"cards_made": True}),
    ("cards", {}, {"own_cards": True}),                      # I make my own cards: step 3 answered
    ("junban", {}, {"junban_ordered": True}),
    ("backfill", {}, {"backfilled": True}),
    ("audiobook", {}, {"lined_up": True}),
    ("hato", {}, {"hato_paired": True}),
    ("piyo", {}, {"piyo_round": True}),
])
def test_a_step_is_done_only_by_its_own_record(step, before, after):
    st = {s.step.id: s for s in P.statuses(facts(**before), {})}
    assert not st[step].done
    st = {s.step.id: s for s in P.statuses(facts(**after), {})}
    assert st[step].done


@pytest.mark.parametrize("step, useful_when", [
    ("junban", {"anki_synced": True, "cards_made": True}),
    ("backfill", {"cards_made": True}),
    ("audiobook", {"book_in_current": True}),
    ("hato", {"video_waiting": True}),
    ("piyo", {"episodes_done": 3}),
])
def test_a_later_step_shows_only_once_useful_and_never_without_its_module(step, useful_when):
    assert not {s.step.id: s for s in P.statuses(facts(), {})}[step].useful
    assert {s.step.id: s for s in P.statuses(facts(**useful_when), {})}[step].useful
    if step in ("junban", "backfill"):                       # S10: the module absent, never offered
        assert not {s.step.id: s for s in P.statuses(facts(junban=False, **useful_when), {})}[step].useful


def test_a_tick_once_seen_is_kept_when_its_record_goes():
    st = {s.step.id: s for s in P.statuses(facts(), {"done": {"hato": "2026-11-12"}})}
    assert st["hato"].done


# --- the Next card ----------------------------------------------------------------------------------------------- #
def test_the_card_walks_chapter_one_then_says_made_once_then_shows_a_useful_later_step():
    assert P.path(facts(), {}).card == ("step", "words", 1, 3)
    assert P.path(facts(journey_opened=True), {}).card == ("step", "watch", 2, 3)
    assert P.path(facts(journey_opened=True, episodes_done=1), {}).card == ("step", "cards", 3, 3)
    done = facts(journey_opened=True, episodes_done=1, own_cards=True)
    assert P.path(done, {}).card == ("made",)
    assert P.path(done, {"first_ack": True}).card is None                       # nothing useful yet: no card
    useful = done._replace(video_waiting=True)
    assert P.path(useful, {"first_ack": True}).card == ("step", "hato", 0, 0)
    assert P.path(useful, {"first_ack": True, "not_now": ["hato"]}).card is None   # set aside for good


def test_not_now_on_chapter_one_waits_for_the_next_start_and_never_skips_ahead():
    assert P.path(facts(), {}, later=("words",)).card is None
    assert P.path(facts(), {}).card == ("step", "words", 1, 3)                    # the next start: back


def test_no_library_no_card():
    assert P.path(facts(has_library=False), {}).card is None


def test_the_glow_is_for_a_newly_useful_later_step_only_and_seeing_it_ends_it():
    assert not P.path(facts(), {}).glow                                          # chapter 1: the card's, never a glow
    useful = facts(video_waiting=True)
    assert P.path(useful, {}).glow
    assert not P.path(useful, {"useful_seen": ["hato"]}).glow
    assert not P.path(useful._replace(hato_paired=True), {}).glow                # done: nothing to glow for


# --- the facts, from the real records ---------------------------------------------------------------------------- #
def _ledger_made(language, outcome="made"):
    from app.connect import ledger
    os.makedirs(os.path.dirname(ledger.path()), exist_ok=True)
    con = sqlite3.connect(ledger.path())
    con.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, language TEXT, item_id INTEGER, state TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS outcomes (job_id INTEGER, word TEXT, reading TEXT, outcome TEXT)")
    con.execute("INSERT INTO jobs (language, item_id, state) VALUES (?, 1, 'done')", (language,))
    con.execute("INSERT INTO outcomes VALUES (last_insert_rowid(), '字幕', 'じまく', ?)", (outcome,))
    con.commit()
    con.close()


def _pairing(language, producer):
    from app import library_store
    path = library_store.library_db_path(language, path_utils.get_data_path(language))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS pairings (content_key TEXT PRIMARY KEY, item_id INTEGER, pairing TEXT, "
                "paired_at TEXT)")
    record = {"schema": 1, "content_key": producer, "video_path": "ぼっち・ざ・ろっく！ 01.mkv"}
    if producer:
        record["producer"] = producer
    con.execute("INSERT INTO pairings VALUES (?, 1, ?, '2026-11-12')", (producer or "none", json.dumps(record)))
    con.commit()
    con.close()


def test_cards_made_reads_connects_ledger_for_this_language_only():
    assert not P._cards_made("ja")                                               # no ledger: not done, nothing made
    _ledger_made("zh")
    _ledger_made("ja", outcome="not_found")
    assert not P._cards_made("ja")
    _ledger_made("ja")
    assert P._cards_made("ja")


def test_hato_paired_is_a_pairing_hato_wrote_never_surasuras_own():
    assert not P._hato_paired("ja")
    _pairing("ja", "surasura")                                                   # Link…'s own record
    assert not P._hato_paired("ja")
    _pairing("ja", None)                                                         # no producer: hato's, as the store reads it
    assert P._hato_paired("ja")


def test_a_finished_line_up_and_the_undo_snapshots_and_a_kept_piyo_round_count():
    from app import practice_rounds
    from app.connect import lineup
    assert not P._lined_up()

    def state(key, data):
        os.makedirs(os.path.join(lineup.root(), key), exist_ok=True)
        with open(os.path.join(lineup.root(), key, lineup.STATE), "w", encoding="utf-8") as f:
            json.dump(data, f)
    state(lineup.SPEECH, {"status": lineup.DONE})                               # the speech model: no book's line-up
    state("k1", {"status": lineup.RUNNING})
    state("k2", {"status": lineup.DONE, "grade": "C"})                          # the wrong edition: no line-up for cards
    assert not P._lined_up()
    state("k3", {"status": lineup.DONE, "grade": "A"})
    assert P._lined_up()
    assert not P._piyo_round("ja")
    practice_rounds.save("ja", practice_rounds.new_id(), start={"role": "friend", "words": [["猫", "ねこ"]]})
    assert P._piyo_round("ja")


def test_the_views_facts_and_a_book_and_a_waiting_video():
    assert P._view_facts(None) == (False, 0, False, False)
    view = View((Row("anime", 2), Row("book", 0)), Counts(1, 0), (Arrival(3),))
    assert P._view_facts(view) == (True, 3, True, True)


def test_a_failed_read_counts_as_not_done_never_a_crash(monkeypatch):
    def broken(*_a, **_k):
        raise OSError("locked")
    monkeypatch.setattr(P, "_cards_made", broken)
    monkeypatch.setattr(P, "_hato_paired", broken)
    f = P.facts("ja", {}, SHOWS, {})
    assert not f.cards_made and not f.hato_paired and f.has_library


# --- the look and the answers ------------------------------------------------------------------------------------ #
def test_no_library_no_path_and_a_done_step_is_kept_with_its_day():
    assert P.look("ja", {}, EMPTY) is None
    P.note_moment("journey")
    way = P.look("ja", {}, SHOWS)
    assert way.card == ("step", "watch", 2, 3)
    assert set(guide.read_state()["done"]) == {"words"}


def test_the_answers_are_kept_once_and_never_in_settings_json(monkeypatch):
    from app import settings_manager

    def refuse(*_a, **_k):
        raise AssertionError("the path wrote settings.json")
    monkeypatch.setattr(settings_manager, "save_settings", refuse)
    assert P.own_cards() is True and P.own_cards() is False                     # written once (S19)
    assert P.first_ack() is True and P.first_ack() is False
    assert P.not_now("hato") is True and P.not_now("hato") is False
    assert P.seen_useful(["hato"]) is True and P.seen_useful(["hato"]) is False
    assert P.note_moment("journey") is True and P.note_moment("journey") is False
    state = guide.read_state()
    assert state["own_cards"] and state["first_ack"] and state["not_now"] == ["hato"]
    assert state["useful_seen"] == ["hato"] and "journey" in state["moments"]


def test_a_first_run_marks_the_useful_steps_seen_so_nothing_glows():
    view = View((Row("anime", 0),), Counts(0, 0), (Arrival(1),))                 # a video waits: hato is useful
    assert not P.look("ja", {}, view, fresh=True).glow
    assert P.look("ja", {}, view).glow is False                                  # seen on the first run
    guide.write_state({})
    assert P.look("ja", {}, view).glow                                           # an update's useful step: it glows
    assert not P.look("ja", {}, view, seen=True).glow                            # the panel opened: over


def test_two_workers_writing_at_once_lose_nothing():
    names = [f"m{n}" for n in range(20)]
    threads = [threading.Thread(target=P.note_moment, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(names) <= set(guide.read_state()["moments"])


# --- the adversary's round 1 ------------------------------------------------------------------------------------- #
def test_junban_and_backfill_tick_by_junbans_own_answer_and_connects_runs():
    pytest.importorskip("modules.junban.undo")
    from modules.junban import undo
    assert not P._junban("ja", "reorder") and not P._junban("ja", "backfill")
    os.makedirs(path_utils.get_user_files_path("ja"), exist_ok=True)
    with open(os.path.join(path_utils.get_user_files_path("ja"), undo.FILENAMES["baseline"]), "w",
              encoding="utf-8") as f:
        f.write("{}")                                                            # an automatic reorder's baseline
    assert P._junban("ja", "reorder") and not P._junban("ja", "backfill")
    os.makedirs(undo.runs_folder("zh"), exist_ok=True)
    with open(os.path.join(undo.runs_folder("zh"), "backfill-20261112-120000-000-1.json"), "w", encoding="utf-8") as f:
        f.write("{}")                                                            # Connect's Backfill run
    assert P._junban("zh", "backfill") and not P._junban("zh", "reorder")


def test_step_one_waits_for_a_journey_on_disk_and_step_three_points_at_anki_miners_card():
    assert P.path(facts(journey_ready=False), {}).card is None                  # no journey yet: nothing to show
    assert BY("cards").where == "settings:anki_miner"


def BY(step_id):
    return P.BY_ID[step_id]


def test_one_later_card_a_run_after_not_now():
    done = facts(journey_opened=True, episodes_done=3, own_cards=True, video_waiting=True, book_in_current=True)
    state = {"first_ack": True, "not_now": ["audiobook"]}
    assert P.path(done, state).card == ("step", "hato", 0, 0)
    assert P.path(done, state, later=(P.READY,)).card is None


def test_an_update_from_before_the_path_is_no_beginner():
    _ledger_made("ja")
    way = P.look("ja", {}, SHOWS)
    assert way.first_done and (way.card is None or way.card[0] == "step" and way.card[3] == 0)   # never chapter 1
    assert guide.read_state()["first_ack"] is True
    guide.write_state({})
    way = P.look("ja", {}, View((Row("anime", 2),), Counts(0, 0), ()))           # ja's ledger has cards: done again
    assert way.first_done


def test_an_update_with_episodes_but_no_cards_starts_at_step_three():
    way = P.look("zh", {}, View((Row("anime", 2),), Counts(0, 0), ()))
    assert way.card == ("step", "cards", 3, 3)


def test_a_malformed_pairing_never_hides_hatos_and_youtube_isnt_hato():
    from app import library_store
    _pairing("ja", "youtube")
    assert not P._hato_paired("ja")
    path = library_store.library_db_path("ja", path_utils.get_data_path("ja"))
    con = sqlite3.connect(path)
    con.execute("INSERT INTO pairings VALUES ('bad', 1, '{ 壊れた', '2026-11-12')")
    con.commit()
    con.close()
    _pairing("ja", "hato")
    assert P._hato_paired("ja")


def test_new_arrivals_alone_is_a_library_and_piyo_waits_for_three_episodes():
    assert P._view_facts(View((), Counts(0, 0), (Arrival(0),)))[0]
    assert not BY("piyo").when(facts(episodes_done=2)) and BY("piyo").when(facts(episodes_done=3))


def test_a_ticked_step_is_never_read_again(monkeypatch):
    calls = []
    monkeypatch.setattr(P, "_hato_paired", lambda language: calls.append(language) or True)
    view = View((Row("anime", 0),), Counts(0, 0), (Arrival(1),))
    P.facts("ja", {}, view, {})
    P.facts("ja", {}, view, {"done": {"hato": "2026-11-12"}})
    assert calls == ["ja"]
