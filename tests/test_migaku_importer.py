
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
