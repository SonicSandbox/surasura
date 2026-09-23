"""Bulk Remove / Graduate / Demote must stay linear (Bugfix_Batch_2026-09-22_Spec.md, Fix B).

Measured on a real Content Manager window: removing 400 of 800 files took 33 s and each doubling cost
~3.6x — a 3,000-file selection froze the window for 10-25 minutes ("Not Responding"). The loops loaded
and saved the whole manifest once or twice PER FILE, and Remove also rebuilt the tree per file. Now the
loops only move files; the manifest is saved once and the tree refreshed once, errors are reported in
one dialog, and the confirmation counts files instead of tree rows.

Headless Content Manager, built like tests/test_library_file_safety.py, on a real data/ + User Files/
layout filled with real Japanese episode text.
"""

import json
import os
import shutil
import time
from unittest.mock import MagicMock, patch

import pytest

from app.content_importer_gui import ContentImporterApp


class MockStringVar:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


@pytest.fixture(autouse=True)
def mock_messagebox():
    with patch("app.content_importer_gui.messagebox") as mock:
        mock.askyesno.return_value = True
        yield mock


@pytest.fixture
def cm(tmp_path):
    data_root = tmp_path / "data" / "ja"
    for sub in ("HighPriority", "LowPriority", "GoalContent", "Graduated", ".trash"):
        (data_root / sub).mkdir(parents=True)
    user_files = tmp_path / "User Files" / "ja"
    user_files.mkdir(parents=True)

    with patch.object(ContentImporterApp, "__init__", lambda self, root, language='ja': None):
        app = ContentImporterApp(None, language="ja")
        app.root = MagicMock()
        app.data_root = str(data_root)
        app.user_files_root = str(user_files)
        app.language = "ja"
        app.target_folder_var = MockStringVar("HighPriority")
        app.status_var = MockStringVar()
        app.tree = MagicMock()
        app.graduate_btn = MagicMock()
        app.undo_btn = MagicMock()
        app.analyzed_filenames = set()
        app._last_stats_mtime = 0
        app._last_stats_size = 0
        app.last_action = None
        return app


# Real subtitle / prose lines — the shapes a learner's library holds.
LINES = [
    "また会えるとは思わなかった。",
    "この街には、まだ秘密が残っている。",
    "吾輩は猫である。名前はまだ無い。",
    "どこで生れたかとんと見当がつかぬ。",
    "少年は静かに扉を開けた。廊下には誰もいなかった。",
    "朝の光が窓から差し込んでいる。彼女はまだ眠っていた。",
    "「もう一度だけ、話を聞かせてくれないか」と彼は言った。",
    "雨が降り始めた。傘を持っていないことに気づいた。",
]

PHASE = {"HighPriority": "PHASE_1_NOW", "LowPriority": "PHASE_2_SOON", "GoalContent": "PHASE_3_LATER"}

# (operation, the tier it runs in, where the files land — None: the trash)
OPERATIONS = [
    pytest.param("remove_files", "HighPriority", None, id="remove"),
    pytest.param("graduate_content", "LowPriority", "HighPriority", id="graduate"),
    pytest.param("demote_content", "HighPriority", "LowPriority", id="demote"),
]


def _library(tmp_path, tier, folders, per_folder):
    """<tier>/シリーズNN/第NNN話.txt of real text. Returns the absolute paths, folder by folder."""
    paths = []
    for f in range(folders):
        folder = tmp_path / "data" / "ja" / tier / f"シリーズ{f:02d}"
        folder.mkdir(parents=True)
        for i in range(per_folder):
            p = folder / f"第{i:03d}話.txt"
            p.write_text(LINES[(f + i) % len(LINES)] + "\n", encoding="utf-8")
            paths.append(str(p))
    return paths


def _rel(cm, path):
    return os.path.relpath(path, cm.data_root).replace("\\", "/")


