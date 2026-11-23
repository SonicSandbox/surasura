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
def test_two_chapters_three_and_six_steps_each_with_its_words_and_a_real_place():
    assert [s.id for s in P.STEPS if s.chapter == P.FIRST] == ["words", "watch", "cards"]
    assert [s.id for s in P.STEPS if s.chapter == P.READY] == ["junban", "backfill", "loop", "yours", "audiobook",
                                                                "hato", "piyo"]
    for step in P.STEPS:
        assert step.id in strings.PATH_STEPS and all(strings.PATH_STEPS[step.id])
        assert guide.anchor_ok(step.where, has_card=help_cards.available, locate=catalog.locate), step.id


def test_the_steps_regroup_into_four_stages_and_the_later_steps_stay_outside_them():
    # Mado-EZP (EZ2-1 / §0.9): ② First episode = words, watch; ③ Automate = cards, 順, Backfill, then the review loop
    # (Mado-LT, WL-9: last of ③); ④ Make it yours = yours; the chapters keep their card rules underneath
    by_stage = {stage: [s.id for s in P.STEPS if s.stage == stage] for stage in P.STAGES}
    assert by_stage == {P.BOARD: [], P.EPISODE: ["words", "watch"],
                        P.AUTOMATE: ["cards", "junban", "backfill", "loop"], P.YOURS: ["yours"]}
    assert [s.id for s in P.STEPS if s.stage is None] == ["audiobook", "hato", "piyo"]
    assert BY("cards").chapter == P.FIRST                                       # comes back at the next start


def test_the_four_stones_say_done_now_and_later_from_the_real_ticks():
    assert P.path(facts(), {}).stages == (P.DONE, P.NOW, P.LATER, P.LATER)     # ① done: a path needs a library
    two = facts(journey_opened=True, episodes_done=1)
    assert P.path(two, {}).stages == (P.DONE, P.DONE, P.NOW, P.LATER)
    three = two._replace(cards_made=True, junban_ordered=True, backfilled=True, loop_read=True)
    assert P.path(three, {}).stages == (P.DONE, P.DONE, P.DONE, P.NOW)
    assert P.path(three._replace(yours_picked=True), {}).stages == (P.DONE,) * 4
    # 順 absent or off: its two steps aren't offered, so ③ is done with the cards alone
    assert P.path(two._replace(cards_made=True, junban=False, loop_read=True), {}).stages == (P.DONE, P.DONE, P.DONE,
                                                                                               P.NOW)
    # Mado-LT: the loop's step is ③'s last — until a sync read a move from the phone, ③ is still to do
    assert P.path(two._replace(cards_made=True, junban=False), {}).stages == (P.DONE, P.DONE, P.NOW, P.LATER)
    # a stage done ahead of the one to do now stays done (nothing is locked: ✦ lets any step be done)
    assert P.path(facts(yours_picked=True), {}).stages == (P.DONE, P.NOW, P.LATER, P.DONE)


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
    ("yours", {}, {"yours_picked": True}),                  # ④: the learner's own pick of which words get a card
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
EP2 = (P.DONE, P.NOW, P.LATER, P.LATER)                # ② First episode now
EP3 = (P.DONE, P.DONE, P.NOW, P.LATER)                 # ③ Automate now


def test_the_card_walks_chapter_one_then_says_made_once_then_shows_a_useful_later_step():
    assert P.path(facts(), {}).card == ("step", "words", EP2)
    assert P.path(facts(journey_opened=True), {}).card == ("step", "watch", EP2)
    assert P.path(facts(journey_opened=True, episodes_done=1), {}).card == ("step", "cards", EP3)
    done = facts(journey_opened=True, episodes_done=1, own_cards=True, junban=False)
    assert P.path(done, {}).card == ("made",)
    assert P.path(done, {"first_ack": True}).card is None                       # ④ not on an old path: no card
    useful = done._replace(video_waiting=True)
    assert P.path(useful, {"first_ack": True}).card == ("step", "hato", ())     # a later step: no stages
    assert P.path(useful, {"first_ack": True, "not_now": ["hato"]}).card is None   # set aside for good


