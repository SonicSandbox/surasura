"""Laptop round 7 #42 (build 3): *Mine now* made nothing while Connect's waiting cards were at the cap, and raising the
cap in Settings didn't help.

Rules pinned, in plain words:
- an episode you asked for (*Mine now*, *Mine this*, *Mine it too*) is mined past the cap: your press is the yes for
  that episode's cards (Sonic's M-3 A), as it is on battery; the episodes nobody asked for still wait at the cap;
- the run's own steps read the cap from settings.json as it is now, so a cap raised while Connect waits at the old
  one reaches it at its next look; a test's steps read the dict they were handed; a file that can't be read falls
  back to the run's settings;
- a kick to a Connect that already runs stamps its wake mark, and the pause between its looks ends at the next look
  at the mark (seconds, never the 2-minute look); one stamp is one wake;
- a Settings change of the cap, like *Trust my subtitles' timing* turned on, kicks Connect.

What a wrong answer would cost: the laptop's state — every episode waiting with "Your 306 cards are waiting", the
asked ones too, for hours, with the cap already at 500 — so no card is ever made until Connect is restarted by hand.

Against `FakeSteps` (real words) and the real ledger in a temp folder; the wake mark in a temp local-data folder.
Never a live Anki.
"""
import threading
import time

import pytest

from app.connect import kick, runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    """Connect's local data (the wake mark's folder) in a temp folder."""
    from app import path_utils
    where = tmp_path / "local"
    where.mkdir()
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: str(where))
    return where


