"""The importers' and Extract's window rules, Qt-free (W3.4 row 2; `app/importers_view.py`), and the numbers a
replacing import states before it runs (`anki_sync.dismissed_words` / `replaced_words` / `replace_numbers`, IK-18:
one rule for Anki's Replace, Migaku's and Jiten's — a clean slate from the source, past Graduates' words kept; the
dismissed words are dropped, counted for the confirmation, and kept by the dated backup).

What a wrong answer would cost: a confirmation whose numbers aren't what the write does (the user agrees to one thing
and gets another); a dismissed word lost with no backup holding it; an Import or Extract button live
when it can't do what it says (a deck with no field, a deck without the "I understand" tick); "done" said for a
child that failed.
"""
import json
import os

import pytest

from app import anki_db_import, anki_sync, extract, importers_view
from app.path_utils import get_user_files_path


def _known(words, language="ja"):
    folder = get_user_files_path(language)
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


def _backup_words(language="ja"):
    """The words of the one dated backup a replace made in the language's .trash."""
    trash = os.path.join(get_user_files_path(language), ".trash")
    names = [n for n in os.listdir(trash) if n.startswith("KnownWord.")]
    assert len(names) == 1
    with open(os.path.join(trash, names[0]), encoding="utf-8") as f:
        return json.load(f)["words"]


def test_dismissed_words_are_the_ignored_entries_the_import_doesnt_name():
    path = _known(CURRENT)
    dismissed = anki_sync.dismissed_words(path, "ja", INCOMING)
    assert [w["dictForm"] for w in dismissed] == ["えっと"]       # あの: the import names it, its entry wins


def test_dismissed_words_are_none_from_a_file_it_cannot_read(tmp_path):
    bad = tmp_path / "KnownWord.json"
    bad.write_text("{broken", encoding="utf-8")
    assert anki_sync.dismissed_words(str(bad), "ja", INCOMING) == []
    assert anki_sync.dismissed_words(str(tmp_path / "missing.json"), "ja", INCOMING) == []


def test_the_confirmation_numbers_are_what_the_replace_writes(tmp_path):
    """now → after, as Jiten's replace then writes it (the same words, the same kept ones, the same dropped)."""
    from app import jiten_converter
    path = _known(CURRENT)
    words = [dict(w) for w in INCOMING]
    now, after, graduated, ignored = anki_sync.replace_numbers("ja", words)
    assert words == INCOMING                                # read only: the caller's words are left as they are
    assert (now, graduated, ignored) == (2, 1, 1)
    cards = [{"wordText": "猫", "state": 5}, {"wordText": "犬", "state": 2}, {"wordText": "あの", "state": 5}]
    assert jiten_converter.replace_known(jiten_converter.words_from_cards(cards), "ja") is True
    assert anki_sync.count_known("ja") == after == 3       # 猫, あの, 旅


def test_one_rule_for_every_replace_drops_the_dismissed_words_and_counts_them():
    """IK-40 / IK-50, a clean slate by decision: Anki's Replace, Migaku's and Jiten's all write `replaced_words` — the
    new words, then past Graduates' kept known; the IGNORED entries are dropped (counted: the ones the new words don't
    name come back on the list; one they name is the new entry)."""
    path = _known(CURRENT)
    words = [dict(w) for w in INCOMING]
    final, graduated, dropped = anki_sync.replaced_words(path, "ja", words)
    assert [w["dictForm"] for w in final] == ["猫", "犬", "あの", "旅"]
    assert (graduated, dropped) == (1, 1)                    # えっと comes back on the list
    assert [w["knownStatus"] for w in final if w["dictForm"] == "あの"] == ["KNOWN"]   # never twice, the new one


def test_the_numbers_count_the_dismissed_words_dropped_and_none_when_there_are_none():
    _known(CURRENT)
    assert anki_sync.replace_numbers("ja", INCOMING)[3] == 1
    _known([w for w in CURRENT if w["knownStatus"] != "IGNORED"])
    assert anki_sync.replace_numbers("ja", INCOMING)[1:] == (3, 1, 0)   # the same known words after, none dropped


