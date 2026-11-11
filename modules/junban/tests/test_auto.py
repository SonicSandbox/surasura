# SPDX-License-Identifier: GPL-3.0-or-later
"""The automatic reorder (`auto.py`) — a test option that writes WITHOUT a preview.

That makes this file the one where "it did nothing" is the usual right answer. What it holds still,
in order of what a wrong answer would cost the user:

  * **positions only, unless asked** — with `junban_auto_actions` off, nothing the panel has saved
    beyond the order reaches Anki: no suspension, no flag, no tag, no field;
  * **never while the user is reviewing**, never for "All decks", never on a list older than the
    library, never over an interrupted run;
  * **no pulling the user out of Anki** — no `reloadCollection` / `guiDeckBrowser` afterwards;
  * and everything else a manual run guarantees still holds, because it IS a manual run underneath.

Against the same FakeCollection as the engine's own tests — real state, never a live Anki.
"""
import os
import time

import pytest

from modules.junban import auto, undo
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FakeCollection, _card_of,
                                                  _collection, _patched, _results, _settings, _tags_of)

_ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")


def _backlog(tmp_path, **kwargs):
    """冒険 / 散歩 on the list, 須藤 / 図書館 not — in the wrong order, so a run has work to do."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険"])
    return FakeCollection(cards, notes, actions=_ACTIONS, **kwargs)


def _auto(**over):
    """The saved settings the dashboard hands over: everything the panel saved — the tag, and here
    all three cards-not-on-your-list actions — with the automatic reorder switched on."""
    return _settings(junban_order="content", junban_auto_reorder=True, junban_later_tag=True,
                     junban_later_flag=True, junban_later_suspend=True, **over)


def test_it_is_off_by_default_and_asks_anki_nothing(tmp_path):
    fake = _backlog(tmp_path)
    with _patched(fake):
        assert auto.run_quietly(_settings(junban_order="content")) == ""
    assert fake.requests == []


def test_by_default_it_moves_positions_and_writes_nothing_else(tmp_path):
    """The user's A3: the automatic run reorders; the actions saved in the panel (suspend
    included) and the touch-ups (the Surasura tag) wait for a manual run. And no refresh call —
    Anki is not sent to its deck list behind the user's back."""
    fake = _backlog(tmp_path)

    with _patched(fake):
        message = auto.run_quietly(_auto())

    # 2.x-dev keeps .startswith("順 (automatic): Reordered") and the window's snapshot (no job: 2.5's dense run);
    # 3.0 (W3.5 row 7): spaced always — an automatic run keeps today's baseline (03 §5), and Restore works from it.
    assert message.startswith("順 (automatic): ") and "Reordered" in message, message
    assert fake.writes, "the positions were written"
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    assert not {"reloadCollection", "guiDeckBrowser"} & set(fake.action_names)
    assert undo.load("ja") is None and undo.load("ja", "baseline"), "today's baseline, never the window's snapshot"


def test_on_3_0_with_the_actions_switched_on_the_automatic_step_moves_positions_spaced_then_applies_them(tmp_path):
    """2.x-dev: `junban_auto_actions` applies everything the panel saved — suspend included — on 2.5's dense run
    (test_with_the_actions_switched_on_it_applies_everything_the_panel_saved). 3.0 (W3.5 row 7, Haya's G2b): the
    automatic step is a spaced job that carries the actions `auto.reorder` decided — positions spaced first, then the
    tag, the flag and the suspend — and keeps the window's snapshot, as 2.5's step did, instead of today's baseline."""
    fake = _backlog(tmp_path)

    with _patched(fake):
        message = auto.run_quietly(_auto(junban_auto_actions=True))

    assert "Spaced your new cards out once" in message and "Reordered" in message and fake.writes, message
    assert [_card_of(fake, word)["queue"] for word in ("須藤", "図書館")] == [-1, -1]
    assert "Surasura::later" in _tags_of(fake, "須藤")
    assert _card_of(fake, "冒険")["queue"] == 0
    assert sorted(card_id for card_id, _flag in fake.flag_writes) == sorted(
        _card_of(fake, word)["cardId"] for word in ("須藤", "図書館"))
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["suspended"] == sorted(
        _card_of(fake, word)["cardId"] for word in ("須藤", "図書館"))
    assert undo.load("ja", "baseline") is None


