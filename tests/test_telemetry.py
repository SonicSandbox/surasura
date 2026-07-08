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
    @patch('app.telemetry.get_telemetry_state')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_heartbeat_includes_language(self, mock_open, mock_exists, mock_get_state, mock_get_user_file, mock_get):
        # Setup
        mock_get_state.return_value = {"uid": "test-uid", "open_count": 5}
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
            self.assertEqual(params['open_count'], 5)

    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_state')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_heartbeat_defaults_language(self, mock_open, mock_exists, mock_get_state, mock_get_user_file, mock_get):
        # Setup
        mock_get_state.return_value = {"uid": "test-uid", "open_count": 5}
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
    @patch('app.telemetry.get_telemetry_state')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_onboard_complete_status(self, mock_open, mock_exists, mock_get_state, mock_get_user_file, mock_get):
        # Setup
        mock_get_state.return_value = {"uid": "test-uid", "open_count": 6}
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        
        # Mock settings
        settings_content = json.dumps({
            "telemetry_enabled": True
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
            self.assertGreaterEqual(params['open_count'], 5)

    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_state')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_normal_heartbeat_suppressed_when_opted_out(self, mock_open, mock_exists, mock_get_state, mock_get_user_file, mock_get):
        """A regular heartbeat must send NOTHING when the user disabled telemetry."""
        mock_get_state.return_value = {"uid": "real-uid", "open_count": 5}
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        mock_open.return_value.read.return_value = json.dumps({"telemetry_enabled": False})

        with patch('app.telemetry.TELEMETRY_ENV', 'production'), \
             patch('app.telemetry.TELEMETRY_URL', 'http://test-url.com'):
            telemetry._send_heartbeat_thread('Multilingual-beta')

        mock_get.assert_not_called()

    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_state')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_forced_update_event_sends_anonymized_when_opted_out(self, mock_open, mock_exists, mock_get_state, mock_get_user_file, mock_get):
        """A forced event (update) is STILL sent when opted out, but with a throwaway id and
        without touching the user's persistent telemetry state."""
        mock_get_state.return_value = {"uid": "real-uid", "open_count": 5}
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        mock_open.return_value.read.return_value = json.dumps({"telemetry_enabled": False})

        with patch('app.telemetry.TELEMETRY_ENV', 'production'), \
             patch('app.telemetry.TELEMETRY_URL', 'http://test-url.com'):
            telemetry._send_heartbeat_thread('Updated 2.0 -> 2.1', respect_optout=False)

        mock_get.assert_called_once()
        params = mock_get.call_args.kwargs.get('params', {})
        self.assertTrue(params['uid'].startswith('anon-'))   # gibberish, not the real id
        self.assertNotEqual(params['uid'], "real-uid")
        self.assertEqual(params['open_count'], 0)
        self.assertEqual(params['status'], "Updated 2.0 -> 2.1")
        # The persistent identity was never read.
        mock_get_state.assert_not_called()

    @patch('app.telemetry.requests.get')
    @patch('app.telemetry.path_utils.get_user_file')
    @patch('app.telemetry.get_telemetry_state')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_forced_update_event_uses_real_id_when_opted_in(self, mock_open, mock_exists, mock_get_state, mock_get_user_file, mock_get):
        """When telemetry is ON, the update event carries the normal persistent id."""
        mock_get_state.return_value = {"uid": "real-uid", "open_count": 7}
        mock_get_user_file.return_value = "dummy_settings.json"
        mock_exists.return_value = True
        mock_open.return_value.read.return_value = json.dumps({"telemetry_enabled": True})

        with patch('app.telemetry.TELEMETRY_ENV', 'production'), \
             patch('app.telemetry.TELEMETRY_URL', 'http://test-url.com'):
            telemetry._send_heartbeat_thread('Updated 2.0 -> 2.1', respect_optout=False)

        mock_get.assert_called_once()
        params = mock_get.call_args.kwargs.get('params', {})
        self.assertEqual(params['uid'], "real-uid")


if __name__ == '__main__':
    unittest.main()
