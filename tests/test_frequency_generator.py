
import pytest
import os
import json
import pandas as pd
from unittest.mock import MagicMock, patch
from app.main import MasterDashboardApp
from app import analyzer
from app.frequency_exporter import FrequencyExporter

# --- Integration Test ---

@pytest.fixture
def frequency_app_env(tmp_path, ja_resources_dir, project_root):
    """Sets up a temporary environment for integration testing."""
    user_files_dir = tmp_path / "User Files"
    user_files_ja = user_files_dir / "ja"
    data_dir = tmp_path / "data"
    data_ja = data_dir / "ja"
    results_dir = tmp_path / "results"
    
    user_files_ja.mkdir(parents=True)
    (data_ja / "HighPriority").mkdir(parents=True)
    results_dir.mkdir()
    
    # Create simple sample text
    with open(data_ja / "HighPriority" / "test.txt", "w", encoding="utf-8") as f:
        f.write("私。君。友達。") # I, You, Friend

    def mock_get_user_file(path):
        return str(tmp_path / path)
    
    return {
        "root": tmp_path,
        "results": results_dir,
        "mock_get_user_file": mock_get_user_file,
        "data_ja": data_ja,
        "user_files_ja": user_files_ja
    }

def test_frequency_integration_real_analysis(frequency_app_env):
    """
    App-level test:
    1. Run real analyzer logic to generate a priority list CSV.
    2. Call the frequency list export wrapper (simulating button click) on that real CSV.
    3. Verify the final JSON format and content.
    """
    results_dir = frequency_app_env["results"]
    
    # 1. Run actual analyzer main logic
    # We patch path_utils and analyzer globals to point to our temp env
    with patch("app.path_utils.get_user_file", side_effect=frequency_app_env["mock_get_user_file"]), \
         patch("app.path_utils.get_data_path", return_value=str(frequency_app_env["data_ja"])), \
         patch("app.path_utils.get_user_files_path", return_value=str(frequency_app_env["user_files_ja"])), \
         patch("app.analyzer.RESULTS_DIR", str(results_dir)), \
         patch("app.analyzer.OUTPUT_CSV", str(results_dir / "priority_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja"]):
        
        analyzer.main()

    # 2. Confirm CSV was created and has words
    priority_csv = results_dir / "priority_learning_list.csv"
    assert priority_csv.exists(), "Analyzer failed to produce priority_learning_list.csv"
    
    df = pd.read_csv(priority_csv)
    words_in_csv = df['Word'].tolist()
    assert len(words_in_csv) >= 3 # '私', '君', '友達'

    # 3. Call export_wrapper via DashboardApp logic (Simulating "Migaku" export)
    app_mock = MagicMock()
    # Mock 'dialog' object which has destroy() method
    dialog_mock = MagicMock()
    
    save_path = frequency_app_env["root"] / "MY Immersion FreqList.json"
    
    with patch("tkinter.filedialog.asksaveasfilename", return_value=str(save_path)), \
         patch("tkinter.messagebox.showinfo") as mock_info:
        
        # Calling the wrapper directly
        MasterDashboardApp.export_wrapper(app_mock, dialog_mock, "migaku", str(priority_csv))

    # 4. Final verification: Does the JSON match the CSV?
    assert save_path.exists(), "Frequency list JSON was not saved"
    with open(save_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # We expect sanitized words
    expected_words = [FrequencyExporter._sanitize_term(w) for w in words_in_csv]
    assert isinstance(data, list)
    assert data == expected_words
    assert "successfully" in mock_info.call_args[0][1]
    
    # Verify dialog was closed
    dialog_mock.destroy.assert_called_once()

# --- Unit Tests (Mocks) ---

def test_export_wrapper_migaku(tmp_path):
    """
    Test the wrapper logic specifically for Migaku path using mocked CSV.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    priority_csv = results_dir / "priority_learning_list.csv"
    
    mock_data = {
        'Word': ['you', 'I', 'to', 'the'],
        'Reading': ['yu', 'ai', 'tu', 'ze'],
        'Score': [100, 90, 80, 70]
    }
    df = pd.DataFrame(mock_data)
    df.to_csv(priority_csv, index=False)
    
    save_path = tmp_path / "MY Immersion FreqList.json"
    app_mock = MagicMock()
    dialog_mock = MagicMock()
    
    with patch('tkinter.filedialog.asksaveasfilename', return_value=str(save_path)), \
         patch('tkinter.messagebox.showinfo') as mock_info:
        
        MasterDashboardApp.export_wrapper(app_mock, dialog_mock, "migaku", str(priority_csv))
        
        assert save_path.exists()
        with open(save_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert data == ['you', 'I', 'to', 'the']
        mock_info.assert_called_once()

def test_generate_frequency_list_no_data(tmp_path):
    """Test behavior when no analysis data exists (still checking generate_frequency_list top level check)."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    
    app_mock = MagicMock()
    
    # Mocking get_user_file to return our tmp path
    with patch('app.path_utils.get_user_file', return_value=str(results_dir)), \
         patch('tkinter.messagebox.showwarning') as mock_warning:
        
        MasterDashboardApp.generate_frequency_list(app_mock)
        mock_warning.assert_called_once()
        assert "run an analysis first" in mock_warning.call_args[0][1]
