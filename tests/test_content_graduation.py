import os
import shutil
import json
import pytest
from unittest.mock import MagicMock, patch
import tkinter as tk

# Mock tkinter.StringVar
class MockStringVar:
    def __init__(self, value=""):
        self._value = value
    def get(self):
        return self._value
    def set(self, value):
        self._value = value

# Mock messagebox
@pytest.fixture(autouse=True)
def mock_messagebox():
    with patch("app.content_importer_gui.messagebox") as mock:
        mock.askyesno.return_value = True
        yield mock

# Import App (will need to patch imports if they have side effects, but should be fine)
import app.content_importer_gui as gui_module
from app.content_importer_gui import ContentImporterApp

@pytest.fixture
def app_instance(tmp_path):
    # Setup Data Dir
    data_root = tmp_path / "data" / "ja"
    (data_root / "HighPriority").mkdir(parents=True)
    (data_root / "LowPriority").mkdir(parents=True)
    (data_root / "GoalContent").mkdir(parents=True)
    (data_root / "Graduated").mkdir(parents=True)
    
    # Mock __init__ to skip GUI setup
    with patch.object(ContentImporterApp, "__init__", lambda self, root, language='ja': None):
        app = ContentImporterApp(None, language="ja")
        app.root = MagicMock()
        app.data_root = str(data_root)
        app.language = "ja"
        app.target_folder_var = MockStringVar("HighPriority")
        app.status_var = MockStringVar()
        app.tree = MagicMock()
        app.graduate_btn = MagicMock()
        app.analyzed_filenames = set()
        app._last_stats_mtime = 0
        app._last_stats_size = 0
        
        # Inject helper methods that depend on manifest
        # We need to make sure get_user_files_path and get_manifest_path work
        # patch get_user_files_path to return tmp_path/data/ja
        
        return app

def test_graduate_content_moves_files_and_updates_manifest(app_instance, tmp_path):
    # Setup: Create a file in HighPriority
    high_prio = tmp_path / "data" / "ja" / "HighPriority"
    test_file = high_prio / "test.txt"
    test_file.write_text("content")
    
    # Setup Manifest
    manifest_path = tmp_path / "data" / "ja" / "master_manifest.json"
    manifest_data = {
        "schedule": {
            "PHASE_1_NOW": [
                {"physical_path": "HighPriority/test.txt", "title": "test.txt"}
            ]
        }
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f)

    # Patch helpers
    app_instance.get_manifest_path = lambda: str(manifest_path)
    
    # Mock Selection
    app_instance.tree.selection.return_value = ["item1"]
    def mock_tree_item(item_id, option=None, **kwargs):
        if option == "values": return [str(test_file)]
        return {}
    app_instance.tree.item.side_effect = mock_tree_item
    
    # Run Graduate
    app_instance.graduate_content()
    
    # Assertions
    # 1. File Moved
    graduated_dir = tmp_path / "data" / "ja" / "Graduated"
    assert not test_file.exists()
    assert (graduated_dir / "test.txt").exists()
    
    # 2. Manifest Updated
    with open(manifest_path, "r") as f:
        new_manifest = json.load(f)
    
    schedule = new_manifest["schedule"]
    # Should be removed from PHASE_1_NOW
    assert not any(e["physical_path"] == "HighPriority/test.txt" for e in schedule.get("PHASE_1_NOW", []))
    # Should NOT be added to any other phase (Graduated items are removed from schedule? Or moved?)
    # Logic says: if dest_folder_name in ["HighPriority", "LowPriority", "GoalContent"] -> Add to manifest.
    # "Graduated" is NOT in that list. So it should just be removed.
    assert "PHASE_1_NOW" in schedule
    assert len(schedule["PHASE_1_NOW"]) == 0

def test_graduate_from_low_to_high(app_instance, tmp_path):
    # Setup
    low_prio = tmp_path / "data" / "ja" / "LowPriority"
    test_file = low_prio / "move_me.txt"
    test_file.write_text("content")
    
    # Manifest
    manifest_path = tmp_path / "data" / "ja" / "master_manifest.json"
    manifest_data = {
        "schedule": {
            "PHASE_2_SOON": [{"physical_path": "LowPriority/move_me.txt"}]
        }
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f)
        
    app_instance.get_manifest_path = lambda: str(manifest_path)
    app_instance.target_folder_var.set("LowPriority")
    
    # Mock Selection
    app_instance.tree.selection.return_value = ["item1"]
    def mock_tree_item(item_id, option=None, **kwargs):
        if option == "text": return "move_me.txt"
        if option == "values": return [str(test_file)]
        return {}
    app_instance.tree.item.side_effect = mock_tree_item
    
    # Run
    app_instance.graduate_content()
    
    # Assert
    # 1. Moved to HighPriority
    high_prio = tmp_path / "data" / "ja" / "HighPriority"
    assert (high_prio / "move_me.txt").exists()
    
    # 2. Manifest: Removed from PHASE_2, Added to PHASE_1
    with open(manifest_path, "r") as f:
        data = json.load(f)
    
    schedule = data["schedule"]
    # Removed from Soon
    assert not any(e["physical_path"] == "LowPriority/move_me.txt" for e in schedule.get("PHASE_2_SOON", []))
    # Added to Now
    # Note: add_to_manifest uses relative path.
    # We need to verify what add_to_manifest does. 
    # It normalizes path relative to data_root?
    # Our mocked app doesn't have _normalize_path mocked, so it uses real method.
    # Real method needs self.data_root.
    
    # We need to verify 'add_to_manifest' called correctly or check result.
    # Since we are using the REAL methods for manifest manipulation (we only mocked __init__), 
    # the integration should work if we set up data_root correctly.
    
    # Check PHASE_1_NOW
    # Expected path: "HighPriority/move_me.txt" (normalized)
    assert any(e["physical_path"] == "HighPriority/move_me.txt" for e in schedule.get("PHASE_1_NOW", []))

def test_move_items_in_manifest_reorders(app_instance, tmp_path):
    # Setup Manifest with 3 items
    manifest_path = tmp_path / "data" / "ja" / "master_manifest.json"
    manifest_data = {
        "schedule": {
            "PHASE_1_NOW": [
                {"physical_path": "HighPriority/A.txt"},
                {"physical_path": "HighPriority/B.txt"},
                {"physical_path": "HighPriority/C.txt"}
            ]
        }
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f)
        
    app_instance.get_manifest_path = lambda: str(manifest_path)
    app_instance.target_folder_var.set("HighPriority")
    
    # helper to check order
    def get_order():
        with open(manifest_path, "r") as f:
            d = json.load(f)
        return [e["physical_path"] for e in d["schedule"]["PHASE_1_NOW"]]

    # 1. Move B up -> A, B, C -> B, A, C
    # items arg is list of absolute paths. 
    # Our app uses _normalize_path. We must assume app_instance.data_root is set correct.
    # We mocked data_root in fixture.
    base = tmp_path / "data" / "ja"
    pB = str(base / "HighPriority" / "B.txt")
    
    app_instance.move_items_in_manifest([pB], "up")
    assert get_order() == ["HighPriority/B.txt", "HighPriority/A.txt", "HighPriority/C.txt"]
    
    # 2. Move B down -> B, A, C -> A, B, C
    app_instance.move_items_in_manifest([pB], "down")
    assert get_order() == ["HighPriority/A.txt", "HighPriority/B.txt", "HighPriority/C.txt"]
    