def test_it_waits_while_the_user_is_reviewing(tmp_path):
    fake = _backlog(tmp_path, reviewing=True)
    with _patched(fake):
        assert auto.run_quietly(_auto()) == ""
    assert fake.writes == []


def test_it_never_runs_for_all_decks_and_says_why(tmp_path):
    """The user's A4: one nominated deck only. Said, because otherwise nothing ever happens and
    nothing says why — the dashboard shows the line once, not every five minutes."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        message = auto.run_quietly(_auto(junban_scope="all"))
    assert "one deck" in message and fake.writes == []


def test_anki_closed_is_simply_not_now(tmp_path):
    fake = _backlog(tmp_path, offline=True)
    with _patched(fake):
        assert auto.run_quietly(_auto()) == ""


def test_a_list_older_than_the_library_waits_for_the_next_generate(tmp_path):
    """A Generate that failed, or content added since: the order would be out of date."""
    fake = _backlog(tmp_path)
    manifest = os.path.join(str(tmp_path), "User Files", "ja", "master_manifest.json")
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write("{}")
    later = time.time() + 60
    os.utime(manifest, (later, later))

    with _patched(fake):
        assert auto.run_quietly(_auto()) == ""
    assert fake.writes == []


def test_an_interrupted_run_is_left_for_the_user_to_restore(tmp_path):
    """The snapshot of a run that died is the only way back; an automatic run must not bury it."""
    fake = _backlog(tmp_path)
    undo.save({999: 1}, ["TheBank"], "ja")              # saved, never marked complete

    with _patched(fake):
        message = auto.run_quietly(_auto())

    assert "did not run" in message and "Undo the last reorder" in message
    assert fake.writes == []


def test_a_second_run_with_nothing_to_move_says_nothing(tmp_path):
    fake = _backlog(tmp_path)
    with _patched(fake):
        auto.run_quietly(_auto())
        assert auto.run_quietly(_auto()) == ""


def test_a_list_out_of_date_by_the_generate_buttons_own_check_waits(tmp_path):
    """§16.6: the dashboard asks what the Generate button's ✓ asks — library, known words, analysis
    settings. Known words changed since the last Generate (the library untouched): no reorder."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        assert auto.run_quietly(_auto(), list_current=False) == ""
    assert fake.writes == []


def test_an_up_to_date_answer_skips_the_old_timestamp_check(tmp_path):
    """True from the dashboard is the better answer; the manifest's timestamp is only the fallback
    for when it could not tell (None)."""
    fake = _backlog(tmp_path)
    manifest = os.path.join(str(tmp_path), "User Files", "ja", "master_manifest.json")
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write("{}")
    later = time.time() + 60
    os.utime(manifest, (later, later))
    with _patched(fake):
        assert auto.run_quietly(_auto(), list_current=None) == ""
        message = auto.run_quietly(_auto(), list_current=True)
    # 2.x-dev keeps .startswith("順 (automatic): Reordered") (no job: 2.5's dense run); 3.0 (W3.5 row 7): spaced
    # always, whose first run says it spaced the cards out once, then "Reordered N cards."
    assert message.startswith("順 (automatic): ") and "Reordered" in message, message


# --- the automatic Backfill: one job, two switches, reorder first ---------------------------------- #
def _backfill_recorder(fake, seen):
    """Stands in for `backfill.run_auto` (its own tests prove new cards / empty fields only): records
    that it ran, and whether the reorder's writes had already landed when it did."""
    def run_auto(settings):
        seen.append({"after_reorder": bool(fake.writes), "settings": dict(settings)})
        return {"ok": True, "written": [1789712000000], "message": "Filled 1 note.", "problems": []}
    return run_auto


def test_the_backfill_step_runs_on_its_own_switch(tmp_path, monkeypatch):
    from modules.junban import backfill
    fake, seen = _backlog(tmp_path), []
    monkeypatch.setattr(backfill, "run_auto", _backfill_recorder(fake, seen))
    settings = _settings(junban_order="content", junban_auto_backfill=True)
    assert auto.enabled(settings)
    with _patched(fake):
        message = auto.run_quietly(settings)
    assert message == "Backfill (automatic): Filled 1 note."
    assert len(seen) == 1 and fake.writes == [], "the reorder's switch is off, so nothing moved"


