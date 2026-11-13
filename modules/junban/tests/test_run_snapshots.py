# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect's runs keep an undo snapshot each (P1.4 row 1.4.2; §7.2; K39).

What a wrong answer would cost, most first:

  * **The snapshot is on disk, marked incomplete, before the first write**, and a run killed between the write and
    "complete" is never snapshotted over: the half-written order must never replace the only record of how the deck
    was. A reorder you start takes it over (Sonic 2026-11-13) only while its record is complete — readable, for this
    deck — and one Undo then goes back past both; otherwise it asks for that run's Undo first.
  * **A restore undoes exactly what that run changed**, and nothing after it: a card you moved by hand since, or a
    later run moved, stays where it is.
  * **Separate from the window's Restore point**: a run of Connect's never replaces it.
  * **The last 20 are kept** (K39), never an unfinished one let go.

Against the fake collection of `connect_scene` — real words, real Lapis fields, never Anki.
"""
import json
import os

import pytest

from modules.junban import auto, reposition, undo
from modules.junban.tests import connect_scene
from modules.junban.tests.connect_scene import scene, settings
from modules.junban.tests.test_reposition import _patched


def _connect_run(fake, **over):
    """One unattended run as Connect starts it (`surasura-cli junban --auto`): positions only, its own run id."""
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(**over), list_current=True, positions_only=True, run_id=run_id)
    return run_id, done


def test_a_connect_run_keeps_its_own_snapshot_written_incomplete_before_the_first_write(tmp_path):
    seen = {}

    def first_write():
        # The moment the first position reaches Anki, the run's snapshot is already on disk, still incomplete.
        seen["at_first_write"] = undo.load("ja", run_id=run_id)

    fake = scene(tmp_path, on_write=first_write)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id)

    assert done["outcome"] == "ran" and fake.writes
    assert seen["at_first_write"]["complete"] is False
    saved = undo.load("ja", run_id=run_id)
    assert saved["complete"] is True and saved["kind"] == "reorder" and saved["run"] == run_id
    # Exactly the cards it moved, each with where it found it and where it put it.
    assert {int(c) for c in saved["cards"]} == {card_id for card_id, _due in fake.writes}
    assert {int(c): d for c, d in saved["after"].items()} == dict(fake.writes)
    assert not os.path.exists(undo.snapshot_path("ja")), "the window's Restore point is never Connect's"
    assert done["report"]["run"] == run_id


def _cut_connect_run(fake, at=2):
    """One of Connect's runs (the fast re-plan's spaced writes, two cards a request) cut by Anki closing at its `at`-th
    write request from now: its first requests landed, its snapshot left unfinished -> its run id."""
    from modules.junban import spaced
    fake.fail_write_chunk = fake.write_chunks + at
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        died = auto.reorder(settings(junban_chunk_size=2), list_current=True, positions_only=True, run_id=run_id,
                            job=spaced.Job())
    fake.fail_write_chunk = None
    assert died["outcome"] == "refused" and undo.load("ja", run_id=run_id)["complete"] is False, died
    return run_id


def _state(fake):
    return {card_id: (card["due"], card["queue"], card.get("flags", 0)) for card_id, card in fake.cards.items()}


def test_a_run_killed_between_its_writes_and_complete_is_taken_over_by_your_reorder_and_one_undo_puts_back_both(
        tmp_path):
    """Sonic 2026-11-13 (overturning the lead's 2026-11-07 ruling: "a manual would be a priority BUT if the data until
    that point isn't prepped than the manual isn't ready to run yet"): Connect's run, cut part way, is never written
    over by Connect's own next run — that one goes on and leaves it offered first. A Reorder you start in 順 now takes
    it over, as it takes over the window's own cut automatic run (Disc-T1): its record is complete, so the reorder
    runs, the cut run is marked taken over (never restored, never offered again), and one Undo — its question saying
    both — puts every card back as it was before the cut run: position, queue, flag."""
    from modules.junban import junban_view
    fake = scene(tmp_path)
    before = _state(fake)
    run_id = _cut_connect_run(fake)
    half = dict(fake.writes)
    assert half and any(before[c][0] != d for c, d in half.items()), "the cut run's first request landed"
    assert undo.unfinished("ja", "reorder") == run_id

    fake.writes = []
    with _patched(fake):
        window = reposition.run(settings(), refresh=False)              # the 順 window's Reorder: it goes on
    assert window["ok"] and not window.get("restore_first") and fake.writes, window
    assert undo.unfinished("ja", "reorder") is None
    cut = undo.load("ja", run_id=run_id)
    assert cut["complete"] is True and cut.get("taken_over_at") and not cut.get("restored_at")
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["finished_automatic"] is True and saved.get("automatic") is not True
    assert all(saved["cards"][str(c)] == before[c][0] for c in half), "the cut run's way back is in yours"
    asked = junban_view.restore_question("ja", settings())
    assert asked["kind"] == "snapshot" and asked["both"] is True, asked

    with _patched(fake):
        put_back = reposition.restore(settings())
    assert put_back["ok"], put_back["problems"]
    assert _state(fake) == before, "one Undo: the order from before both runs"
    with _patched(fake):
        again = reposition.restore(settings())
    assert again["ok"] and _state(fake) == before, "never the half writes back"


def test_connects_own_next_run_still_leaves_a_cut_run_offered_first(tmp_path):
    """Connect's next automatic run goes on in a snapshot of its own and never takes the cut run over: the cut run
    stays unfinished, offered first by Undo, and that Undo takes back exactly that run."""
    fake = scene(tmp_path, fail_write_chunk=1)          # Anki goes away mid-run: nothing in the chunk lands
    run_id, done = _connect_run(fake)
    assert done["outcome"] == "refused"
    assert undo.load("ja", run_id=run_id)["complete"] is False
    fake.fail_write_chunk = None
    second, again = _connect_run(fake)
    assert again["outcome"] == "ran" and fake.writes, again
    assert second != run_id and undo.load("ja", run_id=second)["complete"] is True
    assert undo.load("ja", run_id=run_id)["complete"] is False, "the cut run's snapshot is never written over"
    assert undo.unfinished("ja", "reorder") == run_id
    with _patched(fake):
        put_back = reposition.restore(settings())       # the window's Restore takes that run back first
    assert put_back["ok"], put_back["problems"]
    assert put_back["run"] == run_id and undo.unfinished("ja", "reorder") is None


@pytest.mark.parametrize("why", ["unreadable", "another deck", "all decks"])
def test_your_reorder_asks_for_the_undo_first_while_a_cut_runs_record_isnt_complete(tmp_path, monkeypatch, why):
    """Not prepped, not ready: a cut run whose snapshot can't be read just now (an antivirus or cloud folder holds
    it), or one for another deck or the other scope mode, which your reorder's snapshot couldn't hold the way back
    from. Your Reorder asks for its Undo first, as before, and nothing is written — with something to write, and with
    nothing (the take-over that only saves)."""
    fake = scene(tmp_path)
    run_id = _cut_connect_run(fake)
    path = undo.snapshot_path("ja", run_id=run_id)
    if why == "unreadable":
        real = undo.load
        monkeypatch.setattr(undo, "load", lambda language="ja", kind="reorder", run_id=None:
                            None if run_id is not None and run_id.startswith("reorder-") and run_id in path
                            else real(language, kind, run_id))
    else:
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
        if why == "another deck":
            saved["scope"] = ["Another deck"]
        else:
            saved["mode"] = "all"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(saved, handle)
    with open(path, encoding="utf-8") as handle:
        cut_file = handle.read()
    quiet = settings(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    for chosen in (settings(), quiet):
        fake.writes, fake.suspend_calls = [], []
        with _patched(fake):
            yours = reposition.run(chosen, refresh=False)
        assert not yours["ok"] and yours["restore_first"] and yours["unfinished"] == run_id, yours
        assert fake.writes == [] and fake.suspend_calls == [] and not os.path.exists(undo.snapshot_path("ja"))
    with open(path, encoding="utf-8") as handle:
        assert handle.read() == cut_file, "left exactly as it was"


def test_two_cut_runs_of_this_deck_are_both_taken_over_so_one_undo_goes_back_past_all_of_them(tmp_path):
    """Connect's run cut, then its next run cut too (it goes on past the one before): both are unfinished. Your
    Reorder takes over both, the oldest's numbers winning — the newest alone would leave the older run's half writes
    in your Undo — and one Undo puts back the deck from before the first."""
    fake = scene(tmp_path)
    before = _state(fake)
    first = _cut_connect_run(fake)
    second = _cut_connect_run(fake, at=1)              # its first request dies: none of its own landed
    assert first != second and undo.unfinished("ja", "reorder") == second
    assert undo.load("ja", run_id=first)["complete"] is False
    with _patched(fake):
        window = reposition.run(settings(), refresh=False)
    assert window["ok"] and not window.get("restore_first"), window
    assert all(undo.load("ja", run_id=run_id).get("taken_over_at") for run_id in (first, second))
    assert undo.unfinished("ja", "reorder") is None
    with _patched(fake):
        put_back = reposition.restore(settings())
    assert put_back["ok"], put_back["problems"]
    assert _state(fake) == before


def test_your_reorder_with_nothing_left_to_write_still_takes_a_cut_run_over(tmp_path):
    """Connect's run cut after its last position (every card where your list puts it) leaves nothing for your Reorder
    to write. It still takes the run over — a snapshot of its own, complete, holding the run's numbers from before it —
    so it is never refused or offered again, and one Undo puts back the order from before that run."""
    from modules.junban import junban_view
    fake = scene(tmp_path)
    before = _state(fake)
    quiet = settings(junban_later_tag=False, junban_later_flag=False, junban_later_suspend=False)
    pairs = [(card_id, card["due"]) for card_id, card in fake.cards.items() if card["queue"] == 0]
    with _patched(fake):
        assert reposition.run(quiet, refresh=False)["written"]         # the deck in your order
    after = {card_id: card["due"] for card_id, card in fake.cards.items()}
    run_id = undo.new_run_id("reorder")                                 # as if Connect's run had put it there
    undo.save(pairs, ["TheBank"], language="ja", run_id=run_id, after=[(c, after[c]) for c, _due in pairs])
    writes = list(fake.writes)
    with _patched(fake):
        report = reposition.run(quiet, refresh=False)
    assert report["ok"] and not report.get("restore_first"), report
    assert fake.writes == writes, "nothing written"
    assert undo.load("ja", run_id=run_id).get("taken_over_at") and undo.unfinished("ja", "reorder") is None
    saved = undo.load("ja")
    assert saved["complete"] is True and saved["finished_automatic"] is True
    assert {int(c): d for c, d in saved["cards"].items() if int(c) in dict(pairs)} == dict(pairs)
    assert junban_view.restore_question("ja", quiet)["both"] is True
    with _patched(fake):
        put_back = reposition.restore(quiet)
    assert put_back["ok"], put_back["problems"]
    assert {c: due for c, (due, _q, _f) in _state(fake).items()} == {c: due for c, (due, _q, _f) in before.items()}


def test_an_older_cut_runs_number_wins_where_a_newer_cut_run_moved_the_same_card(tmp_path):
    """Two cut runs moved the same card: the older one's number from before it is the way back (`_take_over`, oldest
    last). The newest's would be the older run's half write."""
    fake = scene(tmp_path)
    before = _state(fake)
    first = _cut_connect_run(fake)
    card_id, half = next(iter(fake.writes))
    newer = undo.new_run_id("reorder")                  # Connect's next run moved it again and was cut too
    undo.save([(card_id, half)], ["TheBank"], language="ja", run_id=newer, after=[(card_id, half + 1000)])
    fake.cards[card_id]["due"] = half + 1000
    assert {run_id for run_id, saved in undo.runs("ja") if saved["complete"] is False} == {first, newer}
    with _patched(fake):
        assert reposition.run(settings(), refresh=False)["ok"]
        put_back = reposition.restore(settings())
    assert put_back["ok"], put_back["problems"]
    assert _state(fake) == before


def test_a_finished_run_after_the_cut_one_is_taken_over_with_it_so_undo_never_mixes_the_two(tmp_path):
    """Connect's run cut, then its own next run finished the job (the adversary's SHOULD 3): your Reorder — nothing left
    to write — takes over both, the finished one too (never put back on its own afterwards, nor its half), and one
    Undo puts back the deck from before them both: never the cut run's cards before it and the rest after the next."""
    fake = scene(tmp_path)
    before = _state(fake)
    cut = _cut_connect_run(fake)
    finished, done = _connect_run(fake)
    assert done["outcome"] == "ran" and undo.load("ja", run_id=finished)["complete"] is True
    with _patched(fake):
        report = reposition.run(settings(), refresh=False)
    assert report["ok"] and not report.get("restore_first"), report
    assert all(undo.load("ja", run_id=run_id).get("taken_over_at") for run_id in (cut, finished))
    assert not undo.load("ja", run_id=finished).get("restored_at")
    with _patched(fake):
        put_back = reposition.restore(settings())
    assert put_back["ok"], put_back["problems"]
    assert _state(fake) == before


