import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib

class TestConditionalSatori(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        Safely setup mocks for app.main import.
        We snapshot sys.modules to ensure we can unload EVERYTHING loaded during this test class.
        """
        cls._original_modules = set(sys.modules.keys())
        
        cls.sys_modules_patcher = patch.dict(sys.modules, {
            'tkinter': MagicMock(),
            'tkinter.ttk': MagicMock(),
            'tkinter.messagebox': MagicMock(),
            'app.path_utils': MagicMock(),
            'app.update_checker': MagicMock(),
            'app.onboarding_gui': MagicMock(),
        })
        cls.sys_modules_patcher.start()
        
        # Now import app.main. It will use the mocks.
        try:
            import app.main
            importlib.reload(app.main) # Force reload with OUR mocks
            cls.app_module = app.main
            cls.MasterDashboardApp = app.main.MasterDashboardApp
        except ImportError as e:
            print(f"DEBUG: Failed to import app.main in setUpClass: {e}")
            cls.app_module = None
            cls.MasterDashboardApp = None

    @classmethod
    def tearDownClass(cls):
        """
        Clean up mocks and force unload of ANY module loaded during this test class.
        This prevents 'poisoned' modules (initialized with mocks) from persisting to other tests.
        """
        cls.sys_modules_patcher.stop()
        
        # Aggressively unload any module that wasn't present before setUpClass
        current_modules = set(sys.modules.keys())
        new_modules = current_modules - cls._original_modules
        
        for mod in new_modules:
            if mod in sys.modules:
                del sys.modules[mod]
        
        # Explicitly ensure app.main is gone just in case
        if 'app.main' in sys.modules:
            del sys.modules['app.main']

    def setUp(self):
        if self.MasterDashboardApp is None:
            self.skipTest("app.main could not be imported")

        # Create a mock instance
        self.app = MagicMock(spec=self.MasterDashboardApp)
        self.app.btn_satori = MagicMock()
        self.app.var_hide_satoru = MagicMock()
        self.app.btn_satori.winfo_ismapped.return_value = False
        
    def test_satori_hidden_by_user_setting(self):
        """Test that button is hidden if user setting is True"""
        self.app.var_hide_satoru.get.return_value = True
        
        self.MasterDashboardApp.update_satori_visibility(self.app)
        
        self.app.btn_satori.pack_forget.assert_called()
        self.app.btn_satori.pack.assert_not_called()

    def test_satori_shown_if_module_present(self):
        """Test that button is shown if setting is False and module imports"""
        self.app.var_hide_satoru.get.return_value = False
        
        with patch.dict(sys.modules, {'modules.immersion_architect': MagicMock()}):
            self.MasterDashboardApp.update_satori_visibility(self.app)
            self.app.btn_satori.pack.assert_called()

    def test_satori_hidden_if_module_missing(self):
        """Test that button is hidden if module raises ImportError"""
        self.app.var_hide_satoru.get.return_value = False
        
        # Ensure module is NOT in sys.modules
        with patch.dict(sys.modules):
            if 'modules.immersion_architect' in sys.modules:
                del sys.modules['modules.immersion_architect']
            
            # Use 'modules.immersion_architect' = None to trigger ImportError on import attempt
            # (Standard Python 3 behavior for "module not found" in sys.modules overrides)
            # Actually, setting it to None explicitly might work best here.
            sys.modules['modules.immersion_architect'] = None
            
            try:
                self.MasterDashboardApp.update_satori_visibility(self.app)
            except (ImportError, AttributeError):
                 # function might catch it, or not since we are simulating import failure
                 pass
            
            self.app.btn_satori.pack_forget.assert_called()

if __name__ == '__main__':
    unittest.main()