def _write_manifest(cm, phases):
    """Write the library order directly — {phase: [absolute paths, in order]} — so the test controls
    it exactly (and doesn't depend on the helpers under test)."""
    schedule = {"PHASE_1_NOW": [], "PHASE_2_SOON": [], "PHASE_3_LATER": []}
    for phase, paths in phases.items():
        for p in paths:
            parts = _rel(cm, p).split("/")
            schedule[phase].append({"title": parts[-1], "physical_path": "/".join(parts),
                                    "parent_folder": "/".join(parts[1:-1]),
                                    "origin_source": "Manual Import", "type": "File", "status": "New"})
    with open(cm.get_manifest_path(), "w", encoding="utf-8") as f:
        json.dump({"schedule": schedule}, f, ensure_ascii=False, indent=2)


def _phase(cm, key):
    with open(cm.get_manifest_path(), "r", encoding="utf-8") as f:
        return [e["physical_path"] for e in json.load(f)["schedule"].get(key, [])]


def _run(cm, op, paths, tier):
    """Select `paths` (as the resolved selection) in `tier` and run the operation."""
    cm.target_folder_var.set(tier)
    cm.tree.selection.return_value = ["row"]
    with patch.object(cm, "_resolve_items_to_paths", return_value=[str(p) for p in paths]):
        getattr(cm, op)()


def _wire_group_selection(cm, group_name, child_paths):
    """Point the mocked tree at ONE folder row whose children are `child_paths` — the real
    _resolve_items_to_paths then expands it, as it does for a click on a folder."""
    child_ids = [f"c{i}" for i in range(len(child_paths))]
    by_id = dict(zip(child_ids, child_paths))

    def get_children(parent=""):
        if parent == "":
            return ["grp"]
        return child_ids if parent == "grp" else []

    def tree_item(item_id, option=None, **kwargs):
        if option == "values":
            if item_id == "grp":
                return ["GROUP:" + group_name]
            return [by_id[item_id]] if item_id in by_id else []
        return {}

    cm.tree.selection.return_value = ["grp"]
    cm.tree.get_children.side_effect = get_children
    cm.tree.item.side_effect = tree_item


# ---------------------------------------------------------------------------------------------- #
# The manifest is written once and the tree rebuilt once, however many files move
# ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_moving_many_files_saves_the_manifest_once_and_refreshes_once(cm, tmp_path, op, tier, dest):
    """Per-file saves and refreshes are what made these quadratic. Remove saved and refreshed once
    per file; Graduate and Demote saved twice per file (a remove, then an add)."""
    paths = _library(tmp_path, tier, folders=3, per_folder=20)
    _write_manifest(cm, {PHASE[tier]: paths})

    with patch.object(cm, "save_manifest", wraps=cm.save_manifest) as save, \
         patch.object(cm, "refresh_file_list", wraps=cm.refresh_file_list) as refresh:
        _run(cm, op, paths[:40], tier)

    assert save.call_count == 1, f"the manifest was saved {save.call_count} times for one batch"
    assert refresh.call_count == 1, f"the tree was rebuilt {refresh.call_count} times for one batch"
    assert _phase(cm, PHASE[tier]) == [_rel(cm, p) for p in paths[40:]]
    if dest:
        assert len(_phase(cm, PHASE[dest])) == 40


def test_bulk_remove_keeps_the_rest_of_the_library_in_order(cm, tmp_path):
    """Guard (passes before and after the fix): batching the manifest update must not reshuffle
    anything. Remove every third file of a 300-file library arranged in reverse disk order — the
    manifest holds exactly the other 200, in the user's order, not folder or alphabetical order."""
    paths = _library(tmp_path, "HighPriority", folders=10, per_folder=30)
    arranged = list(reversed(paths))
    _write_manifest(cm, {"PHASE_1_NOW": arranged})
    doomed = arranged[::3]

    _run(cm, "remove_files", doomed, "HighPriority")

    gone = set(doomed)
    assert _phase(cm, "PHASE_1_NOW") == [_rel(cm, p) for p in arranged if p not in gone]
    assert not any(os.path.exists(p) for p in doomed)


@pytest.mark.parametrize("op, tier, dest", OPERATIONS[1:])
def test_graduate_and_demote_still_preserve_order(cm, tmp_path, op, tier, dest):
    """Guard (passes before and after the fix): the destination order IS the selection order
    (_resolve_items_to_paths docstring). Select the second series before the first — they must land
    in exactly that order, chapter order intact inside each."""
    paths = _library(tmp_path, tier, folders=2, per_folder=20)
    _write_manifest(cm, {PHASE[tier]: paths})
    chosen = paths[20:] + paths[:20]

    _run(cm, op, chosen, tier)

    assert _phase(cm, PHASE[dest]) == [dest + _rel(cm, p)[len(tier):] for p in chosen]
    assert _phase(cm, PHASE[tier]) == []