def test_a_finished_run_already_put_back_or_for_another_deck_is_never_taken_over(tmp_path):
    fake = scene(tmp_path)
    cut = _cut_connect_run(fake)
    for name, extra in (("restored", {"restored_at": "2026-11-13T10:00:00"}), ("other", {"scope": ["Another deck"]})):
        run_id = undo.new_run_id("reorder")
        undo.save([(next(iter(fake.cards)), 1)], ["TheBank"], language="ja", run_id=run_id, after=[])
        assert undo.mark_complete("ja", run_id=run_id)
        path = undo.snapshot_path("ja", run_id=run_id)
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
        saved.update(extra)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(saved, handle)
    with _patched(fake):
        assert reposition.run(settings(), refresh=False)["ok"]
    taken = [run_id for run_id, saved in undo.runs("ja") if saved.get("taken_over_at")]
    assert taken == [cut]


def test_a_cut_run_that_cant_be_marked_taken_over_stops_your_reorder_before_any_write(tmp_path, monkeypatch):
    """Its file held as it is marked (the adversary's SHOULD 4): the run would stay unfinished, offered first by Undo
    on top of your writes. Nothing is written, and the run is still the way back."""
    fake = scene(tmp_path)
    run_id = _cut_connect_run(fake)
    real = undo.mark_complete
    monkeypatch.setattr(undo, "mark_complete", lambda language="ja", kind="reorder", run_id=None, **kw:
                        False if kw.get("taken_over") else real(language, kind, run_id, **kw))
    fake.writes, fake.suspend_calls, fake.tag_calls = [], [], []
    with _patched(fake):
        report = reposition.run(settings(), refresh=False)
    assert not report["ok"] and "nothing was changed" in report["problems"][0], report
    assert fake.writes == [] and fake.suspend_calls == [] and fake.tag_calls == []
    assert undo.unfinished("ja", "reorder") == run_id


