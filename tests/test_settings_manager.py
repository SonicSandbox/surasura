import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
import shutil
from unittest.mock import patch, MagicMock
from app import settings_manager

class TestSettingsManager(unittest.TestCase):
    def setUp(self):
        # Use a temporary settings path for testing
        self.test_settings_path = "test_settings.json"
        self.patcher = patch('app.settings_manager.get_user_file', return_value=self.test_settings_path)
        self.mock_get_user_file = self.patcher.start()
        
        # Ensure a clean state for each test
        if os.path.exists(self.test_settings_path):
            os.remove(self.test_settings_path)

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.test_settings_path):
            os.remove(self.test_settings_path)

    def test_get_default_settings(self):
        defaults = settings_manager.get_default_settings()
        self.assertEqual(defaults, settings_manager.DEFAULT_SETTINGS)
        # Verify it's a copy
        defaults["target_language"] = "fr"
        self.assertNotEqual(defaults["target_language"], settings_manager.DEFAULT_SETTINGS["target_language"])

    def test_load_settings_missing_file(self):
        # Should return defaults if file doesn't exist
        settings = settings_manager.load_settings()
        self.assertEqual(settings, settings_manager.DEFAULT_SETTINGS)

    def test_save_and_load_settings(self):
        custom_settings = settings_manager.get_default_settings()
        custom_settings["target_language"] = "zh"
        custom_settings["logic"]["weights"]["high"] = 20
        
        settings_manager.save_settings(custom_settings)
        
        loaded_settings = settings_manager.load_settings()
        self.assertEqual(loaded_settings["target_language"], "zh")
        self.assertEqual(loaded_settings["logic"]["weights"]["high"], 20)
        # Ensure other defaults are preserved
        self.assertEqual(loaded_settings["logic"]["weights"]["low"], 5)

    def test_load_settings_merging(self):
        # Save a partial settings file
        partial = {"target_language": "zh", "logic": {"weights": {"high": 15}}}
        with open(self.test_settings_path, 'w', encoding='utf-8') as f:
            json.dump(partial, f)
            
        loaded = settings_manager.load_settings()
        self.assertEqual(loaded["target_language"], "zh")
        self.assertEqual(loaded["logic"]["weights"]["high"], 15)
        # Ensure deep merging for logic
        self.assertEqual(loaded["logic"]["weights"]["low"], 5)
        self.assertEqual(loaded["theme"], "Dark Flow")

    def test_save_settings_validation(self):
        # Should handle non-dict input gracefully
        with patch('builtins.print') as mock_print:
            settings_manager.save_settings("not a dict")
            mock_print.assert_any_call("Error: save_settings expected dict, got <class 'str'>")

    def test_save_settings_clean_for_build(self):
        settings = settings_manager.get_default_settings()
        settings["hide_satoru"] = True
        
        # Test cleaning for build
        settings_manager.save_settings(settings, clean_for_build=True)
        
        with open(self.test_settings_path, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
            self.assertNotIn("hide_satoru", saved_data)

    def test_save_settings_missing_module(self):
        settings = settings_manager.get_default_settings()
        settings["hide_satoru"] = True
        
        # Mock module import failure
        with patch('builtins.__import__', side_effect=ImportError):
            with patch('builtins.print') as mock_print:
                settings_manager.save_settings(settings)
                # Should proceed without error but we can check if it stripped the key
                # Wait, save_settings uses open() to write.
        
        with open(self.test_settings_path, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
            self.assertNotIn("hide_satoru", saved_data)

    def test_save_settings_io_error(self):
        settings = settings_manager.get_default_settings()
        # Mock open to raise an exception
        with patch('builtins.open', side_effect=IOError("Permission denied")):
            with patch('builtins.print') as mock_print:
                settings_manager.save_settings(settings)
                mock_print.assert_any_call("Error: Could not save settings: Permission denied")

if __name__ == '__main__':
    unittest.main()
