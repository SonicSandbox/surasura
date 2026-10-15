"""The .apkg known-words import, Qt-free (W3.4 row 2; `app/anki_db_import.py`): the merge the Tk window's
`update_known_words` did, with the data-safety floor raised, and the child the Qt window starts.

What a wrong answer would cost: the user's known words — a file we can't read replaced by a deck-only list; an
ignored word raised to known; Migaku's header or the list's order lost; half a file after a crash; a replace with no
dated copy kept (CLAUDE.md §4); a write beside the Anki sync's (two writers of KnownWord.json); a window that freezes
while a big deck is tokenized (the child's job).

Real data: the Migaku export `tests/Test Resources/ja/KnownWord.json` (one entry per status) and the real decks
`testAnki.apkg` / `ankiTest3.apkg` (inventory §2.4 rows, each a test).
"""
import json
import os
import re
from unittest import mock

import pytest

from app import anki_db_import, anki_sync
from app.path_utils import get_user_files_path
from tests.test_cli_locks import Holder


def _known():
    return os.path.join(get_user_files_path("ja"), "KnownWord.json")


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _load():
    with open(_known(), encoding="utf-8") as f:
        return json.load(f)


def _trash():
    folder = os.path.join(get_user_files_path("ja"), ".trash")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


@pytest.fixture
def migaku_file(ja_resources_dir):
    """A slice of the real Migaku export — one entry per status — in the sandboxed User Files/ja/."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    picked = {}
    for w in data["words"]:
        picked.setdefault(w["knownStatus"], w)
    data["words"] = [picked[s] for s in ("KNOWN", "LEARNING", "UNKNOWN", "IGNORED")]
    data["databaseFile"] = "C:/Users/someone/Downloads/migaku.db"
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    with open(_known(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _key(w):
    return (w["dictForm"], w.get("secondary", ""))


# --- the merge (inventory §2.4) ------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("content", ['{"words": [{"dictForm": "冒険"', '"冒険"', '{"words": "冒険"}'])
def test_a_known_words_file_it_cannot_read_is_never_replaced(content):
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    with open(_known(), "w", encoding="utf-8") as f:
        f.write(content)
    merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    assert merge.error and not merge.busy
    assert _bytes(_known()) == content.encode("utf-8")
    assert _trash() == []                                   # refused before any backup: nothing touched


def test_ignored_words_stay_ignored_and_learning_or_unknown_ones_are_raised(migaku_file):
    by = {w["knownStatus"]: _key(w) for w in migaku_file["words"]}
    merge = anki_db_import.merge_known("ja", {by["LEARNING"], by["UNKNOWN"], by["IGNORED"], by["KNOWN"]})
    assert merge.error is None and merge.added == 0 and merge.raised == 2
    status = {_key(w): w["knownStatus"] for w in _load()["words"]}
    assert status[by["IGNORED"]] == "IGNORED"               # a dismissed word never comes back as known
    assert status[by["LEARNING"]] == status[by["UNKNOWN"]] == status[by["KNOWN"]] == "KNOWN"


def test_the_existing_list_stays_whole_and_in_order_and_other_keys_are_kept(migaku_file):
    before = [_key(w) for w in migaku_file["words"]]
    merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン"), ("旅", "タビ")})
    data = _load()
    assert [_key(w) for w in data["words"]][:4] == before   # the old entries first, in their order
    assert sorted(_key(w) for w in data["words"][4:]) == sorted([("旅", "タビ"), ("冒険", "ボウケン")])
    assert data["databaseFile"] == migaku_file["databaseFile"]   # Migaku's header kept
    assert data["statistics"]["totalWords"] == 6 and merge.added == 2 and merge.total == 6
    new = data["words"][-1]
    assert new["knownStatus"] == "KNOWN" and new["hasCard"] == 1 and new["language"] == "ja"


def test_a_replace_keeps_a_dated_byte_identical_backup_first(migaku_file):
    before = _bytes(_known())
    merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    [backup] = _trash()
    assert re.fullmatch(r"KnownWord\.\d{8}-\d{6}\.json", backup), backup
    assert _bytes(os.path.join(get_user_files_path("ja"), ".trash", backup)) == before
    assert os.path.basename(merge.backup) == backup


def test_a_failed_backup_writes_nothing(migaku_file):
    before = _bytes(_known())
    with mock.patch("app.anki_db_import.backup_to_trash", side_effect=OSError("disk full")):
        merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    assert merge.error and "backed up" in merge.error
    assert _bytes(_known()) == before


def test_a_failed_write_leaves_the_original_and_no_temp_file(migaku_file):
    before = _bytes(_known())
    with mock.patch("app.anki_sync.os.replace", side_effect=OSError("held by a reader")), \
            mock.patch("app.anki_sync.time.sleep"):
        merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    assert merge.error and "saved" in merge.error
    assert _bytes(_known()) == before
    assert not [n for n in os.listdir(get_user_files_path("ja")) if n.endswith(".tmp")]


def test_the_write_is_flushed_to_disk_before_it_replaces_the_file(migaku_file):
    with mock.patch("app.anki_sync.os.fsync", wraps=os.fsync) as fsync:
        anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    assert fsync.called                                     # the Tk window's write had no fsync (inv §2.9 defect 2)


def test_nothing_new_writes_nothing_and_keeps_no_backup(migaku_file):
    before = _bytes(_known())
    known = next(w for w in migaku_file["words"] if w["knownStatus"] == "KNOWN")
    merge = anki_db_import.merge_known("ja", {_key(known)})
    assert merge.error is None and merge.added == merge.raised == 0
    assert _bytes(_known()) == before and _trash() == []


def test_a_missing_file_is_created_with_no_backup():
    merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    assert merge.added == 1 and merge.backup is None
    assert [w["dictForm"] for w in _load()["words"]] == ["冒険"]


def test_a_held_known_words_lock_refuses_and_writes_nothing(migaku_file, monkeypatch):
    before = _bytes(_known())
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.2)
    with Holder("known-words-ja", "Anki known-words sync"):
        merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")})
    assert merge.busy and "being updated by Anki known-words sync" in merge.error
    assert _bytes(_known()) == before and _trash() == []


def test_it_waits_for_a_lock_another_program_lets_go_of(migaku_file):
    """The Tk window waited 0 s (inv §2.9 defect 4): a sync mid-write refused the import. The child waits."""
    import threading
    holder = Holder("known-words-ja", "Anki known-words sync")
    threading.Timer(0.5, holder.release).start()
    merge = anki_db_import.merge_known("ja", {("冒険", "ボウケン")}, wait=10)
    holder.release()
    assert merge.error is None and merge.added == 1


# --- the deck ------------------------------------------------------------------------------------------------------- #
def test_reading_a_deck_gives_its_fields_a_sample_each_and_leaves_no_temporary_copy(ja_resources_dir, monkeypatch):
    made = []
    import tempfile
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    deck = anki_db_import.read_deck(os.path.join(ja_resources_dir, "testAnki.apkg"))
    assert deck.notes > 0 and deck.fields and deck.default in deck.fields
    assert set(deck.samples) == set(deck.fields)
    assert any(deck.samples[f] for f in deck.fields)
    assert made and not any(os.path.exists(d) for d in made)    # the Tk window kept it until __del__ (defect 6)


def test_the_field_chosen_first_follows_the_tk_windows_order():
    assert anki_db_import.pick_field(["Back", "Expression", "Sentence"]) == "Sentence"
    assert anki_db_import.pick_field(["Back", "Word", "Front"]) == "Word"
    assert anki_db_import.pick_field(["Meaning", "Audio"]) == "Meaning"
    assert anki_db_import.pick_field([]) is None


def test_an_unreadable_deck_raises_for_the_window_to_say(tmp_path):
    bad = tmp_path / "壊れた.apkg"
    bad.write_bytes(b"not a zip")
    with pytest.raises(Exception):
        anki_db_import.read_deck(str(bad))


# --- the child --------------------------------------------------------------------------------------------------- #
def test_the_child_tokenizes_a_real_deck_merges_and_ends_with_its_result_line(ja_resources_dir, migaku_file, capsys):
    deck = anki_db_import.read_deck(os.path.join(ja_resources_dir, "testAnki.apkg"))
    code = anki_db_import.main(["--language", "ja", "--file", os.path.join(ja_resources_dir, "testAnki.apkg"),
                                "--field", deck.default])
    out = capsys.readouterr().out.strip().splitlines()
    assert code == anki_db_import.EXIT_DONE
    result = anki_db_import.parse_result(out[-1])
    assert result["added"] > 0 and result["total"] == len(_load()["words"])
    assert result["backup"] and result["backup"] in _trash()


def test_the_child_exits_5_when_another_program_holds_the_known_words(ja_resources_dir, migaku_file, monkeypatch,
                                                                     capsys):
    monkeypatch.setattr(anki_db_import, "words_of", lambda *a: {("冒険", "ボウケン")})
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.2)
    with Holder("known-words-ja", "surasura-cli known-sync"):
        code = anki_db_import.main(["--language", "ja", "--file", "x.apkg", "--field", "Sentence"])
    assert code == anki_db_import.EXIT_BUSY
    assert "Error: Your known words are being updated" in capsys.readouterr().out


def test_the_child_exits_1_on_a_deck_it_cannot_read_and_writes_nothing(tmp_path, migaku_file):
    before = _bytes(_known())
    bad = tmp_path / "壊れた.apkg"
    bad.write_bytes(b"not a zip")
    assert anki_db_import.main(["--language", "ja", "--file", str(bad), "--field", "Sentence"]) == 1
    assert _bytes(_known()) == before


def test_a_result_line_round_trips_and_other_lines_are_not_results():
    line = anki_db_import.result_line(anki_db_import.Merge(3, 1, 10, "/x/.trash/KnownWord.20261014-120000.json",
                                                           None, False))
    assert anki_db_import.parse_result(line) == {"added": 3, "raised": 1, "total": 10,
                                                 "backup": "KnownWord.20261014-120000.json"}
    assert anki_db_import.parse_result("Found 12 words in 'Sentence'") is None
    assert anki_db_import.parse_result("RESULT {not json") is None
