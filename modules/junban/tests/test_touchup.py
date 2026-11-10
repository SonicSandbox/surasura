# SPDX-License-Identifier: GPL-3.0-or-later
"""WP-L's writes, decided against plain data with no collection anywhere in reach. (The extra example
sentence moved to Anki Backfill's 例文, 2026-09-24 — its tests are in test_backfill.py.)

This is the file that guards the only thing junban can do that is **not** reversible by arithmetic.
A wrong `due` is a number; the snapshot holds the old one and a restore puts it back exactly. A
clobbered `Glossary` or `Hint` is something the user wrote, it exists nowhere else, and the snapshot
is the only copy there will ever be. So every claim below is about not destroying something:

  * the frequency `<li>` is **appended** to the list that is already there, and a re-run replaces
    junban's own entry rather than stacking a second one;
  * `FreqSort` — one sort key the user's browser ordering depends on — is untouched unless its own
    separate setting is on;
  * an unmatched card gets nothing at all: no rank exists for it, so no rank is invented.

Field values are the real shapes measured on the user's own 115 anki_miner notes —
`<ul><li>JPDBv2㋕: 54614</li></ul>` in `Frequency`, `54614` in `FreqSort` — and the words and
sentences come from a genuine Surasura export (`tests/Test Resources/ja/expected_output.csv`),
never ASCII stand-ins (`testing.md` §1). Nothing here opens a socket or a window.
"""
import csv
import os

import pytest

from modules.junban import match, touchup, undo

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RESOURCE_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")

# The exact shape 96 of the user's 115 mined notes carry. Kept verbatim, circled-katakana and all:
# a normaliser that mangled ㋕ would break the very re-run detection this file checks.
JPDB = "<ul><li>JPDBv2㋕: 54614</li></ul>"

# Real Japanese, from the same collection the spec measured. 須藤 is the orth the show writes for
# the lemma スドウ — the orth/lemma disagreement the whole match index exists for.
SUDOU_ORTH = "須藤"
SUDOU_LEMMA = "スドウ"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def export_rows():
    """Every row of a real export, contexts included, in rank order."""
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def real_list(tmp_path, export_rows):
    """A real `priority_learning_list.csv`, BOM and `Context N` columns and all."""
    path = tmp_path / "priority_learning_list.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(export_rows[0].keys()))
        writer.writeheader()
        writer.writerows(export_rows)
    return str(path)


def _note(fields, tags=None):
    return {"fields": dict(fields), "tags": list(tags or [])}


def _lapis(word, frequency=JPDB, freqsort="54614", sentence="", selection=""):
    """A Lapis note as `notesInfo` returns it, flattened — the measured field set, measured values."""
    return _note({"Expression": word,
                  "Sentence": sentence or f"{word}が好きだ。",
                  "Frequency": frequency,
                  "FreqSort": freqsort,
                  "Glossary": f"<div>{word} — a word</div>",
                  "MiscInfo": "[SubsPlease] Tetsunabe no Jan! - 04",
                  "Hint": "",
                  "SelectionText": selection})


def _on(**over):
    """Settings with the touch-ups switched on, so a test says what it turns on and nothing else."""
    base = {"junban_tag": "Surasura", "junban_write_frequency": False,
            "junban_frequency_field": "Frequency", "junban_write_freqsort": False}
    base.update(over)
    return touchup.options(base)


# --------------------------------------------------------------------------- #
# The frequency entry — append, never replace
# --------------------------------------------------------------------------- #
def test_append_leaves_the_existing_entry_intact_and_adds_exactly_one():
    """The measured reality: 96/115 notes already carry JPDB's entry. A second `<li>` beside it is
    how multi-dictionary frequency renders; replacing the field would delete a dictionary."""
    after = touchup.frequency_value(JPDB, 42)

    assert "JPDBv2㋕: 54614" in after, "JPDB's own entry must survive untouched"
    assert after.count("<li>") == 2
    assert after.count("Surasura:") == 1
    assert after == "<ul><li>JPDBv2㋕: 54614</li><li>Surasura: 42</li></ul>"


