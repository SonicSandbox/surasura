
import os
import pytest
import sqlite3
import json
import tempfile
from app.migaku_converter import convert_db_to_json

@pytest.fixture
def temp_json_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    os.remove(path)

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