def test_make_it_yours_comes_to_no_card_until_the_mining_model_lands_and_stays_in_the_panel():
    # Sonic 2026-11-20 (train 51's keeper, decision 1): ④ points at *Words to make cards from*, whose *Only i+1* is
    # being retired (Kantan-MO) — a card pushing a new learner there is the 308 off-list cards' trap. Hidden for every
    # path, a new one too; the step stays in ✦'s list, the string keeps ④ NOW, and the kept rule is untouched
    assert P.YOURS_CARD is False
    done = facts(journey_opened=True, episodes_done=1, own_cards=True, junban=False, loop_read=True)
    way = P.path(done, {"first_ack": True, "yours_card": True})
    assert way.card is None and way.stages == (P.DONE, P.DONE, P.DONE, P.NOW)
    assert P.listed(way.steps)[:2] == (P.YOURS, [st for st in way.steps if st.step.id == "yours"])
    later = done._replace(video_waiting=True)                                   # a later step still comes to the card
    assert P.path(later, {"first_ack": True, "yours_card": True}).card == ("step", "hato", ())
    assert "Only" not in strings.PATH_STEPS["yours"][1] and "one new word" not in strings.PATH_STEPS["yours"][1]


def test_make_it_yours_row_presses_only_while_it_opens_level_the_mining_models_one_knob(monkeypatch):
    # the lead 2026-11-21: with *Words to make cards from* retired (Kantan-MO), ④'s press opens Level — its row in ✦
    # has its press again; pointed anywhere else (the retired choice) it has none, its card still off (YOURS_CARD)
    assert P.YOURS_PRESS == "settings:level" and P.has_press("yours") and P.has_press("hato")
    monkeypatch.setattr(P, "YOURS_PRESS", "settings:connect_mine_words")
    assert not P.has_press("yours") and P.has_press("hato")
    monkeypatch.setattr(P, "YOURS_CARD", True)                                  # with its card on: a press as before
    assert P.has_press("yours")


def test_make_it_yours_comes_to_the_card_only_on_a_path_that_was_new_and_after_stage_three(monkeypatch):
    # the kept code path, for when the mining model re-points ④ (YOURS_CARD on again)
    monkeypatch.setattr(P, "YOURS_CARD", True)
    done = facts(journey_opened=True, episodes_done=1, own_cards=True, junban=False, loop_read=True)
    new = {"first_ack": True, "yours_card": True}
    assert P.path(done, new).card == ("step", "yours", (P.DONE, P.DONE, P.DONE, P.NOW))
    assert P.path(done, {"first_ack": True, "yours_card": False}).card is None   # past chapter 1 then: ✦ only
    assert P.path(done, dict(new, not_now=["yours"])).card is None              # a later step's Not now: for good
    with_junban = done._replace(junban=True, anki_synced=True)                  # ③'s 順 first, in the table's order
    assert P.path(with_junban, new).card[1] == "junban"
    assert not {s.step.id: s for s in P.statuses(facts(), {})}["yours"].useful   # before any card: not yet


def test_not_now_on_chapter_one_waits_for_the_next_start_and_never_skips_ahead():
    assert P.path(facts(), {}, later=("words",)).card is None
    assert P.path(facts(), {}).card == ("step", "words", EP2)                     # the next start: back


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
    assert way.card == ("step", "watch", EP2)
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


def test_step_one_waits_for_a_journey_on_disk_and_each_show_me_lights_where_its_press_also_lives():
    assert P.path(facts(journey_ready=False), {}).card is None                  # no journey yet: nothing to show
    # §0.2: Up Next's *N new words ↗* · Up Next's Done · the footer's ⛏ · 順 · Settings' Backfill · Your setup
    assert [BY(i).where for i in ("words", "watch", "cards", "junban", "backfill", "yours")] == [
        "hero:journey", "hero:done", "circle:miner", "circle:junban", "settings:backfill_patterns",
        "settings:setup_mining"]