def test_re_running_replaces_our_own_entry_and_never_accumulates():
    """Pressing Reorder weekly must not grow a column of stale Surasura entries — and a rank that
    has genuinely changed must be the one showing."""
    once = touchup.frequency_value(JPDB, 42)
    twice = touchup.frequency_value(once, 42)
    moved = touchup.frequency_value(twice, 7)

    assert twice == once, "an unchanged rank must produce an identical field"
    assert moved.count("Surasura:") == 1
    assert "Surasura: 7" in moved and "Surasura: 42" not in moved
    assert "JPDBv2㋕: 54614" in moved


def test_a_field_that_somehow_collected_two_of_ours_comes_out_with_one():
    """Defence against a half-finished earlier version, or a hand-edited note: the invariant is
    'exactly one Surasura entry afterwards', not 'one fewer than before'."""
    doubled = "<ul><li>JPDBv2㋕: 54614</li><li>Surasura: 9</li><li>Surasura: 12</li></ul>"
    after = touchup.frequency_value(doubled, 3)
    assert after.count("Surasura:") == 1
    assert "Surasura: 3" in after


def test_an_empty_frequency_field_gets_a_fresh_list():
    """19 of the 115 notes have nothing here. There is no list to append to, so one is started."""
    assert touchup.frequency_value("", 5) == "<ul><li>Surasura: 5</li></ul>"
    assert touchup.frequency_value(None, 5) == "<ul><li>Surasura: 5</li></ul>"


def test_content_with_no_list_is_kept_and_a_list_is_started_beside_it():
    """A hand-typed number is still the user's own writing. Replacing it would be the exact damage
    this module exists not to do."""
    after = touchup.frequency_value("54614", 5)
    assert after.startswith("54614")
    assert "<ul><li>Surasura: 5</li></ul>" in after


# --------------------------------------------------------------------------- #
# FreqSort — the sort key, behind its own switch
# --------------------------------------------------------------------------- #
def test_freqsort_is_untouched_unless_its_own_key_is_on(export_rows):
    """The single most important negative in WP-L. `FreqSort` is what the user's browser orders by;
    overwriting it as a side effect of a harmless frequency append would silently reshuffle their
    whole collection view."""
    note = _lapis(SUDOU_ORTH)
    moved = [(1789712080001, 1789712000001, SUDOU_ORTH, 41)]

    on_frequency = touchup.plan(moved, {1789712000001: note},
                                _on(junban_write_frequency=True))
    edits = on_frequency["fields"][1789712000001]
    assert "Frequency" in edits
    assert "FreqSort" not in edits, "the sort key rode along with the append"

    both = touchup.plan(moved, {1789712000001: note},
                        _on(junban_write_frequency=True, junban_write_freqsort=True))
    assert both["fields"][1789712000001]["FreqSort"] == {"before": "54614", "after": "42"}


def test_freqsort_records_the_prior_sort_key_before_replacing_it():
    """It is the one touch-up that genuinely replaces a value, so the old one has to be in the
    snapshot or it is gone."""
    note = _lapis(SUDOU_ORTH, freqsort="12345")
    plan = touchup.plan([(1, 500, SUDOU_ORTH, 0)], {500: note},
                        _on(junban_write_freqsort=True))
    assert plan["fields"][500]["FreqSort"]["before"] == "12345"
    assert plan["fields"][500]["FreqSort"]["after"] == "1", "rank 0 is the 1st word, not the 0th"


# --------------------------------------------------------------------------- #
# The plan as a whole
# --------------------------------------------------------------------------- #
def test_unmatched_cards_get_no_tag_and_no_frequency():
    """There is no rank for a word the list does not know, so there is nothing honest to write — and a tag saying "Surasura ordered this" would be a claim about a
    card it could not order."""
    notes = {500: _lapis(SUDOU_ORTH), 501: _lapis("鳥取")}
    moved = [(1, 500, SUDOU_ORTH, 3), (2, 501, "鳥取", None)]

    plan = touchup.plan(moved, notes, _on(junban_write_frequency=True))

    assert 500 in plan["fields"] and 501 not in plan["fields"]
    assert plan["tags"] == [500]
    assert plan["counts"]["notes"] == 1


