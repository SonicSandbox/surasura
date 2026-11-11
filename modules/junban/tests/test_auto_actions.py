# SPDX-License-Identifier: GPL-3.0-or-later
"""The automatic step's actions on 3.0 (W3.5 row 7, Haya's G2b seam; G1.3-8).

Every automatic re-order on 3.0 is a spaced job. The job `auto.reorder` hands in carries `actions`: its settings
come in already decided (`junban_auto_actions`, Connect's preview, `positions_only`, and the suspend setting kept
when `connect.suspends_unattended`), and the run applies them. Any other automatic job (the fast re-plan's host,
its per-move job) moves positions only. What a wrong answer would cost, most first:

  * **never a card you suspended, never one you studied meanwhile** — a not-on-list card reviewed or suspended
    between the plan and the write is left alone, and a review starting while the positions go out means no
    actions at all this run;
  * **one Restore puts it all back**: the positions, and exactly the run's own suspends — from the window's snapshot
    (AutoJunban) or the run's own (Connect, `run_id`) — and an unfinished run refuses the next;
  * **positions first**: every position write lands before any tag, flag or suspend, and the suspend goes last;
  * **nothing to act on, nothing new on the wire**: the same requests as a positions-only job (E2.1), and today's
    baseline alone.

Against the fake collection (`ModCollection`: real state, every position checked under the ceiling) — real Japanese
words, never Anki.
"""
import json
import urllib.error

import pytest

from app import anki_connect
from modules.junban import ankiconnect, auto, connect, reposition, spaced, undo
from modules.junban.ankiconnect import AnkiError
from modules.junban.tests.connect_scene import SCENE, scene
from modules.junban.tests.connect_scene import settings as connect_settings
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, _card_of, _collection, _patched, _results,
                                                  _settings, _tags_of)
from modules.junban.tests.test_spaced_runs import ModCollection

_ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")
_OFF_THE_LIST = ["須藤", "図書館", "美術館", "新幹線"]


def _backlog(tmp_path, words=("須藤", "散歩", "図書館", "冒険", "美術館", "新幹線", "洗濯機"), **kwargs):
    """冒険 / 散歩 on the list, 須藤 / 図書館 / 美術館 / 新幹線 not, in the wrong order; 洗濯機 the user suspended
    themselves (no Junban tag) — never Junban's to touch, on the way there or back."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(list(words))
    fake = ModCollection(cards, notes, actions=_ACTIONS, **kwargs)
    if "洗濯機" in words:
        _card_of(fake, "洗濯機")["queue"] = -1
    return fake


def _auto(**over):
    """AutoJunban's settings: the step on, its actions on, and all three not-on-the-list actions saved."""
    return _settings(**dict(dict(junban_order="content", junban_auto_reorder=True, junban_auto_actions=True,
                                 junban_later_tag=True, junban_later_flag=True, junban_later_suspend=True), **over))


def _ids(fake, words):
    return sorted(_card_of(fake, word)["cardId"] for word in words)


def _writes(fake):
    """Each write request in order: "position", "flag", "addTags", "suspend", "unsuspend" or "updateNoteFields"."""
    out = []
    for request in fake.requests:
        action = request["action"]
        if action == "multi":
            inner = [entry for entry in request["params"]["actions"] if entry["action"] == "setSpecificValueOfCard"]
            if inner:
                out.append("position" if inner[0]["params"]["keys"] == ["due"] else "flag")
        elif action in ("addTags", "suspend", "unsuspend", "updateNoteFields"):
            out.append(action)
    return out


def _queues(fake):
    return {card_id: (card["due"], card["queue"]) for card_id, card in fake.cards.items()}


# --------------------------------------------------------------------------------------------------------------- #
# Positions first, then the actions, suspend last
# --------------------------------------------------------------------------------------------------------------- #
def test_every_position_lands_before_any_tag_flag_or_suspend_and_the_suspend_goes_last(tmp_path):
    """2.5's order inside the run (Haya's (2)): positions through the spaced writer, then the touch-ups on the notes
    that moved, then tag → flag → suspend. A card is suspended only once everything else about it has landed."""
    fake = _backlog(tmp_path)
    with _patched(fake):
        done = auto.reorder(_auto(junban_chunk_size=2), list_current=True)
    assert done["outcome"] == "ran", done
    writes = _writes(fake)
    assert writes.count("position") >= 2, writes                  # several position requests, all of them first
    last_position = max(i for i, kind in enumerate(writes) if kind == "position")
    assert all(kind == "position" for kind in writes[:last_position + 1]), writes
    assert {"addTags", "flag", "suspend"} <= set(writes[last_position + 1:]), writes
    assert writes[-1] == "suspend" and writes.index("suspend") > max(
        i for i, kind in enumerate(writes) if kind in ("addTags", "flag")), writes
    assert sorted(c for action, ids in fake.suspend_calls if action == "suspend" for c in ids) == \
        _ids(fake, _OFF_THE_LIST)


