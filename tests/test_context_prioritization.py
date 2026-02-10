
import os
import shutil
import pytest
import pandas as pd
from unittest.mock import patch
from app import analyzer

@pytest.fixture
def context_test_env(tmp_path, ja_resources_dir, zh_resources_dir):
    """
    Sets up a temporary environment for testing context prioritization.
    """
    # Create Structure
    user_files_dir = tmp_path / "User Files"
    data_dir = tmp_path / "data"
    results_dir = tmp_path / "results"
    
    results_dir.mkdir()
    
    def setup_lang(lang, resource_dir):
        lang_data = data_dir / lang / "HighPriority"
        lang_data.mkdir(parents=True)
        (user_files_dir / lang).mkdir(parents=True)
        
        # Copy the test file
        src = os.path.join(resource_dir, "context_test.txt")
        if os.path.exists(src):
            shutil.copy(src, lang_data / "context_test.txt")
            
    setup_lang("ja", ja_resources_dir)
    setup_lang("zh", zh_resources_dir)
    
    # Mock return values for path_utils
    def mock_get_user_file(path):
        return str(tmp_path / path)
        
    def mock_get_data_path(lang=None):
        if lang: return str(data_dir / lang)
        return str(data_dir)
        
    def mock_get_user_files_path(lang=None):
        if lang: return str(user_files_dir / lang)
        return str(user_files_dir)
        
    return {
        "root": tmp_path,
        "results": results_dir,
        "mock_get_user_file": mock_get_user_file,
        "mock_get_data_path": mock_get_data_path,
        "mock_get_user_files_path": mock_get_user_files_path
    }

def verify_context_length(csv_path, word, min_tokens=4):
    """Helper to verify that Context 2 and 3 for a word are long enough."""
    df = pd.read_csv(csv_path)
    row = df[df["Word"] == word].iloc[0]
    
    c1 = row["Context 1"]
    c2 = row["Context 2"]
    c3 = row["Context 3"]
    
    print(f"\nVerifying '{word}':")
    print(f"  C1: {c1}")
    print(f"  C2: {c2}")
    print(f"  C3: {c3}")
    
    # Simple check: longer sentences usually have more characters or obvious tokens
    # But for a robust test, we want to ensure it's NOT one of the known short ones.
    short_ja = ["冒険だ。", "冒険する？", "今夜は冒険。", "冒険！"]
    short_zh = ["冒险。", "去冒险吗？", "冒险很难。", "冒险！"]
    
    if word == "冒険":
        assert c2 not in short_ja, f"Context 2 ('{c2}') is a known short sentence!"
        assert c3 not in short_ja, f"Context 3 ('{c3}') is a known short sentence!"
    elif word == "冒险":
        assert c2 not in short_zh, f"Context 2 ('{c2}') is a known short sentence!"
        assert c3 not in short_zh, f"Context 3 ('{c3}') is a known short sentence!"

def test_context_prioritization_ja(context_test_env):
    """Programmatic check for JA context prioritization."""
    results_dir = context_test_env["results"]
    
    with patch("app.path_utils.get_user_file", side_effect=context_test_env["mock_get_user_file"]), \
         patch("app.path_utils.get_data_path", side_effect=context_test_env["mock_get_data_path"]), \
         patch("app.path_utils.get_user_files_path", side_effect=context_test_env["mock_get_user_files_path"]), \
         patch("app.analyzer.RESULTS_DIR", str(results_dir)), \
         patch("app.analyzer.OUTPUT_CSV", str(results_dir / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results_dir / "file_statistics.txt")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja"]):
            analyzer.main()
            
    verify_context_length(results_dir / "priority_learning_list.csv", "冒険")

def test_context_prioritization_zh(context_test_env):
    """Programmatic check for ZH context prioritization."""
    results_dir = context_test_env["results"]
    
    with patch("app.path_utils.get_user_file", side_effect=context_test_env["mock_get_user_file"]), \
         patch("app.path_utils.get_data_path", side_effect=context_test_env["mock_get_data_path"]), \
         patch("app.path_utils.get_user_files_path", side_effect=context_test_env["mock_get_user_files_path"]), \
         patch("app.analyzer.RESULTS_DIR", str(results_dir)), \
         patch("app.analyzer.OUTPUT_CSV", str(results_dir / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results_dir / "file_statistics.txt")), \
         patch("sys.argv", ["analyzer.py", "--language", "zh"]):
            analyzer.main()
            
    verify_context_length(results_dir / "priority_learning_list.csv", "冒险")