def test_a_note_that_already_carries_the_tag_is_not_recorded_for_removal():
    """`addTags` is idempotent so re-tagging is harmless — but recording it would let a later
    Restore strip a tag the USER put there, and this module removes only its own."""
    notes = {500: _lapis(SUDOU_ORTH, ), 501: _lapis("老婆")}
    notes[500]["tags"] = ["Surasura", "anki_miner"]

    plan = touchup.plan([(1, 500, SUDOU_ORTH, 0), (2, 501, "老婆", 1)], notes, _on())

    assert plan["tags"] == [501]
    assert plan["tag"] == "Surasura"


@pytest.mark.parametrize("theirs", ["surasura", "SURASURA", "Surasura::keep"])
def test_a_tag_anki_would_remove_along_with_ours_counts_as_already_there(theirs):
    """Anki compares tags case-insensitively, and removing `Surasura` also removes `Surasura::keep`.
    Recording such a note would let Restore take away the user's own tag."""
    notes = {500: _lapis(SUDOU_ORTH), 501: _lapis("老婆")}
    notes[500]["tags"] = [theirs, "anki_miner"]

    plan = touchup.plan([(1, 500, SUDOU_ORTH, 0), (2, 501, "老婆", 1)], notes, _on())

    assert plan["tags"] == [501]


def test_carries_tag_is_not_fooled_by_a_longer_name():
    """`Surasura_old` is a different tag, not a child: it must not count as already tagged."""
    assert not touchup.carries_tag(["Surasura_old", "Surasurax"], "Surasura")
    assert touchup.carries_tag(["surasura::star"], "Surasura::star")


def test_everything_off_plans_nothing_at_all():
    """The shipped default apart from the tag. With the tag cleared too, this is the module as it
    behaved before WP-L: `due` and nothing else."""
    plan = touchup.plan([(1, 500, SUDOU_ORTH, 0)], {500: _lapis(SUDOU_ORTH)},
                        _on(junban_tag=""))
    assert plan == {"fields": {}, "tags": [], "tag": "", "marker_tags": {},
                    "counts": {"notes": 0, "tag": 0, "frequency": 0, "freqsort": 0, "markers": 0}}


def test_an_empty_run_plans_nothing_and_does_not_raise():
    """Empty state: nothing moved, no notes, no contexts. The common answer on a second press."""
    plan = touchup.plan([], {}, _on(junban_write_frequency=True))
    assert plan["fields"] == {} and plan["tags"] == []
    plan = touchup.plan(None, None, _on(junban_write_frequency=True))
    assert plan["fields"] == {} and plan["tags"] == []


def test_one_note_with_several_moved_cards_is_written_once_at_its_best_rank():
    """Yomitan and Migaku both make several cards per note; anki_miner does not. The note must not
    collect two `<li>`s, and the rank shown must be the better of the two."""
    notes = {500: _lapis(SUDOU_ORTH)}
    plan = touchup.plan([(1, 500, SUDOU_ORTH, 80), (2, 500, SUDOU_ORTH, 12)], notes,
                        _on(junban_write_frequency=True))

    assert list(plan["fields"]) == [500]
    assert "Surasura: 13" in plan["fields"][500]["Frequency"]["after"]
    assert plan["tags"] == [500]


def test_a_second_identical_run_plans_no_field_write_at_all():
    """Idempotence, the same promise the positions make: pressing the button twice must not queue a
    write that changes nothing, because every write syncs."""
    notes = {500: _lapis(SUDOU_ORTH)}
    first = touchup.plan([(1, 500, SUDOU_ORTH, 41)], notes, _on(junban_write_frequency=True))
    notes[500]["fields"]["Frequency"] = first["fields"][500]["Frequency"]["after"]

    second = touchup.plan([(1, 500, SUDOU_ORTH, 41)], notes, _on(junban_write_frequency=True))
    assert second["fields"] == {}
    assert second["counts"]["frequency"] == 0


def test_the_wire_payload_carries_only_the_new_values():
    plan = touchup.plan([(1, 500, SUDOU_ORTH, 41)], {500: _lapis(SUDOU_ORTH)},
                        _on(junban_write_frequency=True))
    wire = touchup.edits_for_wire(plan["fields"])
    assert wire == {500: {"Frequency": plan["fields"][500]["Frequency"]["after"]}}