# ---------------------------------------------------------------------------------------------- #
# One error dialog per batch, and the rest of the batch still happens
# ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_errors_are_reported_once_not_per_file(cm, tmp_path, mock_messagebox, op, tier, dest):
    """Graduate showed a dialog per failing file (3,000 dialogs for a failing batch of 3,000), Demote
    gave up at the first failure, and Remove failed silently. Two episodes held open by a video
    player must produce ONE dialog naming both — and every other file must still move."""
    paths = _library(tmp_path, tier, folders=3, per_folder=10)
    _write_manifest(cm, {PHASE[tier]: paths})
    locked = {paths[3], paths[17]}
    real_move = shutil.move

    def move(src, dst, *args, **kwargs):
        if str(src) in locked:
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real_move(src, dst, *args, **kwargs)

    with patch("app.content_importer_gui.shutil.move", side_effect=move):
        _run(cm, op, paths, tier)

    assert mock_messagebox.showerror.call_count == 1
    text = mock_messagebox.showerror.call_args[0][1]
    assert "2 of 30" in text
    for p in locked:
        assert os.path.basename(p) in text
        assert os.path.exists(p), "a file that couldn't move must stay where it was"
    assert not any(os.path.exists(p) for p in paths if p not in locked), "the rest of the batch stopped"
    assert set(_phase(cm, PHASE[tier])) == {_rel(cm, p) for p in locked}, \
        "only the files that stayed keep their rows"


# ---------------------------------------------------------------------------------------------- #
# The question counts files
# ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_the_confirmation_counts_files_not_rows(cm, tmp_path, mock_messagebox, op, tier, dest):
    """A folder row holding 20 episodes used to be asked about as '1 items'."""
    paths = _library(tmp_path, tier, folders=1, per_folder=20)
    _write_manifest(cm, {PHASE[tier]: paths})
    cm.target_folder_var.set(tier)
    _wire_group_selection(cm, "シリーズ00", paths)
    mock_messagebox.askyesno.return_value = False      # only look at the question

    getattr(cm, op)()

    question = mock_messagebox.askyesno.call_args[0][1]
    assert "20 files (in 1 folder)" in question
    assert all(os.path.exists(p) for p in paths), "declining must change nothing"


@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_a_long_batch_shows_progress_and_a_busy_cursor(cm, tmp_path, op, tier, dest):
    """The batch runs on the Tk thread, so it must say it's alive: a busy cursor for its duration
    (restored at the end) and a status line every 100 files."""
    paths = _library(tmp_path, tier, folders=3, per_folder=40)
    _write_manifest(cm, {PHASE[tier]: paths})
    shown = []
    cm.status_var.set = shown.append

    _run(cm, op, paths, tier)

    verb = {"remove_files": "Removing", "graduate_content": "Graduating", "demote_content": "Demoting"}[op]
    assert [s for s in shown if s.startswith(verb)] == [f"{verb} 100 / 120…"]
    cursors = [c.kwargs["cursor"] for c in cm.root.config.call_args_list if "cursor" in c.kwargs]
    assert cursors == ["watch", ""], f"busy cursor not shown, or not restored: {cursors}"


def test_a_1000_file_remove_finishes_in_seconds(cm, tmp_path):
    """A regression guard against O(n^2), not a benchmark — the bound is deliberately generous. On this
    headless harness it took 64 s before the fix and about 1 s after."""
    paths = _library(tmp_path, "HighPriority", folders=10, per_folder=100)
    _write_manifest(cm, {"PHASE_1_NOW": paths})

    t0 = time.perf_counter()
    _run(cm, "remove_files", paths, "HighPriority")
    elapsed = time.perf_counter() - t0

    assert elapsed < 10, f"removing 1,000 files took {elapsed:.1f} s"
    assert _phase(cm, "PHASE_1_NOW") == []
    assert len(os.listdir(os.path.join(cm.data_root, ".trash"))) == 1000
