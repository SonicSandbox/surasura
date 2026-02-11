import os
import json
import zipfile
import pandas as pd
import pytest
import os
import sys
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.frequency_exporter import FrequencyExporter

def test_sanitize_term():
    assert FrequencyExporter._sanitize_term("アイリス-iris") == "アイリス"
    assert FrequencyExporter._sanitize_term("apple-fruit") == "apple"
    assert FrequencyExporter._sanitize_term(" 精霊 ") == "精霊" # re.split handles whitespace if we use \s
    assert FrequencyExporter._sanitize_term("精霊-spirit") == "精霊"
    assert FrequencyExporter._sanitize_term(" 精霊 - spirit") == "精霊"
    assert FrequencyExporter._sanitize_term(" 精霊 spirit") == "精霊"

def test_is_pure_katakana():
    assert FrequencyExporter._is_pure_katakana("アイリス") == True
    assert FrequencyExporter._is_pure_katakana("バナナ") == True
    assert FrequencyExporter._is_pure_katakana("ユーザー") == True
    assert FrequencyExporter._is_pure_katakana("コーヒー") == True
    assert FrequencyExporter._is_pure_katakana("精霊") == False
    assert FrequencyExporter._is_pure_katakana("apple") == False
    assert FrequencyExporter._is_pure_katakana("Rem") == False
    assert FrequencyExporter._is_pure_katakana("レム") == True

def test_yomitan_export_logic(tmp_path):
    csv_file = tmp_path / "test.csv"
    data = {
        'Word': ['アイリス-iris', '精霊-spirit', 'バナナ', 'apple'],
        'Reading': ['アイリス', 'セイレイ', 'バナナ', '']
    }
    pd.DataFrame(data).to_csv(csv_file, index=False)
    
    zip_path = tmp_path / "test.zip"
    FrequencyExporter.export_yomitan(str(csv_file), str(zip_path), language='ja')
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Fix 3: Check flat structure
        assert 'index.json' in zf.namelist()
        assert 'term_meta_bank_1.json' in zf.namelist()
        
        with zf.open('term_meta_bank_1.json') as f:
            term_data = json.load(f)
            
            # アイリス-iris -> アイリス (Katakana word, keep reading)
            assert term_data[0][0] == "アイリス"
            assert isinstance(term_data[0][2], dict)
            assert term_data[0][2]['reading'] == "アイリス"
            
            # 精霊-spirit -> 精霊 (Standard word, remove reading)
            assert term_data[1][0] == "精霊"
            assert isinstance(term_data[1][2], int)
            assert term_data[1][2] == 2
            
            # バナナ -> バナナ (Katakana word, keep reading)
            assert term_data[2][0] == "バナナ"
            assert isinstance(term_data[2][2], dict)
            assert term_data[2][2]['reading'] == "バナナ"
            
            # apple -> apple (Not Japanese Katakana, simple format)
            assert term_data[3][0] == "apple"
            assert isinstance(term_data[3][2], int)
            assert term_data[3][2] == 4

def test_migaku_export_logic(tmp_path):
    csv_file = tmp_path / "test.csv"
    data = {
        'Word': ['アイリス-iris', '精霊-spirit'],
    }
    pd.DataFrame(data).to_csv(csv_file, index=False)
    
    save_path = tmp_path / "test.json"
    FrequencyExporter.export_migaku(str(csv_file), str(save_path))
    
    with open(save_path, 'r', encoding='utf-8') as f:
        word_list = json.load(f)
        assert word_list == ["アイリス", "精霊"]