def test_restrict_drops_the_notes_whose_cards_never_moved():
    """Anki can be closed halfway. A tag on a card that stayed put is a lie the user cannot see —
    and the snapshot still covers the superset, so nothing is lost by narrowing afterwards."""
    notes = {500: _lapis(SUDOU_ORTH), 501: _lapis("老婆")}
    plan = touchup.plan([(1, 500, SUDOU_ORTH, 0), (2, 501, "老婆", 1)], notes,
                        _on(junban_write_frequency=True))
    narrowed = touchup.restrict(plan, [501])

    assert list(narrowed["fields"]) == [501]
    assert narrowed["tags"] == [501]
    assert touchup.restrict(plan, [])["tag"] == "", "nothing tagged means no tag to record"


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def test_the_frequency_switch_alone_is_not_a_nomination():
    """The switch says "write it"; the field name says "here". Without the second there is no
    field the user named, so nothing is written."""
    opts = touchup.options({"junban_write_frequency": True, "junban_frequency_field": "   "})
    assert opts["frequency"] is False


# --------------------------------------------------------------------------- #
# The list index's Context columns — core `anki_match` still offers them (`want_contexts`);
# Junban stopped reading them when its sentence moved to Backfill. Pinned until core retires it.
# --------------------------------------------------------------------------- #
def test_the_index_carries_the_real_context_columns_for_a_real_word(real_list, export_rows):
    """Read by NAME from a real export — `Context 1/2/3` sit at positions 11/13/15 behind `Src`
    columns, so anything positional would pick up a file path instead of a sentence."""
    rank_of, contexts = match.load_index(real_list, want_contexts=True)

    first = export_rows[0]
    key = (first.get("Orth") or first.get("Word")).strip()
    assert rank_of[key] == 0
    assert contexts[key][0] == first["Context 1"]
    assert len(contexts[key]) == 3
    assert "HighPriority/" not in "".join(contexts[key]), "a Src path leaked in as a sentence"


def test_contexts_are_not_loaded_when_they_are_not_wanted(real_list):
    """They are the bulk of a real priority list; a reader that does not ask for them must not hold
    them in memory."""
    rank_of, contexts = match.load_index(real_list)
    assert rank_of and contexts == {}
    assert match.load_rank_index(real_list) == rank_of


def test_a_list_without_the_context_columns_simply_has_none(tmp_path):
    """An older `results/` folder predates them. Nothing to add is not an error."""
    path = tmp_path / "old_priority_learning_list.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Reading", "Tier"])
        writer.writerow([SUDOU_LEMMA, SUDOU_ORTH, "スドウ", "NOW"])

    rank_of, contexts = match.load_index(str(path), want_contexts=True)
    assert rank_of == {SUDOU_ORTH: 0, SUDOU_LEMMA: 0}
    assert contexts == {}


def test_a_missing_list_yields_two_empty_dicts(tmp_path):
    assert match.load_index(str(tmp_path / "nope.csv"), want_contexts=True) == ({}, {})


# --------------------------------------------------------------------------- #
# The snapshot's second section
# --------------------------------------------------------------------------- #
def test_the_prior_value_and_what_we_wrote_are_both_saved(tmp_path):
    """Both halves, because a restore has to tell "junban put this here" apart from "the user has
    edited it since" — and it can only do that by knowing what junban wrote."""
    before, after = JPDB, touchup.frequency_value(JPDB, 42)
    undo.save({1789712080001: 2832}, ["TheBank"],
              fields={500: {"Frequency": {"before": before, "after": after}}},
              tags=[500], tag="Surasura")

    saved = undo.load("ja")
    assert saved["fields"]["500"]["Frequency"] == {"before": before, "after": after}
    assert saved["tags"] == [500] and saved["tag"] == "Surasura"
    assert saved["cards"] == {"1789712080001": 2832}, "the positions are untouched by any of this"


def test_a_snapshot_with_no_touch_ups_is_exactly_the_file_it_always_was(tmp_path):
    """A reorder with everything off must write the same JSON previous versions did — the new keys
    are additive, and `SCHEMA` is deliberately NOT bumped so old snapshots still restore."""
    import json
    path = undo.save({1789712080001: 2832}, ["TheBank"])
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    # `complete` is the one key every snapshot now carries: saved False, flipped by a clean run, so
    # an interrupted run can't be overwritten by the next (see undo.save). Additive — an older file
    # without it loads as complete, which is what it was.
    assert set(raw) == {"schema", "written_at", "scope", "cards", "complete"}
    assert raw["complete"] is False
    assert raw["schema"] == undo.SCHEMA == 1

    del raw["complete"]                                  # exactly what previous versions wrote
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    assert undo.load().get("complete") is not False, "an older snapshot must not block a new run"


