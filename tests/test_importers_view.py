"""The importers' and Extract's window rules, Qt-free (W3.4 row 2; `app/importers_view.py`), and the numbers a
replacing import states before it runs (`anki_sync.kept_ignored` / `replace_numbers`, IK-18, W3.4-1).

What a wrong answer would cost: a confirmation whose numbers aren't what the write does (the user agrees to one thing
and gets another); a dismissed word that comes back as new after Jiten's replace; an Import or Extract button live
when it can't do what it says (a deck with no field, a deck without the "I understand" tick); "done" said for a
child that failed.
"""
import json
import os

import pytest

from app import anki_db_import, anki_sync, extract, importers_view
from app.path_utils import get_user_files_path


def _known(words):
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": words}, f, ensure_ascii=False)
    return path


CURRENT = [
    {"dictForm": "冒険", "knownStatus": "KNOWN", "hasCard": 1},
    {"dictForm": "旅", "knownStatus": "KNOWN", "source": "GraduatedList"},
    {"dictForm": "えっと", "knownStatus": "IGNORED", "hasCard": 0},
    {"dictForm": "あの", "knownStatus": "IGNORED", "hasCard": 0},
]
INCOMING = [{"dictForm": "猫", "knownStatus": "KNOWN"}, {"dictForm": "犬", "knownStatus": "LEARNING"},
            {"dictForm": "あの", "knownStatus": "KNOWN"}]


def test_kept_ignored_keeps_the_dismissed_words_the_import_doesnt_name():
    path = _known(CURRENT)
    kept = anki_sync.kept_ignored(path, "ja", INCOMING)
    assert [w["dictForm"] for w in kept] == ["えっと"]       # あの: the import names it, its entry wins


def test_kept_ignored_keeps_none_from_a_file_it_cannot_read(tmp_path):
    bad = tmp_path / "KnownWord.json"
    bad.write_text("{broken", encoding="utf-8")
    assert anki_sync.kept_ignored(str(bad), "ja", INCOMING) == []
    assert anki_sync.kept_ignored(str(tmp_path / "missing.json"), "ja", INCOMING) == []


def test_the_confirmation_numbers_are_what_the_replace_writes(tmp_path):
    """now → after, as Jiten's replace then writes it (the same words, the same kept ones)."""
    from app import jiten_converter
    path = _known(CURRENT)
    words = [dict(w) for w in INCOMING]
    now, after, graduated, ignored = anki_sync.replace_numbers("ja", words, keep_ignored=True)
    assert words == INCOMING                                # read only: the caller's words are left as they are
    assert (now, graduated, ignored) == (2, 1, 1)
    cards = [{"wordText": "猫", "state": 5}, {"wordText": "犬", "state": 2}, {"wordText": "あの", "state": 5}]
    assert jiten_converter.replace_known(jiten_converter.words_from_cards(cards), "ja") is True
    assert anki_sync.count_known("ja") == after == 3       # 猫, あの, 旅


def test_without_keeping_ignored_words_the_numbers_say_none_kept():
    _known(CURRENT)
    assert anki_sync.replace_numbers("ja", INCOMING)[3] == 0


def test_the_numbers_with_no_known_words_file_start_at_zero():
    now, after, graduated, ignored = anki_sync.replace_numbers("ja", INCOMING, keep_ignored=True)
    assert (now, after, graduated, ignored) == (0, 2, 0, 0)


def test_migakus_plan_reads_its_export_and_states_both_numbers(ja_resources_dir):
    from app import migaku_converter
    _known(CURRENT)
    db = os.path.join(ja_resources_dir, "MigakuDb.db")
    plan = importers_view.migaku_plan(db, "ja")
    assert plan.words == len(migaku_converter.read_words(db, "ja")) > 0
    assert plan.now == 2 and plan.after > 0 and plan.graduated in (0, 1) and plan.ignored == 0
    assert plan.saved is not None


def test_jitens_plan_reads_the_kept_cards_and_none_when_unreadable(tmp_path):
    _known(CURRENT)
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps([{"wordText": "猫", "state": 5}], ensure_ascii=False), encoding="utf-8")
    plan = importers_view.jiten_plan(str(cards), "ja")
    assert (plan.words, plan.now, plan.ignored, plan.graduated) == (1, 2, 2, 1)
    cards.write_text("[broken", encoding="utf-8")
    assert importers_view.jiten_plan(str(cards), "ja") is None


# --- the buttons ------------------------------------------------------------------------------------------------- #
DECK = anki_db_import.Deck(["Sentence", "Meaning"], 12, {"Sentence": "猫が好き", "Meaning": ""}, "Sentence")


