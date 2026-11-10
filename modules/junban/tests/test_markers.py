# SPDX-License-Identifier: GPL-3.0-or-later
"""WP-N — Surasura's own markers: ✦ star, ⚖ lopsided, 📖 reading.

These are **not** analyzer output. The report computes them live in the browser from three CSV
columns plus `logic.priority_markers`, which is what keeps them a *presentation* setting: moving a
threshold re-renders the report, it does not force a re-analysis. junban therefore computes them the
same way, from the same settings block, and this file pins it to the template's exact rule
(`templates/web_app.html:2405-2412`):

```js
isLopsided = pTotal > 0 && (pHigh / pTotal) >= lopsided_threshold
isPriority = !isLopsided && pTotal >= priority_min
             && ((pHigh + pLow) / pTotal) >= priority_threshold
isReading  = data.Modality === 'reading'
```

Two traps live here, and both are guarded below because both are wrong in ways that look right:

1. **`isPriority` requires `!isLopsided`.** They are mutually exclusive. On the live library all 39
   lopsided words also clear the star ratio, so treating the two as independent flags would star
   every one of them and nobody would notice until the tags were in Anki.
2. **The two lists name the total differently** — `Occurrences` on the priority list,
   `Occurrences (Global)` on the progressive one. WP-M means junban reads both files, so both names
   have to be honoured, exactly as the template honours them.

Every row below is REAL: the words, the counts and the modality are lifted verbatim from the user's
own 3,704-row export, chosen so that all five outcomes (star / lopsided / reading / star+reading /
none) are represented by a word that genuinely produces it (`testing.md` §1).
"""
import csv
import json
import os

import pytest

from modules.junban import match, plan as plan_module, touchup, undo

# --- the real rows ------------------------------------------------------------------------------ #
# Word, Orth, Count (High), Count (Low), total, Modality  — measured on the live library.
ARUMA = ("アルマ", "アルマ", 0, 4435, 4435, "")        # ✦ via the LOW path: 0 high, 4435 low
TANI = ("タニ", "タニ", 181, 1, 182, "")               # ⚖ 181/182 = 0.995 — and therefore NOT ✦
HONSHO = ("本書", "本書", 1, 57, 78, "reading")        # ✦ and 📖 together (58/78 = 0.74)
YUBISASU = ("指差す", "指差す", 3, 35, 85, "reading")   # 📖 only (38/85 = 0.45, below the star ratio)
FERUTO = ("フェルト", "フェルト", 0, 280, 572, "")      # nothing at all (280/572 = 0.49)

REAL_ROWS = [ARUMA, TANI, HONSHO, YUBISASU, FERUTO]

# The shipped `logic.priority_markers` block, as `settings.json` carries it.
SHIPPED = {"logic": {"priority_markers": {"priority_threshold": 0.5, "priority_min": 3,
                                          "lopsided_threshold": 0.85}}}


def _row(entry, total_column="Occurrences"):
    """One CSV row in the shape the named list writes it."""
    word, orth, high, low, total, modality = entry
    return {"Word": word, "Orth": orth, "Count (High)": str(high), "Count (Low)": str(low),
            total_column: str(total), "Modality": modality}


def _write(path, entries, total_column="Occurrences"):
    """A BOM-carrying list, the way `static_html_generator` emits one."""
    rows = [_row(entry, total_column) for entry in entries]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _marks(entry, settings=SHIPPED, total_column="Occurrences"):
    return match.row_markers(_row(entry, total_column), match.marker_thresholds(settings))


# --- the rule ----------------------------------------------------------------------------------- #
def test_the_star_is_computed_the_way_the_report_computes_it():
    """アルマ: 0 high, 4435 low, 4435 total. (0+4435)/4435 = 1.0, well over the threshold, and the
    total clears the minimum — so it is starred **through the Low path**, with no high-priority
    occurrence anywhere. A rule that only looked at `Count (High)` would miss the single
    highest-ranked word in the user's entire library."""
    assert _marks(ARUMA) == frozenset({"star"})