def BY(step_id):
    return P.BY_ID[step_id]


def test_one_later_card_a_run_after_not_now():
    done = facts(journey_opened=True, episodes_done=3, own_cards=True, video_waiting=True, book_in_current=True)
    state = {"first_ack": True, "not_now": ["audiobook"]}
    assert P.path(done, state).card == ("step", "hato", ())
    assert P.path(done, state, later=(P.READY,)).card is None


def test_an_update_from_before_the_path_is_no_beginner():
    _ledger_made("ja")
    way = P.look("ja", {}, SHOWS)
    assert way.first_done and (way.card is None or way.card[0] == "step" and BY(way.card[1]).chapter == P.READY)
    assert guide.read_state()["first_ack"] is True
    assert guide.read_state()["yours_card"] is False                            # past chapter 1: ④ in ✦ only
    guide.write_state({})
    way = P.look("ja", {}, View((Row("anime", 2),), Counts(0, 0), ()))           # ja's ledger has cards: done again
    assert way.first_done


def test_an_update_with_episodes_but_no_cards_starts_at_step_three():
    way = P.look("zh", {}, View((Row("anime", 2),), Counts(0, 0), ()))
    assert way.card == ("step", "cards", EP3)
    assert guide.read_state()["yours_card"] is True                             # still before its first cards: ④ too


def test_an_upgraders_ticks_and_answers_are_unchanged_by_the_stages():
    # a guide.json written before the stages: every key kept as it was, ticks never undone; ④'s rule decided once
    old = {"version": 1, "path_started": "2026-11-13", "done": {"words": "2026-11-13", "watch": "2026-11-13",
                                                                 "cards": "2026-11-14", "hato": "2026-11-15"},
           "first_ack": True, "not_now": ["piyo"], "own_cards": False, "moments": {"journey": "2026-11-13"},
           "useful_seen": ["hato"]}
    guide.write_state(dict(old))
    way = P.look("ja", {}, SHOWS)
    state = guide.read_state()
    for key, value in old.items():
        assert state[key] == value, key
    assert state["yours_card"] is False and way.first_done
    assert {st.step.id for st in way.steps if st.done} >= {"words", "watch", "cards", "hato"}
    P.look("ja", {}, SHOWS)
    assert guide.read_state() == state                                          # a second look writes nothing new


def test_a_test_run_never_looks_for_the_developers_own_anki_miner(monkeypatch):
    monkeypatch.delenv("ANKI_MINER_HOME", raising=False)
    assert not P._miner_found({})                                               # (under SURASURA_TEST_ROOT: never ~)
    assert P.facts("ja", {}, SHOWS, {"done": {"cards": "2026-11-14"}}).miner_found   # ticked: never looked for


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


#  --- Kantan-S2 (Sonic 2026-11-13: "they would need to be able to see past ones to try again, and if they already did
# one or don't have an audiobook to test one of the steps, etc that needs to account for that ux experience") ------ #
def _mining_session(home, language, cards):
    """A row of Anki Miner's own `stats.db` (`mining_sessions`, written by Anki Miner as it mines an episode)."""
    os.makedirs(home, exist_ok=True)
    con = sqlite3.connect(os.path.join(home, "stats.db"))
    con.execute("CREATE TABLE IF NOT EXISTS mining_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, series_name TEXT "
                "NOT NULL, episode_name TEXT NOT NULL, total_words INTEGER NOT NULL DEFAULT 0, unknown_words INTEGER "
                "NOT NULL DEFAULT 0, cards_created INTEGER NOT NULL DEFAULT 0, elapsed_time REAL NOT NULL DEFAULT 0.0, "
                "mined_at TEXT NOT NULL DEFAULT (datetime('now')), language TEXT NOT NULL DEFAULT 'ja')")
    con.execute("INSERT INTO mining_sessions (series_name, episode_name, cards_created, language) VALUES (?, ?, ?, ?)",
                ("ぼっち・ざ・ろっく！", "第1話", cards, language))
    con.commit()
    con.close()


