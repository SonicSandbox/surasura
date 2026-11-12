# SPDX-License-Identifier: GPL-3.0-or-later
"""The automatic step's actions on 3.0 (`reposition._run` with `job.actions`), at the edges its main suite leaves open:
which action alone makes a run keep the window's snapshot, how it ends (or keeps) today's baseline, and when the
actions wait for the next run — a card the re-check left, a snapshot that couldn't be saved again, Anki not answering.

What a wrong answer would cost a learner, most first: a card suspended (or a returning word's card unsuspended) that
no Restore can put back; a Restore that unsuspends a card the user suspended themselves; actions written onto cards
that changed under the run. Against the fake collection (real Japanese words, never Anki).
"""
import pytest

from app import anki_connect
from modules.junban import ankiconnect, auto, reposition, spaced, undo, unlisted
from modules.junban.ankiconnect import AnkiError
from modules.junban.tests.connect_scene import SCENE, scene
from modules.junban.tests.connect_scene import settings as connect_settings
from modules.junban.tests.test_auto_actions import _OFF_THE_LIST, _auto, _backlog, _ids
from modules.junban.tests.test_reposition import _card_of, _patched


def _positions_only(settings):
    """A move in the window (the host's per-move job): positions only, today's baseline."""
    return reposition.run(settings, refresh=False, verb=anki_connect.AUTOMATIC_STEP, job=spaced.Job(automatic=True))


# --------------------------------------------------------------------------------------------------------------- #
# Which action alone keeps the window's snapshot
# --------------------------------------------------------------------------------------------------------------- #
def test_a_returning_words_card_alone_is_kept_in_the_windows_snapshot(tmp_path, monkeypatch):
    """Nothing to tag, flag or suspend off the list — only 老婆, parked by Junban and back on the list, to unsuspend —
    and, whatever the touch-ups say (here: none), that unsuspend is an action: the automatic step (Connect's preview
    on, so it unsuspends) keeps the window's snapshot naming it, not today's baseline, so Restore can set the card
    aside again."""
    monkeypatch.setattr(reposition, "_has_touchups", lambda touchups: False)
    on_the_list = [row for row in SCENE if row[0] in ("散歩", "冒険", "走る", "老婆")]
    fake = scene(tmp_path, on_the_list)
    settings = connect_settings(junban_auto_reorder=True, junban_auto_actions=True)
    with _patched(fake):
        done = auto.reorder(settings, list_current=True)
    assert done["outcome"] == "ran", done
    assert fake.card_of("老婆")["queue"] == 0, "the setup: 老婆's card came back"
    saved = undo.load("ja")
    assert saved and saved.get("unsuspended") == [fake.card_of("老婆")["cardId"]], saved
    assert undo.load("ja", "baseline") is None, "one restore point: the snapshot instead of today's baseline"


def test_the_cards_off_the_list_alone_keep_the_windows_snapshot(tmp_path):
    """No touch-up (no tag named for the notes that moved): the tag, flag and suspend of the cards off the list are
    the run's only actions — the window's snapshot still names every suspend, so Restore can take them back."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        done = auto.reorder(_auto(junban_tag=""), list_current=True)
    assert done["outcome"] == "ran", done
    saved = undo.load("ja")
    assert saved and saved["suspended"] == _ids(fake, _OFF_THE_LIST), saved
    assert undo.load("ja", "baseline") is None


# --------------------------------------------------------------------------------------------------------------- #
# Today's baseline
# --------------------------------------------------------------------------------------------------------------- #
def test_autojunbans_run_with_actions_ends_todays_baseline(tmp_path):
    """A move earlier today laid today's baseline; AutoJunban's run with actions then keeps the window's snapshot —
    and ends the baseline, as a run from 順's window does: one restore point, never two that undo each other."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        assert _positions_only(_auto())["ok"]
        laid = undo.load("ja", "baseline")
        assert laid and not laid.get("ended_at"), "the setup: a move laid today's baseline"
        done = auto.reorder(_auto(), list_current=True)
    assert done["outcome"] == "ran", done
    assert undo.load("ja")["suspended"] == _ids(fake, _OFF_THE_LIST)
    assert undo.load("ja", "baseline").get("ended_at"), "today's baseline outlived the window's snapshot"