def test_your_reorder_takes_over_the_windows_own_cut_run_and_connects_together(tmp_path):
    """The window's own automatic run cut (Disc-T1) and one of Connect's cut too: your Reorder takes over both, and one
    Undo puts back every card either moved."""
    fake = scene(tmp_path)
    before = _state(fake)
    _cut_connect_run(fake)
    moved = {card_id for card_id, _due in fake.writes}
    other = next(card_id for card_id in sorted(fake.cards) if card_id not in moved and fake.cards[card_id]["queue"] == 0)
    undo.save([(other, before[other][0])], ["TheBank"], language="ja", automatic=True)     # the window's cut run
    fake.cards[other]["due"] = 1                                                           # ...had moved this one
    with _patched(fake):
        report = reposition.run(settings(), refresh=False)
        assert report["ok"] and not report.get("restore_first"), report
        put_back = reposition.restore(settings())
    assert put_back["ok"], put_back["problems"]
    assert _state(fake) == before


def test_a_fields_true_original_survives_a_take_over_whichever_snapshot_is_older():
    """The adversary's BLOCKER: your last reorder (older) wrote FreqSort u -> p1, a cut run of Connect's (newer) p1 ->
    a1, and this run writes a1 -> m. Carried back newest first, the way back is u — whichever order they're handed in;
    and a field this run leaves alone keeps u too, ready for Undo while the note holds a1."""
    note = 1789712000300

    def snapshot(written_at, before, after):
        return {"written_at": written_at, "fields": {str(note): {"FreqSort": {"before": before, "after": after}}}}
    older, newer = snapshot("2026-11-13T09:00:00", "u", "p1"), snapshot("2026-11-13T09:30:00", "p1", "a1")
    for handed in ([older, newer], [newer, older]):
        touched = reposition._carried_fields(handed, {note: {"FreqSort": {"before": "a1", "after": "m"}}})
        assert touched[str(note)]["FreqSort"] == {"before": "u", "after": "m"}
        alone = reposition._carried_fields(handed, None)
        assert alone[str(note)]["FreqSort"] == {"before": "u", "after": "a1"}