def test_cards_made_with_anki_miner_before_the_guide_count_as_done(tmp_path, monkeypatch):
    # an upgrader who mined with Anki Miner long before the guide: told "Get cards made for you" would be wrong. The
    # real record is Anki Miner's own: a mining session that created cards, in this language (its stats.db). Never
    # "Anki Miner installed + cards in Anki": a premade deck (Kaishi) synced on setup's page would tick chapter 1 for a
    # learner who never mined (adversary r1 #1)
    from app import anki_sync
    home = str(tmp_path / ".anki_miner")
    monkeypatch.setenv("ANKI_MINER_HOME", home)
    anki_sync._save_state("ja", {"note_ids": [1700000000001, 1700000000002], "last_sync": "2026-11-01T10:00:00"})
    assert not P.facts("ja", {}, SHOWS, {}).cards_made                          # a synced deck alone: not mined
    _mining_session(home, "ja", 0)
    assert not P.facts("ja", {}, SHOWS, {}).cards_made                          # a session that made no card
    _mining_session(home, "zh", 12)
    assert not P.facts("ja", {}, SHOWS, {}).cards_made                          # another language's cards
    _mining_session(home, "ja", 8)
    assert P.facts("ja", {}, SHOWS, {}).cards_made and P.facts("zh", {}, SHOWS, {}).cards_made
    way = P.look("ja", {}, View((Row("anime", 0),), Counts(0, 0), ()))
    assert way.first_done and way.card != ("step", "words", EP2)               # no beginner's step 1


def test_an_old_anki_miner_stats_db_without_a_language_column_counts_for_japanese(tmp_path, monkeypatch):
    # (re-check r2 #4) before its migration Anki Miner mined Japanese only and kept no language: a long-time miner
    home = str(tmp_path / ".anki_miner")
    monkeypatch.setenv("ANKI_MINER_HOME", home)
    os.makedirs(home)
    con = sqlite3.connect(os.path.join(home, "stats.db"))
    con.execute("CREATE TABLE mining_sessions (id INTEGER PRIMARY KEY, series_name TEXT, episode_name TEXT, "
                "cards_created INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO mining_sessions (series_name, episode_name, cards_created) VALUES ('葬送のフリーレン', "
                "'第1話', 5)")
    con.commit()
    con.close()
    assert P._miner_cards("ja") and not P._miner_cards("zh")


def test_a_test_run_never_reads_the_developers_own_anki_miner(monkeypatch):
    monkeypatch.delenv("ANKI_MINER_HOME", raising=False)
    assert not P._miner_cards("ja")                                             # (under SURASURA_TEST_ROOT: never ~)


def test_a_later_step_done_before_it_applies_now_counts_by_its_record():
    # a line-up finished, a subtitle hato found, a Piyo round kept — while no book is in Current now, no video waits
    # and fewer than three episodes are Done: each is still done (its record), never offered again as new
    from app import practice_rounds
    from app.connect import lineup
    os.makedirs(os.path.join(lineup.root(), "k1"), exist_ok=True)
    with open(os.path.join(lineup.root(), "k1", lineup.STATE), "w", encoding="utf-8") as f:
        json.dump({"status": lineup.DONE, "grade": "A"}, f)
    _pairing("ja", "hato")
    practice_rounds.save("ja", practice_rounds.new_id(), start={"role": "friend", "words": [["猫", "ねこ"]]})
    f = P.facts("ja", {}, SHOWS, {})
    assert f.lined_up and f.hato_paired and f.piyo_round
    st = {s.step.id: s for s in P.statuses(f, {})}
    for step_id in ("audiobook", "hato", "piyo"):
        assert st[step_id].done and not st[step_id].useful, step_id
    assert P.newly_useful(P.statuses(f, {}), {}) == []                          # nothing to light the ✦ for


