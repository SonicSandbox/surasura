# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 5 — the downloader GUI must run host-agnostically so the Content Manager (which is NOT the
main dashboard app) can open it with just a language + a completion callback.

Real Tk root (mirrors the app's GUI tests); output is isolated to a temp dir via SURASURA_TEST_ROOT
so nothing touches real user data. Uses real Japanese transcript text, never dummy ASCII.
"""

import os
import tempfile
import unittest
import tkinter as tk
from unittest.mock import patch

from modules.youtube_downloader import gui as yt_gui
from modules.youtube_downloader import open_downloader


# A realistic, cleaned Japanese transcript line — what core.extract would drop into Processed.
_JA_TRANSCRIPT = "今日はいい天気ですね。散歩に行きましょう。\n新しい単語を覚えるのは楽しいです。\n"


class TestDownloaderHostAgnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._root_dir = tempfile.mkdtemp()

    def setUp(self):
        os.environ["SURASURA_TEST_ROOT"] = self._root_dir
        # A cleanup, not tearDown: it runs even when Tk fails to start below, so the temp root never
        # leaks into the tests after this one (they then looked for templates in a deleted folder).
        self.addCleanup(os.environ.pop, "SURASURA_TEST_ROOT", None)
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_explicit_language_wins_without_an_app(self):
        """A language passed in is used verbatim — no app object, no reading the saved target."""
        win = yt_gui.YoutubeDownloaderGui(self.root, language="zh")
        self.assertEqual(win._lang_code(), "zh")
        # And the Processed output dir is resolved under that language, not the default 'ja'.
        self.assertTrue(win._output_dir().replace("\\", "/").endswith("data/zh/Processed"))

    def test_open_downloader_accepts_language_and_callback(self):
        """The minimal host contract: open_downloader(host, language=, on_complete=) opens the window,
        caches it on the host, and stays decoupled from the app (app is None when a language is given)."""
        class Host:  # a stand-in for the Content Manager (only needs .root)
            pass
        host = Host()
        host.root = self.root
        cb = lambda paths: None
        open_downloader(host, language="ja", on_complete=cb)
        self.assertTrue(host.youtube_window.winfo_exists())
        self.assertEqual(host.youtube_window.language, "ja")
        self.assertIsNone(host.youtube_window.app)
        self.assertIs(host.youtube_window.on_complete, cb)

    def test_extract_reports_new_processed_entries_to_on_complete(self):
        """A finished download must hand the host exactly the NEW Processed entries (so it can copy
        them into the active tier) — pre-existing files are not re-reported."""
        got = {}
        win = yt_gui.YoutubeDownloaderGui(
            self.root, language="ja", on_complete=lambda paths: got.setdefault("paths", paths))
        out = win._output_dir()
        os.makedirs(out, exist_ok=True)
        # A file that already existed before the run must be excluded from the diff.
        with open(os.path.join(out, "old_video.txt"), "w", encoding="utf-8") as f:
            f.write("既存のファイル。\n")

        def fake_extract(urls, out_dir, **kw):
            with open(os.path.join(out_dir, "Channel - New Video.txt"), "w", encoding="utf-8") as f:
                f.write(_JA_TRANSCRIPT)

        with patch.object(yt_gui.ytdlp_manager, "ensure_available", return_value="yt-dlp.exe"), \
             patch.object(yt_gui.core, "extract", side_effect=fake_extract):
            win._run_extract(["https://youtu.be/abc123"])   # synchronous with mocks
            win._drain()                                     # dispatch the queued __DONE__

        self.assertIn("paths", got, "on_complete should fire with the new entries")
        names = [os.path.basename(p) for p in got["paths"]]
        self.assertEqual(names, ["Channel - New Video.txt"])
        self.assertNotIn("old_video.txt", names)

    def test_embedded_window_inherits_host_theme_and_does_not_switch_it(self):
        """ttk styles are process-global, so a module opened in-process must NOT switch the theme —
        that clobbers the host (the Content Manager runs on 'clam'). With a styleable host theme
        already active, constructing the downloader must leave it untouched while still painting its
        own YT.* styles."""
        from tkinter import ttk
        ttk.Style(self.root).theme_use("clam")     # simulate a host (e.g. the Content Manager)
        win = yt_gui.YoutubeDownloaderGui(self.root, language="ja")
        self.root.update()
        self.assertEqual(ttk.Style(self.root).theme_use(), "clam",
                         "embedded module must inherit the host theme, not switch it")
        # Its own brand style is registered regardless of the inherited theme.
        self.assertEqual(win.tk.call("ttk::style", "lookup", "YT.TButton", "-background"),
                         yt_gui.SURFACE)
        win.destroy()

    def test_update_run_does_not_trigger_on_complete(self):
        """An engine-update run emits a bare ('__DONE__',) with no payload, so the host callback that
        routes downloads stays silent (nothing was downloaded)."""
        fired = {"n": 0}
        win = yt_gui.YoutubeDownloaderGui(
            self.root, language="ja", on_complete=lambda paths: fired.__setitem__("n", fired["n"] + 1))
        win.q.put(("__DONE__",))     # what _run_update emits
        win._drain()
        self.assertEqual(fired["n"], 0)


# Tk's start-up read failure, as GitHub's runner reported it.
_START_FAILURE = ("Can't find a usable init.tcl in the following directories:\n"
                  'couldn\'t read file "C:/Python/tcl/tcl8.6/init.tcl": No error')


def test_a_tk_that_cannot_start_leaves_no_test_root_behind(tmp_path):
    """A hosted runner's Tk sometimes can't start; the class's temp root must not outlive the failed
    test, or every test after it reads and writes under a deleted folder."""
    case = TestDownloaderHostAgnostic("test_update_run_does_not_trigger_on_complete")
    result = unittest.TestResult()
    with patch.dict(os.environ), \
         patch.object(TestDownloaderHostAgnostic, "_root_dir", str(tmp_path), create=True), \
         patch.object(tk, "Tk", side_effect=tk.TclError(_START_FAILURE)):
        os.environ.pop("SURASURA_TEST_ROOT", None)
        case.run(result)
        assert len(result.errors) == 1
        assert "SURASURA_TEST_ROOT" not in os.environ


if __name__ == "__main__":
    unittest.main()
