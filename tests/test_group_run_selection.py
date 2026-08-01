"""Fragmented folders in the Content Manager library tree.

The manifest orders content independently of the folders on disk — deliberately, so a library can be
ordered without moving a single file. Because every path that adds or relocates content APPENDS to
the end of a phase (Graduate, Demote, add_files, the disk sync), one folder's files routinely end up
in several non-contiguous runs. The tree draws a node per RUN, so several nodes can share a name.

That exposed a real bug: `_restore_selection` matched nodes by their `GROUP:<name>` value, which is
identical across every run of a folder — so moving one run selected them ALL, and the next press
really did move the lot. Runs now carry a stable id and the label says which run it is.

Real Japanese content per docs/agent instructions/testing.md.

ONE Tk root and ONE app for the whole module, reset between tests. A full Content Manager is a few
hundred widgets (notebook + a Treeview per tier + toolbar); building one per test method consumed
Windows USER/GDI handles fast enough to take the desktop down mid-suite. The library is cleared and
rewritten in setUp instead, which gives the same isolation for a fraction of the cost.
"""

import gc
import json
import os
import shutil
import tempfile
import unittest
import tkinter as tk


# Real sentences, not ASCII filler — the tree stores titles and paths that must survive round-tripping.
EPISODE_TEXT = "冒険だ。\n彼は毎日冒険に出かけます。\n私たちは新しい冒険を求めている。\n"
BOOK_TEXT = "今日はいい天気ですね。\n本を読むのが好きです。\n図書館で勉強しました。\n"

TIERS = ("HighPriority", "LowPriority", "GoalContent")


