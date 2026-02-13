import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import tkinter as tk
from app.content_importer_gui import ContentImporterApp

class TestGraduateButtonLogic(unittest.TestCase):
    @patch('app.content_importer_gui.ensure_data_setup')
    @patch('app.content_importer_gui.get_data_path')
    @patch('app.content_importer_gui.get_user_files_path')
    @patch('app.content_importer_gui.get_icon_path')
    def setUp(self, mock_icon, mock_user_files, mock_data_path, mock_ensure):
        self.root = tk.Tk()
        mock_data_path.return_value = "mock_data"
        mock_user_files.return_value = "mock_user_files"
        mock_icon.return_value = "mock_icon.png"
        
        # Avoid loading manifest and other IO in __init__
        with patch.object(ContentImporterApp, 'load_manifest_ranks'), \
             patch.object(ContentImporterApp, 'refresh_file_list'), \
             patch.object(ContentImporterApp, 'setup_ui'), \
             patch.object(self.root, 'after'):
            self.app = ContentImporterApp(self.root)
            self.app.tree = MagicMock()
            self.app.graduate_btn = MagicMock()
            self.app.data_root = "data/ja"

    def tearDown(self):
        self.root.destroy()

    def test_update_button_disabled_no_selection(self):
        self.app.tree.selection.return_value = []
        self.app._update_graduate_button_state()
        self.app.graduate_btn.config.assert_called_with(state=tk.DISABLED)

    @patch('app.content_importer_gui.ContentImporterApp._has_analysis_for_selection')
    def test_update_button_enabled_low_priority_no_analysis(self, mock_has_analysis):
        self.app.tree.selection.return_value = ['item1']
        self.app.target_folder_var.set("LowPriority")
        mock_has_analysis.return_value = False
        self.app._update_graduate_button_state()
        self.app.graduate_btn.config.assert_called_with(state=tk.NORMAL)

    @patch('app.content_importer_gui.ContentImporterApp._has_analysis_for_selection')
    def test_update_button_disabled_high_priority_no_analysis(self, mock_has_analysis):
        self.app.tree.selection.return_value = ['item1']
        self.app.target_folder_var.set("HighPriority")
        mock_has_analysis.return_value = False
        self.app._update_graduate_button_state()
        self.app.graduate_btn.config.assert_called_with(state=tk.DISABLED)

    @patch('app.content_importer_gui.ContentImporterApp._has_analysis_for_selection')
    def test_update_button_enabled_high_priority_with_analysis(self, mock_has_analysis):
        self.app.tree.selection.return_value = ['item1']
        self.app.target_folder_var.set("HighPriority")
        mock_has_analysis.return_value = True
        self.app._update_graduate_button_state()
        self.app.graduate_btn.config.assert_called_with(state=tk.NORMAL)

    @patch('os.path.getsize')
    @patch('os.path.getmtime')
    @patch('os.path.exists')
    @patch('os.path.isfile')
    @patch('builtins.open', new_callable=mock_open, read_data='{"word|reading": {"sources": ["test.txt"]}}')
    def test_has_analysis_for_selection_true(self, mock_file, mock_isfile, mock_exists, mock_mtime, mock_size):
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_mtime.return_value = 1000
        mock_size.return_value = 50
        self.app.data_root = "data/ja"
        self.app._load_analyzed_filenames()
        self.app._resolve_items_to_paths = MagicMock(return_value=["data/ja/HighPriority/test.txt"])
        
        result = self.app._has_analysis_for_selection(['item1'])
        self.assertTrue(result)

    @patch('os.path.getsize')
    @patch('os.path.getmtime')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"word|reading": {"sources": ["other.txt"]}}')
    def test_has_analysis_for_selection_false(self, mock_file, mock_exists, mock_mtime, mock_size):
        mock_exists.return_value = True
        mock_mtime.return_value = 1000
        mock_size.return_value = 50
        self.app.data_root = "data/ja"
        self.app._load_analyzed_filenames()
        self.app._resolve_items_to_paths = MagicMock(return_value=["data/ja/HighPriority/test.txt"])
        
        result = self.app._has_analysis_for_selection(['item1'])
        self.assertFalse(result)

    @patch('os.path.getsize')
    @patch('os.path.getmtime')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='{"word|reading": {"sources": ["test.txt"]}}')
    def test_load_analyzed_filenames_caching(self, mock_file, mock_exists, mock_mtime, mock_size):
        mock_exists.return_value = True
        self.app.data_root = "data/ja"
        
        # First load
        mock_mtime.return_value = 1000
        mock_size.return_value = 50
        self.app._load_analyzed_filenames()
        self.assertEqual(mock_file.call_count, 1)
        
        # Second load with same stats - should NOT call open
        self.app._load_analyzed_filenames()
        self.assertEqual(mock_file.call_count, 1)
        
        # Third load with changed mtime - SHOULD call open
        mock_mtime.return_value = 2000
        self.app._load_analyzed_filenames()
        self.assertEqual(mock_file.call_count, 2)

        # Fourth load with changed size - SHOULD call open
        mock_size.return_value = 100
        self.app._load_analyzed_filenames()
        self.assertEqual(mock_file.call_count, 3)

if __name__ == '__main__':
    unittest.main()