def test_restore_puts_the_prior_value_back_when_the_field_still_holds_ours():
    after = touchup.frequency_value(JPDB, 42)
    snapshot = {"fields": {"500": {"Frequency": {"before": JPDB, "after": after}}}}

    edits, skipped = undo.restore_fields(snapshot, {500: {"Frequency": after}})
    assert edits == {500: {"Frequency": JPDB}}
    assert skipped == 0


def test_restore_skips_a_field_the_user_edited_after_the_run_and_says_so():
    """The promise that makes this safe to press. Their edit is newer than anything junban knows
    about, and reverting it would destroy writing that exists nowhere else."""
    after = touchup.frequency_value(JPDB, 42)
    theirs = after.replace("</ul>", "<li>私のメモ: 1</li></ul>")
    snapshot = {"fields": {"500": {"Frequency": {"before": JPDB, "after": after}}}}

    edits, skipped = undo.restore_fields(snapshot, {500: {"Frequency": theirs}})
    assert edits == {}, "the user's own later edit was about to be thrown away"
    assert skipped == 1


def test_a_field_already_holding_the_prior_value_is_not_counted_as_skipped():
    """The half-finished run: the position write failed, so the field was never written. There is
    nothing to put back and nothing the user did wrong — reporting it as "you edited this" would
    be a confusing lie."""
    after = touchup.frequency_value(JPDB, 42)
    snapshot = {"fields": {"500": {"Frequency": {"before": JPDB, "after": after}}}}

    edits, skipped = undo.restore_fields(snapshot, {500: {"Frequency": JPDB}})
    assert edits == {} and skipped == 0


def test_restore_ignores_a_note_that_no_longer_exists():
    """Deleted since the run. Writing to it by id is a write we cannot reason about."""
    snapshot = {"fields": {"500": {"Frequency": {"before": JPDB, "after": "x"}}}}
    edits, skipped = undo.restore_fields(snapshot, {})
    assert edits == {} and skipped == 0


def test_restore_only_ever_offers_junbans_own_tag_and_only_its_own_notes():
    snapshot = {"tag": "Surasura", "tags": [500, 501]}
    assert undo.restore_tag(snapshot) == ("Surasura", [500, 501])
    assert undo.restore_tag(snapshot, existing_ids=[501]) == ("Surasura", [501])
    assert undo.restore_tag({"tags": [500]}) == ("", []), "no tag name means nothing to remove"
    assert undo.restore_tag(None) == ("", [])


def test_a_malformed_touch_up_section_never_quarantines_a_good_snapshot(tmp_path):
    """The positions are the part a user cannot reconstruct by hand. Losing them to a typo in an
    OPTIONAL section would be the exact destruction this file exists to prevent."""
    import json
    path = undo.snapshot_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "scope": ["TheBank"], "cards": {"1789712080001": 2832},
                   "fields": {"not-a-note": "garbage", "500": {"Frequency": {"before": JPDB}}},
                   "tags": "nonsense", "tag": 7}, handle)

    saved = undo.load("ja")
    assert saved is not None, "a good `cards` map was thrown away over a bad `fields` block"
    assert saved["cards"] == {"1789712080001": 2832}
    assert saved["fields"] == {}, "half a change is not a change we may reverse"
    assert saved["tags"] == []


def test_describe_names_the_notes_as_well_as_the_cards():
    """Restoring a field is the half a user would want to know about before pressing: a position is
    a position, a field is something they wrote."""
    undo.save({1789712080001: 2832}, ["TheBank"],
              fields={500: {"Frequency": {"before": JPDB, "after": "x"}}},
              tags=[500, 501], tag="Surasura")
    line = undo.describe(undo.load("ja"))
    assert "1 card" in line and "1 note edited" in line and "2 tagged 'Surasura'" in line


def test_note_ids_names_everything_the_second_section_touches():
    snapshot = {"fields": {"500": {"Frequency": {"before": "a", "after": "b"}}},
                "tag": "Surasura", "tags": [501]}
    assert undo.note_ids(snapshot) == [500, 501]
    assert undo.note_ids(None) == []