# --------------------------------------------------------------------------------------------------------------- #
# One restore point
# --------------------------------------------------------------------------------------------------------------- #
def test_autojunbans_restore_puts_positions_back_and_unsuspends_only_its_own_suspends(tmp_path):
    """AutoJunban without a run id: the window's snapshot, as 2.5's automatic step saved — not today's baseline — so
    the one Restore takes the positions, the tags, the flags and exactly the run's suspends back. 洗濯機, which the
    user suspended, stays suspended."""
    fake = _backlog(tmp_path)
    before = _queues(fake)
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True)
    assert done["outcome"] == "ran", done
    assert [_card_of(fake, word)["queue"] for word in _OFF_THE_LIST] == [-1] * 4
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["suspended"] == _ids(fake, _OFF_THE_LIST)
    assert undo.load("ja", "baseline") is None, "one restore point: the snapshot instead of today's baseline"

    with _patched(fake):
        restored = reposition.restore(_auto())
    assert restored["ok"], restored["problems"]
    assert _queues(fake) == before
    assert _card_of(fake, "洗濯機")["queue"] == -1
    assert ("unsuspend", [_card_of(fake, "洗濯機")["cardId"]]) not in fake.suspend_calls
    assert all("Surasura::later" not in _tags_of(fake, word) for word in _OFF_THE_LIST)
    assert all(not fake.cards[card_id].get("flags") for card_id in _ids(fake, _OFF_THE_LIST))


def test_a_connect_runs_restore_puts_back_its_suspends_and_sets_its_returning_card_aside_again(tmp_path):
    """Connect's run (`run_id`, 3.0): its own snapshot holds what it suspended and the returning word's card it
    unsuspended; `restore_run` undoes exactly those. 洗濯機, suspended by the user without Junban's tag, is no parked
    card and is never touched."""
    fake = scene(tmp_path, SCENE + [("洗濯機", "洗濯機が壊れた。", 8000, [], -1)])
    before = _queues(fake)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(connect_settings(), list_current=True, positions_only=True, run_id=run_id,
                            job=spaced.Job(automatic=True))
    assert done["outcome"] == "ran", done
    saved = undo.load("ja", run_id=run_id)
    assert saved["suspended"] and saved["unsuspended"] == [fake.card_of("老婆")["cardId"]]
    assert fake.card_of("洗濯機")["queue"] == -1
    assert not undo.load("ja") and undo.load("ja", "baseline") is None

    with _patched(fake):
        report = reposition.restore_run(connect_settings(), run_id)
    assert report["ok"], report["problems"]
    assert _queues(fake) == before
    assert all(fake.card_of("洗濯機")["cardId"] not in ids for _action, ids in fake.suspend_calls)


def test_a_connect_run_takes_nothing_over_from_a_cut_window_snapshot(tmp_path):
    """Connect's run (`run_id`) keeps its own snapshot and carries nothing over from the window's: a cut automatic
    run's window snapshot stays exactly as it was (the way back from that run), and the run's own snapshot holds only
    the positions and suspends it wrote — never the cut run's, which its restore would otherwise undo too."""
    fake = scene(tmp_path, SCENE)
    elsewhere = 1789712090000                                      # a card only the cut run moved and suspended
    undo.save([(elsewhere, 50)], ["TheBank"], language="ja", automatic=True, suspended=[elsewhere])
    cut_snapshot = undo.load("ja")
    assert cut_snapshot["complete"] is False and cut_snapshot["automatic"] is True
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(connect_settings(), list_current=True, positions_only=True, run_id=run_id,
                            job=spaced.Job(automatic=True))
    assert done["outcome"] == "ran", done
    saved = undo.load("ja", run_id=run_id)
    assert saved["suspended"], "the run acted: it suspended cards off the list"
    assert str(elsewhere) not in saved["cards"] and elsewhere not in saved["suspended"], saved
    assert undo.load("ja") == cut_snapshot


def _anki_closes_after_the_first(fake, action):
    """Anki closes just after the first `action` request lands ("position": a position write; "suspend"): every
    request after it fails, as when you quit Anki mid-run. `fake.offline = False` opens it again."""
    if action == "position":
        fake.on_write = lambda: setattr(fake, "offline", True)
        return
    real = fake._suspend

    def closing(name, card_ids):
        done = real(name, card_ids)
        if name == action:
            fake.offline, fake._suspend = True, real            # once: Anki opened again stays open
        return done
    fake._suspend = closing


def _cut(fake, action="suspend", **over):
    """AutoJunban's run with its actions, cut by Anki closing after the first `action` request -> its outcome. Its
    window snapshot is left unfinished, and marked as an automatic run's."""
    _anki_closes_after_the_first(fake, action)
    with _patched(fake):
        cut = auto.reorder(_auto(junban_chunk_size=2, **over), list_current=True)
    fake.offline = False
    saved = undo.load("ja")
    assert saved["complete"] is False and saved["automatic"] is True, saved
    return cut


