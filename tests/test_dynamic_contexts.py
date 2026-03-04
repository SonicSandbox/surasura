import pytest
import pandas as pd
import json
import os
import shutil
import tempfile
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app.analyzer as analyzer
from app.analyzer import JapaneseTokenizer

@pytest.fixture
def mock_environment():
    temp_dir = tempfile.mkdtemp()
    
    # Mock data directories
    data_dir = os.path.join(temp_dir, "User Data", "data", "ja")
    os.makedirs(os.path.join(data_dir, "HighPriority"))
    os.makedirs(os.path.join(data_dir, "LowPriority"))
    os.makedirs(os.path.join(data_dir, "GoalContent"))
    
    # Mock user files directory
    user_files_dir = os.path.join(temp_dir, "User Files", "ja")
    os.makedirs(user_files_dir)
    
    # Create required files
    with open(os.path.join(user_files_dir, "KnownWord.json"), 'w', encoding='utf-8') as f:
        json.dump({}, f)
    with open(os.path.join(user_files_dir, "IgnoreList.txt"), 'w', encoding='utf-8') as f:
        f.write("")
    with open(os.path.join(user_files_dir, "Blacklist.txt"), 'w', encoding='utf-8') as f:
        f.write("")
    with open(os.path.join(user_files_dir, "GraduatedList.txt"), 'w', encoding='utf-8') as f:
        f.write("")
        
    # Create results directory
    results_dir = os.path.join(temp_dir, "Results")
    os.makedirs(results_dir)

    # Mock variables in analyzer module
    analyzer.get_data_path = lambda lang: data_dir
    analyzer.get_user_files_path = lambda lang: user_files_dir
    analyzer.RESULTS_DIR = results_dir
    analyzer.OUTPUT_CSV = os.path.join(results_dir, "Priority_Words.csv")
    analyzer.OUTPUT_STATS = os.path.join(results_dir, "file_statistics.txt")
    analyzer.OUTPUT_PROGRESSIVE = os.path.join(results_dir, "Progressive_Coverage.csv")
    
    yield {
        "temp_dir": temp_dir,
        "data_dir": data_dir,
        "user_files_dir": user_files_dir,
        "results_dir": results_dir
    }
    
    shutil.rmtree(temp_dir)

def test_dynamic_max_contexts_exports(mock_environment, monkeypatch):
    data_dir = mock_environment["data_dir"]
    results_dir = mock_environment["results_dir"]
    
    test_text = """
    昨日は学校へ行きました。
    毎日学校で勉強します。
    新しい学校が好きです。
    古い学校を見ました。
    学校の先生です。
    学校について話した。
    """
    
    with open(os.path.join(data_dir, "HighPriority", "test.txt"), 'w', encoding='utf-8') as f:
        f.write(test_text)

    # Mock command line args for 5 contexts
    sys.argv = ["analyzer.py", "--max-contexts", "5", "--context-min", "0"]
    
    # Run analyzer
    analyzer.main()
    
    # Check CSV export columns
    csv_path = os.path.join(results_dir, "Priority_Words.csv")
    assert os.path.exists(csv_path)
    
    df = pd.read_csv(csv_path)
    
    assert "Context 1" in df.columns
    assert "Context 5" in df.columns
    assert "Context 6" not in df.columns
    
    kare_rows = df[df["Word"] == "学校"]
    assert not kare_rows.empty, "The multi-character word '学校' should be in the CSV."
    row = kare_rows.iloc[0]
    assert pd.notna(row["Context 1"]) and len(row["Context 1"]) > 0
    assert pd.notna(row["Context 5"]) and len(row["Context 5"]) > 0
        
def test_dynamic_max_contexts_exports_one(mock_environment, monkeypatch):
    data_dir = mock_environment["data_dir"]
    results_dir = mock_environment["results_dir"]
    
    test_text = """
    先生は優しかった。
    先生が昨日来た。
    先生と話した。
    """
    
    with open(os.path.join(data_dir, "HighPriority", "test2.txt"), 'w', encoding='utf-8') as f:
        f.write(test_text)

    # Mock command line args for strictly 1 context
    sys.argv = ["analyzer.py", "--max-contexts", "1", "--context-min", "0"]
    
    # Run analyzer
    analyzer.main()
    
    # Check CSV export columns
    csv_path = os.path.join(results_dir, "Priority_Words.csv")
    df = pd.read_csv(csv_path)
    
    assert "Context 1" in df.columns
    assert "Context 2" not in df.columns
    
    sensei_rows = df[df["Word"] == "先生"]
    assert not sensei_rows.empty
    
def test_json_word_stats_exports_dynamic_contexts(mock_environment, monkeypatch):
    data_dir = mock_environment["data_dir"]
    results_dir = mock_environment["results_dir"]
    
    test_text = """
    友達は友達です。
    友達が来る。
    友達と歩く。
    友達の家です。
    """
    
    with open(os.path.join(data_dir, "HighPriority", "test3.txt"), 'w', encoding='utf-8') as f:
        f.write(test_text)

    # 4 contexts requested
    sys.argv = ["analyzer.py", "--max-contexts", "4", "--context-min", "0"]
    analyzer.main()
    
    json_path = os.path.join(results_dir, "word_stats.json")
    assert os.path.exists(json_path)
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Check dictionary format
    keys = list(data.keys())
    inu_key = next((k for k in keys if "友達" in k), None)
         
    assert inu_key is not None
    word_data = data[inu_key]
    
    assert "final_context_1" in word_data
    assert "final_context_4" in word_data
    assert "final_context_5" not in word_data
