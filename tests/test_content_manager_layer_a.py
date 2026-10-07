"""Content Manager, Layer A (S1.1: RD-A1, A2, A7) — driven through real Tk events where it matters.

A1  One refresh per drag and no disk walk per refresh: the disk is synced on open, on focus and after
    an undo; the four flows that drop files into a tier (samples, pasted text, YouTube, the splicer)
    register them themselves. A file hato drops into HighPriority/Hato shows at the top of NOW.
A2  ONE focus handler (there were two; the later def shadowed the force-refresh): focus returning to
    the window re-reads disk and manifest; focus moving between widgets inside it does nothing.
A7  A drop onto itself is judged by FILE (an episode dropped below its own group, a group dropped on
    its own episode); Ctrl / Shift press leaves the selection to the Treeview (Ctrl-click adds a row).

Real Japanese content per docs/agent instructions/testing.md. One Tk root and one app for the whole
module (see test_group_run_selection.py: a Content Manager per test eats USER/GDI handles). The
window is shown (not withdrawn) so rows have geometry and real press / release events land on them.
"""

import gc
import json
import os
import shutil
import tempfile
import time
import unittest
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch

EPISODE_TEXT = "冒険だ。\n彼は毎日冒険に出かけます。\n私たちは新しい冒険を求めている。\n"
BOOK_TEXT = "今日はいい天気ですね。\n本を読むのが好きです。\n図書館で勉強しました。\n"
TIERS = ("HighPriority", "LowPriority", "GoalContent")
SERIES = "ブリーチ"


def _make_empty(path, timeout=10.0):
    """`path` removed and made again, empty. On Windows a file another process still holds (a virus scanner on a file
    just written, more often on a loaded machine) is deleted only once it lets go, and its folders stay: an empty
    sub-folder left in HighPriority made seed_samples (it fills only an empty tier) skip it, and NOW stayed empty."""
    deadline = time.monotonic() + timeout
    while os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            if time.monotonic() > deadline:
                raise AssertionError(f"{path} could not be emptied: {os.listdir(path)}")
            time.sleep(0.05)
    os.makedirs(path)


class LayerATestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._root_dir = tempfile.mkdtemp()
        os.environ["SURASURA_TEST_ROOT"] = cls._root_dir
        project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copytree(os.path.join(project, "samples"), os.path.join(cls._root_dir, "samples"))
        from app.content_importer_gui import ContentImporterApp
        cls.root = tk.Tk()
        cls.app = ContentImporterApp(cls.root, language="ja")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass
        cls.app = None
        cls.root = None
        gc.collect()
        os.environ.pop("SURASURA_TEST_ROOT", None)
        shutil.rmtree(cls._root_dir, ignore_errors=True)

    def setUp(self):
        for tier in TIERS:
            _make_empty(os.path.join(self.app.data_root, tier))
        self._write_manifest({})
        from app import content_importer_gui
        content_importer_gui._DIALOGS[0] = 0
        self.app._refresh_on_focus = False
        self._pump()          # drain any focus refresh a previous test left pending
        self.app.notebook.select(0)
        self.root.update()
        self.app.refresh_file_list(force=True)

    # --- helpers ------------------------------------------------------------------------------
    def _write(self, rel, text=EPISODE_TEXT):
        path = os.path.join(self.app.data_root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    @staticmethod
    def _entry(rel):
        parts = rel.split("/")
        return {"title": parts[-1], "physical_path": rel,
                "parent_folder": "/".join(parts[1:-1]) if len(parts) > 2 else "",
                "origin_source": "Manual Import", "type": "File", "status": "New"}

    def _write_manifest(self, phases):
        schedule = {"PHASE_1_NOW": [], "PHASE_2_SOON": [], "PHASE_3_LATER": []}
        for k, rels in phases.items():
            schedule[k] = [self._entry(r) for r in rels]
        path = self.app.get_manifest_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schedule": schedule}, f, ensure_ascii=False, indent=2)

    def _now_paths(self):
        return [e["physical_path"] for e in self.app.load_manifest()["schedule"].get("PHASE_1_NOW", [])]

    def _library(self, rels):
        """Files on disk + the manifest in this order, the tree drawn, every group open."""
        for r in rels:
            self._write(r, BOOK_TEXT if r.count("/") == 1 else EPISODE_TEXT)
        self._write_manifest({"PHASE_1_NOW": rels})
        self.app.refresh_file_list(force=True)
        for node in self.app.tree.get_children(""):
            self.app.tree.item(node, open=True)
        self.root.update()

    def _row(self, rel=None, group=None):
        """The tree row for a file (by its path) or a group (by its folder name)."""
        want = ("GROUP:" + group) if group else os.path.join(self.app.data_root, rel.replace("/", os.sep))
        def walk(parent):
            for child in self.app.tree.get_children(parent):
                vals = self.app.tree.item(child, "values")
                if vals and os.path.normcase(str(vals[0])) == os.path.normcase(want):
                    return child
                hit = walk(child)
                if hit:
                    return hit
            return None
        row = walk("")
        self.assertIsNotNone(row, f"no tree row for {rel or group}")
        return row

    def _y(self, row, half):
        self.app.tree.see(row)
        self.root.update()
        x, y, w, h = self.app.tree.bbox(row)
        return x + 20, (y + 2) if half == "top" else (y + h - 2)

    def _press(self, row, half="top", state=0):
        x, y = self._y(row, half)
        self.app.tree.event_generate("<ButtonPress-1>", x=x, y=y, state=state)
        self.app.tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=state)
        self.root.update()

    def _drag(self, src_row, dst_row, half):
        """A real drag: press on src, move, release on the given half of dst."""
        x0, y0 = self._y(src_row, "top")
        self.app.tree.event_generate("<ButtonPress-1>", x=x0, y=y0)
        x1, y1 = self._y(dst_row, half)
        self.app.tree.event_generate("<B1-Motion>", x=x1, y=y1)
        self.app.tree.event_generate("<ButtonRelease-1>", x=x1, y=y1)
        self.root.update()

    def _pump(self, seconds=0.25):
        """Let after() callbacks (the focus refresh is deferred 100 ms) run."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.01)

    def _focus_event(self, widget):
        return SimpleNamespace(widget=widget)


class TestA1OneRefreshNoWalk(LayerATestBase):

    def test_a_drag_refreshes_once_and_never_walks_the_disk(self):
        """The drag used to refresh twice (move_manifest_items_relative, then on_drag_stop), and
        every refresh walked all three tiers. Now: one refresh, zero syncs — and the move lands."""
        rels = ["HighPriority/本.txt", f"HighPriority/{SERIES}/第01話.txt", f"HighPriority/{SERIES}/第02話.txt"]
        self._library(rels)
        real_refresh, real_sync = self.app.refresh_file_list, self.app._sync_disk_to_manifest
        calls = {"refresh": 0, "sync": 0}
        def refresh(*a, **k):
            calls["refresh"] += 1
            return real_refresh(*a, **k)
        def sync(*a, **k):
            calls["sync"] += 1
            return real_sync(*a, **k)
        with patch.object(self.app, "refresh_file_list", side_effect=refresh), \
             patch.object(self.app, "_sync_disk_to_manifest", side_effect=sync):
            self._drag(self._row("HighPriority/本.txt"), self._row(f"HighPriority/{SERIES}/第02話.txt"), "bottom")
            self._pump()   # a focus event the press caused (inner widget) must not add a refresh
        self.assertEqual(calls, {"refresh": 1, "sync": 0})
        self.assertEqual(self._now_paths(), rels[1:] + rels[:1])

    def test_a_tab_switch_does_not_walk_the_disk(self):
        self._library(["HighPriority/本.txt"])
        with patch.object(self.app, "_sync_disk_to_manifest") as sync:
            self.app.notebook.select(1)
            self.root.update()
            self.app.notebook.select(0)
            self.root.update()
        sync.assert_not_called()

    def test_samples_flow_registers_its_files(self):
        """'Test with samples' copies files into the tiers; nothing would list them without its sync."""
        with patch.dict(os.environ, {"SURASURA_TEST_ROOT": self._root_dir}):   # this window's root
            self.app._seed_samples_clicked()
        now = self._now_paths()
        self.assertTrue(now, "the samples must be in NOW's manifest")
        self.assertTrue(self.app.tree.get_children(""), "and drawn")

    def test_pasted_text_flow_registers_its_file(self):
        self.app._save_pasted_text("貼り付けた文章", BOOK_TEXT, "HighPriority")
        self.assertIn("HighPriority/貼り付けた文章.txt", self._now_paths())
        self._row("HighPriority/貼り付けた文章.txt")

    def test_youtube_flow_registers_its_transcripts(self):
        processed = os.path.join(self.app.data_root, "Processed", "YouTube")
        os.makedirs(processed, exist_ok=True)
        src = os.path.join(processed, "日本語の動画.ja.srt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\n今日はいい天気ですね。\n")
        self.app._on_youtube_downloaded([src])
        self.assertIn("HighPriority/日本語の動画.ja.srt", self._now_paths())
        self._row("HighPriority/日本語の動画.ja.srt")

    def test_splicer_flow_registers_its_output_when_focus_returns(self):
        """The splicer is another process: its output is picked up when focus comes back — even if
        Tk hands that FocusIn to an inner widget first (the launched-tool case is not filtered)."""
        with patch("app.content_importer_gui.subprocess.Popen"):
            self.app.open_splicer()
        self._write("HighPriority/分割した本.txt", BOOK_TEXT)   # what the splicer writes
        self.app._on_focus_in(self._focus_event(self.app.tree))
        self._pump()
        self.assertIn("HighPriority/分割した本.txt", self._now_paths())
        self._row("HighPriority/分割した本.txt")

    def test_hato_drop_lands_at_the_top_of_now_on_focus(self):
        self._library(["HighPriority/本.txt", f"HighPriority/{SERIES}/第01話.txt"])
        self._write("HighPriority/Hato/鳩のメモ.txt", BOOK_TEXT)    # hato writes; the window is open
        self.app._on_focus_in(self._focus_event(self.root))
        self._pump()
        self.assertEqual(self._now_paths()[0], "HighPriority/Hato/鳩のメモ.txt")
        first = self.app.tree.get_children("")[0]
        self.assertEqual(self.app.tree.item(first, "values")[0], "GROUP:Hato")
        # A second drop goes into the Hato group, still at the top.
        self._write("HighPriority/Hato/鳩のメモ2.txt", BOOK_TEXT)
        self.app._on_focus_in(self._focus_event(self.root))
        self._pump()
        self.assertEqual(self._now_paths()[:2], ["HighPriority/Hato/鳩のメモ.txt", "HighPriority/Hato/鳩のメモ2.txt"])

    def test_hato_drop_lands_at_the_top_of_now_on_open(self):
        self._library(["HighPriority/本.txt"])
        self._write("HighPriority/Hato/鳩のメモ.txt", BOOK_TEXT)    # hato wrote while it was closed
        self.app._initial_load()                                   # what opening the window runs
        self.assertEqual(self._now_paths()[0], "HighPriority/Hato/鳩のメモ.txt")


class TestA2FocusHandler(LayerATestBase):

    def test_one_focus_handler_and_it_force_refreshes(self):
        """Two `_on_focus_in` defs: the later one shadowed the force-refresh. One def is left."""
        import inspect
        from app import content_importer_gui
        src = inspect.getsource(content_importer_gui.ContentImporterApp)
        self.assertEqual(src.count("def _on_focus_in("), 1)

    def test_outside_manifest_write_then_focus_shows_it(self):
        """An outside writer reorders the manifest without moving its mtime (the fast path's key);
        focus returning must still rebuild from it."""
        rels = ["HighPriority/本.txt", "HighPriority/漫画.txt", "HighPriority/小説.txt"]
        self._library(rels)
        path = self.app.get_manifest_path()
        st = os.stat(path)
        self._write_manifest({"PHASE_1_NOW": list(reversed(rels))})
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.app._on_focus_in(self._focus_event(self.root))
        self._pump()
        drawn = [self.app.tree.item(r, "text") for r in self.app.tree.get_children("")]
        self.assertEqual(drawn, ["小説.txt", "漫画.txt", "本.txt"])

    def test_up_on_a_changed_row_acts_on_the_fresh_order(self):
        rels = ["HighPriority/本.txt", "HighPriority/漫画.txt", "HighPriority/小説.txt"]
        self._library(rels)
        self._write_manifest({"PHASE_1_NOW": list(reversed(rels))})   # 小説, 漫画, 本
        self.app._on_focus_in(self._focus_event(self.root))
        self._pump()
        self.app.tree.selection_set(self._row("HighPriority/本.txt"))
        self.app.move_selected_up()
        self.assertEqual(self._now_paths(), ["HighPriority/小説.txt", "HighPriority/本.txt", "HighPriority/漫画.txt"])

    def test_focus_moving_between_inner_widgets_does_not_refresh(self):
        """<FocusIn> bound on the root fires for every inner widget through the bindtags — a real
        event on the tree reaches the root's binding with event.widget = the tree."""
        self._library(["HighPriority/本.txt"])
        with patch.object(self.app, "refresh_file_list") as refresh:
            self.app.tree.event_generate("<FocusIn>")
            self._pump()
            refresh.assert_not_called()
            self.app._on_focus_in(self._focus_event(self.root))   # the window's own: refreshes
            self._pump()
            refresh.assert_called_once_with(force=True, sync=True)

    def test_focus_is_ignored_while_a_dialog_of_ours_is_open(self):
        from app import content_importer_gui as ci

        def dialog(*args, **kwargs):
            self.app._on_focus_in(self._focus_event(self.root))
            return True
        with patch.object(self.app, "refresh_file_list") as refresh,                 patch("tkinter.messagebox.askyesno", side_effect=dialog):
            self.assertTrue(ci.messagebox.askyesno("確認", "「本.txt」を移動しますか？"))
            self._pump()
            refresh.assert_not_called()

    def _dialog_queues_focus_in(self, *args, **kwargs):
        """A dialog of ours closing: Windows hands the window its focus back — a real FocusIn, queued behind it."""
        self.root.event_generate("<FocusIn>", when="tail")
        return True

    def test_the_focus_a_closing_dialog_hands_back_does_not_refresh(self):
        """The adversary's finding 6: every dialog closing fired a focus refresh after its action's own refresh
        (two rebuilds and a disk walk per Remove / Add / Reset). Real events: the FocusIn queued as the
        confirmation closes runs after the action, and refreshes nothing; the user coming back later still does."""
        from app import content_importer_gui as ci
        self._library(["HighPriority/本.txt"])
        with patch.object(self.app, "_refresh_from_focus") as refresh,                 patch("tkinter.messagebox.askyesno", side_effect=self._dialog_queues_focus_in),                 patch("tkinter.filedialog.askopenfilenames", side_effect=self._dialog_queues_focus_in):
            ci.messagebox.askyesno("確認", "「本.txt」を移動しますか？")
            self._pump()
            refresh.assert_not_called()
            ci.filedialog.askopenfilenames(title="ファイルを選ぶ")
            self._pump()
            refresh.assert_not_called()
            self.root.event_generate("<FocusIn>", when="tail")          # back from Explorer
            self._pump()
            refresh.assert_called_once_with()

    def test_a_real_demote_refreshes_once(self):
        """Through the action itself: Demote's confirmation closes, the move refreshes, and the FocusIn the
        confirmation handed back adds no second refresh."""
        self._library(["HighPriority/本.txt", "HighPriority/漫画.txt"])
        self.app.tree.selection_set(self._row("HighPriority/本.txt"))
        with patch.object(self.app, "_refresh_from_focus") as refresh,                 patch("tkinter.messagebox.askyesno", side_effect=self._dialog_queues_focus_in):
            self.app.demote_content()
            self._pump()
            refresh.assert_not_called()
        self.assertTrue(os.path.exists(os.path.join(self.app.data_root, "LowPriority", "本.txt")))

    def test_the_paste_dialog_closing_does_not_refresh_but_a_return_while_it_is_open_does(self):
        with patch.object(self.app, "_refresh_from_focus") as refresh:
            self.app.paste_text_dialog()
            self.root.update()
            dlg = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Paste text"][0]
            self.root.event_generate("<FocusIn>", when="tail")          # back to the main window, dialog open
            self._pump()
            refresh.assert_called_once_with()
            refresh.reset_mock()
            dlg.destroy()
            self.root.event_generate("<FocusIn>", when="tail")          # the focus its closing hands back
            self._pump()
            refresh.assert_not_called()


class TestA7SelfDropAndModifiers(LayerATestBase):

    def _series_library(self):
        rels = [f"HighPriority/{SERIES}/第01話.txt", f"HighPriority/{SERIES}/第02話.txt",
                f"HighPriority/{SERIES}/第03話.txt", "HighPriority/本.txt"]
        self._library(rels)
        return rels

    def test_last_episode_dropped_below_its_own_group_changes_nothing(self):
        rels = self._series_library()
        with open(self.app.get_manifest_path(), "rb") as f:
            before = f.read()
        self._drag(self._row(rels[2]), self._row(group=SERIES), "bottom")
        self.assertEqual(self._now_paths(), rels)
        with open(self.app.get_manifest_path(), "rb") as f:
            self.assertEqual(f.read(), before, "no write at all")

    def test_group_dropped_on_its_own_episode_changes_nothing(self):
        rels = self._series_library()
        grp = self._row(group=SERIES)
        x, y = self._y(grp, "top")
        # Press on the group header (selects it), then release below its own second episode.
        self.app.tree.event_generate("<ButtonPress-1>", x=x, y=y)
        x1, y1 = self._y(self._row(rels[1]), "bottom")
        self.app.tree.event_generate("<B1-Motion>", x=x1, y=y1)
        self.app.tree.event_generate("<ButtonRelease-1>", x=x1, y=y1)
        self.root.update()
        self.assertEqual(self._now_paths(), rels)

    def test_an_episode_dropped_above_its_own_group_still_moves(self):
        """Judging by file must not block a real move inside the group."""
        rels = self._series_library()
        self._drag(self._row(rels[2]), self._row(group=SERIES), "top")
        self.assertEqual(self._now_paths(), [rels[2], rels[0], rels[1], rels[3]])

    def _drag_with(self, rels_selected_first, ctrl_row, dst_row, half):
        """Select the first rows, then begin the drag with a Ctrl-press on one more (a drag of several rows)."""
        self._press(self._row(rels_selected_first))
        x0, y0 = self._y(ctrl_row, "top")
        self.app.tree.event_generate("<ButtonPress-1>", x=x0, y=y0, state=0x0004)
        x1, y1 = self._y(dst_row, half)
        self.app.tree.event_generate("<B1-Motion>", x=x1, y=y1, state=0x0004)
        self.app.tree.event_generate("<ButtonRelease-1>", x=x1, y=y1, state=0x0004)
        self.root.update()

    def test_a_loose_file_dropped_below_a_group_with_its_last_episode_still_moves(self):
        """The adversary's finding 8: the last episode and a loose file dropped below the group — the near
        edge was being moved, so the whole drop was refused and the loose file stayed. Now the group's own
        episode stays where it is and the loose file lands below the group."""
        rels = ["HighPriority/本.txt", f"HighPriority/{SERIES}/第01話.txt", f"HighPriority/{SERIES}/第02話.txt",
                f"HighPriority/{SERIES}/第03話.txt"]
        self._library(rels)
        self._drag_with(rels[0], self._row(rels[3]), self._row(group=SERIES), "bottom")
        self.assertEqual(len(self.app.tree.selection()), 2)
        self.assertEqual(self._now_paths(), rels[1:] + rels[:1])

    def test_a_loose_file_dropped_above_a_group_with_its_first_episode_still_moves(self):
        rels = [f"HighPriority/{SERIES}/第01話.txt", f"HighPriority/{SERIES}/第02話.txt",
                f"HighPriority/{SERIES}/第03話.txt", "HighPriority/本.txt"]
        self._library(rels)
        self._drag_with(rels[3], self._row(rels[0]), self._row(group=SERIES), "top")
        self.assertEqual(self._now_paths(), rels[3:] + rels[:3])

    def test_ctrl_click_selects_two_rows(self):
        rels = self._series_library()
        self._press(self._row(rels[0]))
        self._press(self._row(rels[2]), state=0x0004)          # Control
        sel = {self.app.tree.item(i, "values")[0] for i in self.app.tree.selection()}
        self.assertEqual({os.path.normcase(p) for p in sel},
                         {os.path.normcase(os.path.join(self.app.data_root, r.replace("/", os.sep)))
                          for r in (rels[0], rels[2])})

    def test_shift_click_extends_the_selection(self):
        rels = self._series_library()
        self._press(self._row(rels[0]))
        self._press(self._row(rels[2]), state=0x0001)          # Shift
        self.assertEqual(len(self.app.tree.selection()), 3)


if __name__ == "__main__":
    unittest.main()
