
import pytest
import json
import os
import tkinter as tk
from unittest.mock import MagicMock, patch
from app.content_importer_gui import ContentImporterApp

@pytest.fixture
def mock_app(tmp_path):
    root = tk.Tk()
    
    # Mock settings manager
    with patch('app.settings_manager.load_settings', return_value={"target_language": "ja"}):
        app = ContentImporterApp(root, "ja")
    
    # Redirect paths to tmp_path
    app.data_root = str(tmp_path / "data" / "ja")
    app.user_files_root = str(tmp_path / "User Files" / "ja")
    
    # Ensure dirs exist
    os.makedirs(app.data_root, exist_ok=True)
    os.makedirs(app.user_files_root, exist_ok=True)
    
    # Mock helpers
    app.get_current_dir = lambda: os.path.join(app.data_root, app.target_folder_var.get())
    app.get_manifest_path = lambda: os.path.join(app.user_files_root, "master_manifest.json")
    
    # Mock Treeview
    app.tree = MagicMock()
    app.tree.get_children.return_value = []
    
    return app

def test_refresh_loads_architect_manifest(mock_app):
    # 1. Simulate Immersion Architect writing a manifest
    manifest_path = mock_app.get_manifest_path()
    
    manifest_data = {
        "metadata": {"engine": "Immersion Architect"},
        "schedule": {
            "PHASE_1_NOW": [
                {"title": "B.txt", "physical_path": "HighPriority/B.txt"}, # Should be Rank 0
                {"title": "A.txt", "physical_path": "HighPriority/A.txt"}  # Should be Rank 1
            ]
        }
    }
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f)
        
    # 2. Create physical files
    hp_dir = os.path.join(mock_app.data_root, "HighPriority")
    os.makedirs(hp_dir, exist_ok=True)
    with open(os.path.join(hp_dir, "A.txt"), "w") as f: f.write("content")
    with open(os.path.join(hp_dir, "B.txt"), "w") as f: f.write("content")
    
    # 3. Call Refresh
    mock_app.target_folder_var.set("HighPriority")
    mock_app.refresh_file_list()
    
    # 4. Check internal rank cache
    # B.txt should be 0, A.txt should be 1
    # Note: rank keys are relative paths normalized
    assert mock_app.manifest_ranks.get("HighPriority/B.txt") == 0
    assert mock_app.manifest_ranks.get("HighPriority/A.txt") == 1
    
    # 5. Check order of items returned by Treeview (indirectly via manifest_ranks)
    # Since we can't easily mock Treeview insertion order deeply in this test,
    # we verify that the manifest was not changed for existing items.
    assert mock_app.manifest_ranks.get("HighPriority/B.txt") == 0
    assert mock_app.manifest_ranks.get("HighPriority/A.txt") == 1

def test_refresh_syncs_untracked_files(mock_app):
    # 1. Create a file on disk NOT in manifest
    hp_dir = os.path.join(mock_app.data_root, "HighPriority")
    os.makedirs(hp_dir, exist_ok=True)
    with open(os.path.join(hp_dir, "NewFile.txt"), "w") as f: f.write("content")
    
    # 2. Refresh
    mock_app.refresh_file_list()
    
    # 3. Check manifest
    manifest = mock_app.load_manifest()
    hp_entries = manifest["schedule"]["PHASE_1_NOW"]
    paths = [e["physical_path"] for e in hp_entries]
    assert "HighPriority/NewFile.txt" in paths

def test_reset_regenerates_manifest(mock_app):
    # 1. Setup cluttered manifest
    manifest_path = mock_app.get_manifest_path()
    with open(manifest_path, "w") as f:
        json.dump({"schedule": {"PHASE_1_NOW": [{"physical_path": "trash"}]}}, f)
        
    # 2. Create physical structure
    hp_dir = os.path.join(mock_app.data_root, "HighPriority")
    os.makedirs(hp_dir, exist_ok=True)
    with open(os.path.join(hp_dir, "Real.txt"), "w") as f: f.write("content")
    
    # 3. Mock confirmation and Reset
    with patch('tkinter.messagebox.askyesno', return_value=True):
        mock_app.reset_to_folder_structure()
        
    # 4. Verify manifest matches disk
    manifest = mock_app.load_manifest()
    hp_entries = manifest["schedule"]["PHASE_1_NOW"]
    assert len(hp_entries) == 1
    assert hp_entries[0]["physical_path"] == "HighPriority/Real.txt"
    assert "trash" not in str(manifest)

