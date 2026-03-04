import os
import shutil
import pytest
import pandas as pd
from unittest.mock import patch
from app import analyzer

@pytest.fixture
def i_plus_one_env(tmp_path):
    """
    Sets up a temporary environment for testing i+1 sentence logic.
    """
    user_files_dir = tmp_path / "User Files"
    data_dir = tmp_path / "data"
    results_dir = tmp_path / "results"
    
    results_dir.mkdir()
    
    # Create language dirs
    lang_data = data_dir / "ja" / "HighPriority"
    lang_data.mkdir(parents=True)
    (user_files_dir / "ja").mkdir(parents=True)
    
    # Create mock test content that tests the rolling algorithm
    # Initial knowns in mock (defined in the test logic):
    # - 私 (lemma=私)
    # - は (lemma=は)
    # - です (lemma=だ)
    
    # Sentence 1: 私は本です。(Unknowns: 本) -> i+1 for 本
    # Sentence 2: 私は本を読みます。(Unknowns: 本, を, 読む, ます)
    # Sentence 3: 私はリンゴを食べます。(Unknowns: リンゴ, を, 食べる, ます)
    
    test_text = "私は本です。\n私は本を読みます。\n私はリンゴを食べます。\n"
    test_file_path = lang_data / "test_rolling.txt"
    test_file_path.write_text(test_text, encoding="utf-8")
    
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

def read_results(csv_path):
    if not os.path.exists(csv_path): return pd.DataFrame()
    return pd.read_csv(csv_path)

def test_i_plus_one_fallback(i_plus_one_env):
    """Test standard fallback: i+1 preferred, but words without i+1 are still included."""
    results_dir = i_plus_one_env["results"]
    csv_path = results_dir / "priority_learning_list.csv"
    
    # Let's mock the initial known list and frequencies to enforce sorting
    mock_known_words = set()
    mock_known_lemmas = {"私", "私-代名詞", "は", "だ", "です", "ます", "を"}
    
    with patch("app.path_utils.get_user_file", side_effect=i_plus_one_env["mock_get_user_file"]), \
         patch("app.path_utils.get_data_path", side_effect=i_plus_one_env["mock_get_data_path"]), \
         patch("app.path_utils.get_user_files_path", side_effect=i_plus_one_env["mock_get_user_files_path"]), \
         patch("app.analyzer.RESULTS_DIR", str(results_dir)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv_path)), \
         patch("app.analyzer.OUTPUT_STATS", str(results_dir / "file_statistics.txt")), \
         patch("app.analyzer.load_known_words", return_value=(mock_known_words, mock_known_lemmas)), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--include-single-chars"]):
            analyzer.main()
            
    df = read_results(csv_path)
    assert not df.empty, "CSV should not be empty"
    
    words = df["Word"].tolist()
    
    # In standard mode, all unknown words should be present
    assert "本" in words
    assert "読む" in words
    assert "林檎" in words
    
    # "本" only has 1 unknown in "私は本です。", so it's a perfect i+1
    row_hon = df[df["Word"] == "本"].iloc[0]
    assert row_hon["Context 1"] == "私は本です。"

def test_only_i_plus_one_strict(i_plus_one_env):
    """Test --only-i-plus-one flag: Strict filtering out of words with no i+1 sentences."""
    results_dir = i_plus_one_env["results"]
    csv_path = results_dir / "priority_learning_list.csv"
    
    # Initial knowns
    mock_known_words = set()
    mock_known_lemmas = {"私", "私-代名詞", "は", "だ", "です", "ます", "を"}
    
    with patch("app.path_utils.get_user_file", side_effect=i_plus_one_env["mock_get_user_file"]), \
         patch("app.path_utils.get_data_path", side_effect=i_plus_one_env["mock_get_data_path"]), \
         patch("app.path_utils.get_user_files_path", side_effect=i_plus_one_env["mock_get_user_files_path"]), \
         patch("app.analyzer.RESULTS_DIR", str(results_dir)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv_path)), \
         patch("app.analyzer.OUTPUT_STATS", str(results_dir / "file_statistics.txt")), \
         patch("app.analyzer.load_known_words", return_value=(mock_known_words, mock_known_lemmas)), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--only-i-plus-one", "--include-single-chars"]):
            analyzer.main()
            
    df = read_results(csv_path)
    words = df["Word"].tolist()
    
    # "本" is i+1 initially ("私は本です。") -> Included.
    assert "本" in words, "'本' should be included because it has an initial i+1 sentence."
    
    # Since "を" and "ます" are known, "読む" is also i+1!
    assert "読む" in words, "'読む' should be included because it is an i+1 context."
    
    # 林檎 and 食べる occur together in "私はリンゴを食べます。" -> BOTH are unknown.
    # Therefore, neither has an i+1 sentence!
    assert "林檎" not in words, "'林檎' should be skipped because it has >1 unknowns context."
    assert "食べる" not in words, "'食べる' should be skipped because it has >1 unknowns context."
