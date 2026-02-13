import os
import json
import pytest
from unittest.mock import MagicMock, patch
from app.content_importer_gui import ContentImporterApp

@pytest.fixture
def mock_app():
    root = MagicMock()
    with patch('app.content_importer_gui.ensure_data_setup'):
        with patch('app.content_importer_gui.get_data_path', return_value="fake_data"):
            with patch('app.content_importer_gui.get_user_files_path', return_value="fake_user"):
                app = ContentImporterApp(root)
                app.tree = MagicMock()
                return app

def test_fractured_grouping_logic(mock_app):
    """Verifies that refresh_file_list groups items correctly in a fractured way."""
    schedule = {
        "PHASE_1_NOW": [
            {"title": "f1.txt", "physical_path": "HP/f1.txt", "parent_folder": "HP"},
            {"title": "f2.txt", "physical_path": "HP/f2.txt", "parent_folder": "HP"},
            {"title": "f3.txt", "physical_path": "LOTR/f3.txt", "parent_folder": "LOTR"},
            {"title": "f4.txt", "physical_path": "HP/f4.txt", "parent_folder": "HP"},
            {"title": "f5.txt", "physical_path": "HP/f5.txt", "parent_folder": "HP"}
        ]
    }
    
    with patch.object(mock_app, 'load_manifest', return_value={"schedule": schedule}):
        with patch.object(mock_app, '_sync_disk_to_manifest'):
            with patch('os.path.exists', return_value=True):
                mock_app.target_folder_var.set("HighPriority")
                mock_app.tree.insert.reset_mock() # Reset after variable trigger
                mock_app.refresh_file_list()
                
                calls = mock_app.tree.insert.call_args_list
                assert len(calls) == 7
                
                assert calls[0].kwargs["text"] == "HP"
                assert "GROUP:HP" in str(calls[0].kwargs["values"])
                assert calls[3].args[0] == "" # f3 should be in root
                assert calls[4].kwargs["text"] == "HP"
                
def test_group_node_expansion_for_movement(mock_app):
    """Verifies that selecting a group node selects all its children for movement."""
    def mock_item(tid, option=None):
        if option == "values":
            if tid == "node1": return ["GROUP:HP"]
            if tid == "child1": return ["/abs/path/f1"]
            if tid == "child2": return ["/abs/path/f2"]
        return {}

    mock_app.tree.item.side_effect = mock_item
    mock_app.tree.get_children.side_effect = lambda tid: ["child1", "child2"] if tid == "node1" else []

    with patch.object(mock_app, 'move_items_in_manifest') as mock_move:
        mock_app.tree.selection.return_value = ["node1"]
        mock_app.move_selected_up()
        
        args = mock_move.call_args[0][0]
        assert "/abs/path/f1" in args
        assert "/abs/path/f2" in args