def test_the_next_acting_run_takes_over_a_cut_one_and_one_restore_undoes_both_never_your_own_suspend(tmp_path):
    """3.0: a run nobody started never stops the automation it belongs to. AutoJunban's run is cut by Anki closing
    after its first suspend (須藤 and 図書館 suspended, 美術館 and 新幹線 not). The next run goes on and takes the cut
    one's snapshot over: the cut run's original positions and flags win, and the suspends are the union of both runs.
    One Restore then puts back how the deck was before either run — 洗濯機, which you suspended yourself, is never
    touched on the way there or back."""
    fake = _backlog(tmp_path)
    before = _queues(fake)
    _cut(fake)
    cut_snapshot_cards = undo.load("ja")["cards"]
    assert [_card_of(fake, word)["queue"] for word in _OFF_THE_LIST] == [-1, -1, 0, 0], "cut after the first suspend"

    with _patched(fake):
        done = auto.reorder(_auto(junban_chunk_size=2), list_current=True)
    assert done["outcome"] == "ran" and done["report"]["ok"], done
    assert [ids for action, ids in fake.suspend_calls if action == "suspend"][-1] == _ids(fake, ["美術館", "新幹線"])
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["automatic"] is True, saved
    assert saved["suspended"] == _ids(fake, _OFF_THE_LIST), "the union: the cut run's suspends and this run's"
    assert {key: due for key, due in saved["cards"].items() if key in cut_snapshot_cards} == cut_snapshot_cards
    assert sorted(int(card_id) for card_id in saved["flags"]) == _ids(fake, _OFF_THE_LIST)
    assert all(flag == 0 for flag in saved["flags"].values()), "each card's flag from before the cut run"
    baseline = undo.load("ja", "baseline")
    assert baseline is None or baseline.get("ended_at"), "one restore point"

    with _patched(fake):
        restored = reposition.restore(_auto())
    assert restored["ok"], restored["problems"]
    assert _queues(fake) == before, "one Restore undoes both runs"
    assert all("Surasura::later" not in _tags_of(fake, word) for word in _OFF_THE_LIST)
    assert all(not fake.cards[card_id].get("flags") for card_id in _ids(fake, _OFF_THE_LIST))
    yours = _card_of(fake, "洗濯機")["cardId"]
    assert _card_of(fake, "洗濯機")["queue"] == -1 and not [ids for _a, ids in fake.suspend_calls if yours in ids]


def test_a_positions_only_job_after_a_cut_acting_run_keeps_its_snapshot_unfinished_and_restorable(tmp_path):
    """The cut run's snapshot is the only way back from it. A positions-only job after it (AutoJunban with its
    actions off) goes on — it keeps today's baseline, a file of its own — and leaves the cut snapshot exactly as it
    was: unfinished, and what 順's Restore offers over that newer baseline. That Restore puts the deck back as it was
    before the cut run, the later move included."""
    fake = _backlog(tmp_path)
    before = _queues(fake)
    _cut(fake, "position")
    cut_snapshot = undo.load("ja")
    one, two = _card_of(fake, "冒険"), _card_of(fake, "散歩")
    one["due"], two["due"] = two["due"], one["due"]                     # a move in Anki since: the job has work

    with _patched(fake):
        done = auto.reorder(_auto(junban_auto_actions=False), list_current=True)
    assert done["outcome"] == "ran" and done["report"]["written"], done
    assert fake.suspend_calls == [] and fake.flag_writes == []
    assert undo.load("ja") == cut_snapshot, "the cut run's snapshot is left exactly as it was"
    assert undo.load("ja", "baseline") and undo.restorable("ja") == cut_snapshot

    with _patched(fake):
        restored = reposition.restore(_auto())
    assert restored["ok"], restored["problems"]
    assert _queues(fake) == before


def test_a_cut_run_on_another_deck_is_never_taken_over_and_a_positions_only_job_still_goes(tmp_path):
    """A cut automatic run's snapshot for another deck (順's deck changed since): taking it over here would leave its
    own deck's positions with no way back, so a job with an action to write refuses, as I3 does, and the bar sends you
    to 順's Restore; a positions-only job goes on and leaves it alone."""
    fake = _backlog(tmp_path)
    undo.save([(1789712090000, 50)], ["Kanji"], language="ja", automatic=True)
    cut_snapshot = undo.load("ja")
    with _patched(fake):
        acting = auto.reorder(_auto(), list_current=True)
    assert acting["outcome"] == "refused" and acting["report"]["restore_first"], acting
    assert fake.writes == [] and fake.suspend_calls == [] and fake.tag_calls == []
    with _patched(fake):
        positions = auto.reorder(_auto(junban_auto_actions=False), list_current=True)
    assert positions["outcome"] == "ran" and positions["report"]["written"], positions
    assert undo.load("ja") == cut_snapshot