def test_a_lopsided_word_is_never_also_starred():
    """⚠ TRAP. タニ is 181/182 from one tier, so it is ⚖. Its combined ratio is 182/182 = 1.0, which
    clears the star threshold easily — and it must STILL not be starred, because the template reads
    `isPriority = !isLopsided && …`.

    This is the failure that looks plausible: as independent flags every one of the live library's
    39 lopsided words would also get a ✦, and the wrongness would only surface as tags in Anki."""
    marks = _marks(TANI)
    assert "lopsided" in marks
    assert "star" not in marks, "a lopsided word must never also carry the star"
    assert marks == frozenset({"lopsided"})


def test_a_word_can_be_starred_and_a_reading_word_at_once():
    """本書 is both: the two are independent of each other, unlike ✦ and ⚖."""
    assert _marks(HONSHO) == frozenset({"star", "reading"})


def test_a_reading_word_below_the_star_ratio_carries_only_the_book():
    """指差す: 📖 from Modality, and (3+35)/85 = 0.447 is under 0.5, so no star."""
    assert _marks(YUBISASU) == frozenset({"reading"})


def test_a_word_can_carry_no_marker_at_all():
    """38% of the live library carries nothing. フェルト is 280/572 = 0.4895 — just under."""
    assert _marks(FERUTO) == frozenset()


def test_a_blank_modality_is_never_asserted_as_hearable():
    """Blank means "hearable **or** not enough evidence" — deliberately not a claim either way. All
    junban may conclude from it is the absence of 📖, never the presence of anything."""
    assert "reading" not in _marks(ARUMA)
    assert _marks(ARUMA) == frozenset({"star"}), "a blank Modality must add no marker of its own"


# --- the two column names ----------------------------------------------------------------------- #
def test_both_occurrences_and_occurrences_global_are_honoured_as_the_total():
    """⚠ TRAP. The priority list says `Occurrences`; the progressive list says
    `Occurrences (Global)`. WP-M means junban reads both files, so a reader that knew only one name
    would silently score every word in the other file as total 0 — which means no star, no lopsided,
    and a marker filter that matched nothing."""
    assert _marks(ARUMA, total_column="Occurrences") == frozenset({"star"})
    assert _marks(ARUMA, total_column="Occurrences (Global)") == frozenset({"star"})
    assert _marks(TANI, total_column="Occurrences (Global)") == frozenset({"lopsided"})


def test_a_list_with_neither_total_column_scores_zero_rather_than_raising():
    """An older results folder, or a hand-trimmed export. Total 0 means no ✦ and no ⚖ — which is
    right: with no evidence there is nothing to claim. It must not divide by zero on the way."""
    row = {"Word": "老婆", "Count (High)": "16", "Count (Low)": "0", "Modality": ""}
    assert match.row_markers(row, match.marker_thresholds(SHIPPED)) == frozenset()
    assert match.row_total(row) == 0


def test_a_blank_or_junk_count_reads_as_zero_like_parseint_does():
    """`parseInt(x) || 0` is what the template does, and these cells are genuinely blank on rows the
    analyser could not count. A traceback here would happen on the way to a collection write."""
    row = {"Word": "老婆", "Count (High)": "", "Count (Low)": None, "Occurrences": "n/a",
           "Modality": ""}
    assert match.row_markers(row, match.marker_thresholds(SHIPPED)) == frozenset()


# --- thresholds come from settings -------------------------------------------------------------- #
def test_the_thresholds_are_read_from_settings_not_hardcoded():
    """The whole reason the marks are computed rather than stored: they are a RENDER-time setting.
    Moving `lopsided_threshold` past タニ's ratio turns it from ⚖ into ✦ — with no re-analysis, and
    with the report agreeing, because the report reads the same block."""
    strict = {"logic": {"priority_markers": {"priority_threshold": 0.5, "priority_min": 3,
                                             "lopsided_threshold": 0.999}}}
    assert _marks(TANI, settings=strict) == frozenset({"star"}), \
        "181/182 = 0.995 is below 0.999, so it is no longer lopsided — and the star is freed"

    lenient = {"logic": {"priority_markers": {"priority_threshold": 0.4, "priority_min": 3,
                                              "lopsided_threshold": 0.85}}}
    assert "star" in _marks(FERUTO, settings=lenient), \
        "0.4895 clears a 0.4 threshold; the same row must change answer when the setting does"