def test_a_restore_puts_back_what_the_run_moved_and_leaves_a_card_you_moved_since(tmp_path):
    fake = scene(tmp_path)
    before = {card_id: card["due"] for card_id, card in fake.cards.items()}
    run_id, done = _connect_run(fake)
    moved = [card_id for card_id, _due in fake.writes]
    assert len(moved) >= 3
    yours = moved[0]
    fake.cards[yours]["due"] = 99                       # you moved one card by hand in Anki since

    with _patched(fake):
        report = reposition.restore_run(settings(), run_id)

    assert report["ok"], report["problems"]
    assert report["moved"] == 1 and fake.cards[yours]["due"] == 99
    for card_id in moved[1:]:
        assert fake.cards[card_id]["due"] == before[card_id]
    assert undo.load("ja", run_id=run_id)["restored_at"]
    with _patched(fake):
        twice = reposition.restore_run(settings(), run_id)
    assert not twice["ok"] and "already put back" in twice["problems"][0]


def test_two_runs_in_a_row_each_restore_undoes_only_its_own(tmp_path):
    """Run 1 orders the deck; a new card arrives and run 2 places it, moving a few. Putting run 1 back leaves every
    card run 2 moved where run 2 put it."""
    fake = scene(tmp_path)
    first_id, _ = _connect_run(fake)
    first_writes = dict(fake.writes)
    # A new card of a list word arrives at the back (Connect's next batch).
    note_id, card_id = max(fake.notes) + 1, max(fake.cards) + 1
    fake.notes[note_id] = {"noteId": note_id, "modelName": "Lapis", "tags": [connect_scene.CONNECT_TAG], "fields": {
        "Expression": {"value": "散歩", "order": 0}, "Sentence": {"value": "<b>散歩</b>した。", "order": 1},
        "FreqSort": {"value": "100", "order": 2}, "MiscInfo": {"value": "", "order": 3}}}
    fake.cards[card_id] = {"cardId": card_id, "note": note_id, "due": 3000, "type": 0, "queue": 0,
                           "deckName": "TheBank"}
    fake.writes = []
    second_id, done = _connect_run(fake)
    assert done["outcome"] == "ran" and second_id != first_id
    second_writes = dict(fake.writes)
    assert card_id in second_writes
    # Run 2's snapshot holds the cards IT moved — fewer than the deck — and nothing else.
    assert {int(c) for c in undo.load("ja", run_id=second_id)["cards"]} == set(second_writes)
    assert len(second_writes) < len([c for c in fake.cards.values() if c["queue"] == 0])

    with _patched(fake):
        report = reposition.restore_run(settings(), first_id)
    assert report["ok"]
    for moved, due in second_writes.items():
        assert fake.cards[moved]["due"] == due, "run 2's move stays"
    assert report["moved"] == len(set(first_writes) & set(second_writes))
    assert undo.load("ja", run_id=second_id).get("restored_at") is None


def test_the_last_twenty_runs_are_kept_and_an_unfinished_one_never_let_go(tmp_path):
    oldest = "reorder-20261005-235959-000"         # older than every run after it
    undo.save({1789712080300: 2800}, ["TheBank"], run_id=oldest, after={1789712080300: 2801})   # never completed
    for n in range(24):
        run_id = f"reorder-20261006-0100{n:02d}-000"
        undo.save({1789712080300: 2800 + n}, ["TheBank"], run_id=run_id, after={1789712080300: 2801 + n})
        undo.mark_complete(run_id=run_id)
    kept = connect_scene.runs_on_disk()
    assert f"{oldest}.json" in kept, "the only way back from a run that died is never let go"
    finished = [name for name in kept if name != f"{oldest}.json"]
    assert len(kept) <= undo.KEEP_RUNS + 1 and len(finished) >= undo.KEEP_RUNS - 1
    assert "reorder-20261006-010023-000.json" in kept and "reorder-20261006-010000-000.json" not in kept


