"""Undo in the Content Manager (Library_Store_Spec §6.11; L2.1 WP-L7).

From 2.5 Undo is a store-mode feature: each change a window makes is kept, and Undo reverses that change alone
— a later drag survives undoing an earlier Add (2.4's whole-manifest snapshot erased it, RD-A6). In JSON mode
(no store yet) Undo is off. The file work goes through the window's own file code: Undo-Add sends the copied
files to `.trash` (never a delete), Undo-Remove puts them back, Undo-Graduate strips its GraduatedList block.

A real window (Tk) on a data/ + User Files/ layout under the test's SURASURA_TEST_ROOT, with real Japanese text.
"""
import json
from contextlib import contextmanager
import os
from unittest.mock import patch

import pytest
import tkinter as tk

from app import library_store as ls
from app.content_importer_gui import ContentImporterApp

EPISODE = "1\n00:00:01,000 --> 00:00:03,500\nまた会えるとは思わなかった。\n"
CHAPTER = "吾輩は猫である。名前はまだ無い。\n"


@pytest.fixture
def gui(tmp_path):
    root = tk.Tk()
    data_root = os.path.join(tmp_path, "data", "ja")
    user_root = os.path.join(tmp_path, "User Files", "ja")
    os.makedirs(user_root, exist_ok=True)
    for folder in ["HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed", ".trash"]:
        os.makedirs(os.path.join(data_root, folder), exist_ok=True)
    with patch("app.content_importer_gui.get_data_path", return_value=str(data_root)), \
         patch("app.content_importer_gui.get_user_files_path", return_value=str(user_root)), \
         patch("app.content_importer_gui.ensure_data_setup"):
        app = ContentImporterApp(root, "ja")
        yield app
    try:
        root.destroy()
    except Exception:
        pass


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _to_store(app):
    assert ls.maintain("ja", app.data_root, app.user_files_root, from_folders=True) == ls.EXIT_DONE
    assert app._store_mode() == "store"


def _order(app, tier):
    return [e["physical_path"] for _i, e, _a in app._store().ordered(tier)]


@contextmanager
def _select(app, tier_folder, paths):
    """`paths` as the resolved selection of one tree row, for the length of one action."""
    app.target_folder_var.set(tier_folder)
    with patch.object(app.tree, "selection", return_value=("row",)), \
         patch.object(app, "_resolve_items_to_paths", return_value=[str(p) for p in paths]):
        yield


def test_undo_add_files_trashes_the_copies_and_keeps_a_later_drag(gui, tmp_path):
    """Add; a drag of another item; Undo the Add → the Add is gone (its file in .trash, never deleted) and the
    drag is kept — the store-level proof (ORDER L1.2), through the window."""
    a = _write(os.path.join(gui.data_root, "HighPriority", "第01話.srt"), EPISODE)
    b = _write(os.path.join(gui.data_root, "HighPriority", "第02話.srt"), EPISODE + "2\n")
    _to_store(gui)
    new = _write(os.path.join(tmp_path, "downloads", "こころ.txt"), CHAPTER)
    gui.target_folder_var.set("HighPriority")
    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[new]):
        gui.add_files()
    added = os.path.join(gui.data_root, "HighPriority", "こころ.txt")
    assert "HighPriority/こころ.txt" in _order(gui, "now")

    gui.move_manifest_items_relative([a], b, "after")            # the drag: 第01話 after 第02話
    gui._undo_changes.insert(0, gui._undo_changes.pop())          # undo the Add first, not the drag
    gui.undo_last_action()

    assert not os.path.exists(added)
    assert any(n.startswith("こころ_") for n in os.listdir(os.path.join(gui.data_root, ".trash")))
    row = gui._store().trash_rows()[-1]                          # the trash row knows where the file went
    assert row["rel_path"] == "HighPriority/こころ.txt" and row["trashed_path"].startswith(".trash/こころ_")
    assert os.path.isfile(os.path.join(gui.data_root, *row["trashed_path"].split("/")))
    assert _order(gui, "now") == ["HighPriority/第02話.srt", "HighPriority/第01話.srt"], "the drag is kept"