class TestFragmentedGroupRuns(unittest.TestCase):

    # --- one GUI for the whole module ---------------------------------------------------------
    @classmethod
    def setUpClass(cls):
        cls._root_dir = tempfile.mkdtemp()
        os.environ["SURASURA_TEST_ROOT"] = cls._root_dir
        from app.content_importer_gui import ContentImporterApp
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.app = ContentImporterApp(cls.root, language="ja")

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
        # Isolation without a new GUI: empty the tiers so a previous test's files can't be picked
        # up by _sync_disk_to_manifest, then start from an empty manifest.
        for tier in TIERS:
            d = os.path.join(self.app.data_root, tier)
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
        self._write_manifest({})
        self.app.refresh_file_list(force=True)

    # --- fixture helpers ---------------------------------------------------------------------
    def _write(self, rel, text=EPISODE_TEXT):
        """Create a content file under data/ja/ at `rel` (e.g. 'HighPriority/Bleach/ep01.srt')."""
        path = os.path.join(self.app.data_root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _entry(self, rel):
        parts = rel.split("/")
        parent = "/".join(parts[1:-1]) if len(parts) > 2 else ""
        return {
            "title": parts[-1],
            "physical_path": rel,
            "parent_folder": parent,
            "origin_source": "Manual Import",
            "type": "File",
            "status": "New",
        }

    def _write_manifest(self, phases):
        data = {"schedule": {"PHASE_1_NOW": [], "PHASE_2_SOON": [], "PHASE_3_LATER": []}}
        for phase, rels in phases.items():
            data["schedule"][phase] = [self._entry(r) for r in rels]
        with open(self.app.get_manifest_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _manifest(self, rels, phase="PHASE_1_NOW"):
        """Write a manifest ordering exactly `rels`, then render it."""
        self._write_manifest({phase: rels})
        self.app.refresh_file_list(force=True)

    def _top_labels(self):
        return [self.app.tree.item(i, "text") for i in self.app.tree.get_children("")]

    def _phase(self, phase="PHASE_1_NOW"):
        with open(self.app.get_manifest_path(), encoding="utf-8") as f:
            return [e["physical_path"] for e in json.load(f)["schedule"][phase]]

    def _fragmented_library(self):
        """Bleach split by a loose file: run 1 = ep01+ep02, run 2 = ep03."""
        for rel in ("HighPriority/Bleach/ep01.srt", "HighPriority/Bleach/ep02.srt",
                    "HighPriority/Bleach/ep03.srt"):
            self._write(rel)
        self._write("HighPriority/loose.txt", BOOK_TEXT)
        self._manifest([
            "HighPriority/Bleach/ep01.srt",
            "HighPriority/Bleach/ep02.srt",
            "HighPriority/loose.txt",
            "HighPriority/Bleach/ep03.srt",
        ])

    # --- labels -------------------------------------------------------------------------------
    def test_fragmented_folder_draws_a_node_per_run_and_says_which(self):
        """The old label claimed to be the whole folder, twice over. It now says '1 of 2'."""
        self._fragmented_library()
        self.assertEqual(self._top_labels(),
                         ["Bleach  (1 of 2)", "loose.txt", "Bleach  (2 of 2)"])

    def test_contiguous_folder_keeps_its_plain_name(self):
        """No suffix when there's nothing to disambiguate — the common case must look unchanged."""
        for rel in ("HighPriority/Bleach/ep01.srt", "HighPriority/Bleach/ep02.srt"):
            self._write(rel)
        self._write("HighPriority/loose.txt", BOOK_TEXT)
        self._manifest(["HighPriority/Bleach/ep01.srt",
                        "HighPriority/Bleach/ep02.srt",
                        "HighPriority/loose.txt"])
        self.assertEqual(self._top_labels(), ["Bleach", "loose.txt"])

    def test_group_value_is_unchanged_so_selection_resolution_still_works(self):
        """Only the id and the label are new. Drag-drop, double-click and Graduate/Demote all key
        off values[0], so decorating the label must not leak into it."""
        self._fragmented_library()
        for node in self.app.tree.get_children(""):
            if self.app.tree.get_children(node):     # a group node
                self.assertEqual(self.app.tree.item(node, "values")[0], "GROUP:Bleach")

    def test_a_manifest_row_whose_file_is_missing_does_not_desync_run_counts(self):
        """Rows are skipped when the file is gone. The run counter and the insert loop must agree
        about that, or the labels would count runs that are never drawn."""
        self._write("HighPriority/Bleach/ep01.srt")
        self._write("HighPriority/Bleach/ep02.srt")
        self._write("HighPriority/loose.txt", BOOK_TEXT)
        self._manifest([
            "HighPriority/Bleach/ep01.srt",
            "HighPriority/loose.txt",             # splits Bleach...
            "HighPriority/Bleach/ep02.srt",
            "HighPriority/Bleach/ghost.srt",      # ...but this row has no file on disk
        ])
        self.assertEqual(self._top_labels(), ["Bleach  (1 of 2)", "loose.txt", "Bleach  (2 of 2)"])

    def test_unique_iid_decides_against_a_set_not_the_tree(self):
        """This one killed whole test runs.

        _unique_tree_iid used to loop on `self.tree.exists(...)`. Several tests replace self.tree
        with a MagicMock, whose exists() returns a truthy Mock — so the loop never terminated, and
        every iteration allocated another recorded mock call until the process died of MemoryError
        mid-suite (taking pytest's own error reporting down with it).

        Deciding uniqueness against a plain set makes non-termination impossible: the set grows by
        exactly one per call, so the search always ends. Asserting it is a *staticmethod* pins the
        structural property — with no `self`, it cannot reach the tree at all."""
        import inspect
        from app.content_importer_gui import ContentImporterApp

        self.assertIsInstance(
            inspect.getattr_static(ContentImporterApp, "_unique_tree_iid"), staticmethod,
            "_unique_tree_iid must not take self, so it cannot query the tree")

        used = set()
        ids = [ContentImporterApp._unique_tree_iid("grp:HighPriority/Bleach/ep01.srt", used)
               for _ in range(3)]
        self.assertEqual(ids, ["grp:HighPriority/Bleach/ep01.srt",
                               "grp:HighPriority/Bleach/ep01.srt#1",
                               "grp:HighPriority/Bleach/ep01.srt#2"])
        self.assertEqual(len(used), 3, "every id handed out must be recorded")

    def test_duplicate_physical_path_does_not_crash_the_tree(self):
        """Tree ids must be unique or Tk raises. The manifest is also written by the Immersion
        Architect and is hand-editable, so a duplicated row must degrade, not take the window down."""
        self._write("HighPriority/Bleach/ep01.srt")
        self._write("HighPriority/loose.txt", BOOK_TEXT)
        self._manifest([
            "HighPriority/Bleach/ep01.srt",
            "HighPriority/loose.txt",
            "HighPriority/Bleach/ep01.srt",   # same path again -> same candidate id
        ])
        self.assertEqual(len(self._top_labels()), 3, "all three rows should still render")
        self.assertEqual(len(set(self.app.tree.get_children(""))), 3, "ids must be unique")

    # --- selection ----------------------------------------------------------------------------
    def test_moving_one_run_leaves_only_that_run_selected(self):
        """The reported bug: after moving, every node sharing the folder name lit up."""
        self._fragmented_library()
        second_run = self.app.tree.get_children("")[2]
        self.assertEqual(self.app.tree.item(second_run, "text"), "Bleach  (2 of 2)")

        self.app.tree.selection_set(second_run)
        self.app.move_selected_up()

        selected = self.app.tree.selection()
        self.assertEqual(len(selected), 1,
                         "only the moved run should stay selected, not every run of the folder")
        self.assertIn("Bleach", self.app.tree.item(selected[0], "text"))

    def test_moving_one_run_does_not_drag_the_other_run_with_it(self):
        """Selection was the visible symptom; this guards the underlying order. ep03 moves above the
        loose file; ep01/ep02 stay where they were."""
        self._fragmented_library()
        self.app.tree.selection_set(self.app.tree.get_children("")[2])
        self.app.move_selected_up()

        self.assertEqual(self._phase(), [
            "HighPriority/Bleach/ep01.srt",
            "HighPriority/Bleach/ep02.srt",
            "HighPriority/Bleach/ep03.srt",
            "HighPriority/loose.txt",
        ])

    def test_moving_a_loose_file_still_restores_by_path(self):
        """File rows keep Tk's generated ids, which do not survive a rebuild — they fall back to
        matching their value, which is safe because a file's value is its unique absolute path."""
        self._fragmented_library()
        loose = self.app.tree.get_children("")[1]
        self.assertEqual(self.app.tree.item(loose, "text"), "loose.txt")

        self.app.tree.selection_set(loose)
        self.app.move_selected_up()

        selected = self.app.tree.selection()
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.app.tree.item(selected[0], "text"), "loose.txt")

    def test_a_contiguous_group_still_restores_after_a_move(self):
        """Regression guard for the ordinary case — the fix must not break the unfragmented path."""
        for rel in ("HighPriority/Bleach/ep01.srt", "HighPriority/Bleach/ep02.srt"):
            self._write(rel)
        self._write("HighPriority/loose.txt", BOOK_TEXT)
        self._manifest(["HighPriority/loose.txt",
                        "HighPriority/Bleach/ep01.srt",
                        "HighPriority/Bleach/ep02.srt"])
        self.app.tree.selection_set(self.app.tree.get_children("")[1])
        self.app.move_selected_up()

        selected = self.app.tree.selection()
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.app.tree.item(selected[0], "text"), "Bleach")
        self.assertEqual(self._phase()[0], "HighPriority/Bleach/ep01.srt")

    # --- drag and drop ------------------------------------------------------------------------
    def _drag(self, source_node, target_node, region="above"):
        """Drive on_drag_stop without real mouse geometry.

        identify_row/_get_drop_region are the only things that need a pointer; everything the fix
        touches (which entries move, and what they land against) is downstream of them."""
        self.app.tree.selection_set(source_node)
        self.app._drag_item = source_node
        self.app.tree.identify_row = lambda y: target_node
        self.app._get_drop_region = lambda item, y: region
        try:
            self.app.on_drag_stop(type("_Ev", (), {"y": 0})())
        finally:
            del self.app.tree.identify_row
            del self.app._get_drop_region

    def _split_with_two_loose_files(self):
        """[a_loose, ep01, ep02, m_loose, ep03] — Bleach in two runs, separated by a loose file."""
        for rel in ("HighPriority/Bleach/ep01.srt", "HighPriority/Bleach/ep02.srt",
                    "HighPriority/Bleach/ep03.srt"):
            self._write(rel)
        self._write("HighPriority/a_loose.txt", BOOK_TEXT)
        self._write("HighPriority/m_loose.txt", BOOK_TEXT)
        self._manifest([
            "HighPriority/a_loose.txt",
            "HighPriority/Bleach/ep01.srt",
            "HighPriority/Bleach/ep02.srt",
            "HighPriority/m_loose.txt",
            "HighPriority/Bleach/ep03.srt",
        ])

    def test_dragging_one_run_moves_only_that_run(self):
        """Drag-drop used to pass the raw "GROUP:<name>" cell value to the manifest move, which
        matches on parent_folder and therefore selected EVERY run of the folder — so dragging the
        second block silently dragged the first one with it. The arrow keys never did this, and two
        paths behaving differently is worse than both being wrong."""
        self._split_with_two_loose_files()
        nodes = self.app.tree.get_children("")
        a_loose, run2 = nodes[0], nodes[3]
        self.assertEqual(self.app.tree.item(run2, "text"), "Bleach  (2 of 2)")

        self._drag(run2, a_loose, region="above")

        self.assertEqual(self._phase(), [
            "HighPriority/Bleach/ep03.srt",     # only run 2 moved to the front
            "HighPriority/a_loose.txt",
            "HighPriority/Bleach/ep01.srt",     # run 1 stayed exactly where it was
            "HighPriority/Bleach/ep02.srt",
            "HighPriority/m_loose.txt",
        ])

    def test_dropping_onto_a_run_lands_against_that_run(self):
        """The target had the same fault: a "GROUP:" drop target expands to every run, so dropping
        just above the SECOND block inserted before the FIRST one."""
        self._split_with_two_loose_files()
        nodes = self.app.tree.get_children("")
        run2, m_loose = nodes[3], nodes[2]
        self.assertEqual(self.app.tree.item(m_loose, "text"), "m_loose.txt")

        self._drag(m_loose, run2, region="above")

        self.assertEqual(self._phase(), [
            "HighPriority/a_loose.txt",
            "HighPriority/Bleach/ep01.srt",
            "HighPriority/Bleach/ep02.srt",
            "HighPriority/m_loose.txt",         # landed against run 2, not before run 1
            "HighPriority/Bleach/ep03.srt",
        ])

    def test_dragging_a_loose_file_still_works(self):
        """Regression guard for the ordinary, unfragmented drag."""
        self._split_with_two_loose_files()
        nodes = self.app.tree.get_children("")
        a_loose, m_loose = nodes[0], nodes[2]

        self._drag(m_loose, a_loose, region="above")
        self.assertEqual(self._phase()[0], "HighPriority/m_loose.txt")

    # --- expansion ----------------------------------------------------------------------------
    def test_expanding_one_run_does_not_expand_the_other(self):
        """Expansion used to be remembered by LABEL, so every run of a folder opened together.
        Keyed on the node id, each run remembers its own state."""
        self._fragmented_library()
        first, _, second = self.app.tree.get_children("")
        self.app.tree.item(first, open=True)
        self.app.tree.item(second, open=False)

        self.app.refresh_file_list(force=True)

        first, _, second = self.app.tree.get_children("")
        self.assertTrue(self.app.tree.item(first, "open"), "the expanded run should stay expanded")
        self.assertFalse(self.app.tree.item(second, "open"), "the other run should stay collapsed")

    def test_expansion_survives_a_label_that_carries_a_run_suffix(self):
        """The label is now decorated; a name-keyed memory would silently stop matching."""
        self._fragmented_library()
        first = self.app.tree.get_children("")[0]
        self.assertIn("(1 of 2)", self.app.tree.item(first, "text"))
        self.app.tree.item(first, open=True)

        self.app.refresh_file_list(force=True)
        self.assertTrue(self.app.tree.item(self.app.tree.get_children("")[0], "open"))

    # --- run scope (Graduate / Demote) --------------------------------------------------------
    def test_resolving_a_run_yields_only_that_runs_files(self):
        """Graduate and Demote resolve through _resolve_items_to_paths, which walks the selected
        node's CHILDREN — keeping them scoped to the clicked run. Worth pinning, because the
        manifest/disk separation means a folder's files can live in several runs."""
        self._fragmented_library()
        first, _, second = self.app.tree.get_children("")

        self.assertEqual([os.path.basename(p) for p in self.app._resolve_items_to_paths([first])],
                         ["ep01.srt", "ep02.srt"])
        self.assertEqual([os.path.basename(p) for p in self.app._resolve_items_to_paths([second])],
                         ["ep03.srt"])

    def test_resolution_stays_in_display_order(self):
        """Graduate/Demote re-append files in exactly this order, so it IS the resulting library
        order — a set() here once reshuffled the inside of every moved group."""
        self._fragmented_library()
        first = self.app.tree.get_children("")[0]
        children = list(self.app.tree.get_children(first))
        self.assertEqual(self.app._resolve_items_to_paths([first]),
                         [self.app.tree.item(c, "values")[0] for c in children])


if __name__ == "__main__":
    unittest.main()