def test_the_minimum_occurrence_count_is_honoured():
    """`priority_min` exists so a word seen twice cannot be starred on a perfect ratio."""
    rare = ("稀語", "稀語", 0, 2, 2, "")
    assert _marks(rare) == frozenset(), "2 occurrences is under the shipped minimum of 3"
    loose = {"logic": {"priority_markers": {"priority_threshold": 0.5, "priority_min": 2,
                                            "lopsided_threshold": 0.85}}}
    assert _marks(rare, settings=loose) == frozenset({"star"})


def test_settings_without_a_logic_block_fall_back_to_the_shipped_numbers():
    """A hand-built settings dict — every engine test in this module uses one — must still produce
    the marks the user would see, not no marks at all."""
    assert match.marker_thresholds({}) == match.MARKER_DEFAULTS
    assert match.marker_thresholds(None) == match.MARKER_DEFAULTS
    assert _marks(ARUMA, settings={}) == frozenset({"star"})


def test_one_broken_threshold_does_not_discard_the_others():
    """Half a block is still worth half a block: a string where a number belongs falls back for that
    key alone rather than throwing the user's other two settings away."""
    broken = {"logic": {"priority_markers": {"priority_threshold": "half", "priority_min": 9}}}
    limits = match.marker_thresholds(broken)
    assert limits["priority_threshold"] == match.MARKER_DEFAULTS["priority_threshold"]
    assert limits["priority_min"] == 9


# --- the filter --------------------------------------------------------------------------------- #
@pytest.fixture
def list_path(tmp_path):
    return _write(tmp_path / "priority_learning_list.csv", REAL_ROWS)


def test_an_empty_filter_matches_everything(list_path):
    index = match.build_index(list_path, thresholds=match.marker_thresholds(SHIPPED), only=())
    assert set(index.rank_of) == {word for word, *_rest in REAL_ROWS}
    assert index.rank_of["アルマ"] == 0 and index.rank_of["フェルト"] == 4


def test_a_filter_keeps_only_the_words_carrying_it(list_path):
    """"Only the stars" means the starred words are ranked and nothing else is — every other word
    becomes UNMATCHED, which already means "keeps its existing relative order, at the back"."""
    index = match.build_index(list_path, thresholds=match.marker_thresholds(SHIPPED),
                              only=["star"])
    assert set(index.rank_of) == {"アルマ", "本書"}
    assert "タニ" not in index.rank_of, "lopsided is not starred, so the star filter excludes it"
    assert "指差す" not in index.rank_of


def test_a_filter_of_several_markers_is_a_union_not_an_intersection(list_path):
    index = match.build_index(list_path, thresholds=match.marker_thresholds(SHIPPED),
                              only=["lopsided", "reading"])
    assert set(index.rank_of) == {"タニ", "本書", "指差す"}


def test_the_ranks_of_the_words_that_survive_a_filter_are_their_own_rows(list_path):
    """Filtering must not renumber anything. The rank IS the row index, and only the ORDER of the
    surviving words matters to the planner — which is exactly what a gapped index preserves."""
    index = match.build_index(list_path, thresholds=match.marker_thresholds(SHIPPED),
                              only=["star"])
    assert index.rank_of == {"アルマ": 0, "本書": 2}


def test_the_markers_of_every_word_are_available_even_under_a_filter(list_path):
    """The preview shows a marker column, and a word the filter pushed to the back should still show
    the marker it does carry — that IS the explanation for why it was left behind."""
    index = match.build_index(list_path, thresholds=match.marker_thresholds(SHIPPED),
                              only=["star"])
    assert index.marks_of["タニ"] == frozenset({"lopsided"})
    assert index.marks_of["指差す"] == frozenset({"reading"})
    assert index.marks_of["フェルト"] == frozenset()


