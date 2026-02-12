import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json

# Ensure app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import telemetry

class TestTelemetry(unittest.TestCase):
    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_id')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_heartbeat_includes_language(self, mock_open, mock_exists, mock_get_id, mock_get_user_file, mock_get):
        # Setup
        mock_get_id.return_value = "test-uid"
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        
        # Mock settings with Chinese language
        settings_content = json.dumps({
            "telemetry_enabled": True,
            "target_language": "zh"
        })
        mock_open.return_value.read.return_value = settings_content
        
        # Force environment to be production so it sends
        with patch('app.telemetry.TELEMETRY_ENV', 'production'), \
             patch('app.telemetry.TELEMETRY_URL', 'http://test-url.com'):
            
            # Execute
            telemetry._send_heartbeat_thread('Multilingual-beta')
            
            # Verify
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            params = kwargs.get('params', {})
            
            self.assertEqual(params['uid'], "test-uid")
            self.assertEqual(params['lang'], "zh")
            self.assertEqual(params['env'], "production")
            self.assertEqual(params['status'], "Multilingual-beta")
            self.assertIn('open_count', params)

    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_id')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_heartbeat_defaults_language(self, mock_open, mock_exists, mock_get_id, mock_get_user_file, mock_get):
        # Setup
        mock_get_id.return_value = "test-uid"
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        
        # Mock settings without language (should default to ja)
        settings_content = json.dumps({
            "telemetry_enabled": True
        })
        mock_open.return_value.read.return_value = settings_content
        
        # Force environment to be production so it sends
        with patch('app.telemetry.TELEMETRY_ENV', 'production'), \
             patch('app.telemetry.TELEMETRY_URL', 'http://test-url.com'):
            
            # Execute
            telemetry._send_heartbeat_thread('Multilingual-beta')
            
            # Verify
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            params = kwargs.get('params', {})
            
            self.assertEqual(params['lang'], "ja")
            self.assertEqual(params['status'], "Multilingual-beta")

    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_id')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_onboard_complete_status(self, mock_open, mock_exists, mock_get_id, mock_get_user_file, mock_get):
        # Setup
        mock_get_id.return_value = "test-uid"
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        
        # Mock settings
        settings_content = json.dumps({
            "telemetry_enabled": True,
            "open_count": 5
        })
        mock_open.return_value.read.return_value = settings_content
        
        # Force environment to be production so it sends
        with patch('app.telemetry.TELEMETRY_ENV', 'production'), \
             patch('app.telemetry.TELEMETRY_URL', 'http://test-url.com'):
            
            # Execute with specific status
            telemetry._send_heartbeat_thread('Onboard Complete')
            
            # Verify
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            params = kwargs.get('params', {})
            
            self.assertEqual(params['status'], "Onboard Complete")
            # open_count should be incremented if not already done in this session
            # In tests, we might need to reset the global flag if we want to be sure
            # But here, it should be at least 5 (default) or 6 (incremented)
            self.assertGreaterEqual(params['open_count'], 5)

if __name__ == '__main__':
    unittest.main()
