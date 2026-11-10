# SPDX-License-Identifier: GPL-3.0-or-later
"""WP-M — the two orders: the journey, or raw leverage.

Surasura computes two orderings of the same library and they are **genuinely different**, which is
the whole reason this package exists:

  * `priority_learning_list.csv` — row order is leverage. Measured on the live library its rank-0
    word (アルマ) is not encountered until **file #148**.
  * `progressive_learning_list.csv` — row order is file order (the manifest's study order), then
    within-file score. Literally "in the order you will meet it". Its first three words come from
    **file #1** and carry priority ranks 350, 897 and 981.

Content order is the **default**, by the user's decision. Priority order stays as an option, because
it is what a leverage-first learner wants. Both files name a word the same way — `Word` plus `Orth`,
pinned by `tests/test_orth_column.py::test_both_output_lists_name_a_word_the_same_way` — so content
mode keeps the 20.6% orthBase matching gain rather than falling back to the lemma.

The fixture below is that shape in miniature, with the real words the evidence names. The fake
collection and the settings shape come from `test_reposition` deliberately: a second copy of the
wire would be a second implementation of it, free to disagree with the one the rest of the suite
checks against.
"""
import csv
import json
import os

import pytest

from modules.junban import match, reposition
from modules.junban.tests.test_reposition import (FIRST_CARD, FIRST_NOTE, FakeCollection, URL,
                                                  _card, _note, _patched, _settings)

# --- the fixture library ------------------------------------------------------------------------ #
# The live library's actual head, in miniature. アルマ/ルッツ/マイン really are priority ranks 0/1/2
# (spec §13 #9 — no proper-noun filter, by decision §15 Q2), and スタ/寄り/延々 really are the first
# three rows of the progressive list, all from file #1.
PRIORITY_ORDER = [
    ("アルマ", "アルマ"),
    ("ルッツ", "ルッツ"),
    ("マイン", "マイン"),
    ("スドウ", "須藤"),      # the lemma is katakana; the show writes 須藤 — anki_miner's mined_form
    ("スタ", "スタ"),
    ("寄り", "寄り"),
    ("延々", "延々"),
]

# (source file, word, orth). File 1 first, then file 2, then the file where アルマ is finally met —
# standing in for the live library's file #148.
PROGRESSIVE_ORDER = [
    ("01 - 忠犬ハチ公.txt", "スタ", "スタ"),
    ("01 - 忠犬ハチ公.txt", "寄り", "寄り"),
    ("01 - 忠犬ハチ公.txt", "延々", "延々"),
    ("02 - 本好きの下剋上.txt", "ルッツ", "ルッツ"),
    ("02 - 本好きの下剋上.txt", "スドウ", "須藤"),
    ("148 - BOM Mosiah_18.txt", "アルマ", "アルマ"),
    # The 3-in-3,560 case: a word met again in a later file. The FIRST sighting is the one that
    # counts, because that is when the learner actually needs it.
    ("148 - BOM Mosiah_18.txt", "スタ", "スタ"),
    ("148 - BOM Mosiah_18.txt", "マイン", "マイン"),
]


def _results_dir(tmp_path):
    path = os.path.join(str(tmp_path), "results")
    os.makedirs(path, exist_ok=True)
    return path


def _write_priority(tmp_path, rows=None):
    """`priority_learning_list.csv` — `Occurrences`, and no `Source File`."""
    path = os.path.join(_results_dir(tmp_path), reposition.PRIORITY_CSV_NAME)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Reading", "Tier", "Score", "Occurrences",
                         "Count (High)", "Count (Low)", "Count (Goal)", "Modality"])
        for word, orth in (PRIORITY_ORDER if rows is None else rows):
            writer.writerow([word, orth, "", "Outside", 100, 40, 0, 40, 0, ""])
    return path


def _write_progressive(tmp_path, rows=None):
    """`progressive_learning_list.csv` — `Occurrences (Global)`, and a `Source File` per row."""
    path = os.path.join(_results_dir(tmp_path), reposition.PROGRESSIVE_CSV_NAME)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Sequence", "Source File", "Word", "Orth", "Reading", "Tier", "Score",
                         "Occurrences (Global)", "Occurrences (File)", "Count (High)",
                         "Count (Low)", "Count (Goal)", "Modality"])
        for index, (source, word, orth) in enumerate(
                PROGRESSIVE_ORDER if rows is None else rows, start=1):
            writer.writerow([index, source, word, orth, "", "Outside", 100, 40, 4, 0, 40, 0, ""])
    return path