def test_a_filtered_out_word_keeps_its_place_at_the_back(list_path):
    """The filter composing with what already exists, end to end through the planner: nothing is
    stranded, nothing is unpositioned, and the block is still contiguous from the old minimum."""
    rank_of = match.build_index(list_path, thresholds=match.marker_thresholds(SHIPPED),
                                only=["star"]).rank_of
    cards = [{"card_id": 10 + i, "due": 2800 + i, "type": 0, "queue": 0, "word": word,
              "deck": "TheBank"}
             # Mined in exactly the wrong order: the starred words are last in the queue today.
             for i, word in enumerate(["フェルト", "タニ", "指差す", "本書", "アルマ"])]
    writes, stats = plan_module.plan(cards, rank_of)

    order = [row.word for row in stats["order"]]
    assert order[:2] == ["アルマ", "本書"], "the starred words come first, in Surasura's order"
    assert order[2:] == ["フェルト", "タニ", "指差す"], \
        "everything else keeps the relative order it already had, at the back"
    assert stats["matched"] == 2 and stats["unmatched"] == 3
    positions = [row.position for row in stats["order"]]
    assert positions == list(range(2800, 2805)), "still one contiguous block from the old minimum"
    assert len(set(positions)) == len(positions), "no two cards may share a position"
    assert writes, "the starred words were at the back, so this must actually move something"


def test_an_unknown_marker_name_is_dropped_rather_than_widening_the_filter(list_path):
    """A typo must not silently become "everything" — that would reorder every card the user asked
    to leave alone. It is dropped here and refused by preflight, which names it."""
    assert match.normalize_markers(["star", "sparkle"]) == ("star",)
    assert match.unknown_markers(["star", "sparkle"]) == ["sparkle"]
    assert match.unknown_markers(["star", "reading"]) == []


def test_the_filter_accepts_the_shapes_a_settings_file_can_hold():
    """A list, a bare string, a set, `None`, junk. Normalised to a stable tuple in MARKERS order."""
    assert match.normalize_markers(None) == ()
    assert match.normalize_markers([]) == ()
    assert match.normalize_markers("star") == ("star",)
    assert match.normalize_markers({"reading", "star"}) == ("star", "reading")
    assert match.normalize_markers(["READING", " Star "]) == ("star", "reading")
    assert match.normalize_markers(42) == ()


# --- the tags ----------------------------------------------------------------------------------- #
def _note(word, tags=None):
    return {"fields": {"Expression": word, "Sentence": f"{word}を使った文。"},
            "tags": list(tags or [])}


def _marks_of(entries=REAL_ROWS):
    return {entry[0]: match.row_markers(_row(entry), match.marker_thresholds(SHIPPED))
            for entry in entries}


def _opts(**over):
    base = {"junban_tag": "Surasura", "junban_tag_markers": True}
    base.update(over)
    return touchup.options(base)


def test_marker_tags_are_ascii_and_hierarchical_under_the_configured_parent():
    """A tag has to be typable in Anki's search box. `tag:Surasura::✦` is miserable; the glyph
    belongs in the UI, and the tag stays plain letters under whatever parent the user named."""
    result = touchup.plan([(1, 500, "アルマ", 0), (2, 501, "タニ", 1)],
                          {500: _note("アルマ"), 501: _note("タニ")},
                          _opts(), marks_of=_marks_of())

    assert result["marker_tags"] == {"Surasura::☆": [500], "Surasura::⚖": [501]}
    for name in result["marker_tags"]:
        # NOT ascii any more — the user asked for the mark itself in the tag tree. What still
        # has to hold is that no leaf carries an invisible variation selector: verified live,
        # "Surasura::⚖" and "Surasura::⚖︎" round-trip as TWO SEPARATE TAGS.
        assert "︎" not in name and "️" not in name, f"{name} carries an invisible selector"
        assert name.startswith("Surasura::")


def test_the_parent_tag_is_whatever_the_user_named_it():
    result = touchup.plan([(1, 500, "アルマ", 0)], {500: _note("アルマ")},
                          _opts(junban_tag="流"), marks_of=_marks_of())
    assert result["marker_tags"] == {"流::☆": [500]}