def test_a_run_id_that_names_no_file_is_refused_untouched(tmp_path):
    fake = scene(tmp_path)
    with _patched(fake):
        for bad in ("../junban_undo", "reorder-none", ""):
            report = reposition.restore_run(settings(), bad)
            assert not report["ok"]
    assert fake.writes == [] and fake.suspend_calls == []


def test_on_3_0_with_the_preview_off_an_unattended_run_keeps_todays_baseline_and_no_run_snapshot(tmp_path):
    # 2.x-dev keeps the window's snapshot here, as in 2.5
    # (test_with_the_preview_off_an_unattended_run_keeps_the_windows_snapshot_as_in_2_5: no job, 2.5's dense run);
    # 3.0 (Haya's G2b): the command line's run is a spaced, automatic job whatever the switches — today's baseline
    # (E1.1 03 §5), never the window's Restore point — and, Connect off, still no run snapshot of its own
    fake = scene(tmp_path)
    with _patched(fake):
        done = auto.reorder(settings(preview=False), list_current=True, positions_only=True,
                            run_id=undo.new_run_id("reorder"))
    assert done["outcome"] == "ran"
    assert connect_scene.runs_on_disk() == []
    assert undo.load("ja") is None and undo.load("ja", "baseline")


def test_mixed_kinds_keep_the_newest_twenty_by_when_they_ran_never_by_name(tmp_path):
    """Pruning goes by when a run started, never by its file name: every `reorder-` sorts above every `backfill-`, so
    the newest fill's way back was let go behind twenty older reorders (review P1.4-adversary #2)."""
    for n in range(20):
        run_id = f"reorder-20261006-0100{n:02d}-000"
        undo.save({1789712080300: 2800 + n}, ["TheBank"], run_id=run_id, after={1789712080300: 2801 + n})
        undo.mark_complete(run_id=run_id)
    for n in range(2):
        run_id = f"backfill-20261006-0200{n:02d}-000"
        undo.save([], ["TheBank"], kind="backfill", run_id=run_id,
                  fields={1789712080400: {"パターン": {"before": "", "after": f"<div>〜を探検する {n}</div>"}}})
        undo.mark_complete(kind="backfill", run_id=run_id)
    kept = connect_scene.runs_on_disk()
    assert "backfill-20261006-020000-000.json" in kept and "backfill-20261006-020001-000.json" in kept
    assert "reorder-20261006-010000-000.json" not in kept and "reorder-20261006-010019-000.json" in kept
    assert [run_id for run_id, _saved in undo.runs("ja")][:2] == ["backfill-20261006-020001-000",
                                                                  "backfill-20261006-020000-000"]


def test_a_run_snapshot_another_program_holds_keeps_refusing_and_is_never_moved_aside(tmp_path, monkeypatch):
    """An antivirus or a cloud folder holding the file is no corrupt snapshot: the run may be the one that died, so it
    keeps refusing until the file reads again (review P1.4-adversary #8)."""
    run_id = "reorder-20261006-030000-000"
    undo.save({1789712080300: 2800}, ["TheBank"], run_id=run_id, after={1789712080300: 2801})
    undo.mark_complete(run_id=run_id)
    real_open = open

    def held(path, *args, **kwargs):
        if str(path).endswith(run_id + ".json") and "r" in (args[0] if args else kwargs.get("mode", "r")):
            raise PermissionError(13, "The process cannot access the file", str(path))
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr("builtins.open", held)
    assert undo.unfinished("ja", "reorder") == run_id
    monkeypatch.setattr("builtins.open", real_open)
    assert connect_scene.runs_on_disk() == [f"{run_id}.json"], "kept where it was"
    assert undo.unfinished("ja", "reorder") is None, "read again: it had finished"


def _junban_panel(language="ja"):
    import threading
    from unittest import mock
    panel = mock.MagicMock()
    panel.busy, panel._stop = False, threading.Event()
    panel._lang_code.return_value = language
    panel._settings.return_value = settings()
    return panel


def test_with_no_snapshot_of_its_own_the_windows_restore_names_the_unfinished_run_and_puts_back_that_one(tmp_path):
    """Connect first: 順 had no Restore point of its own, so Restore said "nothing to restore" while every reorder was
    refused — a dead end (review P1.4-adversary #1). Restore now names the run and puts back exactly that one."""
    from unittest import mock
    pytest = __import__("pytest")
    gui = pytest.importorskip("modules.junban.gui")
    fake = scene(tmp_path, fail_write_chunk=1)
    run_id, _done = _connect_run(fake)
    fake.fail_write_chunk = None
    assert undo.unfinished("ja", "reorder") == run_id and not os.path.exists(undo.snapshot_path("ja"))
    panel, asked = _junban_panel(), []
    with mock.patch.object(gui, "ask", lambda parent, message, details=None, **k: asked.append(details) or True):
        gui.JunbanGui.on_restore(panel)
    assert asked and run_id in asked[0][0] and "TheBank" in asked[0][0]
    panel._restore_worker = lambda s, confirmed=None, run=None: gui.JunbanGui._restore_worker(panel, s, confirmed,
                                                                                              run)
    with _patched(fake):
        panel._start.call_args.args[0]()
    report = panel.q.put.call_args.args[0][1]
    assert report["ok"] and report["run"] == run_id, report
    assert undo.unfinished("ja", "reorder") is None
    _again, last = _connect_run(fake)
    assert last["outcome"] == "ran", "the way out of the refusal"


