
import os
import shutil
import pytest
import pandas as pd
from unittest.mock import patch
import sys

# Ensure module is loaded to patch globals if needed
from app import analyzer

@pytest.fixture
def mock_env(tmp_path, ja_resources_dir, project_root):
    """
    Sets up a temporary environment with:
    - User Files/ja/KnownWord.json (from Test Resources)
    - data/ja/GoalContent (from samples)
    - results/ directory
    """
    # 1. Create Structure
    user_files_dir = tmp_path / "User Files"
    user_files_ja = user_files_dir / "ja"
    data_dir = tmp_path / "data"
    data_ja = data_dir / "ja"
    high_dir = data_ja / "HighPriority"
    
    user_files_ja.mkdir(parents=True)
    high_dir.mkdir(parents=True)
    (tmp_path / "results").mkdir()
    
    # 2. Copy Resources
    # KnownWord.json
    known_word_src = os.path.join(ja_resources_dir, "KnownWord.json")
    if os.path.exists(known_word_src):
        shutil.copy(known_word_src, user_files_ja / "KnownWord.json")
    
    # Samples
    samples_src = os.path.join(project_root, "samples", "ja", "HighPriority")
    if os.path.exists(samples_src):
         # Copy contents
         shutil.copytree(samples_src, high_dir, dirs_exist_ok=True)
         
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
        "results": tmp_path / "results",
        "mock_get_user_file": mock_get_user_file,
        "mock_get_data_path": mock_get_data_path,
        "mock_get_user_files_path": mock_get_user_files_path
    }

def test_analyzer_snapshot_ja(mock_env, ja_resources_dir):
    """
    Run analyzer on JA samples and compare output CSV with expected.
    """
    results_dir = mock_env["results"]
    expected_csv_path = os.path.join(ja_resources_dir, "expected_output.csv")
    
    # Patch path_utils AND analyzer globals
    with patch("app.path_utils.get_user_file", side_effect=mock_env["mock_get_user_file"]), \
         patch("app.path_utils.get_data_path", side_effect=mock_env["mock_get_data_path"]), \
         patch("app.path_utils.get_user_files_path", side_effect=mock_env["mock_get_user_files_path"]), \
         patch("app.analyzer.RESULTS_DIR", str(results_dir)), \
         patch("app.analyzer.OUTPUT_CSV", str(results_dir / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results_dir / "file_statistics.txt")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja"]):
         
            print(f"\nRunning analysis in {mock_env['root']}...")
            analyzer.main()
            
    # Check output
    generated_csv = results_dir / "priority_learning_list.csv"
    assert generated_csv.exists(), "Output CSV was not generated!"
    
    # Compare with Snapshot
    if not os.path.exists(expected_csv_path):
        shutil.copy(generated_csv, expected_csv_path)
        pytest.skip(f"Snapshot created: {generated_csv} -> {expected_csv_path}. Run again to verify.")
    else:
        # Load both and compare
        # We use pandas for robust comparison (handling float tolerance, empty/NaN)
        df_gen = pd.read_csv(generated_csv)
        df_exp = pd.read_csv(expected_csv_path)
        
        # Sort by Word to ensure order doesn't fail the test if logic is same
        df_gen = df_gen.sort_values(by="Word").reset_index(drop=True)
        df_exp = df_exp.sort_values(by="Word").reset_index(drop=True)
        
        pd.testing.assert_frame_equal(df_gen, df_exp, check_dtype=False)
        print("Snapshot test PASSED: Output matches expected CSV.")