def test_no_parent_tag_means_no_marker_tags():
    """They hang UNDER the plain tag. With no parent there is nowhere for them to go, and three
    loose `::☆` tags at the root of the sidebar would say nothing about who put them there."""
    result = touchup.plan([(1, 500, "アルマ", 0)], {500: _note("アルマ")},
                          _opts(junban_tag=""), marks_of=_marks_of())
    assert result["marker_tags"] == {}


def test_a_word_with_no_markers_gets_no_marker_tag():
    """38% of the live library. A `Surasura::` branch that tagged them anyway would say nothing."""
    result = touchup.plan([(1, 500, "フェルト", 0)], {500: _note("フェルト")},
                          _opts(), marks_of=_marks_of())
    assert result["marker_tags"] == {}
    assert result["counts"]["markers"] == 0
    assert result["tags"] == [500], "the plain tag still goes on — that card did move"


def test_a_word_with_two_markers_gets_both_tags():
    result = touchup.plan([(1, 500, "本書", 0)], {500: _note("本書")},
                          _opts(), marks_of=_marks_of())
    assert result["marker_tags"] == {"Surasura::☆": [500], "Surasura::文": [500]}
    assert result["counts"]["markers"] == 1, "one NOTE was marked, however many tags it took"


def test_marker_tags_are_off_unless_asked_for():
    result = touchup.plan([(1, 500, "アルマ", 0)], {500: _note("アルマ")},
                          _opts(junban_tag_markers=False), marks_of=_marks_of())
    assert result["marker_tags"] == {}
    assert result["tags"] == [500], "the plain tag is unaffected by the marker switch"


def test_a_tag_the_note_already_carries_is_not_recorded_again():
    """Anki ignores a duplicate `addTags`, but the snapshot would then promise to remove a tag the
    user put there themselves — and Restore would take it away."""
    result = touchup.plan([(1, 500, "アルマ", 0)],
                          {500: _note("アルマ", tags=["Surasura", "Surasura::☆"])},
                          _opts(), marks_of=_marks_of())
    assert result["marker_tags"] == {}
    assert result["tags"] == []


def test_a_word_the_marker_map_says_nothing_about_gets_no_marker_tag():
    """Empty state: an unmatched-but-moved word, or a list too old to carry the columns."""
    result = touchup.plan([(1, 500, "須藤", 0)], {500: _note("須藤")},
                          _opts(), marks_of={})
    assert result["marker_tags"] == {}
    result = touchup.plan([(1, 500, "須藤", 0)], {500: _note("須藤")},
                          _opts(), marks_of=None)
    assert result["marker_tags"] == {}


def test_marker_tag_refuses_to_build_a_name_it_does_not_recognise():
    assert touchup.marker_tag("Surasura", "star") == "Surasura::☆"
    assert touchup.marker_tag("Surasura", "sparkle") == ""
    assert touchup.marker_tag("", "star") == ""


def test_restricting_to_the_notes_that_actually_moved_narrows_the_marker_tags():
    """If Anki goes away halfway, a `Surasura::☆` on a card that never budged is a small lie the
    user cannot see. The snapshot still covers the superset, so the undo stays complete."""
    result = touchup.plan([(1, 500, "アルマ", 0), (2, 501, "タニ", 1)],
                          {500: _note("アルマ"), 501: _note("タニ")},
                          _opts(), marks_of=_marks_of())
    narrowed = touchup.restrict(result, {500})
    assert narrowed["marker_tags"] == {"Surasura::☆": [500]}