def test_with_both_switches_the_reorder_goes_first(tmp_path, monkeypatch):
    # A new card's place is settled before anything is written onto it.
    from modules.junban import backfill
    fake, seen = _backlog(tmp_path), []
    monkeypatch.setattr(backfill, "run_auto", _backfill_recorder(fake, seen))
    with _patched(fake):
        message = auto.run_quietly(_auto(junban_auto_backfill=True))
    # 2.x-dev keeps .startswith("順 (automatic): Reordered") (no job: 2.5's dense run); 3.0 (W3.5 row 7): spaced
    # always, whose first run says it spaced the cards out once, then "Reordered N cards."
    assert message.startswith("順 (automatic): ") and "Reordered" in message and message.endswith("Filled 1 note.")
    assert seen == [{"after_reorder": True, "settings": seen[0]["settings"]}]


def test_the_backfill_step_waits_while_the_user_is_reviewing(tmp_path, monkeypatch):
    from modules.junban import backfill
    fake, seen = _backlog(tmp_path, reviewing=True), []
    monkeypatch.setattr(backfill, "run_auto", _backfill_recorder(fake, seen))
    with _patched(fake):
        assert auto.run_quietly(_settings(junban_auto_backfill=True)) == ""
    assert seen == []


# --------------------------------------------------------------------------- #
# The guards the dashboard used to hold (P1.2): one copy, here, for the dashboard and `surasura-cli junban --auto`
# --------------------------------------------------------------------------- #
def test_the_shared_guards_say_why_nothing_may_run(monkeypatch):
    import threading
    from app import locks, updater
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    on = {"enable_junban": True}
    assert auto.blocked(on) is None
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    assert auto.blocked(on) == "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)"
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC")
    assert auto.blocked({"enable_junban": False}) == "順 is switched off"
    assert auto.blocked({}) == "順 is switched off"
    monkeypatch.setattr(updater, "children_held", lambda: True)
    assert auto.blocked(on) == "an update is waiting"
    monkeypatch.setattr(updater, "children_held", lambda: False)

    # a 順 window open in this program: it holds `junban-window` on one of its workers
    taken, done = threading.Event(), threading.Event()

    def window():
        with locks.take("junban-window", "the 順 window"):
            taken.set()
            done.wait(10)
    worker = threading.Thread(target=window)
    worker.start()
    try:
        assert taken.wait(10)
        assert auto.window_open()
        assert auto.blocked(on) == "the 順 window is open"
        assert auto.blocked(on, window=False) is None
    finally:
        done.set()
        worker.join(10)
    assert not auto.window_open()


def test_the_command_lines_reorder_writes_positions_only_even_with_actions_on(tmp_path):
    """`surasura-cli junban --auto` (P0.3 03): positions only, whatever `junban_auto_actions` says."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        done = auto.reorder(_auto(junban_auto_actions=True), list_current=True, positions_only=True)
    assert done["outcome"] == "ran" and done["report"]["written"] and fake.writes
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    assert not {"reloadCollection", "guiDeckBrowser"} & set(fake.action_names)


# --- Anki busy with a collection operation (#370, a 3.0.2 field report) ----------------------------- #
# "順 automatic reorder skipped: Anki refused 'guiReviewActive': A collection operation is active. Backfill (automatic)
# skipped: …", over and over: the newer AnkiConnect refuses while Anki runs its sync (often the one Surasura asked for),
# Check Database, an import. Anki is open and nothing is wrong: the step waits a little, then is simply not now.
_BUSY = "A collection operation is active."
_SYNCING = "Collection lifecycle operation is active."


def _busy_for(fake, action, n, text=_BUSY):
    """The fake answers `action` (asked on its own or in a `multi`) with Anki's busy refusal `n` times."""
    from modules.junban.tests.test_reposition import AnkiRefusal
    left, dispatch = [n], fake._dispatch

    def busy(name, params):
        if name == action and left[0] > 0:
            left[0] -= 1
            return AnkiRefusal(text)
        return dispatch(name, params)
    fake._dispatch = busy
    return fake