def test_the_windows_restore_never_puts_back_a_run_it_did_not_ask_about(tmp_path):
    """You said yes to the window's own snapshot; a Connect run that died meanwhile is not put back in its place
    (review P1.4-intent-keeper #3): nothing restored, press again to see it."""
    fake = scene(tmp_path)
    with _patched(fake):
        reposition.run(settings())                      # the window's own Restore point
    confirmed = undo.load("ja")["written_at"]
    fake.card_of("冒険")["due"] = 99999                 # out of place again: Connect's next run has work
    fake.fail_write_chunk = fake.write_chunks + 1       # and Anki goes away at its first write
    run_id, _done = _connect_run(fake)                  # dies after you pressed Restore, before it held the writer
    fake.fail_write_chunk = None
    assert undo.unfinished("ja", "reorder") == run_id
    writes = list(fake.writes)
    with _patched(fake):
        report = reposition.restore(settings(), confirmed=confirmed)
    assert not report["ok"] and report["problems"] == [reposition.RESTORE_CHANGED]
    assert fake.writes == writes and undo.unfinished("ja", "reorder") == run_id
    with _patched(fake):
        report = reposition.restore(settings(), run=run_id)    # pressed again: asked about that run
    assert report["ok"] and report["run"] == run_id


def test_the_backfill_windows_restore_names_an_unfinished_fill_of_connects_and_puts_back_that_one(tmp_path):
    """The Backfill window had filled nothing itself, so its Restore said "Nothing has been filled yet" while every fill
    was refused (review P1.4-adversary #1). It now names Connect's fill and puts back what that fill wrote."""
    from unittest import mock
    pytest = __import__("pytest")
    window_module = pytest.importorskip("modules.junban.backfill_gui")
    from modules.junban.tests.test_backfill import _fake, _lapis
    from modules.junban.tests.test_backfill import _settings as fill_settings
    note, card = _lapis(0, "探検", "たんけん", patterns="<div>〜を探検する</div>")
    fake = _fake((note, card))
    run_id = "backfill-20261006-040000-000"
    undo.save([], ["TheBank"], kind="backfill", run_id=run_id,       # written, never marked complete: it died
              fields={note["noteId"]: {"Patterns": {"before": "", "after": "<div>〜を探検する</div>"}}})
    assert undo.unfinished("ja", "backfill") == run_id
    panel, asked = _junban_panel(), []
    panel._settings.return_value = fill_settings()
    with mock.patch.object(window_module.junban_gui, "ask",
                           lambda parent, message, details=None, **k: asked.append(details) or True):
        window_module.BackfillGui.on_restore(panel)
    assert asked and run_id in asked[0][0] and "1 note filled" in asked[0][0]
    with _patched(fake):
        panel._start.call_args.args[0]()
    report = panel.q.put.call_args.args[0][1]
    assert report["ok"], report
    assert fake.notes[note["noteId"]]["fields"]["Patterns"]["value"] == ""
    assert undo.unfinished("ja", "backfill") is None


# --------------------------------------------------------------------------- #
# With the fast re-plan's job too (E2.1 merged in: its notes' seams a–f)
# --------------------------------------------------------------------------- #
class _Rechecked(connect_scene.ConnectCollection):
    """The scene's collection, with a hook before each `cardsInfo` answers — the fast re-plan re-reads each request's
    cards before writing them (E2.1), and a test moves one in that moment."""

    before_cards_info = None

    def _dispatch(self, action, params):
        if action == "cardsInfo" and self.before_cards_info is not None:
            self.before_cards_info(list(params.get("cards", [])))
        return super()._dispatch(action, params)


def _rechecked(tmp_path, **kwargs):
    plain = scene(tmp_path, **kwargs)
    fake = _Rechecked(list(plain.cards.values()), list(plain.notes.values()), **kwargs)
    return fake