def test_a_run_you_start_in_junban_takes_over_a_cut_automatic_run_and_one_restore_undoes_both(tmp_path):
    """Disc-T1 (Mattias, 3.0.0: "Can't reorder with Junban" — "The last reorder did not finish… Press Undo the last
    reorder first"; Sonic 2026-11-12: "yes to the Junban recovery one"; HY-11 before). AutoJunban's run after a
    Generate is cut by Anki closing after its first suspend; the next automatic job, positions only, goes on and leaves
    the cut snapshot unfinished — for good, as his did. A Reorder you start in 順 now takes it over and finishes the
    job instead of being refused: the cut run's original positions and flags win, the suspends are both runs', and
    one Undo — its question saying so — puts back how the deck was before either. 洗濯機, suspended by you, is never
    touched."""
    from modules.junban import junban_view
    fake = _backlog(tmp_path)
    before = _queues(fake)
    _cut(fake)
    cut_cards = undo.load("ja")["cards"]
    one, two = _card_of(fake, "冒険"), _card_of(fake, "散歩")
    one["due"], two["due"] = two["due"], one["due"]                     # a move in Anki since: the job has work
    with _patched(fake):
        positions = auto.reorder(_auto(junban_auto_actions=False), list_current=True)
    assert positions["outcome"] == "ran", positions
    assert undo.load("ja")["complete"] is False, "his state: the cut run's snapshot left unfinished"

    with _patched(fake):
        report = reposition.run(_auto(), refresh=False)
    assert report["ok"] is True and not report.get("restore_first"), report
    assert [_card_of(fake, word)["queue"] for word in _OFF_THE_LIST] == [-1, -1, -1, -1], "the job finished"
    saved = undo.load("ja")
    assert saved["complete"] is True and saved.get("automatic") is not True, saved
    assert saved["finished_automatic"] is True
    assert {key: due for key, due in saved["cards"].items() if key in cut_cards} == cut_cards
    assert saved["suspended"] == _ids(fake, _OFF_THE_LIST), "the cut run's suspends and this run's"
    asked = junban_view.restore_question("ja", _auto())
    assert asked["kind"] == "snapshot" and asked["both"] is True, asked

    with _patched(fake):
        restored = reposition.restore(_auto())
    assert restored["ok"], restored["problems"]
    assert _queues(fake) == before, "one Undo puts back both runs (the move since included)"
    assert all("Surasura::later" not in _tags_of(fake, word) for word in _OFF_THE_LIST)
    assert all(not fake.cards[card_id].get("flags") for card_id in _ids(fake, _OFF_THE_LIST))
    yours = _card_of(fake, "洗濯機")["cardId"]
    assert _card_of(fake, "洗濯機")["queue"] == -1 and not [ids for _a, ids in fake.suspend_calls if yours in ids]