@pytest.fixture
def short_waits(monkeypatch):
    from app import anki_connect
    monkeypatch.setattr(anki_connect, "BUSY_POLL_S", 0.0)
    monkeypatch.setattr(anki_connect, "BUSY_WAIT_S", 0.0)
    return anki_connect


def test_anki_busy_for_a_moment_is_waited_out_then_the_reorder_runs(tmp_path, short_waits, monkeypatch):
    monkeypatch.setattr(short_waits, "BUSY_WAIT_S", 60.0)        # two refusals, well inside the wait
    fake = _busy_for(_backlog(tmp_path), "guiReviewActive", 2)
    with _patched(fake):
        message = auto.run_quietly(_auto())
    assert "Reordered" in message and "refused" not in message, message
    assert fake.writes


def test_anki_busy_past_the_wait_is_quietly_not_now_for_both_steps(tmp_path, short_waits, monkeypatch):
    from modules.junban import backfill
    fake, seen = _busy_for(_backlog(tmp_path), "guiReviewActive", 99), []
    monkeypatch.setattr(backfill, "run_auto", _backfill_recorder(fake, seen))
    with _patched(fake):
        assert auto.run_quietly(_auto(junban_auto_backfill=True)) == "", "never a refusal shown for a busy Anki"
        assert auto.reorder(_auto())["outcome"] == "anki-busy"
    assert fake.writes == [] and seen == []


def test_anki_starting_its_sync_mid_run_is_quietly_not_now(tmp_path, short_waits):
    # the reads after the first guards meet the sync's refusal: reposition.run reports it, never a refusal shown
    fake = _busy_for(_backlog(tmp_path), "findCards", 99, text=_SYNCING)
    with _patched(fake):
        done = auto.reorder(_auto())
        assert done["outcome"] == "anki-busy", done
        assert auto.run_quietly(_auto()) == ""
    assert fake.writes == []


def test_the_backfill_meeting_a_busy_anki_mid_read_is_quiet(tmp_path, short_waits, monkeypatch):
    from modules.junban import backfill
    monkeypatch.setattr(backfill, "run_auto", lambda settings: backfill._report(
        False, "Nothing was filled.", problems=[f"Anki refused 'findNotes': {_SYNCING}"], anki_busy=True))
    with _patched(_backlog(tmp_path)):
        assert auto.run_quietly(_settings(junban_order="content", junban_auto_backfill=True)) == ""


def test_a_real_refusal_is_still_said(tmp_path):
    from modules.junban.tests.test_reposition import AnkiRefusal
    fake = _backlog(tmp_path)
    dispatch = fake._dispatch
    fake._dispatch = lambda action, params: (AnkiRefusal("unsupported action") if action == "guiReviewActive"
                                             else dispatch(action, params))
    with _patched(fake):
        message = auto.run_quietly(_auto())
    assert message.startswith("順 automatic reorder skipped:") and "unsupported action" in message, message


def test_a_busy_re_check_read_leaves_the_cards_for_the_next_re_order_never_failures(tmp_path, short_waits):
    # review 1 B1: S1's sync runs just before the writes; a re-check refused while it runs is not a failed card
    from modules.junban import ankiconnect
    fake = _busy_for(_backlog(tmp_path), "cardsInfo", 99, text=_SYNCING)
    ids = sorted(fake.cards)
    batches = [[(ids[0], 5)], [(ids[1], 6)]]
    with _patched(fake):
        written, failures, left = ankiconnect.set_due_checked(
            "http://127.0.0.1:8765", batches, {card_id: fake.cards[card_id]["due"] for card_id in ids})
    assert (written, failures, sorted(left)) == ([], [], sorted(ids[:2])) and fake.writes == []


def test_a_busy_review_check_inside_the_re_checks_multi_counts_as_a_review(tmp_path):
    # review 1 S6: a card answered in the reviewer is itself a collection operation — busy is no proof you aren't
    from modules.junban import ankiconnect
    fake = _busy_for(_backlog(tmp_path), "guiReviewActive", 1)
    ids = sorted(fake.cards)
    with _patched(fake):
        reviewing, _sure, now = ankiconnect._checked("http://127.0.0.1:8765", ids[:1], {}, None, True)
    assert reviewing is True and ids[0] in now
