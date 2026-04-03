import os
import shutil
import pytest
import tkinter as tk
from app.content_importer_gui import ContentImporterApp

from unittest.mock import patch

@pytest.fixture
def mock_gui(tmp_path):
    root = tk.Tk()
    
    # Mock data structure
    data_root = os.path.join(tmp_path, "data", "ja")
    user_root = os.path.join(tmp_path, "User Files", "ja")
    os.makedirs(data_root, exist_ok=True)
    os.makedirs(user_root, exist_ok=True)
    for folder in ["HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed", ".trash"]:
        os.makedirs(os.path.join(data_root, folder), exist_ok=True)
        
    with patch("app.content_importer_gui.get_data_path", return_value=str(data_root)), \
         patch("app.content_importer_gui.get_user_files_path", return_value=str(user_root)), \
         patch("app.content_importer_gui.ensure_data_setup"):
        app = ContentImporterApp(root, "ja")
        yield app
    
    try: root.destroy()
    except: pass

def test_undo_add_files(mock_gui, tmp_path):
    # Setup test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Test content", encoding="utf-8")
    
    # Snapshot before action
    mock_gui._temp_manifest_snapshot = mock_gui.load_manifest()
    
    # Simulate an add action
    dest = os.path.join(mock_gui.data_root, "HighPriority", "test.txt")
    shutil.copy2(test_file, dest)
    mock_gui.add_to_manifest(dest, "HighPriority")
    
    mock_gui.set_undo_action("add", "Add files", {"paths": [dest]})
    
    assert os.path.exists(dest)
    
    # Run Undo
    mock_gui.undo_last_action()
    
    # Verify
    assert not os.path.exists(dest)
    manifest = mock_gui.load_manifest()
    assert "test.txt" not in str(manifest)
    
def test_undo_move_graduate(mock_gui, tmp_path):
    # Setup src and dest
    src_folder = os.path.join(mock_gui.data_root, "GoalContent")
    dest_folder = os.path.join(mock_gui.data_root, "LowPriority")
    
    src_file = os.path.join(src_folder, "move_test.txt")
    dest_file = os.path.join(dest_folder, "move_test.txt")
    
    # Initial state
    with open(src_file, "w") as f: f.write("Test")
    mock_gui.add_to_manifest(src_file, "GoalContent")
    
    # Snapshot before action
    mock_gui._temp_manifest_snapshot = mock_gui.load_manifest()
    
    # Action
    shutil.move(src_file, dest_file)
    mock_gui.remove_from_manifest(src_file)
    mock_gui.add_to_manifest(dest_file, "LowPriority")
    
    mock_gui.set_undo_action("graduate", "Graduate Content", {
        "moves": [{"source": src_file, "dest": dest_file}],
        "words_added": 0,
        "sources": []
    })
    
    mock_gui.undo_last_action()
    
    # Verify moved back
    assert not os.path.exists(dest_file)
    assert os.path.exists(src_file)
    manifest = mock_gui.load_manifest()
    # It should be added back to GoalContent (PHASE_3_LATER)
    found = False
    for item in manifest.get("schedule", {}).get("PHASE_3_LATER", []):
        if "move_test.txt" in item.get("physical_path", ""):
             found = True
    assert found

def test_undo_remove_items(mock_gui, tmp_path):
    # Setup trash and original
    orig_file = os.path.join(mock_gui.data_root, "HighPriority", "remove_test.txt")
    trash_file = os.path.join(mock_gui.data_root, ".trash", "remove_test_timestamp.txt")
    
    # Initial state
    with open(orig_file, "w") as f: f.write("Test")
    mock_gui.add_to_manifest(orig_file, "HighPriority")
    
    # Snapshot before action
    mock_gui._temp_manifest_snapshot = mock_gui.load_manifest()
    
    # Action
    shutil.move(orig_file, trash_file)
    mock_gui.remove_from_manifest(orig_file)
    
    mock_gui.set_undo_action("remove", "Remove Items", {
        "removals": [{"original": orig_file, "trash": trash_file}]
    })
    
    mock_gui.undo_last_action()
    
    # Verify restored
    assert not os.path.exists(trash_file)
    assert os.path.exists(orig_file)
    manifest = mock_gui.load_manifest()
    # Ensure it's in HighPriority (PHASE_1_NOW)
    found = False
    for item in manifest.get("schedule", {}).get("PHASE_1_NOW", []):
        if "remove_test.txt" in item.get("physical_path", ""):
             found = True
    assert found
