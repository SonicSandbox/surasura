# SPDX-License-Identifier: GPL-3.0-or-later
"""
Public contract of the YouTube Downloader module.

The core app depends on this surface: the settings it contributes (SETTINGS_DEFAULTS)
and its launch entry points (open_downloader / open_preview). These live in the module's
own suite because they describe the module's API, not the core wiring.
"""
import unittest

import modules.youtube_downloader as yt


class TestModuleContract(unittest.TestCase):
    def test_settings_defaults_shape(self):
        """The module declares its three settings. The transcript downloader is ON by default (owner
        choice — shown whenever the module is bundled); Preview and the risk-ack stay OFF."""
        self.assertIsInstance(yt.SETTINGS_DEFAULTS, dict)
        for key in ("enable_youtube_transcripts", "enable_youtube_preview", "youtube_risk_acknowledged"):
            self.assertIn(key, yt.SETTINGS_DEFAULTS)
        self.assertTrue(yt.SETTINGS_DEFAULTS["enable_youtube_transcripts"], "transcripts on by default")
        self.assertFalse(yt.SETTINGS_DEFAULTS["enable_youtube_preview"], "preview stays opt-in")
        self.assertFalse(yt.SETTINGS_DEFAULTS["youtube_risk_acknowledged"], "risk-ack stays off")

    def test_launch_entry_points_are_callable(self):
        """The core dashboard calls these thin entry points; they must exist and be callable."""
        self.assertTrue(callable(yt.open_downloader))
        self.assertTrue(callable(yt.open_preview))


if __name__ == "__main__":
    unittest.main()
