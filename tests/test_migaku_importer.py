
import os
import re
import sys
import pytest
import sqlite3
import json
from unittest.mock import patch
from app.migaku_converter import convert_db_to_json

@pytest.fixture
def temp_json_file(tmp_path):
    """An output path inside the test's own sandbox, not yet created. (It used to be an empty
    mkstemp file in the system temp dir; an existing file is now backed up to a `.trash` folder
    beside it before being replaced, which there would leave litter outside the sandbox.)"""
    return str(tmp_path / "KnownWord.json")

def test_migaku_import_ja(ja_resources_dir, temp_json_file):
    """Test importing the Japanese Migaku DB."""
    db_path = os.path.join(ja_resources_dir, "MigakuDb.db")
    if not os.path.exists(db_path):
        pytest.skip("Skiped: Japanese Migaku DB not found in Test Resources.")
    
    # 1. Run maximize conversion
    success = convert_db_to_json(db_path, temp_json_file, language='ja')
    assert success, "Database conversion failed!"
    
    # 2. Verify JSON content
    with open(temp_json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    assert "statistics" in data
    assert "words" in data
    assert len(data["words"]) > 0
    
    # Check a sample word structure
    sample = data["words"][0]
    expected_keys = {"dictForm", "knownStatus", "language"}
    assert expected_keys.issubset(sample.keys())
    
    print(f"Verified {len(data['words'])} words from JA Migaku DB.")

def test_migaku_import_zh(zh_resources_dir, temp_json_file):
    """Test importing the Chinese Migaku DB (if available)."""
    db_path = os.path.join(zh_resources_dir, "MigakuDb.db")
    if not os.path.exists(db_path):
        pytest.skip("Skiped: Chinese Migaku DB not found in Test Resources.")
        
    success = convert_db_to_json(db_path, temp_json_file, language='zh')
    assert success
    
    with open(temp_json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    assert len(data["words"]) > 0
    print(f"Verified {len(data['words'])} words from ZH Migaku DB.")


def _make_wordlist_db(path, columns, rows):
    """Create a minimal Migaku-style DB whose WordList table has exactly `columns`."""
    conn = sqlite3.connect(path)
    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
    conn.execute(f"CREATE TABLE WordList ({col_defs})")
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(f"INSERT INTO WordList VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()


def test_migaku_missing_columns_do_not_crash(tmp_path, temp_json_file):
    """A Migaku export whose schema lacks some columns must convert gracefully — the missing
    fields default to None — instead of raising IndexError on row['<missing>'] and aborting the
    whole import (migaku-jiten-onboard-06)."""
    db = tmp_path / "partial.db"
    # Only three of the ten columns the converter reads.
    _make_wordlist_db(db, ["dictForm", "knownStatus", "language"],
                      [("猫", "KNOWN", "ja"), ("走る", "LEARNING", "ja")])
    assert convert_db_to_json(str(db), temp_json_file, language="ja") is True
    with open(temp_json_file, encoding="utf-8") as f:
        data = json.load(f)
    words = {w["dictForm"]: w for w in data["words"]}
    assert set(words) == {"猫", "走る"}
    # Absent columns come through as None (not a KeyError, not a crash).
    assert words["猫"]["secondary"] is None
    assert words["猫"]["partOfSpeech"] is None


def test_migaku_creates_missing_output_directory(tmp_path):
    """Writing KnownWord.json into a not-yet-existing User Files/<lang> dir must create the dir
    rather than raising FileNotFoundError (migaku-jiten-onboard-07)."""
    db = tmp_path / "full.db"
    cols = ["dictForm", "secondary", "partOfSpeech", "language", "knownStatus",
            "hasCard", "tracked", "created", "mod", "isModern"]
    _make_wordlist_db(db, cols, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    nested = tmp_path / "User Files" / "ja" / "KnownWord.json"  # parents don't exist yet
    assert convert_db_to_json(str(db), str(nested), language="ja") is True
    assert nested.exists()


# --- Replacing known words: a dated backup first, never an empty overwrite -------------------- #
# A Migaku import REPLACES KnownWord.json. Before, it did so with no copy kept — words synced from
# Anki, an earlier Jiten import, anything else in the file was simply gone.
_FULL_COLS = ["dictForm", "secondary", "partOfSpeech", "language", "knownStatus",
              "hasCard", "tracked", "created", "mod", "isModern"]
_PREVIOUS = {"source": "AnkiConnect",
             "words": [{"dictForm": "冒険", "knownStatus": "KNOWN", "hasCard": 1, "language": "ja"}]}


def _known_words_file(tmp_path, data=_PREVIOUS):
    path = tmp_path / "User Files" / "ja" / "KnownWord.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_replacing_known_words_keeps_a_dated_backup_of_the_old_file(tmp_path):
    db = tmp_path / "migaku.db"
    _make_wordlist_db(db, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    known = _known_words_file(tmp_path)
    before = known.read_bytes()

    assert convert_db_to_json(str(db), str(known), language="ja") is True

    [backup] = list((known.parent / ".trash").iterdir())
    assert re.fullmatch(r"KnownWord\.\d{8}-\d{6}\.json", backup.name), backup.name
    assert backup.read_bytes() == before
    assert [w["dictForm"] for w in json.loads(known.read_text(encoding="utf-8"))["words"]] == ["日本語"]


def test_a_first_import_makes_no_backup(tmp_path, temp_json_file):
    db = tmp_path / "migaku.db"
    _make_wordlist_db(db, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    assert convert_db_to_json(str(db), temp_json_file, language="ja") is True
    assert not os.path.exists(os.path.join(os.path.dirname(temp_json_file), ".trash"))


def test_an_empty_import_never_replaces_existing_known_words(tmp_path):
    """A database holding only Chinese rows, imported for Japanese, finds nothing — and must not
    wipe the Japanese list with that nothing."""
    db = tmp_path / "migaku.db"
    _make_wordlist_db(db, _FULL_COLS, [("学习", "xuéxí", "v", "zh", "KNOWN", 1, 0, 0, 0, 1)])
    known = _known_words_file(tmp_path)
    before = known.read_bytes()

    assert convert_db_to_json(str(db), str(known), language="ja") is False
    assert known.read_bytes() == before
    assert not (known.parent / ".trash").exists()


def test_a_failed_backup_leaves_the_known_words_untouched(tmp_path):
    db = tmp_path / "migaku.db"
    _make_wordlist_db(db, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    known = _known_words_file(tmp_path)
    before = known.read_bytes()

    with patch("app.migaku_converter.backup_to_trash", side_effect=OSError("disk full")):
        assert convert_db_to_json(str(db), str(known), language="ja") is False
    assert known.read_bytes() == before


def test_the_exit_code_tells_the_import_window_whether_it_worked(tmp_path, monkeypatch):
    """The window shows "Success" on exit code 0. A failed conversion used to exit 0 as well."""
    from app import migaku_converter
    good = tmp_path / "good.db"
    _make_wordlist_db(good, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    out = str(tmp_path / "KnownWord.json")

    monkeypatch.setattr(sys, "argv", ["convert_db", str(good), out, "--language", "ja"])
    with pytest.raises(SystemExit) as ok:
        migaku_converter.main()
    assert ok.value.code == 0

    no_table = tmp_path / "not_migaku.db"
    sqlite3.connect(no_table).close()
    monkeypatch.setattr(sys, "argv", ["convert_db", str(no_table), out, "--language", "ja"])
    with pytest.raises(SystemExit) as failed:
        migaku_converter.main()
    assert failed.value.code == 1


# --- W3.4 row 2: the window's reads, moved out of the Tk class --------------------------------------------------- #
def test_finding_the_export_looks_at_the_newest_db_files_only(tmp_path):
    from app import migaku_converter
    old = tmp_path / "migaku_old.db"
    _make_wordlist_db(old, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    others = []
    for n in range(3):
        p = tmp_path / f"other_{n}.db"
        sqlite3.connect(p).close()
        others.append(p)
    now = os.path.getmtime(old)
    os.utime(old, (now - 100, now - 100))
    for n, p in enumerate(others):
        os.utime(p, (now + n, now + n))
    assert migaku_converter.find_export(str(tmp_path)) == (None, 4)   # the export is the 4th newest: not looked at
    os.utime(old, (now + 10, now + 10))
    assert migaku_converter.find_export(str(tmp_path)) == (str(old), 4)
    assert migaku_converter.find_export(str(tmp_path / "empty")) == (None, 0)


def test_reading_the_words_closes_its_database_even_when_it_is_not_migaku(tmp_path):
    from app import migaku_converter
    no_table = tmp_path / "not_migaku.db"
    sqlite3.connect(no_table).close()
    with pytest.raises(migaku_converter.NotMigaku):
        migaku_converter.read_words(str(no_table), "ja")
    os.remove(no_table)                                    # Windows refuses while a connection is left open
    plain = tmp_path / "plain.db"
    sqlite3.connect(plain).close()
    assert not migaku_converter.is_migaku_db(str(plain))
    good = tmp_path / "good.db"
    _make_wordlist_db(good, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    assert migaku_converter.is_migaku_db(str(good))


def test_the_words_read_for_the_confirmation_are_the_words_the_import_writes(ja_resources_dir, tmp_path):
    from app import migaku_converter
    db = os.path.join(ja_resources_dir, "MigakuDb.db")
    words = migaku_converter.read_words(db, "ja")
    out = tmp_path / "KnownWord.json"
    assert convert_db_to_json(db, str(out), language="ja") is True
    assert len(json.loads(out.read_text(encoding="utf-8"))["words"]) == len(words)


# --- AD2-1: a known-words file that exists but can't be read is never replaced #
@pytest.mark.parametrize("content", ['{"words": [{"dictForm": "冒険"', '"冒険"', '{"words": "冒険"}'])
def test_an_unreadable_known_words_file_refuses_migakus_replace_and_writes_nothing(tmp_path, content):
    """Its past Graduates' and dismissed words can't be kept from a file no one can read: refused, nothing written,
    no backup (the .apkg merge's rule)."""
    db = tmp_path / "migaku.db"
    _make_wordlist_db(db, _FULL_COLS, [("日本語", "にほんご", "n", "ja", "KNOWN", 1, 0, 0, 0, 1)])
    known = _known_words_file(tmp_path)
    known.write_text(content, encoding="utf-8")
    assert convert_db_to_json(str(db), str(known), language="ja") is False
    assert known.read_bytes() == content.encode("utf-8")
    assert not (known.parent / ".trash").exists()


# --- IK-56: the replace writes only the numbers its confirmation stated ------------------------------------------ #
def test_migakus_replace_refuses_when_the_numbers_moved_since_the_confirmation(ja_resources_dir, monkeypatch):
    from app import anki_sync, migaku_converter
    from app.path_utils import get_user_files_path
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    known = os.path.join(get_user_files_path("ja"), "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        json.dump(_PREVIOUS, f, ensure_ascii=False)
    db = os.path.join(ja_resources_dir, "MigakuDb.db")
    numbers = anki_sync.replace_numbers("ja", migaku_converter.read_words(db, "ja"))
    before = open(known, "rb").read()
    stale = ",".join(map(str, (numbers[0], numbers[1] - 1, numbers[2], numbers[3])))
    monkeypatch.setattr(sys, "argv", ["migaku_converter.py", db, "--language", "ja", "--expect", stale])
    with pytest.raises(SystemExit) as done:
        migaku_converter.main()
    assert done.value.code == anki_sync.EXIT_CHANGED and open(known, "rb").read() == before
    monkeypatch.setattr(sys, "argv", ["migaku_converter.py", db, "--language", "ja", "--expect",
                                      ",".join(map(str, numbers))])
    with pytest.raises(SystemExit) as done:
        migaku_converter.main()
    assert done.value.code == 0 and anki_sync.count_known("ja") == numbers[1]