def _steps(tmp_path, **plan):
    return FakeSteps(str(tmp_path), dict({"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}, **plan))


def test_an_asked_episode_is_mined_past_the_cap_and_the_others_still_wait(tmp_path, ledger):
    # why: the laptop's ledger held four asked jobs waiting "Your 306 cards are waiting" — a press that does nothing.
    # The press is the yes for that episode alone: episode 2, never asked for, keeps waiting at the cap.
    steps = _steps(tmp_path, cap=300, waiting=306)
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
    assert {j["item_id"]: j["state"] for j in ledger.jobs("ja")} == {1: "waiting", 2: "waiting"}
    first = next(j for j in ledger.jobs("ja") if j["item_id"] == 1)
    with ledger.transaction():
        ledger.ask("ja", 1, "2026-10-23T00:53:30.691086Z")          # *Mine now* on episode 1
    assert ledger.job_by_id(first["id"])["asked_at"]
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
    states = {j["item_id"]: (j["state"], j.get("reason")) for j in ledger.jobs("ja")}
    assert states[1][0] == "done", states
    assert states[2][0] == "waiting" and states[2][1].startswith("Your "), states
    assert [e for e in steps.log if e[0] == "mine"] and all(e[1] == 1 for e in steps.log if e[0] == "mine")


def test_a_job_an_ask_made_is_mined_past_the_cap(tmp_path, ledger):
    # why: an ask on an episode with no job yet (kind `asked`, the laptop's job 37) is the same press
    steps = _steps(tmp_path, cap=300, waiting=306, line={"ja": [1]}, queue={"ja": []})
    with ledger.transaction():
        ledger.ask("ja", 1, "2026-10-23T00:22:44.699889Z", store_id="store-1")
    runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda _s: None, looks=1)
    assert [j["state"] for j in ledger.jobs("ja")] == ["done"]
    assert not any(e[0] == "shelve" for e in steps.log), "an ask shelves nothing: it isn't held by the cap"


def test_full_never_holds_an_asked_job_even_after_the_shelf_had_its_try():
    # why: `_full` runs before every pick; with the shelf tried it would stop the ask before `_at_cap` is reached
    class Steps:
        def shelf_tried(self, _lang):
            return True

        def cap(self, _lang):
            return 300

        def waiting_count(self, _lang):
            return 306
    assert runner._full(Steps(), "ja") is not None, "an episode nobody asked for waits at the cap"
    assert runner._full(Steps(), "ja", asked=True) is None
    assert runner._at_cap(Steps(), None, "ja", [], asked=True) is None
    assert runner.held_by_cap(False) and not runner.held_by_cap(True)


def test_the_runs_own_steps_read_the_cap_as_settings_json_holds_it_now(monkeypatch, local_data):
    # why: the laptop's Connect kept 300 for hours after the cap was set to 500 — it read the settings it started with
    from app.cli import verbs
    on_disk = {"connect_backlog_cap": {"ja": 500, "zh": 300}}
    monkeypatch.setattr(verbs, "settings", lambda: dict(on_disk))
    started = {"connect_backlog_cap": 300}
    assert runner.Steps(started, live=True).cap("ja") == 500
    assert runner.Steps(started, live=True).cap("zh") == 300
    assert runner.Steps(started).cap("ja") == 300, "a test's steps read the dict they were handed"
    on_disk["connect_backlog_cap"] = 0
    assert runner.Steps(started, live=True).cap("ja") == 0, "0 is no cap, read live too"


def test_a_settings_file_that_cant_be_read_falls_back_to_the_runs_cap(monkeypatch, local_data):
    # why: a half-written settings.json is a moment's state; the run's own cap holds meanwhile, never the default
    from app.cli import verbs

    def unreadable():
        raise RuntimeError("settings.json is being written")
    monkeypatch.setattr(verbs, "settings", unreadable)
    assert runner.Steps({"connect_backlog_cap": 120}, live=True).cap("ja") == 120


def test_the_run_builds_its_own_steps_live(monkeypatch):
    # why: `run` without steps is the command line's: its steps must read the cap live, or the fix never runs
    made = []

    class Built(Exception):
        pass

    def steps(loaded, live=False):
        made.append(live)
        raise Built()
    monkeypatch.setattr(runner, "Steps", steps)
    with pytest.raises(Built):
        runner.run({}, ["ja"])
    assert made == [True]


def test_one_wake_stamp_is_one_wake(local_data):
    # why: the pause ends on a kick; a mark seen once must not end every later pause too
    steps = runner.Steps({})
    assert steps.kicked() is False, "no kick since the run started"
    kick.wake()
    assert steps.kicked() is True
    assert steps.kicked() is False, "the same stamp, seen: no second wake"
    kick.wake()                                 # at once: two kicks inside one tick of the file clock are two wakes
    assert steps.kicked() is True


def test_a_kick_to_a_running_connect_stamps_its_wake_mark(monkeypatch, local_data):
    # why: before, `kick` did nothing at all while Connect ran — a *Mine now* waited for the 2-minute look
    from app import library_store
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    monkeypatch.setattr(library_store, "update_staged", lambda looks=None: False)
    monkeypatch.setattr(kick, "running", lambda: True)
    assert kick.wake_stamp() is None
    assert kick.kick({"connect_enabled": True}) is None, "nothing started: one runs already"
    assert kick.wake_stamp() is not None


def test_no_wake_while_connect_is_off_or_an_update_is_staged(monkeypatch, local_data):
    # why: Connect off is never woken (D29's one gate); an update staged starts nothing and wakes nothing
    from app import library_store
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    monkeypatch.setattr(kick, "running", lambda: True)
    monkeypatch.setattr(library_store, "update_staged", lambda looks=None: False)
    kick.kick({"connect_enabled": False})
    assert kick.wake_stamp() is None
    monkeypatch.setattr(library_store, "update_staged", lambda looks=None: True)
    kick.kick({"connect_enabled": True})
    assert kick.wake_stamp() is None


def test_the_pause_between_looks_ends_on_a_kick(tmp_path, ledger, monkeypatch):
    # why: the second look must come within the pause's small step after the kick, not after LOOK_EVERY_S
    monkeypatch.setattr(runner, "LOOK_EVERY_S", 60)
    monkeypatch.setattr(runner, "UPDATE_LOOK_S", 0.01)
    steps = _steps(tmp_path, cap=300, waiting=306)
    kicks = iter([False, True])         # the look's own baseline sees nothing; the kick lands in the pause
    steps.kicked = lambda: next(kicks, False)
    started = time.monotonic()
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, cancel=threading.Event(), looks=2)
    assert summary["looks"] == 2
    assert time.monotonic() - started < 10, "woken by the kick, never the 60 s pause"


def test_a_kick_before_a_look_is_answered_by_it_with_no_extra_look(tmp_path, ledger, monkeypatch):
    # why (review r42 #6): the look reads the ask itself; a wake left over from before it would cost one more look
    # (an Anki count per waiting job) for nothing
    monkeypatch.setattr(runner, "LOOK_EVERY_S", 0.3)
    monkeypatch.setattr(runner, "UPDATE_LOOK_S", 0.1)
    steps = _steps(tmp_path, cap=300, waiting=306)
    calls = []
    steps.kicked = lambda: (calls.append(1), len(calls) == 1)[1]     # one kick, seen at the look's start
    started = time.monotonic()
    runner.run({}, ["ja"], steps=steps, ledger=ledger, cancel=threading.Event(), looks=2)
    assert time.monotonic() - started >= 0.3, "the pause ran whole: the kick was the first look's"


def test_a_wake_look_that_fails_is_no_wake():
    # why: a stat that raises must never end the run nor every pause
    class Steps:
        def kicked(self):
            raise OSError("the folder went away")
    assert runner._kicked(Steps()) is False
    assert runner._kicked(object()) is False, "a test's steps without the look: no wake"


def test_a_parked_episode_you_ask_for_is_tried_again_in_the_same_run(tmp_path, ledger):
    # why (review r42 #3): a job waiting for the next start is parked for the run; with episodes waiting at the cap
    # Connect runs for hours, so a *Mine now* on a parked one must try it again now, never at the next start
    steps = _steps(tmp_path, line={"ja": [1]}, queue={"ja": [1]})
    job = None
    parked = {}
    with ledger.transaction():
        ledger.queue("ja", 1, "user", None, store_id="store-1")
    job = ledger.jobs("ja")[0]
    out = {"waiting": {}}
    runner._wait(ledger, job, runner.Wait("Connect stopped on an error", look=False), out, parked)
    assert runner._open_jobs(ledger, "ja", parked) == [], "parked: not tried again this run"
    with ledger.transaction():
        ledger.ask("ja", 1, "2026-10-23T00:53:30.691086Z", store_id="store-1")
    assert [j["id"] for j in runner._open_jobs(ledger, "ja", parked)] == [job["id"]], "your press tries it again"
    runner._wait(ledger, ledger.job_by_id(job["id"]), runner.Wait("Connect stopped on an error", look=False), out,
                 parked)
    assert runner._open_jobs(ledger, "ja", parked) == [], "the same ask, parked again: once a press"
    assert steps is not None


def test_the_shelf_never_takes_the_cards_of_an_episode_you_asked_for(tmp_path, ledger, monkeypatch):
    # why (review r42 #2): the asked episode is mined past the cap; the next episode at the cap asks the shelf, which
    # must count the asked episode as pinned, or it suspends the cards your press just made
    import contextlib
    from app.connect import shelf
    with ledger.transaction():
        ledger.ask("ja", 7, "2026-10-23T00:53:30.691086Z", store_id="store-1")
        ledger.queue("ja", 8, "user", None, store_id="store-1")
    seen = {}
    monkeypatch.setattr(shelf, "made_notes", lambda store: {})
    monkeypatch.setattr(shelf, "pinned_items", lambda store: {3})
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    monkeypatch.setattr(shelf, "kept", lambda led: set())
    monkeypatch.setattr(shelf, "cards", lambda anki, query, made: [])
    monkeypatch.setattr(shelf, "plan", lambda waiting, needed, cap, count, pinned, holder, finished:
                        seen.setdefault("pinned", set(pinned)) and [])
    steps = runner.Steps({})
    monkeypatch.setattr(steps, "_open", lambda lang: contextlib.nullcontext(object()))
    monkeypatch.setattr(steps, "_list_order", lambda lang: {})
    monkeypatch.setattr(steps, "_top_words", lambda lang, store: set())
    monkeypatch.setattr(steps, "_anki", lambda: object())
    assert steps._shelve("ja", ledger, [], 306, 300) == 0
    assert seen["pinned"] == {3, 7}, "the store's pins and the asked episode, never the one nobody asked for"


def _counting(monkeypatch, deck_notes, connect_notes, made):
    """Steps whose Anki answers `deck_notes` for the deck search and `connect_notes` for Connect's tag, and whose
    store made `made` (note ids) -> (steps, the queries asked)."""
    import contextlib
    from app import anki_connect, anki_sync
    from app.connect import shelf
    asked = []

    def find_notes(url, query):
        asked.append(query)
        return list(connect_notes if query == anki_sync.backlog_query([], connect=True) else deck_notes)
    monkeypatch.setattr(anki_connect, "find_notes", find_notes)
    monkeypatch.setattr(shelf, "made_notes", lambda store: {n: (1, "勇気") for n in made})
    steps = runner.Steps({"anki_sync_decks": {"ja": ["Mining"]}})
    monkeypatch.setattr(steps, "_open", lambda lang: contextlib.nullcontext(object()))
    return steps, asked


def test_the_caps_count_is_every_new_unsuspended_card_in_your_decks_and_connects(monkeypatch):
    # why (row 41, Sonic's B3-2 A): the hover said 306 (Surasura's cards), the bottom bar 344 (every new note in the
    # deck + Surasura's). One count: the deck's new notes and Connect's own, each once
    from app import anki_sync
    own = list(range(1, 39))                            # 38 of your own new notes in the deck
    connect = list(range(1000, 1306))                   # 306 of Connect's, ten of them in the deck too
    steps, asked = _counting(monkeypatch, own + connect[:10], connect, connect)
    assert steps.waiting_count("ja") == 344
    assert all("-is:suspended" in q for q in asked), "a suspended card isn't waiting: yours means known"
    assert anki_sync.backlog_query(["Mining"]) in asked


def test_the_cap_counts_only_this_languages_connect_cards(monkeypatch):
    # why (review r2 #2, D31): Connect's tag spans every language; Japanese's cards must never fill Chinese's cap
    steps, _ = _counting(monkeypatch, [], [1000, 1001, 2000], [2000])   # this store made 2000 alone
    assert steps.waiting_count("ja") == 1


def test_with_no_deck_chosen_the_count_is_connects_own_cards():
    # why: an empty deck list must still be a valid search (before: "( OR tag…)")
    from app import anki_sync
    assert anki_sync.backlog_query([], connect=True) == '("tag:surasura::connect::*") is:new -is:suspended'


def test_the_shelf_suspends_nothing_when_it_cant_bring_the_batch_under_the_cap(tmp_path, ledger, monkeypatch):
    # why (review r2 #3): the count holds your own new cards too; the shelf takes only Connect's. 520 waiting, cap
    # 500, a 50-word batch: 70 must go, only 2 of Connect's could, so shelving them would change nothing
    import contextlib
    from app.connect import shelf
    for name, fn in (("made_notes", lambda store: {}), ("pinned_items", lambda store: set()),
                     ("finished_items", lambda store, made: set()), ("kept", lambda led: set()),
                     ("cards", lambda anki, query, made: [])):
        monkeypatch.setattr(shelf, name, fn)
    monkeypatch.setattr(shelf, "plan", lambda *a, **k: [shelf.Card(1, 11, "勇気", 9), shelf.Card(2, 12, "約束", 9)])
    shelved = []
    monkeypatch.setattr(shelf, "shelve", lambda *a, **k: shelved.append(a) or 1)
    steps = runner.Steps({})
    monkeypatch.setattr(steps, "_open", lambda lang: contextlib.nullcontext(object()))
    monkeypatch.setattr(steps, "_list_order", lambda lang: {})
    monkeypatch.setattr(steps, "_top_words", lambda lang, store: set())
    monkeypatch.setattr(steps, "_anki", lambda: object())
    todo = [{"word": "気配", "reading": "ケハイ"}] * 50
    assert steps._shelve("ja", ledger, todo, 520, 500) == 0
    assert shelved == [], "nothing suspended for nothing"


def test_an_ask_from_an_earlier_run_no_longer_keeps_its_cards_off_the_shelf(tmp_path, ledger, monkeypatch):
    # why (review r2 #7): the ledger keeps every ask; an episode pressed weeks before, long done, is no pin today
    with ledger.transaction():
        ledger.ask("ja", 7, "2026-09-01T00:00:00Z", store_id="store-1")
    old = ledger.jobs("ja")[0]
    ledger.set_state(old["id"], "done")
    ledger.conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", ("2026-09-01T00:10:00Z", old["id"]))
    seen = {}
    import contextlib
    from app.connect import shelf
    for name, fn in (("made_notes", lambda store: {}), ("pinned_items", lambda store: set()),
                     ("finished_items", lambda store, made: set()), ("kept", lambda led: set()),
                     ("cards", lambda anki, query, made: [])):
        monkeypatch.setattr(shelf, name, fn)
    monkeypatch.setattr(shelf, "plan", lambda waiting, needed, cap, count, pinned, holder, finished:
                        seen.setdefault("pinned", set(pinned)) and [])
    steps = runner.Steps({})
    monkeypatch.setattr(steps, "_open", lambda lang: contextlib.nullcontext(object()))
    monkeypatch.setattr(steps, "_list_order", lambda lang: {})
    monkeypatch.setattr(steps, "_top_words", lambda lang, store: set())
    monkeypatch.setattr(steps, "_anki", lambda: object())
    steps._shelve("ja", ledger, [], 306, 300)
    assert seen["pinned"] == set()
