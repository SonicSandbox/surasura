# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for ytdlp_manager — path resolution, platform handling, availability, and the
update/self-update flow. Fully mocked: no network, no real binary, no APPDATA writes
(the persistent path is redirected to a temp dir).
"""
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

from modules.youtube_downloader import ytdlp_manager as ym


class TestPlatformBits(unittest.TestCase):
    def test_exe_name_windows_vs_unix(self):
        with patch.object(ym.sys, "platform", "win32"):
            self.assertEqual(ym._exe_name(), "yt-dlp.exe")
        with patch.object(ym.sys, "platform", "linux"):
            self.assertEqual(ym._exe_name(), "yt-dlp")

    def test_no_window_flag(self):
        with patch.object(ym.sys, "platform", "linux"):
            self.assertEqual(ym.no_window_flag(), 0)
        with patch.object(ym.sys, "platform", "win32"):
            self.assertIsInstance(ym.no_window_flag(), int)

    def test_download_url_per_platform(self):
        with patch.object(ym.sys, "platform", "win32"):
            self.assertTrue(ym._download_url().endswith("yt-dlp.exe"))
        with patch.object(ym.sys, "platform", "darwin"):
            self.assertTrue(ym._download_url().endswith("yt-dlp_macos"))
        with patch.object(ym.sys, "platform", "linux"):
            self.assertTrue(ym._download_url().endswith("/yt-dlp"))


class TestManagedPathAndUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ymtest_")
        self._patch = patch.object(ym, "persistent_root", return_value=self.tmp)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _place(self):
        """A binary in the managed folder, as a download leaves it."""
        os.makedirs(os.path.dirname(ym.get_ytdlp_path()), exist_ok=True)
        open(ym.get_ytdlp_path(), "w").close()

    def test_asking_where_or_whether_makes_no_folder(self):
        # 2026-10-31: a `get_ytdlp_path()` run by hand made the real, empty %APPDATA%\Houseki\Surasura\bin (and
        # failed other runs' guards): the path, and whether the binary is there, are reads; only a download makes it.
        p = ym.get_ytdlp_path()
        self.assertEqual(os.path.dirname(p), os.path.join(self.tmp, "bin"))
        self.assertFalse(ym.is_available())
        self.assertIsNone(ym.current_version(log=lambda *_: None))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_download_makes_the_folder_and_leaves_the_binary(self):
        class Response:                                     # an empty body: no network
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                return b""

        with patch.object(ym.urllib.request, "urlopen", return_value=Response()):
            dest = ym.download(log=lambda *_: None)
        self.assertEqual(dest, ym.get_ytdlp_path())
        self.assertTrue(os.path.isfile(dest) and ym.is_available())
        self.assertEqual(os.listdir(os.path.join(self.tmp, "bin")), [ym._exe_name()])     # no .part left

    def test_is_available_reflects_file_presence(self):
        self.assertFalse(ym.is_available())
        self._place()
        self.assertTrue(ym.is_available())

    def test_ensure_available_returns_existing_without_download(self):
        self._place()
        with patch.object(ym, "download") as dl:
            res = ym.ensure_available(log=lambda *_: None)
            dl.assert_not_called()
        self.assertEqual(res, ym.get_ytdlp_path())

    def test_ensure_available_downloads_when_missing(self):
        with patch.object(ym, "download", return_value="DL") as dl:
            res = ym.ensure_available(log=lambda *_: None)
            dl.assert_called_once()
        self.assertEqual(res, "DL")

    def test_ensure_available_returns_none_on_download_failure(self):
        with patch.object(ym, "download", side_effect=Exception("offline")):
            self.assertIsNone(ym.ensure_available(log=lambda *_: None))

    def test_update_when_missing_delegates_to_ensure(self):
        with patch.object(ym, "ensure_available", return_value="DL") as ea:
            res = ym.update(log=lambda *_: None)
            ea.assert_called_once()
        self.assertEqual(res, "DL")

    def test_update_runs_self_update_when_present(self):
        self._place()
        fake = types.SimpleNamespace(returncode=0, stdout="Updated yt-dlp to ...", stderr="")
        with patch.object(ym, "run", return_value=fake) as run:      # (3.0: a child its run can stop, ym.run)
            res = ym.update(log=lambda *_: None)
            run.assert_called_once()
            self.assertIn("-U", run.call_args[0][0])
        self.assertEqual(res, ym.get_ytdlp_path())

    def test_update_falls_back_to_download_on_self_update_error(self):
        self._place()
        with patch.object(ym, "run", side_effect=Exception("boom")), \
             patch.object(ym, "download", return_value="DL") as dl:
            res = ym.update(log=lambda *_: None)
            dl.assert_called_once()
        self.assertEqual(res, "DL")

    def test_a_stopped_update_downloads_nothing(self):
        # 3.0: the job cancelled (or the app quitting) mid self-update ends it there — no re-download behind it.
        self._place()
        with patch.object(ym, "run", side_effect=ym.Stopped()), \
             patch.object(ym, "download", return_value="DL") as dl:      # (the fallback would swallow a raise)
            self.assertIsNone(ym.update(log=lambda *_: None, should_stop=lambda: True))
            dl.assert_not_called()

    def test_current_version_parses_and_handles_missing(self):
        self.assertIsNone(ym.current_version(log=lambda *_: None))  # no binary
        self._place()
        fake = types.SimpleNamespace(returncode=0, stdout="2026.06.09\n", stderr="")
        with patch.object(ym.subprocess, "run", return_value=fake):
            self.assertEqual(ym.current_version(log=lambda *_: None), "2026.06.09")


if __name__ == "__main__":
    unittest.main()