def test_the_rule_reads_chinese_words_the_same_way():
    # A Chinese list: 嗯 / 那个 dismissed, 那个 now known from the import; 学习 a past Graduate's word.
    path = _known([{"dictForm": "朋友", "knownStatus": "KNOWN", "hasCard": 1},
                   {"dictForm": "学习", "knownStatus": "KNOWN", "source": "GraduatedList"},
                   {"dictForm": "嗯", "knownStatus": "IGNORED", "hasCard": 0},
                   {"dictForm": "那个", "knownStatus": "IGNORED", "hasCard": 0}], "zh")
    incoming = [{"dictForm": "那个", "knownStatus": "KNOWN"}, {"dictForm": "喜欢", "knownStatus": "KNOWN"}]
    final, graduated, dropped = anki_sync.replaced_words(path, "zh", [dict(w) for w in incoming])
    assert [w["dictForm"] for w in final] == ["那个", "喜欢", "学习"] and (graduated, dropped) == (1, 1)
    assert anki_sync.replace_numbers("zh", incoming) == (2, 3, 1, 1)


def test_the_numbers_with_no_known_words_file_start_at_zero():
    now, after, graduated, ignored = anki_sync.replace_numbers("ja", INCOMING)
    assert (now, after, graduated, ignored) == (0, 2, 0, 0)


def test_migakus_plan_reads_its_export_and_states_both_numbers(ja_resources_dir):
    from app import migaku_converter
    _known(CURRENT)
    db = os.path.join(ja_resources_dir, "MigakuDb.db")
    plan = importers_view.migaku_plan(db, "ja")
    assert plan.words == len(migaku_converter.read_words(db, "ja")) > 0
    assert plan.now == 2 and plan.after > 0 and plan.graduated in (0, 1)
    assert plan.ignored == 1            # えっと dropped; あの is in the export, so Migaku's own entry wins (IK-50)
    assert plan.saved is not None


def test_a_migaku_replace_drops_the_dismissed_words_migaku_doesnt_have_and_writes_what_it_stated(ja_resources_dir):
    """IK-50, a clean slate by decision: Migaku's replace drops every IGNORED entry Migaku doesn't have, like Jiten's
    and Anki's; the dated backup keeps them, and the confirmation's numbers are the write's."""
    from app import migaku_converter
    _known(CURRENT)
    db = os.path.join(ja_resources_dir, "MigakuDb.db")
    plan = importers_view.migaku_plan(db, "ja")
    assert migaku_converter.convert_db_to_json(db, language="ja") is True
    with open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), encoding="utf-8") as f:
        written = json.load(f)["words"]
    assert not [w for w in written if w["dictForm"] == "えっと"]
    assert len([w for w in written if w["dictForm"] == "あの"]) == 1       # Migaku's own entry, once
    assert anki_sync.count_known("ja") == plan.after
    assert _backup_words() == CURRENT                                     # えっと kept by the backup


def test_a_jiten_replace_drops_the_dismissed_words_and_its_backup_keeps_them():
    """Jiten's replace, the same rule: えっと / あの dismissed — えっと (Jiten doesn't name it) is gone, あの is Jiten's
    known word; 旅 (a past Graduate's) stays known; the backup holds the old list whole."""
    from app import jiten_converter
    _known(CURRENT)
    cards = [{"wordText": "猫", "state": 5}, {"wordText": "あの", "state": 5}]
    words = jiten_converter.words_from_cards(cards)
    assert jiten_converter.replace_known(words, "ja", expect=anki_sync.replace_numbers("ja", words)) is True
    with open(os.path.join(get_user_files_path("ja"), "KnownWord.json"), encoding="utf-8") as f:
        written = json.load(f)
    assert [(w["dictForm"], w["knownStatus"]) for w in written["words"]] == [("猫", "KNOWN"), ("あの", "KNOWN"),
                                                                             ("旅", "KNOWN")]
    assert written["statistics"]["ignoredWords"] == 0 and written["statistics"]["totalWords"] == 3
    assert _backup_words() == CURRENT