def ids(sts):
    return [st.step.id for st in sts]


def test_the_panels_one_list_is_now_then_later_then_done():
    f = facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True, lined_up=True)
    stage, now, later, done = P.listed(P.statuses(f, {}))
    assert stage == P.AUTOMATE
    assert ids(now) == ["cards", "junban", "backfill", "loop", "hato"]          # ③'s steps, then a useful later step
    assert ids(later) == ["yours", "piyo"]                                      # ④'s, and one that can't apply yet
    assert ids(done) == ["words", "watch", "audiobook"]                         # ②'s, and a line-up done before
    _stage, now, later, done = P.listed(P.statuses(f._replace(junban=False), {}))   # 順 absent or off: never listed
    assert not {"junban", "backfill"} & set(ids(now + later + done))


def test_every_step_says_in_one_short_line_when_it_applies():
    for step in P.STEPS:                        # (the panel lists a later stage's steps before they apply, too)
        line = strings.PATH_WHEN[step.id]
        assert line and "\n" not in line and len(line) <= 60, step.id


def test_manga_and_plain_text_are_not_books_an_audiobook_lines_up_with():
    assert not P._view_facts(View((Row("manga", 0), Row("text", 0)), Counts(0, 0), ()))[2]
    assert P._view_facts(View((Row("lightnovel", 0),), Counts(0, 0), ()))[2]


# --- Mado-LT: the review loop's step (WL-9, last of ③; PROVISIONAL words) ------------------------------------------ #
def test_the_loop_step_is_useful_once_cards_are_in_anki_and_synced_and_done_once_a_move_was_read():
    # why: it teaches what to do on the phone — useless before there are cards and a sync to read them
    st = {s.step.id: s for s in P.statuses(facts(), {})}["loop"]
    assert not st.useful and not st.done and strings.PATH_WHEN["loop"]
    st = {s.step.id: s for s in P.statuses(facts(cards_made=True, anki_synced=True), {})}["loop"]
    assert st.useful and not st.done
    st = {s.step.id: s for s in P.statuses(facts(own_cards=True, anki_synced=True, loop_read=True), {})}["loop"]
    assert st.useful and st.done


def test_the_loop_steps_sheet_says_delete_freely_and_its_press_is_the_move_cards():
    title, line = strings.PATH_STEPS["loop"]
    assert "delete freely" in line and len(line.split()) <= 25
    assert BY("loop").where == "settings:known_from_anki" and BY("loop").stage == P.AUTOMATE
    assert catalog.locate("known_from_anki") == ("anki", "known_from_anki")       # the move cards' block


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_loop_is_done_from_its_record_and_an_unreadable_or_missing_one_is_not_done(language, tmp_path,
                                                                                    monkeypatch):
    # why: done is the real thing (a sync that moved something); a record that can't be read never ticks it
    from app.connect import review_loop
    record = tmp_path / f"review-loop-{language}.json"
    monkeypatch.setattr(review_loop, "record_path", lambda lang: str(tmp_path / f"review-loop-{lang}.json"))
    assert not P._loop_read(language)                                            # empty state: no record
    record.write_text('{"syncs": []}', encoding="utf-8")
    assert not P._loop_read(language)
    word = "冒険" if language == "ja" else "冒险"
    record.write_text(json.dumps({"syncs": [{"id": "1", "known": [word], "changes": []}]}), encoding="utf-8")
    assert P._loop_read(language)
    record.write_text("{not json", encoding="utf-8")
    assert P.facts(language, {}, None, {}).loop_read is False
    assert P.facts(language, {}, None, {"done": {"loop": "2026-11-22"}}).loop_read is True   # ticked: never read again