def test_import_needs_a_read_deck_one_of_its_fields_and_nothing_running():
    assert importers_view.can_import_deck("C:/decks/日本語.apkg", DECK, "Sentence", False)
    assert not importers_view.can_import_deck("C:/decks/日本語.apkg", None, "Sentence", False)
    assert not importers_view.can_import_deck("C:/decks/日本語.apkg", DECK, "Audio", False)
    assert not importers_view.can_import_deck("C:/decks/日本語.apkg", DECK, "", False)
    assert not importers_view.can_import_deck("C:/decks/日本語.apkg", DECK, "Sentence", True)
    assert not importers_view.can_import_deck("C:/books/旅.epub", DECK, "Sentence", False)


def test_extract_needs_a_file_and_a_name_and_a_deck_its_field_and_the_tick():
    assert importers_view.can_extract("C:/books/旅.epub", "旅", "", False, False)
    assert not importers_view.can_extract("C:/books/旅.epub", "  ", "", False, False)
    assert not importers_view.can_extract("", "旅", "", False, False)
    assert not importers_view.can_extract("C:/books/旅.epub", "旅", "", False, True)
    assert not importers_view.can_extract("C:/d/日本語.apkg", "デッキ", "Sentence", False, False, DECK)
    assert not importers_view.can_extract("C:/d/日本語.apkg", "デッキ", "", True, False, DECK)
    assert importers_view.can_extract("C:/d/日本語.apkg", "デッキ", "Sentence", True, False, DECK)


def test_the_default_name_is_the_files_own():
    assert importers_view.default_name("C:/books/吾輩は猫である.epub") == "吾輩は猫である"
    assert importers_view.default_name("") == ""


def test_an_error_line_gives_its_reason_and_other_lines_none():
    assert importers_view.error_of("Error: Invalid API key.") == "Invalid API key."
    assert importers_view.error_of("SQLite error: file is not a database") == "file is not a database"
    assert importers_view.error_of("Found 120 words") is None


# --- what a child's end means ------------------------------------------------------------------------------------ #
def test_the_deck_imports_end_follows_its_exit_code_and_result():
    assert importers_view.deck_outcome(0, {"added": 3, "raised": 1, "total": 9}, None) == \
        ("done", {"added": 3, "raised": 1, "total": 9})
    assert importers_view.deck_outcome(0, {"added": 0, "raised": 0, "total": 9}, None) == ("nothing", {})
    assert importers_view.deck_outcome(0, None, None)[0] == "failed"          # exit 0 with no result: not done
    assert importers_view.deck_outcome(5, None, "held")[1] == {"why": "held"}


def test_a_replaces_end_is_decided_by_its_exit_code():
    assert importers_view.replace_outcome(0, None) == ("done", {})
    assert importers_view.replace_outcome(1, "Invalid API key.") == ("failed", {"why": "Invalid API key."})
    assert importers_view.replace_outcome(None, None)[0] == "failed"         # never started


@pytest.mark.parametrize("result, key", [
    (extract.Result(0, 4, "旅", "soon", True, None), "done"),
    (extract.Result(0, 4, "旅", None, False, None), "processed"),
    (extract.Result(3, 4, "旅", "soon", False, "store"), "processed-only"),
    (extract.Result(2, 0, "旅", "soon", False, "taken"), "taken"),
    (extract.Result(2, 0, None, "soon", False, "name"), "name"),
    (extract.Result(1, 0, "旅", "soon", False, "empty"), "empty"),
    (extract.Result(1, 0, "旅", "soon", False, "read"), "failed"),
    (None, "failed"),
])
def test_extracts_end_names_what_happened(result, key):
    assert importers_view.extract_outcome(result.code if result else 1, result, "why")[0] == key


# --- the mutant pass's survivors --------------------------------------------------------------------------------- #
def test_the_numbers_never_change_the_words_they_count():
    _known(CURRENT)
    words = [{"dictForm": "旅", "knownStatus": "UNKNOWN"}, {"dictForm": "猫", "knownStatus": "KNOWN"}]
    anki_sync.replace_numbers("ja", words, keep_ignored=True)
    assert words[0] == {"dictForm": "旅", "knownStatus": "UNKNOWN"}   # kept_graduated raises in place: on a copy


def test_a_failed_child_is_never_done_even_with_a_result_line():
    assert importers_view.deck_outcome(1, {"added": 3, "raised": 0, "total": 9}, "why")[0] == "failed"


def test_a_known_words_import_never_runs_beside_a_sync_and_extract_beside_generate():
    from app.services import jobs
    assert jobs.conflicts("known-import", "anki-sync") and jobs.conflicts("known-import", "known-import")
    assert not jobs.conflicts("extract", "generate") and jobs.conflicts("extract", "extract")