def test_jitens_plan_reads_the_kept_cards_and_none_when_unreadable(tmp_path):
    _known(CURRENT)
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps([{"wordText": "猫", "state": 5}], ensure_ascii=False), encoding="utf-8")
    plan = importers_view.jiten_plan(str(cards), "ja")
    assert (plan.words, plan.now, plan.ignored, plan.graduated) == (1, 2, 2, 1)   # えっと and あの come back
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
    anki_sync.replace_numbers("ja", words)
    assert words[0] == {"dictForm": "旅", "knownStatus": "UNKNOWN"}   # kept_graduated raises in place: on a copy


def test_a_failed_child_is_never_done_even_with_a_result_line():
    assert importers_view.deck_outcome(1, {"added": 3, "raised": 0, "total": 9}, "why")[0] == "failed"


def test_a_known_words_import_never_runs_beside_a_sync_and_extract_beside_generate():
    from app.services import jobs
    assert jobs.conflicts("known-import", "anki-sync") and jobs.conflicts("known-import", "known-import")
    assert not jobs.conflicts("extract", "generate") and jobs.conflicts("extract", "extract")


# --- AD2-1: the plans refuse a known-words file that can't be read, before anything is confirmed #
def test_both_plans_refuse_a_known_words_file_that_cant_be_read(ja_resources_dir, tmp_path):
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write('{"words": "冒険"}')
    with pytest.raises(importers_view.KnownUnreadable):
        importers_view.migaku_plan(os.path.join(ja_resources_dir, "MigakuDb.db"), "ja")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps([{"wordText": "猫", "state": 5}], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(importers_view.KnownUnreadable):
        importers_view.jiten_plan(str(cards), "ja")


def test_a_missing_known_words_file_is_no_refusal(ja_resources_dir):
    # A first import has no file at all: nothing to keep, nothing refused.
    assert importers_view.migaku_plan(os.path.join(ja_resources_dir, "MigakuDb.db"), "ja").now == 0


def test_a_replace_that_found_its_numbers_moved_is_its_own_end():
    assert importers_view.replace_outcome(anki_sync.EXIT_CHANGED, None)[0] == "changed"
    assert importers_view.expect_arg(importers_view.Plan("p", 3, 2, 5, 1, 0, None)) == "2,5,1,0"


# --- IK-59: the window decides nothing --------------------------------------------------------------------------- #
def test_the_split_value_follows_the_method_as_the_tk_window_did():
    # By length: a pattern in the field gives way to the saved length; by pattern: an empty or digit field to the default.
    assert importers_view.split_value(True, r"\n\d+\n", "1500") == "1500"
    assert importers_view.split_value(True, "800", "1500") is None             # a length stays
    assert importers_view.split_value(False, "800", "1500") == extract.DEFAULT_DELIMITER
    assert importers_view.split_value(False, "", "1500") == extract.DEFAULT_DELIMITER
    assert importers_view.split_value(False, "第.章", "1500") is None           # a pattern stays


def test_extract_picks_a_decks_sentence_or_expression_field_only():
    assert importers_view.extract_field(["Expression", "Sentence", "Meaning"]) == "Sentence"
    assert importers_view.extract_field(["Expression", "Meaning"]) == "Expression"
    assert importers_view.extract_field(["Front", "Back"]) is None             # the Tk window chose these two only


# --- the round-2 mutant pass's survivors ------------------------------------------------------------------------ #
def test_the_numbers_count_the_file_asked_for_not_the_languages_default(tmp_path):
    """A replace into another file (the command line's out_file) checks its --expect against that file's count."""
    _known(CURRENT)                                          # the default file: 2 known
    other = tmp_path / "KnownWord.json"
    other.write_text(json.dumps({"words": [{"dictForm": "冒険", "knownStatus": "KNOWN", "hasCard": 1}]},
                                ensure_ascii=False), encoding="utf-8")
    assert anki_sync.replace_numbers("ja", INCOMING, str(other))[0] == 1
    assert anki_sync.replace_numbers("ja", INCOMING)[0] == 2