# --- the way back ------------------------------------------------------------------------------- #
def test_the_snapshot_records_which_note_got_which_marker_tag():
    """Each marker went on a different subset, so one flat list would not be enough to undo them:
    a restore has to take `Surasura::☆` off exactly the words that were starred, and never off a
    word junban only marked 📖."""
    path = undo.save([(1, 2800)], ["TheBank"],
                     marker_tags={"Surasura::☆": [500], "Surasura::文": [500, 502]})
    with open(path, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["marker_tags"] == {"Surasura::☆": [500], "Surasura::文": [500, 502]}

    loaded = undo.load()
    assert undo.restore_marker_tags(loaded) == {"Surasura::☆": [500],
                                                "Surasura::文": [500, 502]}
    assert undo.note_ids(loaded) == [500, 502], "notesInfo has to be asked for every marked note"


def test_a_run_with_no_marker_tags_writes_the_snapshot_it_always_did():
    """Additive, so an ordinary reorder's snapshot is byte-for-byte the shape earlier versions
    produced — a `SCHEMA` bump would make `restore_pairs` refuse every file already on disk."""
    path = undo.save([(1, 2800)], ["TheBank"])
    with open(path, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert "marker_tags" not in saved
    assert undo.restore_marker_tags(undo.load()) == {}


def test_a_note_that_has_gone_since_the_run_is_not_marked_for_untagging():
    """Deleted between the reorder and the restore. Writing to it by id is a write we cannot reason
    about, so it is dropped rather than attempted."""
    undo.save([(1, 2800)], ["TheBank"],
              marker_tags={"Surasura::☆": [500, 501]})
    assert undo.restore_marker_tags(undo.load(), existing_ids=[500]) == {"Surasura::☆": [500]}
    assert undo.restore_marker_tags(undo.load(), existing_ids=[]) == {}


def test_a_malformed_marker_section_never_quarantines_a_good_snapshot():
    """The positions are the part the user cannot reconstruct by hand. Losing them to a typo in an
    optional section would be the exact destruction this file exists to prevent."""
    path = undo.snapshot_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "scope": ["TheBank"], "cards": {"1789712080047": 2944},
                   "marker_tags": {"Surasura::☆": "not a list", "": [1], "ok": [500]}}, handle)

    loaded = undo.load()
    assert loaded is not None, "a good cards map must survive a broken marker section"
    assert loaded["cards"] == {"1789712080047": 2944}
    assert undo.restore_marker_tags(loaded) == {"ok": [500]}


def test_restrict_recomputes_the_counts_instead_of_carrying_them_over():
    """The counts used to pass through `restrict` untouched, so a run that intended 3 notes and
    moved 2 still reported 3 — and once a preview row could be deselected, the panel promised the
    same wrong number BEFORE the write. The preview is the only confirmation there is (I5), so a
    number in it that does not describe the run is the one thing it must not do.
    """
    touchups = {
        "fields": {500: {"Frequency": {"before": "", "after": "x"}},
                   501: {"Frequency": {"before": "", "after": "y"}},
                   502: {"FreqSort": {"before": "54614", "after": "3"}}},
        "tags": [500, 501, 502],
        "tag": "Surasura",
        "marker_tags": {"Surasura::☆": [500, 501], "Surasura::文": [502]},
        "counts": {"notes": 3, "tag": 3, "frequency": 2, "freqsort": 1, "markers": 3},
    }
    opts = {"frequency_field": "Frequency"}

    narrowed = touchup.restrict(touchups, {500}, opts)
    assert narrowed["counts"]["tag"] == 1
    assert narrowed["counts"]["notes"] == 1
    assert narrowed["counts"]["frequency"] == 1
    assert narrowed["counts"]["freqsort"] == 0, "502's sort-number edit was dropped with 502"
    assert narrowed["counts"]["markers"] == 1
    # ...and the narrowed plan agrees with its own counts, which is the real invariant.
    assert len(narrowed["tags"]) == narrowed["counts"]["tag"]
    assert len({n for ids in narrowed["marker_tags"].values() for n in ids}) \
        == narrowed["counts"]["markers"]


def test_restrict_leaves_the_field_counts_alone_when_it_cannot_tell_them_apart():
    """Without `opts` there is no way to know which field name was the frequency one. Guessing
    would be worse than saying nothing, so those two are left as they were."""
    touchups = {"fields": {500: {"Frequency": {"before": "", "after": "x"}}},
                "tags": [500, 501], "tag": "Surasura", "marker_tags": {},
                "counts": {"notes": 2, "tag": 2, "frequency": 1, "freqsort": 0, "markers": 0}}
    narrowed = touchup.restrict(touchups, {500})
    assert narrowed["counts"]["tag"] == 1, "the structural counts are still exact"
    assert narrowed["counts"]["frequency"] == 1, "unchanged rather than guessed"