@pytest.fixture
def both_lists(tmp_path):
    """Both files in the sandboxed `results/`, so a run can choose either one."""
    return _write_priority(tmp_path), _write_progressive(tmp_path)


# --- the index, per order ----------------------------------------------------------------------- #
def test_both_files_load_and_produce_a_rank_index(both_lists):
    priority, progressive = both_lists
    assert match.load_rank_index(priority), "the priority list must still index"
    assert match.load_rank_index(progressive), "the progressive list must index the same way"


def test_priority_mode_reproduces_todays_order_exactly(both_lists):
    """The regression guard on the default change: switching the default to content order must not
    have altered what `priority` does by so much as one rank."""
    priority, _progressive = both_lists
    index = match.load_rank_index(priority)
    assert index["アルマ"] == 0
    assert index["ルッツ"] == 1
    assert index["マイン"] == 2
    assert index["スタ"] == 4, "スタ sits well down the leverage list"


def test_content_mode_ranks_a_file_one_word_above_a_high_leverage_word_met_much_later(both_lists):
    """The evidence, in one assertion. アルマ is the single highest-leverage word in the library and
    is not met until file #148; スタ is met in file #1. Under "as I'll meet it" スタ comes first,
    which is the entire point of the option."""
    _priority, progressive = both_lists
    index = match.load_rank_index(progressive)
    assert index["スタ"] == 0
    assert index["アルマ"] == 5
    assert index["スタ"] < index["アルマ"]

    leverage = match.load_rank_index(_priority)
    assert leverage["アルマ"] < leverage["スタ"], "the two orders genuinely disagree"


def test_the_first_occurrence_of_a_word_wins(both_lists):
    """A word that appears under two files is ranked where it is FIRST met. Measured at 3 of 3,560
    words on the live library, so it is rare — and unambiguous when it happens."""
    _priority, progressive = both_lists
    index = match.load_rank_index(progressive)
    assert index["スタ"] == 0, "row 6 must not overwrite row 0's rank"


def test_orth_is_the_key_in_both_modes(both_lists):
    """20.6% of mined words can only ever match through the orth: anki_miner writes 須藤 onto the
    card while Surasura's lemma is スドウ. Losing that in one mode would make the same backlog match
    in one order and silently fail in the other."""
    priority, progressive = both_lists
    for path in (priority, progressive):
        index = match.load_rank_index(path)
        assert "須藤" in index, f"the orth key is missing from {os.path.basename(path)}"
        assert "スドウ" in index, "the lemma stays a key too, for anything unconjugated"
        assert index["須藤"] == index["スドウ"], "both spellings are the same word, at one rank"


def test_a_progressive_list_with_no_orth_column_still_loads(tmp_path):
    """Backward compatibility: a results folder written before the column existed matches on the
    lemma alone rather than yielding nothing."""
    path = os.path.join(_results_dir(tmp_path), reposition.PROGRESSIVE_CSV_NAME)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Sequence", "Source File", "Word", "Occurrences (Global)"])
        writer.writerow([1, "01.txt", "スタ", 40])
    assert match.load_rank_index(path) == {"スタ": 0}


def test_an_empty_progressive_list_yields_an_empty_index(tmp_path):
    """Empty state: an analysis that produced a header and no rows. Not an error — every card is
    simply unmatched and keeps its place."""
    path = os.path.join(_results_dir(tmp_path), reposition.PROGRESSIVE_CSV_NAME)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write("Sequence,Source File,Word,Orth\n")
    assert match.load_rank_index(path) == {}


# --- which file a run reads --------------------------------------------------------------------- #
def test_the_order_decides_which_file_is_read(both_lists):
    priority, progressive = both_lists
    assert reposition.order_csv_path(_settings(junban_order="priority")) == priority
    assert reposition.order_csv_path(_settings(junban_order="content")) == progressive