def test_a_connect_run_with_the_replans_job_keeps_todays_baseline_and_its_own_snapshot_and_completes_it(
        tmp_path, monkeypatch):
    """Seams a + b: an automatic job keeps today's baseline instead of the window's snapshot, and one of Connect's
    runs keeps its own as well — written before the first write, then marked complete, or every later reorder would
    be refused. Held with the 3.0 line's flag off (positions only, as 2.6 / 2.7); 3.0's run with its suspends keeps its
    own snapshot alone (test_auto_actions.py::test_a_connect_runs_restore_puts_back_its_suspends_and_sets_its_…)."""
    from modules.junban import connect, spaced
    monkeypatch.setattr(connect, "UNATTENDED_SUSPEND", False)
    fake = scene(tmp_path)
    before = {card_id: card["due"] for card_id, card in fake.cards.items() if card["queue"] == 0}
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id, job=spaced.Job())
    assert done["outcome"] == "ran", done
    report = done["report"]
    assert report["run"] == run_id and report["numbering"]["kind"] == spaced.FULL and fake.writes
    saved = undo.load("ja", run_id=run_id)
    assert saved["complete"] is True and saved["kind"] == "reorder"
    assert {int(c): d for c, d in saved["after"].items()} == dict(fake.writes)
    assert {int(c) for c in saved["cards"]} == {card_id for card_id, _due in fake.writes}
    baseline = undo.load("ja", "baseline")
    assert baseline and {int(c): d for c, d in baseline["cards"].items()} == before
    assert not os.path.exists(undo.snapshot_path("ja")), "the window's Restore point is never Connect's"
    assert undo.unfinished("ja", "reorder") is None
    # Its restore puts back exactly what it moved.
    with _patched(fake):
        put_back = reposition.restore_run(settings(), run_id)
    assert put_back["ok"], put_back["problems"]
    assert all(fake.cards[card_id]["due"] == due for card_id, due in before.items())


def test_the_replans_job_takes_over_a_cut_connect_run_so_one_undo_goes_back_past_both(tmp_path):
    """Seams c + d as amended (lead 2026-11-07; Sonic's W3.5 row 7, "a run nobody started never stops the automation"):
    Connect's run cut part way (its first request landed, the second didn't); the re-plan's automatic job goes on and
    takes that run over in the window's snapshot (the run's own file is marked taken over, never refused or offered
    again). One Undo then puts back the order from before BOTH runs — never the older run first and the newer after,
    which put the cut run's half-written numbers back (the adversary's MUST) — and a second Undo changes nothing."""
    from modules.junban import spaced
    fake = scene(tmp_path)
    before = {card_id: card["due"] for card_id, card in fake.cards.items()}
    fake.fail_write_chunk = 2
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        died = auto.reorder(settings(junban_chunk_size=2), list_current=True, positions_only=True, run_id=run_id,
                            job=spaced.Job())
    assert died["outcome"] == "refused" and undo.unfinished("ja", "reorder") == run_id
    half = dict(fake.writes)
    assert half and any(before[c] != d for c, d in half.items()), "the cut run's first request landed"
    fake.fail_write_chunk, fake.writes = None, []
    with _patched(fake):
        automatic = reposition.run(settings(), refresh=False, job=spaced.Job(automatic=True))
    assert automatic["ok"] and not automatic.get("restore_first") and fake.writes, automatic
    assert undo.unfinished("ja", "reorder") is None, "taken over: nothing left to refuse a reorder of yours"
    cut = undo.load("ja", run_id=run_id)
    assert cut["complete"] is True and cut.get("taken_over_at") and not cut.get("restored_at")
    window = undo.load("ja")
    assert window["complete"] is True and window["automatic"] is True
    assert all(window["cards"][str(c)] == before[c] for c in half), "the cut run's way back is in the window's snapshot"
    with _patched(fake):
        put_back = reposition.restore(settings())
    assert put_back["ok"], put_back["problems"]
    assert {c: card["due"] for c, card in fake.cards.items()} == before, "the order from before both runs"
    with _patched(fake):
        again = reposition.restore(settings())
    assert again["ok"] and {c: card["due"] for c, card in fake.cards.items()} == before, "never the half writes back"


def test_connects_own_next_run_leaves_a_cut_run_pending_and_a_cut_run_of_another_deck_is_never_taken_over(tmp_path):
    """Connect's own next run (`run_id`) goes on but takes nothing over: its complete snapshot isn't 順's Undo, so the
    cut run stays the way back (offered first). An automatic job for ANOTHER deck goes on and leaves it as it is."""
    from modules.junban import spaced
    fake = scene(tmp_path, fail_write_chunk=1)
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id, job=spaced.Job())
    fake.fail_write_chunk = None
    with open(undo.snapshot_path("ja", run_id=run_id), encoding="utf-8") as handle:
        cut_file = handle.read()
    _second, again = _connect_run(fake)
    assert again["outcome"] == "ran" and undo.unfinished("ja", "reorder") == run_id
    saved = undo.load("ja", run_id=run_id)
    saved["scope"] = ["Another deck"]                   # as if the cut run had been for another deck
    with open(undo.snapshot_path("ja", run_id=run_id), "w", encoding="utf-8") as handle:
        json.dump(saved, handle)
    ids = sorted(fake.cards)                            # work for the job: two cards swapped in Anki since
    fake.cards[ids[0]]["due"], fake.cards[ids[-1]]["due"] = fake.cards[ids[-1]]["due"], fake.cards[ids[0]]["due"]
    fake.writes = []
    with _patched(fake):
        other = reposition.run(settings(), refresh=False, job=spaced.Job(automatic=True))
    assert other["ok"] and fake.writes, other
    assert undo.unfinished("ja", "reorder") == run_id
    assert undo.load("ja", run_id=run_id) == saved, "another deck's cut run is left exactly as it was"
    assert cut_file


