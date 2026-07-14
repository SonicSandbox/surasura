import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
import shutil
import types
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
        # Should return defaults if file doesn't exist, plus any present optional-module defaults
        settings = settings_manager.load_settings()
        expected = settings_manager.get_default_settings()
        expected.update(settings_manager._optional_module_defaults())
        self.assertEqual(settings, expected)

    def test_optional_module_defaults_merges_declared_settings(self):
        # Generic mechanism (module-agnostic): any importable module exposing SETTINGS_DEFAULTS
        # contributes its keys. Uses a dummy module so the test doesn't depend on any real one.
        fake = types.ModuleType("fake_optional_module")
        fake.SETTINGS_DEFAULTS = {"fake_feature_enabled": True}
        with patch.dict('sys.modules', {"fake_optional_module": fake}):
            with patch.object(settings_manager, "_OPTIONAL_MODULE_NAMES", ["fake_optional_module"]):
                merged = settings_manager._optional_module_defaults()
        self.assertEqual(merged.get("fake_feature_enabled"), True)

    def test_optional_module_defaults_ignores_absent_modules(self):
        # A declared optional module that isn't importable contributes nothing (and never crashes).
        with patch.object(settings_manager, "_OPTIONAL_MODULE_NAMES", ["modules.definitely_not_a_real_module"]):
            self.assertEqual(settings_manager._optional_module_defaults(), {})

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

    def test_selection_defaults_present(self):
        # The band-selection block ships with a default band, the one-off floor, and ppm floors.
        # (The method switch is the existing top-level 'strategy': freq -> bands, coverage.)
        sel = settings_manager.get_default_settings()["logic"]["selection"]
        self.assertIn(sel["band"], ["core", "common", "occasional", "uncommon", "rare", "very_rare", "native"])
        self.assertEqual(sel["bands_ppm"]["occasional"], 25)
        self.assertEqual(sel["bands_ppm"]["uncommon"], 10)   # the added band
        self.assertEqual(sel["bands_ppm"]["rare"], 4)        # tightened
        self.assertEqual(sel["bands_ppm"]["very_rare"], 2.5)
        self.assertEqual(sel["min_count"], 2)  # universal one-off floor (Native lands just under 100%)
        self.assertEqual(sel["minutes_per_file"], 18)  # feeds the "meet each word every N hours" estimate

    def test_selection_partial_override_deep_merges(self):
        # A user overriding just the band keeps the shipped ppm floors (deep merge for logic.*).
        partial = {"logic": {"selection": {"band": "common"}}}
        with open(self.test_settings_path, 'w', encoding='utf-8') as f:
            json.dump(partial, f)
        loaded = settings_manager.load_settings()
        self.assertEqual(loaded["logic"]["selection"]["band"], "common")
        self.assertEqual(loaded["logic"]["selection"]["min_count"], 2)
        self.assertEqual(loaded["logic"]["selection"]["bands_ppm"]["core"], 2000)

    def test_bands_ppm_user_edits_respected_and_gaps_filled(self):
        # bands_ppm is user-editable (like 'weights'): a floor the user set wins, and any band key
        # they DIDN'T set is filled from defaults so a partial/older file can't break the structure.
        partial = {"logic": {"selection": {"band": "rare", "bands_ppm": {"rare": 8}}}}
        with open(self.test_settings_path, 'w', encoding='utf-8') as f:
            json.dump(partial, f)
        sel = settings_manager.load_settings()["logic"]["selection"]
        self.assertEqual(sel["band"], "rare")               # preference kept
        self.assertEqual(sel["bands_ppm"]["rare"], 8)        # user edit respected
        self.assertEqual(sel["bands_ppm"]["core"], 2000)     # untouched band -> default
        self.assertIn("very_rare", sel["bands_ppm"])         # missing band filled
        self.assertEqual(sel["min_count"], 2)                # missing scalar filled
        self.assertEqual(sel["minutes_per_file"], 18)

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