def test_content_is_the_shipped_default(both_lists):
    """The user's decision, pinned where a future edit would have to notice it."""
    import modules.junban as junban
    assert junban.SETTINGS_DEFAULTS["junban_order"] == "content"
    _priority, progressive = both_lists
    settings = _settings()
    settings.pop("junban_order")                # as a profile that predates the setting would load
    assert reposition.order_csv_path(settings) == progressive


# --- preflight ---------------------------------------------------------------------------------- #
@pytest.fixture
def collection():
    """Four new cards, one per real word, mined in an order that matches neither list."""
    words = ["アルマ", "スタ", "ルッツ", "寄り"]
    cards, notes = [], []
    for index, word in enumerate(words):
        note_id = FIRST_NOTE + index
        notes.append(_note(note_id, word))
        cards.append(_card(FIRST_CARD + index, note_id, 2800 + index))
    return FakeCollection(cards, notes)


def test_a_missing_progressive_list_degrades_with_a_clear_problem(tmp_path, collection):
    """Content order with no content list: the user is told which list is missing and what to do,
    and NOT told about the other file, which they never chose. A traceback here would land in front
    of a collection write."""
    _write_priority(tmp_path)                   # the other list exists — this must not rescue it
    assert not os.path.isfile(os.path.join(_results_dir(tmp_path),
                                           reposition.PROGRESSIVE_CSV_NAME))

    with _patched(collection):
        checks = reposition.preflight(_settings(junban_order="content"))

    assert checks["ok"] is False
    assert any("progressive_learning_list.csv" in problem for problem in checks["problems"]), \
        checks["problems"]
    assert any("run an analysis" in problem for problem in checks["problems"])


def test_a_missing_progressive_list_never_raises_from_the_preview(tmp_path, collection):
    """`dry_run` reads the list directly, without preflight. An absent file must never raise — the panel calls both.
    M-W2-1: nor does it read as "nothing matched" any more — with 順's actions on, that plan put every card away — but
    as no list (`match.build_index`: no file, no rows): nothing to write or put away. (A run never gets here: preflight
    refuses a missing list first.)"""
    _write_priority(tmp_path)
    with _patched(collection):
        writes, stats = reposition.dry_run(_settings(junban_order="content"))
    assert writes == [] and stats["to_write"] == 0 and stats["matched"] == 0
    assert stats.get("empty_list") and not stats.get("problems")


def test_a_missing_priority_list_still_names_the_priority_list(tmp_path, collection):
    """The other half of the same gate, unchanged from before WP-M."""
    _write_progressive(tmp_path)
    with _patched(collection):
        checks = reposition.preflight(_settings(junban_order="priority"))
    assert checks["ok"] is False
    assert any("priority learning list" in problem for problem in checks["problems"])


def test_an_order_this_version_does_not_know_is_refused(tmp_path, collection):
    """A typo must not quietly pick one. The two orders put genuinely different words at the front
    of the queue, and the write syncs to AnkiWeb with no Anki-side undo."""
    _write_priority(tmp_path)
    _write_progressive(tmp_path)
    with _patched(collection):
        checks = reposition.preflight(_settings(junban_order="whatever"))
    assert checks["ok"] is False
    assert any("whatever" in problem for problem in checks["problems"])


def test_an_unknown_marker_name_is_refused_rather_than_silently_ignored(tmp_path, collection):
    """A filter that matched nothing would be indistinguishable from no filter at all — and would
    reorder every card the user asked to leave alone."""
    _write_priority(tmp_path)
    _write_progressive(tmp_path)
    with _patched(collection):
        checks = reposition.preflight(_settings(junban_only_markers=["star", "sparkle"]))
    assert checks["ok"] is False
    assert any("sparkle" in problem for problem in checks["problems"])


def test_a_valid_marker_filter_passes_preflight(tmp_path, collection):
    _write_priority(tmp_path)
    _write_progressive(tmp_path)
    with _patched(collection):
        checks = reposition.preflight(_settings(junban_only_markers=["star", "reading"]))
    assert checks["ok"] is True, checks["problems"]


