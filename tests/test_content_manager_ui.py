"""GUI tests for the Content Manager redesign — Phase 2 (the "Add Content" options row).

Real Tk root (mirrors tests/test_flag_ui.py); dest paths are isolated to a temp dir via
SURASURA_TEST_ROOT so construction never touches real user data.
"""

import os
import tempfile
import unittest
import tkinter as tk
from tkinter import ttk


class TestContentManagerOptionsRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._root_dir = tempfile.mkdtemp()

    def setUp(self):
        os.environ["SURASURA_TEST_ROOT"] = self._root_dir
        from app.content_importer_gui import ContentImporterApp
        self._Cls = ContentImporterApp
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = ContentImporterApp(self.root, language="ja")
        self.root.update()

    def tearDown(self):
        try:
            self.root.destroy()
        finally:
            os.environ.pop("SURASURA_TEST_ROOT", None)

    def _all_widgets(self):
        out = []
        def walk(w):
            for c in w.winfo_children():
                out.append(c)
                walk(c)
        walk(self.root)
        return out

    def _button_texts_under(self, widget):
        out = []
        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Button):
                    out.append(c.cget("text"))
                walk(c)
        walk(widget)
        return out

    def test_add_content_row_has_add_files_and_extract(self):
        opts = next((w for w in self._all_widgets() if isinstance(w, ttk.LabelFrame)
                     and "Add Content" in w.cget("text")), None)
        self.assertIsNotNone(opts, "the 'Add Content' options row should exist")
        joined = " ".join(self._button_texts_under(opts))
        self.assertIn("Add files", joined)
        self.assertIn("Extract", joined)

    def test_add_buttons_removed_from_manage_toolbar(self):
        """The old 'Files' / 'Folder' toolbar add-buttons are gone (they live in the options row)."""
        btns = {w.cget("text") for w in self._all_widgets() if isinstance(w, ttk.Button)}
        self.assertNotIn("Files", btns)
        self.assertNotIn("Folder", btns)

    def test_core_add_methods_exist(self):
        for m in ("open_splicer", "paste_text_dialog", "_launch_tool", "_on_focus_in",
                  "add_files", "add_folder"):
            self.assertTrue(hasattr(self.app, m), f"Content Manager missing method: {m}")

    def test_subtitle_link_shown_for_ja(self):
        self.assertIsNotNone(self.app._subtitle_url(), "ja should have a subtitle-source link")

    def test_subtitle_link_hidden_for_zh(self):
        top = tk.Toplevel(self.root)
        zh_app = self._Cls(top, language="zh")
        self.assertIsNone(zh_app._subtitle_url(), "zh has no known source -> link hidden")

    # --- Phase 3: the tier tabs (ttk.Notebook, one file-list per tier) ---------------------------- #
    def test_library_uses_a_notebook_with_three_tier_tabs(self):
        nb = self.app.notebook
        self.assertIsInstance(nb, ttk.Notebook)
        labels = [nb.tab(t, "text").strip() for t in nb.tabs()]
        self.assertEqual(labels, ["NOW", "Soon", "6+ months"])
        titles = [w.cget("text") for w in self._all_widgets() if isinstance(w, ttk.LabelFrame)]
        self.assertFalse(any("Select Section" in t for t in titles), "old radio section is gone")
        self.assertTrue(any("Your Library" in t for t in titles), "library frame present")

    def test_switching_notebook_tab_drives_tree_tier_and_meta(self):
        """Selecting a tab points self.tree at that tier's tree, sets the shared tier var (so ALL the
        existing file/reorder logic keeps working), and updates the right-justified guidance
        (description + 'order matters' hint)."""
        nb = self.app.notebook
        nb.select(nb.tabs()[2])       # 6+ months
        self.root.update()
        self.assertEqual(self.app.target_folder_var.get(), "GoalContent")
        self.assertIs(self.app.tree, self.app.tier_trees["GoalContent"])
        self.assertIn("someday", self.app.tier_desc_var.get())        # 6+ description (above the toolbar)
        self.assertIn("matter", self.app.tier_meta_var.get())         # order hint (inline on the tabs)
        nb.select(nb.tabs()[0])       # NOW
        self.root.update()
        self.assertTrue(self.app.get_current_dir().endswith("HighPriority"))
        self.assertIn("right now", self.app.tier_desc_var.get())

    # --- Phase 4: empty-state onboarding --------------------------------------------------------- #
    def _clear_tiers(self):
        for tier in ("HighPriority", "LowPriority", "GoalContent"):
            d = os.path.join(self._root_dir, "data", "ja", tier)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp):
                        os.remove(fp)

    def test_empty_library_shows_card_and_flips_to_tabs_on_content(self):
        self._clear_tiers()
        self.app.refresh_file_list()
        self.assertEqual(self.app.empty_card.winfo_manager(), "pack", "empty -> onboarding card shown")
        self.assertEqual(self.app.library_body.winfo_manager(), "", "empty -> tabbed library hidden")
        # Add content -> the tabbed library replaces the card.
        d = os.path.join(self._root_dir, "data", "ja", "HighPriority")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "book.txt"), "w", encoding="utf-8") as f:
            f.write("冒険。")
        self.app.refresh_file_list()
        self.assertEqual(self.app.library_body.winfo_manager(), "pack", "content -> tabs shown")
        self.assertEqual(self.app.empty_card.winfo_manager(), "", "content -> card hidden")
        os.remove(os.path.join(d, "book.txt"))

    def test_test_with_samples_button_seeds_and_reveals_library(self):
        from unittest.mock import patch
        self._clear_tiers()
        self.app.refresh_file_list()
        self.assertEqual(self.app.empty_card.winfo_manager(), "pack")
        d = os.path.join(self._root_dir, "data", "ja", "HighPriority")

        def fake_seed(language=None):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "sample.txt"), "w", encoding="utf-8") as f:
                f.write("今日は。")
            return 1

        with patch("app.path_utils.seed_samples", side_effect=fake_seed):
            self.app._seed_samples_clicked()
        self.assertEqual(self.app.library_body.winfo_manager(), "pack", "samples -> library revealed")
        os.remove(os.path.join(d, "sample.txt"))

    # --- Phase 5: the YouTube downloader relocation --------------------------------------------- #
    def test_youtube_button_shown_by_default_hidden_when_disabled(self):
        """The transcript downloader is ON by default (module bundled), so the ▶ button shows in the
        default build. When the toggle is off (or the module absent), the button is hidden."""
        from unittest.mock import patch
        self.assertIsNotNone(self.app.btn_youtube, "downloader button shown by default")
        top = tk.Toplevel(self.root)
        with patch.object(self._Cls, "_youtube_enabled", return_value=False):
            off_app = self._Cls(top, language="ja")
        self.assertIsNone(off_app.btn_youtube, "downloader button hidden when disabled")

    def test_opening_youtube_downloader_inherits_host_theme(self):
        """The healthy architecture (app/ui_theme): a module opened in-process must INHERIT the
        host's ttk theme, never switch the global theme. The Content Manager runs on 'clam'; opening
        the downloader must leave it on 'clam' (the Phase-5 regression was it flipping to 'default'
        and clobbering the whole window). No focus-restore workaround should be needed."""
        from modules.youtube_downloader.gui import YoutubeDownloaderGui
        self.assertEqual(self.app.style.theme_use(), "clam")
        win = YoutubeDownloaderGui(self.app.root, language="ja")   # what open_downloader constructs
        self.root.update()
        self.assertEqual(self.app.style.theme_use(), "clam",
                         "the downloader must inherit the host theme, not clobber it")
        # And the CM's own dark styling is still intact (tabs readable).
        from app.content_importer_gui import SURFACE_COLOR
        self.assertEqual(self.app.style.lookup("TNotebook.Tab", "background"), SURFACE_COLOR)
        win.destroy()

    def _find_button(self, text_contains):
        for w in self._all_widgets():
            if isinstance(w, ttk.Button) and text_contains in w.cget("text"):
                return w
        return None

    def test_add_content_buttons_are_big_full_width_options(self):
        """The add-content actions must read like the main GUI's big, full-width choices — they
        expand to fill the row (not small and left-justified) and use the prominent Action style."""
        add = self._find_button("Add files")
        extract = self._find_button("Extract")
        self.assertIsNotNone(add)
        self.assertIsNotNone(extract)
        self.assertEqual(str(add.pack_info().get("expand")), "1", "Add files must expand to fill width")
        self.assertEqual(str(extract.pack_info().get("expand")), "1", "Extract must expand to fill width")
        self.assertEqual(add.cget("style"), "Action.TButton")

    def test_folder_button_is_the_tail_of_the_add_files_group(self):
        """The 📂 folder button lives INSIDE the Add-files group (as its tail), so the pair is one
        equal-width option slot rather than the folder overrunning the row."""
        add = self._find_button("Add files")
        folder = next((w for w in self._all_widgets() if isinstance(w, ttk.Button)
                       and w.cget("style") == "ActionIcon.TButton"), None)
        self.assertIsNotNone(folder, "the add-folder icon button should exist")
        self.assertEqual(add.master, folder.master, "folder icon shares the Add-files group")
        self.assertEqual(str(add.master.pack_info().get("expand")), "1",
                         "the Add-files group is one of the equal-expanding option slots")

    def test_tier_desc_is_on_the_toolbar_line_and_hint_inline_on_tabs(self):
        """The tier description shares the manage-toolbar line (left-justified, same frame as the
        Demote button); the 'order matters' hint is separate, placed inline on the tab strip."""
        self.assertTrue(self.app.tier_desc_var.get(), "description populated")
        self.assertTrue(self.app.tier_meta_var.get(), "order hint populated")
        self.assertEqual(self.app.tier_meta_lbl.winfo_manager(), "place", "hint stays inline on the tabs")
        demote = self._find_button("Demote")
        self.assertEqual(self.app.tier_desc_lbl.master, demote.master, "description is on the toolbar line")
        self.assertEqual(self.app.tier_desc_lbl.pack_info().get("side"), "left", "description left-justified")

    def test_also_helper_line_is_right_justified(self):
        """The muted 'Also:' helper line hugs the right edge of the Add Content box."""
        also = next((w for w in self._all_widgets()
                     if isinstance(w, ttk.Label) and w.cget("text") == "Also:"), None)
        self.assertIsNotNone(also)
        self.assertEqual(also.master.pack_info().get("side"), "right")

    def test_utility_buttons_stay_icon_only(self):
        """The obvious utility actions stay icon-only for a clean bar — the word-labelled versions
        (e.g. '📂 Open', '🗑 Reset') must not exist; the bare glyphs must."""
        texts = {w.cget("text") for w in self._all_widgets() if isinstance(w, ttk.Button)}
        for labelled in ("📂 Open", "↺ Undo", "🏆 Graduated"):
            self.assertNotIn(labelled, texts, f"utility button should be icon-only, not '{labelled}'")
        self.assertIn("\U0001f4c2", texts, "open-folder icon (📂) present")
        self.assertIn("\U0001f393", texts, "graduated-list icon (🎓) present")

    def test_manage_toolbar_sits_above_the_tabs(self):
        """The library management buttons are moved ABOVE the tabs (packed before the notebook row)."""
        kids = self.app.library_body.winfo_children()
        def has_demote(w):
            return any(isinstance(c, ttk.Button) and "Demote" in c.cget("text") for c in w.winfo_children())
        toolbar_idx = next(i for i, w in enumerate(kids) if has_demote(w))
        nb_idx = next(i for i, w in enumerate(kids) if self.app.notebook in w.winfo_children())
        self.assertLess(toolbar_idx, nb_idx, "manage toolbar should sit above the tabs")

    def test_all_tier_tabs_are_the_same_width(self):
        """All three tabs must be the SAME size (only colour differentiates the active one) — their
        labels are padded to a common pixel width, so their measured widths match within a space."""
        import tkinter.font as tkfont
        nb = self.app.notebook
        f = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        widths = [f.measure(nb.tab(t, "text")) for t in nb.tabs()]
        # Equalized to within a space; far tighter than the ~40px gap between raw "NOW" and "6+ months".
        self.assertLessEqual(max(widths) - min(widths), f.measure(" ") + 2,
                             "tab label widths should be equalized")

    def test_tier_guidance_sits_inline_with_the_tabs(self):
        """The purple tier guidance is placed inline on the tab strip (not a separate stacked row),
        so it takes no extra vertical space."""
        self.assertEqual(self.app.tier_meta_lbl.winfo_manager(), "place",
                         "guidance must be placed over the tab strip, not packed as its own row")

    def test_help_memo_icon_right_of_the_also_links(self):
        """The '?' help memo sits to the RIGHT of the 'Also' quick-links (last item in that group)."""
        q = next((w for w in self._all_widgets() if isinstance(w, tk.Label) and w.cget("text") == "?"), None)
        self.assertIsNotNone(q, "the '?' help memo should exist")
        also = next((w for w in self._all_widgets()
                     if isinstance(w, ttk.Label) and w.cget("text") == "Also:"), None)
        self.assertIsNotNone(also)
        self.assertEqual(q.master, also.master, "help memo shares the 'Also' quick-links group")
        self.assertIs(q.master.winfo_children()[-1], q, "help memo is the right-most item")

    def test_order_hint_underlines_only_the_emphasis_word(self):
        """The tab-strip 'order matters' hint underlines ONLY the emphasis word (e.g. 'a lot'); the
        surrounding words are not underlined."""
        import tkinter.font as tkfont
        self.app.target_folder_var.set("HighPriority")
        self.app._sync_tier_meta()
        self.assertEqual(self.app._meta_mid.cget("text"), "a lot")
        self.assertTrue(tkfont.Font(font=self.app._meta_mid.cget("font")).actual("underline"),
                        "emphasis word must be underlined")
        self.assertFalse(tkfont.Font(font=self.app._meta_pre.cget("font")).actual("underline"),
                         "the leading words must NOT be underlined")

    def test_selected_tab_has_no_dotted_focus_ring(self):
        """The dotted focus outline on the selected tab is removed by dropping Notebook.focus from
        the tab layout (visually noisy)."""
        layout = str(self.app.style.layout("TNotebook.Tab"))
        self.assertNotIn("focus", layout.lower(), "tab layout must not include the focus ring element")

    def test_file_list_scrollbar_is_dark(self):
        """The file-list scrollbar matches the dark theme (dark trough), not clam's light default."""
        from app.content_importer_gui import BG_COLOR
        self.assertEqual(self.app.style.lookup("Vertical.TScrollbar", "troughcolor"), BG_COLOR)

    def test_tabs_do_not_resize_on_selection(self):
        """clam grows the selected Notebook tab via a larger PADDING map ('6 4 6 2' vs the base),
        which is what made tabs change size when picked. We pin the selected padding to the base."""
        pad = self.app.style.map("TNotebook.Tab", "padding")
        sel = [v for st, v in pad if st == "selected"]
        self.assertTrue(sel, "selected-tab padding must be pinned so the tab keeps its size")
        self.assertNotIn("4", str(sel[0]), "must not be clam's growing '6 4 6 2' padding")

    def test_reorder_arrows_sit_beside_the_list_not_in_the_toolbar(self):
        """The ▴▾ reorder arrows belong on the right side of the file list (a vertical column),
        not up in the action toolbar — regression guard for the placement fix."""
        up, down = self.app.up_btn, self.app.down_btn
        self.assertEqual(up.master, down.master, "both arrows share the side column")
        # Their column is a sibling of the notebook inside the same row (i.e. beside the list),
        # and is packed to the RIGHT.
        self.assertEqual(up.master.master, self.app.notebook.master)
        self.assertEqual(up.master.pack_info().get("side"), "right")

    def test_youtube_download_routes_new_files_into_active_tier(self):
        """The on_complete callback copies the freshly-downloaded Processed transcripts into the
        currently-selected section, so a download immediately becomes part of the library."""
        import tempfile as _tf
        self.app.target_folder_var.set("HighPriority")
        # A stand-in for what the downloader just wrote into Processed.
        proc = _tf.mkdtemp()
        src = os.path.join(proc, "Channel - Episode 1.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("これはテスト用の字幕です。新しい言葉を学びましょう。\n")

        self.app._on_youtube_downloaded([src])

        dst = os.path.join(self._root_dir, "data", "ja", "HighPriority", "Channel - Episode 1.txt")
        self.assertTrue(os.path.isfile(dst), "downloaded transcript should land in the active tier")
        os.remove(dst)


class TestContentManagerYouTubeEnabled(unittest.TestCase):
    """Separate case: the ▶ YouTube button must APPEAR once the module is opted-in. `_youtube_enabled`
    is consulted during construction, so it's patched before the app is built."""
    @classmethod
    def setUpClass(cls):
        cls._root_dir = tempfile.mkdtemp()

    def setUp(self):
        from unittest.mock import patch
        os.environ["SURASURA_TEST_ROOT"] = self._root_dir
        from app.content_importer_gui import ContentImporterApp
        self.root = tk.Tk()
        self.root.withdraw()
        with patch.object(ContentImporterApp, "_youtube_enabled", return_value=True):
            self.app = ContentImporterApp(self.root, language="ja")
        self.root.update()

    def tearDown(self):
        try:
            self.root.destroy()
        finally:
            os.environ.pop("SURASURA_TEST_ROOT", None)

    def test_youtube_button_shown_in_options_row_when_enabled(self):
        self.assertIsNotNone(self.app.btn_youtube, "the ▶ YouTube button should exist when opted-in")
        self.assertIn("YouTube", self.app.btn_youtube.cget("text"))
        # It lives in the top "Add Content" options row, not on the library toolbar.
        opts = None
        def walk(w):
            nonlocal opts
            for c in w.winfo_children():
                if isinstance(c, ttk.LabelFrame) and "Add Content" in c.cget("text"):
                    opts = c
                walk(c)
        walk(self.root)
        self.assertIsNotNone(opts)
        found = []
        def collect(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Button):
                    found.append(c.cget("text"))
                collect(c)
        collect(opts)
        self.assertTrue(any("YouTube" in t for t in found), "button must be in the options row")


if __name__ == "__main__":
    unittest.main()