def test_a_connect_runs_actions_leave_todays_baseline_as_it_was(tmp_path):
    """Connect's run keeps its own snapshot (`run_id`) beside the window's line: today's baseline, laid by a move
    earlier, is still there to go back to."""
    fake = scene(tmp_path)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        assert _positions_only(connect_settings())["ok"]
        baseline = undo.load("ja", "baseline")
        assert baseline
        done = auto.reorder(connect_settings(), list_current=True, positions_only=True, run_id=run_id,
                            job=spaced.Job(automatic=True))
    assert done["outcome"] == "ran", done
    assert undo.load("ja", run_id=run_id)["suspended"]
    assert undo.load("ja", "baseline") == baseline, "Connect's run ended the window's baseline"


# --------------------------------------------------------------------------------------------------------------- #
# When the actions wait for the next run
# --------------------------------------------------------------------------------------------------------------- #
def test_a_card_the_recheck_left_means_no_actions_this_run(tmp_path):
    """No review — but a card moved in Anki between the plan and its write (the re-check leaves it for the next job):
    the actions wait too, every one of them."""
    fake = _backlog(tmp_path)
    moved = []

    def meanwhile(ids):
        if not moved and not fake.writes and undo.load("ja") is not None:
            card = fake.cards[ids[0]]                      # the first request's re-check: you moved it in Anki
            card["due"] += 1
            moved.append(ids[0])
    fake.before_cards_info = meanwhile
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True)
    report = done["report"]
    assert moved and report["left"] == moved, report
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == [], "actions with a card left"


def test_a_snapshot_that_cannot_be_saved_again_means_no_actions(tmp_path, monkeypatch):
    """The re-check narrowed the actions (須藤 studied meanwhile) and the snapshot can't be saved again with them (the
    disk full): the copy on disk still names 須藤 — so nothing is tagged, flagged or suspended this run, never a Restore
    that would unsuspend a card the run didn't suspend."""
    fake = _backlog(tmp_path)

    def meanwhile(ids):
        if fake.writes and set(ids) == set(_ids(fake, _OFF_THE_LIST)):
            studied = _card_of(fake, "須藤")
            studied["type"], studied["queue"] = 2, 2
    fake.before_cards_info = meanwhile
    real, saves = undo.save, []

    def save(*args, **kwargs):
        saves.append(1)
        if len(saves) > 1:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)
    monkeypatch.setattr(undo, "save", save)
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True)
    assert len(saves) == 2, "the setup: the snapshot was asked to be saved again"
    assert fake.writes, done
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == [], "actions the disk can't undo"


def test_marker_tags_alone_are_a_touch_up_to_keep_in_the_snapshot():
    """A WP-N marker tag is a write to the user's notes: alone, it still makes the run keep the window's snapshot."""
    assert reposition._has_touchups({"marker_tags": {"Surasura::star": [1_700_000_000_001]}}) is True
    assert reposition._has_touchups({}) is False


def test_anki_not_answering_at_the_recheck_leaves_nothing_to_act_on(monkeypatch):
    """The one read just before the actions fails: nothing to act on this run (never the plan, unchecked)."""
    def silent(*_args, **_kwargs):
        raise AnkiError("Anki stopped answering", kind="connection")
    monkeypatch.setattr(ankiconnect, "multi", silent)          # the read rides one `multi` with the review check
    later = {"cards": [1, 2], "note_of": {1: 10, 2: 20}, "tag_notes": [10, 20], "flags": {1: 3, 2: 3},
             "suspend": [1, 2], "counts": {"cards": 2, "tag": 2, "flag": 2, "suspend": 2}}
    checked = reposition._still_new("http://127.0.0.1:8765", later)
    assert checked is not later and not unlisted.has_work(checked), checked