def test_a_run_you_start_with_nothing_left_to_do_still_finishes_a_cut_automatic_run(tmp_path):
    """Disc-T1: an automatic run cut after its last position, and your Reorder (its not-on-the-list actions off) finds
    every card in place — nothing to write. It still ends the block: the cut snapshot is marked finished, and its Undo
    still puts back what the cut run did."""
    from modules.junban import junban_view
    fake = _backlog(tmp_path)
    before = _queues(fake)
    pairs = [(card_id, card["due"]) for card_id, card in fake.cards.items()]
    quiet = _auto(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    with _patched(fake):
        assert reposition.run(quiet, refresh=False)["ok"]               # the deck in your order
    undo.save(pairs, ["TheBank"], language="ja", automatic=True)        # then a run cut after its last position
    writes = list(fake.writes)
    with _patched(fake):
        report = reposition.run(quiet, refresh=False)
    assert report["ok"] is True and not report.get("restore_first"), report
    assert fake.writes == writes, "nothing written"
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["finished_automatic"] is True, saved
    assert junban_view.restore_question("ja", quiet)["both"] is True
    with _patched(fake):
        again = reposition.run(quiet, refresh=False)
    assert again["ok"] is True and not again.get("restore_first"), "never blocked again"
    with _patched(fake):
        restored = reposition.restore(quiet)
    assert restored["ok"], restored["problems"]
    assert _queues(fake) == before


def test_a_run_you_start_never_takes_over_another_decks_cut_run(tmp_path):
    """A cut automatic run's snapshot for another deck (順's deck changed since): taking it over would leave its own
    deck's positions with no way back, so a run you start refuses, as I3 does, and nothing is written."""
    fake = _backlog(tmp_path)
    undo.save([(1789712090000, 50)], ["Kanji"], language="ja", automatic=True)
    cut_snapshot = undo.load("ja")
    with _patched(fake):
        report = reposition.run(_auto(), refresh=False)
    assert report["ok"] is False and report["restore_first"] is True, report
    assert "did not finish" in report["problems"][0], report["problems"]
    assert fake.writes == [] and fake.suspend_calls == [] and undo.load("ja") == cut_snapshot


@pytest.mark.parametrize("unfinished", ["2.5", "not-quite-true"])
def test_a_snapshot_without_the_automatic_mark_reads_as_manual(tmp_path, unfinished):
    """I3 is kept wherever you started the run: only a window snapshot carrying `"automatic": true` lets an automatic
    job go on. A 2.5 file (no mark) and a mark that isn't exactly true still refuse every automatic job, with actions
    or without. (One of Connect's unfinished runs no longer does: the next test.)"""
    fake = _backlog(tmp_path)
    pairs = [(card_id, card["due"]) for card_id, card in fake.cards.items()]
    if unfinished == "2.5":
        undo.save(pairs, ["TheBank"], language="ja")
        assert "automatic" not in undo.load("ja"), "a snapshot saved without the mark carries none"
    elif unfinished == "not-quite-true":
        path = undo.save(pairs, ["TheBank"], language="ja", automatic=True)
        assert undo.load("ja")["automatic"] is True
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
        saved["automatic"] = "true"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(saved, handle)
    with _patched(fake):
        acting = auto.reorder(_auto(), list_current=True)
        positions = auto.reorder(_auto(junban_auto_actions=False), list_current=True)
    for done in (acting, positions):
        assert done["outcome"] == "refused" and "did not finish" in done["report"]["problems"][0], done
        assert done["report"]["restore_first"] is True, "the bar sends you to 順's Restore"
    assert fake.writes == [] and fake.suspend_calls == []


@pytest.mark.parametrize("actions", [True, False])
def test_an_unfinished_connect_run_never_stops_an_automatic_job_which_takes_it_over(tmp_path, actions):
    """Lead 2026-11-07 (Mattias, alpha 3; Sonic's W3.5 row 7, "a run nobody started never stops the automation"): 順's
    automatic step, with actions or positions only, goes on past one of Connect's unfinished runs and takes it over in
    the window's snapshot (its cards' numbers from before it, its suspends), as row 7 takes over the window's own cut
    run; the run's file is marked taken over, so 順's Reorder is no longer refused."""
    fake = _backlog(tmp_path)
    pairs = [(card_id, card["due"]) for card_id, card in fake.cards.items()]
    first = pairs[0][0]
    run_id = undo.new_run_id("reorder")
    undo.save([(first, pairs[0][1] + 7)], ["TheBank"], language="ja", run_id=run_id, after=[(first, pairs[0][1])],
              suspended=[pairs[1][0]])
    with _patched(fake):
        done = auto.reorder(_auto(junban_auto_actions=actions), list_current=True)
    assert done["outcome"] == "ran" and not done["report"].get("restore_first"), done
    assert undo.unfinished("ja", "reorder") is None
    assert undo.load("ja", run_id=run_id)["taken_over_at"]
    window = undo.load("ja")
    assert window["cards"][str(first)] == pairs[0][1] + 7, "the cut run's number from before it wins"
    assert pairs[1][0] in window.get("suspended", []), "and what it suspended is undone with it"
    with _patched(fake):
        again = reposition.run(_auto())
    assert not again.get("restore_first"), again


def test_a_run_you_start_takes_over_an_unfinished_connect_run_too(tmp_path):
    """Disc-T1 (Sonic's yes): one of Connect's runs is an automatic reorder too. Left unfinished, it no longer blocks
    a Reorder you start (it asked for its Undo first before): your run takes it over in the window's snapshot as the
    automatic step does — its cards' numbers from before it, its suspends — and marks it taken over."""
    fake = _backlog(tmp_path)
    pairs = [(card_id, card["due"]) for card_id, card in fake.cards.items()]
    first = pairs[0][0]
    run_id = undo.new_run_id("reorder")
    undo.save([(first, pairs[0][1] + 7)], ["TheBank"], language="ja", run_id=run_id, after=[(first, pairs[0][1])],
              suspended=[pairs[1][0]])
    with _patched(fake):
        yours = reposition.run(_auto(), refresh=False)
    assert yours["ok"] is True and not yours.get("restore_first"), yours
    assert undo.unfinished("ja", "reorder") is None
    assert undo.load("ja", run_id=run_id)["taken_over_at"]
    window = undo.load("ja")
    assert window["complete"] is True and window["finished_automatic"] is True
    assert window["cards"][str(first)] == pairs[0][1] + 7, "the cut run's number from before it wins"
    assert pairs[1][0] in window.get("suspended", []), "and what it suspended is undone with it"


# --------------------------------------------------------------------------------------------------------------- #
# Nothing to act on: E2.1's requests, request for request
# --------------------------------------------------------------------------------------------------------------- #
def _two_runs(root, monkeypatch, words, settings, job):
    """A full run, then a delta (two cards swapped in Anki since), in a data root of its own -> (requests, reports)."""
    persistent = root / "persistent"
    persistent.mkdir(parents=True)
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
    monkeypatch.setattr("app.path_utils.get_persistent_user_data_path", lambda: str(persistent))
    _results(root, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(list(words))
    fake = ModCollection(cards, notes, actions=_ACTIONS)
    reports = []
    with _patched(fake):
        reports.append(reposition.run(settings, refresh=False, verb=anki_connect.AUTOMATIC_STEP, job=job()))
        one, two = _card_of(fake, "冒険"), _card_of(fake, "散歩")
        one["due"], two["due"] = two["due"], one["due"]
        reports.append(reposition.run(settings, refresh=False, verb=anki_connect.AUTOMATIC_STEP, job=job()))
    assert undo.load("ja") is None and undo.load("ja", "baseline"), "today's baseline alone"
    return fake.requests, reports


@pytest.mark.parametrize("words,over", [
    (("須藤", "散歩", "老婆", "冒険"), {"junban_later_tag": False, "junban_later_flag": False,
                                       "junban_later_suspend": False}),     # off the list, nothing saved for it
    (("散歩", "老婆", "冒険"), {}),                                         # the actions saved, every card listed
], ids=["actions-off", "nothing-off-the-list"])
def test_with_nothing_to_act_on_a_job_with_actions_sends_exactly_a_positions_only_jobs_requests(
        tmp_path, monkeypatch, words, over):
    """E2.1's behaviour (Haya's (7)): a full write and a delta with nothing to tag, flag, suspend or unsuspend send the
    very requests a positions-only automatic job sends — no re-check read, no snapshot of the window's."""
    settings = _auto(junban_tag="", **over)
    acting, acted = _two_runs(tmp_path / "actions", monkeypatch, words, settings,
                              lambda: spaced.Job(automatic=True, actions=True))
    plain, placed = _two_runs(tmp_path / "positions", monkeypatch, words, settings,
                              lambda: spaced.Job(automatic=True))
    parked = [r for r in acting if r.get("action") == "findCards" and
              " is:suspended " in f" {(r.get('params') or {}).get('query') or ''} "]
    # M-W1: with the suspend setting saved (Connect off), the job looks for the cards it parked once per list — the
    # full write's, never the delta's (a returning word's card comes back, Connect on or off)
    assert len(parked) == (1 if over == {} else 0), parked
    acting = [r for r in acting if r not in parked]
    assert [report["numbering"]["kind"] for report in acted] == [spaced.FULL, spaced.DELTA]
    assert [report["written"] for report in acted] == [report["written"] for report in placed]
    assert len(acting) == len(plain)
    for index, (sent, positions_only) in enumerate(zip(acting, plain)):
        if sent["action"] == "apiReflect" and over == {}:
            # The one difference, and no write: with the suspend setting saved, the preflight's capability check
            # (the same request) also names `suspend` / `unsuspend` — asked before the plan knows there's nothing
            # to suspend, as 2.5's automatic step asked.
            asked = sent["params"]["actions"]
            assert [name for name in asked if name not in ("suspend", "unsuspend")] == \
                positions_only["params"]["actions"], asked
            continue
        assert sent == positions_only, f"request {index} differs"


# --------------------------------------------------------------------------------------------------------------- #
# Never onto a card that changed meanwhile
# --------------------------------------------------------------------------------------------------------------- #
def test_a_card_off_the_list_studied_or_suspended_while_the_positions_went_out_is_left_alone(tmp_path):
    """One `cardsInfo` read of the planned cards, after the positions and before the actions: 須藤 reviewed on the
    phone (the session's sync brought it) and 図書館 suspended by the user are neither tagged, flagged nor suspended,
    and the snapshot never names them — so Restore leaves 図書館 suspended."""
    fake = _backlog(tmp_path)
    planned = None

    def meanwhile(ids):
        if fake.writes and planned is None and set(ids) == set(_ids(fake, _OFF_THE_LIST)):
            studied, yours = _card_of(fake, "須藤"), _card_of(fake, "図書館")
            studied["type"], studied["queue"] = 2, 2
            yours["queue"] = -1
            seen.append(sorted(ids))
    seen = []
    fake.before_cards_info = meanwhile
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True)
    assert done["outcome"] == "ran", done
    assert seen == [_ids(fake, _OFF_THE_LIST)], "one read of the planned cards, after the positions"
    acted = _ids(fake, ["美術館", "新幹線"])
    assert [ids for action, ids in fake.suspend_calls if action == "suspend"] == [acted]
    assert sorted(card_id for card_id, _flag in fake.flag_writes) == acted
    assert "Surasura::later" not in _tags_of(fake, "須藤") and "Surasura::later" not in _tags_of(fake, "図書館")
    assert "Surasura::later" in _tags_of(fake, "美術館")
    saved = undo.load("ja")
    assert saved["suspended"] == acted and sorted(int(c) for c in saved["flags"]) == acted

    with _patched(fake):
        assert reposition.restore(_auto())["ok"]
    assert _card_of(fake, "図書館")["queue"] == -1, "suspended by the user: never unsuspended"
    assert all(_card_of(fake, word)["queue"] == 0 for word in ("美術館", "新幹線"))


def test_a_review_starting_while_the_positions_go_out_means_no_actions_this_run(tmp_path):
    """04 §6: never while reviewing. The job stops between requests, the rest wait — and so do the actions, every one
    of them (Haya's (2)); the snapshot then names none, and its Restore puts the positions back."""
    fake = _backlog(tmp_path)
    before = _queues(fake)

    def review_begins():
        fake.reviewing = True
    fake.on_write = review_begins
    with _patched(fake):
        done = auto.reorder(_auto(junban_chunk_size=1), list_current=True)
    report = done["report"]
    assert report["left"] and fake.writes, report["message"]
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == [] and fake.note_writes == []
    saved = undo.load("ja")
    assert not saved.get("suspended") and not saved.get("flags") and not saved.get("marker_tags"), saved
    assert saved["complete"] is True, "the run finished what it did: the next one may go"

    fake.reviewing = False
    with _patched(fake):
        assert reposition.restore(_auto())["ok"]
    assert _queues(fake) == before


@pytest.mark.parametrize("over", [{}, dict(junban_later_tag=False, junban_later_flag=False,
                                           junban_later_suspend=False)], ids=["off-the-list", "touch-ups-only"])
def test_a_review_starting_after_the_last_position_request_means_no_actions_this_run(tmp_path, over):
    """04 §6: an automatic job never writes while you review. `stop_if` asks before each position request, never after
    the last — so the run asks once more, just before its actions: `guiReviewActive` in the same request as the
    re-check read (or alone, with the Surasura tag the only thing to write). A review begun after the positions means
    no touch-up, tag, flag or suspend this run; they wait for the next. The snapshot is saved again with none of them,
    and complete."""
    fake = _backlog(tmp_path)
    real = fake._multi

    def review_begins(actions):
        replies = real(actions)
        if any(entry.get("action") == "setSpecificValueOfCard" and entry["params"]["keys"] == ["due"]
               for entry in actions):
            fake.reviewing = True                       # just after a position request landed
        return replies
    fake._multi = review_begins
    with _patched(fake):
        done = auto.reorder(_auto(**over), list_current=True)
    report = done["report"]
    assert fake.writes and not report["left"] and report["ok"], report      # every position went: the last too
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == [] and fake.note_writes == []
    asked = [request for request in fake.requests if request["action"] == "guiReviewActive"
             or request["action"] == "multi" and any(entry["action"] == "guiReviewActive"
                                                     for entry in request["params"]["actions"])]
    last = asked[-1]
    if not over:
        assert [entry["action"] for entry in last["params"]["actions"]] == ["cardsInfo", "guiReviewActive"], last
    else:
        assert last["action"] == "guiReviewActive", last
    assert fake.requests[-1] is last, "asked last, just before the actions"
    saved = undo.load("ja")
    assert saved["complete"] is True, saved
    assert not saved.get("suspended") and not saved.get("flags") and not saved.get("marker_tags")         and not saved.get("tags"), saved


_LATER = {"cards": [1, 2], "note_of": {1: 10, 2: 20}, "tag_notes": [10, 20], "flags": {1: 0, 2: 0},
          "suspend": [1, 2], "counts": {"cards": 2, "tag": 2, "flag": 2, "suspend": 2}}
_NEW = {"result": [{"cardId": 1, "type": 0, "queue": 0}, {"cardId": 2, "type": 0, "queue": 0}], "error": None}


@pytest.mark.parametrize("replies,acts", [
    ([_NEW, {"result": False, "error": None}], True),                    # no review: the plan as it was
    ([_NEW, {"result": None, "error": "unsupported action"}], True),     # Anki won't say: as `_checked`, no review
    ([_NEW, {"result": True, "error": None}], False),                    # a review began
    ([{"result": None, "error": "collection is not available"}, {"result": False, "error": None}], False),
    ([{"result": "garbled", "error": None}, {"result": False, "error": None}], False),
    ([_NEW], False),                                                     # not every action answered
    ("garbled", False),
    (AnkiError("Anki stopped answering", kind="connection"), False),
], ids=["no-review", "review-unknown", "review", "read-refused", "read-garbled", "short", "not-a-list", "offline"])
def test_the_recheck_acts_only_on_a_sure_answer_with_no_review(monkeypatch, replies, acts):
    """The read and the review question go in one request; anything short of a clear answer — the read refused or
    garbled, a reply missing, Anki gone, a review begun — means nothing is acted on this run (`None`)."""
    sent = []

    def multi(actions, url):
        sent.append([entry["action"] for entry in actions])
        if isinstance(replies, Exception):
            raise replies
        return replies
    monkeypatch.setattr(ankiconnect, "multi", multi)
    checked = reposition._still_new("http://127.0.0.1:8765", _LATER)
    assert sent == [["cardsInfo", "guiReviewActive"]]
    assert (checked is _LATER) if acts else checked is None, checked


@pytest.mark.parametrize("answer,touchups,acts,asked", [
    (False, True, True, 1),                         # touch-ups only, no review: they go
    (True, True, False, 1),                         # a review began: they wait
    (AnkiError("gone", kind="connection"), True, False, 1),
    (True, False, True, 0),                         # nothing left to write: nothing asked
], ids=["no-review", "review", "offline", "nothing-to-write"])
def test_with_touch_ups_only_one_review_question_and_nothing_else(monkeypatch, answer, touchups, acts, asked):
    """No card off the list to read: `guiReviewActive` alone, only while a touch-up is still to write."""
    calls = []

    def invoke(action, url, **_params):
        calls.append(action)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(ankiconnect, "invoke", invoke)
    monkeypatch.setattr(ankiconnect, "multi", lambda *a, **k: pytest.fail("no read without cards to read"))
    nothing = {}
    checked = reposition._still_new("http://127.0.0.1:8765", nothing, touchups)
    assert calls == ["guiReviewActive"] * asked
    assert (checked is nothing) if acts else checked is None, checked


def test_the_recheck_reads_a_big_backlog_in_requests_of_250_cards_and_one_review_question(monkeypatch):
    """A big backlog off the list (251 cards to suspend): the re-check reads them 250 at a time — AnkiConnect's
    `cardsInfo` batches, so one huge request never holds Anki — in the one `multi` that ends with `guiReviewActive`."""
    cards = list(range(1789700000000, 1789700000251))
    later = {"cards": cards, "note_of": {}, "tag_notes": [], "flags": {}, "suspend": list(cards),
             "counts": {"cards": len(cards), "suspend": len(cards)}}
    sent = []

    def multi(actions, url, **_params):
        sent.append(actions)
        return [{"error": None, "result": [{"cardId": card_id, "type": 0, "queue": 0}
                                           for card_id in action["params"]["cards"]]}
                for action in actions[:-1]] + [{"error": None, "result": False}]
    monkeypatch.setattr(ankiconnect, "multi", multi)
    monkeypatch.setattr(ankiconnect, "invoke", lambda *a, **k: pytest.fail("the review question rides the read"))
    assert reposition._still_new("http://127.0.0.1:8765", later) is later
    assert len(sent) == 1 and [action["action"] for action in sent[0]] == ["cardsInfo", "cardsInfo", "guiReviewActive"]
    assert [len(action["params"]["cards"]) for action in sent[0][:-1]] == [250, 1]


def _after_the_positions(fake):
    """The write requests that went out after the last position write."""
    writes = _writes(fake)
    last_position = max(i for i, kind in enumerate(writes) if kind == "position")
    return writes[last_position + 1:]


def test_anki_stopping_during_the_recheck_means_no_touch_up_tag_flag_or_suspend_this_run(tmp_path):
    """Anki stops answering just as the cards off the list are read again: nothing is known about them, so nothing is
    acted on this run — not the actions, and not the touch-ups either (fields, the Surasura tag, marker tags), as with
    a review that stopped the job. The positions stand; the snapshot is saved again without the planned suspends and
    is complete, so the next run may go and a Restore puts the positions back."""
    fake = _backlog(tmp_path)
    before = _queues(fake)
    failed = []

    def anki_stops(ids):
        if fake.writes and not failed and set(ids) == set(_ids(fake, _OFF_THE_LIST)):
            failed.append(sorted(ids))
            raise urllib.error.URLError("[WinError 10061] No connection could be made")
    fake.before_cards_info = anki_stops
    with _patched(fake):
        done = auto.reorder(_auto(), list_current=True)
    assert failed, "the re-check read went out after the positions"
    assert fake.writes and _after_the_positions(fake) == [], _writes(fake)
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == [] and fake.note_writes == []
    assert done["report"]["ok"], done
    saved = undo.load("ja")
    assert saved["complete"] is True, "the run finished what it did: the next one may go"
    assert not saved.get("suspended") and not saved.get("flags") and not saved.get("marker_tags"), saved

    with _patched(fake):
        assert reposition.restore(_auto())["ok"]
    assert _queues(fake) == before


def test_a_snapshot_that_cant_be_saved_again_after_the_recheck_writes_no_action(tmp_path, monkeypatch):
    """The re-check narrows the plan (須藤 studied on the phone meanwhile), so the snapshot is saved again with what
    will really be written. If that save fails, the copy on disk still names the planned suspends — so none of them,
    and no touch-up, is written: the request log ends at the positions."""
    fake = _backlog(tmp_path)

    def studied_meanwhile(ids):
        if fake.writes and set(ids) == set(_ids(fake, _OFF_THE_LIST)):
            card = _card_of(fake, "須藤")
            card["type"], card["queue"] = 2, 2
    fake.before_cards_info = studied_meanwhile
    real_save, saves = undo.save, []

    def save(*args, **kwargs):
        saves.append(kwargs.get("suspended"))
        if len(saves) == 2:
            raise OSError("disk full")
        return real_save(*args, **kwargs)
    monkeypatch.setattr(undo, "save", save)
    with _patched(fake):
        auto.reorder(_auto(), list_current=True)
    assert len(saves) == 2 and saves[0] == _ids(fake, _OFF_THE_LIST), "saved once, then again after the re-check"
    assert fake.writes and _after_the_positions(fake) == [], _writes(fake)
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == [] and fake.note_writes == []


# --------------------------------------------------------------------------------------------------------------- #
# Who acts: only the jobs auto.reorder hands in
# --------------------------------------------------------------------------------------------------------------- #
def test_an_automatic_job_without_actions_moves_positions_only_whatever_the_settings_say(tmp_path, monkeypatch):
    """The fast re-plan's host (and its per-move job) never sets `actions`: a move in the window writes positions
    only (E1.1 04 §1), even with the actions, Connect's preview and the unattended suspend all on."""
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", True)
    fake = _backlog(tmp_path)
    with _patched(fake):
        report = reposition.run(_auto(connect_enabled=True), refresh=False, verb="the re-plan",
                                job=spaced.Job(automatic=True))
    assert report["ok"] and fake.writes, report["problems"]
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    assert undo.load("ja") is None and undo.load("ja", "baseline")


@pytest.mark.parametrize("unattended,suspend", [(False, True), (True, False)],
                         ids=["2.6-2.7", "3.0-suspend-setting-off"])
def test_positions_only_with_no_unattended_suspend_acts_on_nothing(tmp_path, monkeypatch, unattended, suspend):
    """`positions_only=True` (`junban --auto`, Connect's step) with `suspends_unattended` False — 2.6 / 2.7, or 3.0
    with Junban's suspend setting off: no suspend, no unsuspend, no tag, no flag; today's baseline and the run's own
    snapshot, with nothing in it but positions."""
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", unattended)
    fake = scene(tmp_path)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(connect_settings(junban_later_suspend=suspend), list_current=True, positions_only=True,
                            run_id=run_id, job=spaced.Job(automatic=True))
    assert done["outcome"] == "ran" and fake.writes, done
    assert fake.suspend_calls == [] and fake.flag_writes == [] and fake.tag_calls == []
    assert fake.card_of("老婆")["queue"] == -1
    saved = undo.load("ja", run_id=run_id)
    assert not saved.get("suspended") and not saved.get("unsuspended") and not saved.get("marker_tags"), saved
    assert undo.load("ja", "baseline")


def test_on_3_0_the_line_flag_is_set():
    """The lead's 🧭 (W3.5 row 7): the 3.0 line suspends unattended as Junban's setting says (G1.3-8). 2.x-dev keeps
    it False."""
    assert connect.UNATTENDED_SUSPEND is True