def test_the_staleness_warning_is_about_the_list_this_run_actually_reads(tmp_path, collection):
    """Checking the priority list's timestamp while ordering by the progressive one would report the
    staleness of a file this run never opened — and stay silent about the one it did."""
    _write_priority(tmp_path)
    progressive = _write_progressive(tmp_path)
    manifest = os.path.join(str(tmp_path), "User Files", "ja", "master_manifest.json")
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, "w", encoding="utf-8") as handle:
        json.dump({"phases": {"HighPriority": []}}, handle)
    newer = os.path.getmtime(progressive) + 60
    os.utime(manifest, (newer, newer))

    with _patched(collection):
        checks = reposition.preflight(_settings(junban_order="content"))
    assert checks["ok"] is True, "a stale list warns, it never blocks (spec §15 #5)"
    assert any("changed since the last analysis" in warning for warning in checks["warnings"])


# --- end to end --------------------------------------------------------------------------------- #
def test_the_two_orders_produce_different_queues_from_the_same_backlog(both_lists, collection):
    """The claim the feature makes, on the wire. Same cards, same collection, two orders — and the
    card at the front is a different card."""
    with _patched(collection):
        _writes, content = reposition.dry_run(_settings(junban_order="content"))
    with _patched(collection):
        _writes, leverage = reposition.dry_run(_settings(junban_order="priority"))

    content_words = [row.word for row in content["order"] if row.rank is not None]
    leverage_words = [row.word for row in leverage["order"] if row.rank is not None]

    assert content_words[0] == "スタ", "content order starts with the word from file #1"
    assert leverage_words[0] == "アルマ", "leverage order starts with the highest-leverage word"
    assert content_words != leverage_words
    assert sorted(content_words) == sorted(leverage_words), "the same cards, in a different order"


def test_the_preview_says_which_order_it_is_of(both_lists, collection):
    """The preview is the only confirmation (I5), so it has to carry the order it was taken under —
    the panel gates Reorder on exactly this."""
    with _patched(collection):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    assert stats["order_mode"] == "content"
    with _patched(collection):
        _writes, stats = reposition.dry_run(_settings(junban_order="priority"))
    assert stats["order_mode"] == "priority"


def test_a_marker_filter_leaves_the_excluded_cards_unmatched_at_the_back(both_lists, collection):
    """Through the whole engine: the fixture's words are all starred, so filtering to ⚖ alone leaves
    every one of them unmatched — and unmatched already means "keeps its place, at the back".
    Nothing is stranded and no card is left without a position."""
    with _patched(collection):
        writes, stats = reposition.dry_run(_settings(junban_order="content",
                                                     junban_only_markers=["lopsided"]))
    assert stats["matched"] == 0
    assert stats["unmatched"] == stats["considered"] == 4
    assert writes == [], "they were already in their existing relative order, so nothing moves"
    positions = [row.position for row in stats["order"]]
    assert positions == list(range(2800, 2804)), "still one contiguous block from the old minimum"
    assert stats["only_markers"] == ["lopsided"]


def test_a_filtered_run_still_orders_the_words_that_do_qualify(both_lists, collection):
    """The other half: with the filter matching, the run behaves exactly as an unfiltered one."""
    with _patched(collection):
        filtered = reposition.dry_run(_settings(junban_order="content",
                                                junban_only_markers=["star"]))[1]
    with _patched(collection):
        plain = reposition.dry_run(_settings(junban_order="content"))[1]
    assert [row.word for row in filtered["order"]] == [row.word for row in plain["order"]]


def test_the_preview_carries_the_markers_of_every_word_it_lists(both_lists, collection):
    """The preview's marker column. Every fixture word is starred (40 occurrences, all Low), so the
    map has to answer for each of them rather than only for the ones a filter kept."""
    with _patched(collection):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    marks = stats["marks"]
    assert marks["スタ"] == frozenset({"star"})
    assert marks["アルマ"] == frozenset({"star"})


def test_the_order_setting_does_not_leak_between_runs(both_lists, collection):
    """`junban_only_markers` is a container, so after `settings_manager`'s shallow merge it can be
    the very object inside SETTINGS_DEFAULTS (spec §13 #12). Nothing downstream may hold it."""
    import modules.junban as junban
    settings = _settings(junban_only_markers=junban.SETTINGS_DEFAULTS["junban_only_markers"])
    with _patched(collection):
        _writes, stats = reposition.dry_run(settings)
    stats["only_markers"].append("star")
    assert junban.SETTINGS_DEFAULTS["junban_only_markers"] == []