def test_undo_graduate_puts_the_items_back_and_moves_no_file(gui):
    """Soon → NOW in store mode moves no file (L5); Undo puts the items back in Soon, in their places."""
    files = [_write(os.path.join(gui.data_root, "LowPriority", "こころ", f"ch{n:02d}.txt"), CHAPTER) for n in (1, 2, 3)]
    _to_store(gui)
    before = _order(gui, "soon")
    with _select(gui, "LowPriority", files[:2]):
        gui.graduate_content()
    assert _order(gui, "now") == ["LowPriority/こころ/ch01.txt", "LowPriority/こころ/ch02.txt"]
    assert all(os.path.exists(f) for f in files), "the store never moves a file"
    gui.undo_last_action()
    assert _order(gui, "soon") == before and _order(gui, "now") == []


def test_undo_graduate_from_now_strips_its_graduated_list_block(gui):
    """NOW → Graduated adds the file's words to GraduatedList.txt (file work); Undo strips exactly that block."""
    path = _write(os.path.join(gui.data_root, "HighPriority", "吾輩は猫である.txt"), CHAPTER)
    grad = os.path.join(gui.user_files_root, "GraduatedList.txt")
    _write(grad, "# Graduated Words\n猫\n")
    _to_store(gui)
    with _select(gui, "HighPriority", [path]), \
         patch.object(gui, "_load_graduate_index", return_value={"吾輩は猫である.txt": ["吾輩", "名前"]}):
        gui.graduate_content()
    with open(grad, encoding="utf-8") as f:
        assert "# Source: HighPriority/吾輩は猫である.txt (2 words graduated)" in f.read()
    assert _order(gui, "now") == []
    gui.undo_last_action()
    with open(grad, encoding="utf-8") as f:
        assert f.read() == "# Graduated Words\n猫\n"
    assert _order(gui, "now") == ["HighPriority/吾輩は猫である.txt"]


def test_undo_remove_puts_the_file_and_its_place_back(gui):
    files = [_write(os.path.join(gui.data_root, "HighPriority", f"第{n:02d}話.srt"), EPISODE + str(n)) for n in (1, 2, 3)]
    _to_store(gui)
    before = _order(gui, "now")
    with _select(gui, "HighPriority", [files[1]]):
        gui.remove_files()
    assert not os.path.exists(files[1])
    assert _order(gui, "now") == [before[0], before[2]]
    gui.undo_last_action()
    assert os.path.exists(files[1])
    assert _order(gui, "now") == before


def test_undo_remove_never_overwrites_a_file_that_took_the_name(gui):
    """Removed, then a new file saved under the same name: Undo puts the removed one back beside it (`_1`), never
    over it, and its row points at the name it went back to."""
    files = [_write(os.path.join(gui.data_root, "HighPriority", f"第{n:02d}話.srt"), EPISODE + str(n)) for n in (1, 2, 3)]
    _to_store(gui)
    before = _order(gui, "now")
    with _select(gui, "HighPriority", [files[1]]):
        gui.remove_files()
    _write(files[1], EPISODE + "新しい")
    gui.undo_last_action()
    with open(files[1], encoding="utf-8") as f:
        assert f.read() == EPISODE + "新しい", "the new file is untouched"
    back = os.path.join(gui.data_root, "HighPriority", "第02話_1.srt")
    with open(back, encoding="utf-8") as f:
        assert f.read() == EPISODE + "2"
    assert _order(gui, "now") == [before[0], "HighPriority/第02話_1.srt", before[2]]


def test_undo_is_off_in_json_mode(gui, tmp_path):
    """No store: the previous release's code path, with Undo off (G1.1-12) — nothing recorded, the button stays
    disabled, and an Undo press changes nothing."""
    a = _write(os.path.join(gui.data_root, "HighPriority", "第01話.srt"), EPISODE)
    assert gui._store_mode() == "json"
    new = _write(os.path.join(tmp_path, "downloads", "こころ.txt"), CHAPTER)
    gui.target_folder_var.set("HighPriority")
    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[new]):
        gui.add_files()
    added = os.path.join(gui.data_root, "HighPriority", "こころ.txt")
    assert os.path.exists(added)
    assert str(gui.undo_btn.cget("state")) == tk.DISABLED
    gui.undo_last_action()
    assert os.path.exists(added) and os.path.exists(a)
    with open(gui.get_manifest_path(), encoding="utf-8") as f:
        assert "HighPriority/こころ.txt" in json.dumps(json.load(f), ensure_ascii=False)
