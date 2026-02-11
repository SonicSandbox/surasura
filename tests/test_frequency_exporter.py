import pytest
import os
import json
import zipfile
import pandas as pd
from app.frequency_exporter import FrequencyExporter

@pytest.fixture
def mock_csv(tmp_path):
    csv_path = tmp_path / "test_data.csv"
    data = {
        "Word": ["apple", "banana", "cherry"],
        "Reading": ["アップル", "バナナ", "チェリー"], # Katakana for JA tests
        "Score": [10, 5, 1]
    }
    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    return csv_path

def test_export_migaku(mock_csv, tmp_path):
    save_path = tmp_path / "migaku_list.json"
    FrequencyExporter.export_migaku(str(mock_csv), str(save_path))
    
    assert save_path.exists()
    with open(save_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    assert isinstance(data, list)
    assert data == ["apple", "banana", "cherry"]

def test_export_word_list(mock_csv, tmp_path):
    save_path = tmp_path / "word_list.txt"
    FrequencyExporter.export_word_list(str(mock_csv), str(save_path))
    
    assert save_path.exists()
    with open(save_path, 'r', encoding='utf-8') as f:
        content = f.read().splitlines()
        
    assert content == ["apple", "banana", "cherry"]

def test_export_yomitan_simple(mock_csv, tmp_path):
    save_path = tmp_path / "yomitan_simple.zip"
    # Use 'en' or 'zh' to force simple format (Option A)
    FrequencyExporter.export_yomitan(str(mock_csv), str(save_path), language='en')
    
    assert save_path.exists()
    assert zipfile.is_zipfile(save_path)
    
    with zipfile.ZipFile(save_path, 'r') as zf:
        # Check files exist
        assert "index.json" in zf.namelist()
        assert "term_meta_bank_1.json" in zf.namelist()
        
        # Check index
        index_data = json.loads(zf.read("index.json"))
        assert index_data["format"] == 3
        
        # Check terms (Simple format)
        term_data = json.loads(zf.read("term_meta_bank_1.json"))
        # Expected: ["apple", "freq", 1]
        assert term_data[0] == ["apple", "freq", 1]
        assert term_data[1] == ["banana", "freq", 2]

def test_export_yomitan_strict(tmp_path):
    # Use actual Katakana words for this test to trigger reading object
    csv_path = tmp_path / "ja_data.csv"
    data = {
        "Word": ["バナナ", "アップル"],
        "Reading": ["バナナ", "アップル"]
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)
    
    save_path = tmp_path / "yomitan_strict.zip"
    # Use 'ja' with readings present -> Option B
    FrequencyExporter.export_yomitan(str(csv_path), str(save_path), language='ja')
    
    assert save_path.exists()
    with zipfile.ZipFile(save_path, 'r') as zf:
        term_data = json.loads(zf.read("term_meta_bank_1.json"))
        # Expected: ["バナナ", "freq", {"reading": "バナナ", "frequency": 1}]
        entry = term_data[0]
        assert entry[0] == "バナナ"
        assert entry[1] == "freq"
        assert isinstance(entry[2], dict)
        assert entry[2]["reading"] == "バナナ"
        assert entry[2]["frequency"] == 1

def test_export_yomitan_missing_reading_fallback(tmp_path):
    # CSV without Reading column
    csv_path = tmp_path / "no_reading.csv"
    pd.DataFrame({"Word": ["apple"]}).to_csv(csv_path, index=False)
    
    save_path = tmp_path / "yomitan_fallback.zip"
    # Even if JA, if reading is missing, should fallback to Option A or handle gracefully
    FrequencyExporter.export_yomitan(str(csv_path), str(save_path), language='ja')
    
    with zipfile.ZipFile(save_path, 'r') as zf:
        term_data = json.loads(zf.read("term_meta_bank_1.json"))
        # Fallback to simple format: ["apple", "freq", 1]
        assert term_data[0] == ["apple", "freq", 1]