def test_a_card_the_recheck_leaves_is_not_in_the_runs_after(tmp_path):
    """Seam f: the fast re-plan re-reads each request's cards and leaves one moved meanwhile for the next job. The run
    never moved it, so its snapshot's `after` doesn't hold it, and its restore leaves the card where you put it."""
    from modules.junban import spaced
    fake = _rechecked(tmp_path)
    calls = []

    def move_one(ids):
        calls.append(ids)
        if len(calls) == 2:                             # the first re-check: you repositioned a card by hand
            fake.cards[ids[-1]]["due"] = 1
    fake.before_cards_info = move_one
    run_id = undo.new_run_id("reorder")
    with _patched(fake):
        done = auto.reorder(settings(), list_current=True, positions_only=True, run_id=run_id, job=spaced.Job())
    assert done["outcome"] == "ran", done
    left = done["report"]["left"]
    assert left == [calls[1][-1]] and fake.cards[left[0]]["due"] == 1
    saved = undo.load("ja", run_id=run_id)
    assert saved["complete"] is True
    assert str(left[0]) not in saved["after"] and {int(c): d for c, d in saved["after"].items()} == dict(fake.writes)
    with _patched(fake):
        put_back = reposition.restore_run(settings(), run_id)
    assert put_back["ok"] and fake.cards[left[0]]["due"] == 1


def test_a_run_that_gathers_parked_cards_reads_afresh_without_the_warm_card_map(tmp_path):
    """Seam e: the warm card map reads unsuspended new cards only, so a run from 順 that also gathers the cards Junban
    parked (a returning word, MR-R3) reads them without it — and the returning card still comes back."""
    from modules.junban import spaced
    from modules.junban.tests.connect_scene import without_connect
    fake = scene(tmp_path, without_connect())
    card_map = reposition.CardMap()
    with _patched(fake):
        report = reposition.run(settings(), job=spaced.Job(cards=card_map))
    assert report["ok"], report["problems"]
    assert card_map.fresh == 0 and not card_map.rows, "the map was never asked"
    assert fake.card_of("老婆")["queue"] == 0 and "Back on your list: unsuspended 1 card" in report["message"]
    # Unsuspended before the job's re-check reads it, so its position is written in this run, never left over.
    assert not report["left"] and fake.card_of("老婆")["cardId"] in report["written"]


# --------------------------------------------------------------------------- #
# The mutant round's gaps (P1.4): a restore asked about one run puts back that run or nothing (Backfill's: test_backfill.py)
# --------------------------------------------------------------------------- #
def test_a_restore_asked_about_a_run_put_back_meanwhile_restores_nothing_else(tmp_path):
    """The window asked about Connect's unfinished run; by the time Restore runs, that run was put back (another
    window's Restore). Nothing is restored — never the window's own snapshot in its place — and the answer says what
    changed."""
    fake = scene(tmp_path)
    with _patched(fake):
        reposition.run(settings())                      # the window's own Restore point
    fake.card_of("冒険")["due"] = 99999
    fake.fail_write_chunk = fake.write_chunks + 1
    run_id, _done = _connect_run(fake)                  # dies at its first write
    fake.fail_write_chunk = None
    assert undo.unfinished("ja", "reorder") == run_id
    with _patched(fake):
        assert reposition.restore(settings(), run=run_id)["ok"]       # put back elsewhere first
    writes, suspends = list(fake.writes), list(fake.suspend_calls)
    with _patched(fake):
        report = reposition.restore(settings(), run=run_id)          # the window's Restore, asked about that run
    assert not report["ok"] and report["problems"] == [reposition.RESTORE_CHANGED], report
    assert fake.writes == writes and fake.suspend_calls == suspends


def test_the_reorder_restore_refuses_a_backfill_run(tmp_path):
    """A Backfill run's snapshot handed to the reorder's restore is refused untouched: it stays Backfill's unfinished
    fill, for Backfill's Restore to put back — never marked put back by a restore that wrote nothing of it."""
    fake = scene(tmp_path)
    run_id = "backfill-20261006-040000-000"
    undo.save([], ["TheBank"], kind="backfill", run_id=run_id,
              fields={fake.card_of("冒険")["note"]: {"Patterns": {"before": "", "after": "<div>〜を冒険する</div>"}}})
    with _patched(fake):
        report = reposition.restore_run(settings(), run_id)
    assert not report["ok"] and "no saved reorder run" in report["problems"][0], report
    assert fake.writes == [] and fake.suspend_calls == [] and fake.note_writes == []
    assert undo.unfinished("ja", "backfill") == run_id and not undo.load("ja", run_id=run_id).get("restored_at")


def test_the_windows_restore_hands_its_worker_the_run_it_asked_about(tmp_path):
    """The 順 window names Connect's unfinished run and you say yes: its worker restores exactly that run (`run=`), so
    a run that changed meanwhile is refused rather than another put back in its place."""
    from unittest import mock
    pytest = __import__("pytest")
    gui = pytest.importorskip("modules.junban.gui")
    fake = scene(tmp_path, fail_write_chunk=1)
    run_id, _done = _connect_run(fake)
    assert undo.unfinished("ja", "reorder") == run_id
    panel = _junban_panel()
    with mock.patch.object(gui, "ask", lambda parent, message, details=None, **k: True):
        gui.JunbanGui.on_restore(panel)
    panel._start.call_args.args[0]()
    assert panel._restore_worker.call_args.kwargs.get("run") == run_id, panel._restore_worker.call_args
