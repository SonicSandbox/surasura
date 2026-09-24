"""Where new content lands in a tab (New_Content_Placement_Spec.md, the user 2026-09-24).

"I've noticed that i'm always dragging them back to the top after insertion. at the top is best."
Every path that added content used to APPEND to the end of its tab. Now it is PLACED:

  * a file whose folder already has files in the tab goes right after that folder's LAST item — for a
    series the user split to interleave it with other content, after its last part;
  * everything else — a new series, a new season folder inside a series, a loose file, a series
    moved in by Graduate / Demote — goes to the TOP of the tab, in the order it came.

And what must never change: the existing order (splitting and interleaving a series is the user's
own arrangement — "It's an ADVANTAGE that someone can split a series"), an empty tab (it comes out
exactly as appending did), and the selection order of a move. Files on disk never move.

The folder names are the user's own library's (Peko Peko Vlog, HonzukiV1, Seihantai, 陰の実力者,
BOM); the text in each file is real Japanese.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.content_importer_gui import ContentImporterApp, place_new_entries

TEXT = ["また会えるとは思わなかった。", "この街には、まだ秘密が残っている。",
        "吾輩は猫である。名前はまだ無い。", "朝の光が窓から差し込んでいる。彼女はまだ眠っていた。"]
PHASE = {"HighPriority": "PHASE_1_NOW", "LowPriority": "PHASE_2_SOON", "GoalContent": "PHASE_3_LATER"}


# --- the rule itself, on plain entries -------------------------------------------------------- #
def _entry(path):
    parts = path.split("/")
    return {"title": parts[-1], "physical_path": path, "parent_folder": "/".join(parts[1:-1])}


def _paths(entries):
    return [entry["physical_path"] for entry in entries]


INTERLEAVED = ["HighPriority/Seihantai/第01話.txt", "HighPriority/Peko Peko Vlog/vlog01.txt",
               "HighPriority/HonzukiV1/第01章.txt", "HighPriority/Peko Peko Vlog/vlog02.txt",
               "HighPriority/雑談.txt"]


def test_a_new_file_in_a_folder_goes_after_that_folders_last_item_and_nothing_else_moves():
    """Peko Peko Vlog is split around HonzukiV1 on purpose: vlog03 joins its LAST part, and every
    existing row stays exactly where the user put it."""
    existing = [_entry(p) for p in INTERLEAVED]
    placed = place_new_entries(existing, [_entry("HighPriority/Peko Peko Vlog/vlog03.txt"),
                                          _entry("HighPriority/HonzukiV1/第02章.txt")])
    assert _paths(placed) == ["HighPriority/Seihantai/第01話.txt", "HighPriority/Peko Peko Vlog/vlog01.txt",
                              "HighPriority/HonzukiV1/第01章.txt", "HighPriority/HonzukiV1/第02章.txt",
                              "HighPriority/Peko Peko Vlog/vlog02.txt", "HighPriority/Peko Peko Vlog/vlog03.txt",
                              "HighPriority/雑談.txt"]


def test_a_new_series_a_new_season_folder_and_a_loose_file_all_go_to_the_top_in_the_order_given():
    """The user: a new season folder goes to the top too ("Just keep it consistent by putting it at
    the top"), and so does a loose file — even with loose files already in the tab."""
    existing = [_entry(p) for p in INTERLEAVED + ["HighPriority/陰の実力者/陰の実力者-1/第01話.txt"]]
    new = [_entry("HighPriority/葬送のフリーレン/第01話.txt"), _entry("HighPriority/葬送のフリーレン/第02話.txt"),
           _entry("HighPriority/陰の実力者/陰の実力者-2/第01話.txt"), _entry("HighPriority/メモ.txt")]
    placed = place_new_entries(existing, new)
    assert _paths(placed[:4]) == _paths(new)
    assert _paths(placed[4:]) == _paths(existing), "the existing order is untouched"


def test_both_kinds_in_one_pass_and_an_empty_tab_comes_out_as_it_always_did():
    existing = [_entry(p) for p in INTERLEAVED]
    new = [_entry("HighPriority/葬送のフリーレン/第01話.txt"), _entry("HighPriority/Seihantai/第02話.txt"),
           _entry("HighPriority/葬送のフリーレン/第02話.txt")]
    placed = _paths(place_new_entries(existing, new))
    assert placed[:2] == ["HighPriority/葬送のフリーレン/第01話.txt", "HighPriority/葬送のフリーレン/第02話.txt"]
    assert placed[2:4] == ["HighPriority/Seihantai/第01話.txt", "HighPriority/Seihantai/第02話.txt"]
    assert [p for p in placed if p in INTERLEAVED] == INTERLEAVED

    fresh = [_entry(p) for p in INTERLEAVED]
    assert _paths(place_new_entries([], fresh)) == INTERLEAVED, "an empty tab: exactly the old append"


def test_every_entry_appears_once_and_the_existing_relative_order_never_changes():
    """The property the whole change rests on, over every split of one list into old and new."""
    everything = [_entry(p) for p in INTERLEAVED + ["HighPriority/葬送のフリーレン/第01話.txt",
                                                   "HighPriority/Peko Peko Vlog/vlog03.txt",
                                                   "HighPriority/BOM/Alma/Alma_1.txt"]]
    for cut in range(len(everything) + 1):
        existing, new = everything[:cut], everything[cut:]
        placed = place_new_entries(existing, new)
        assert sorted(_paths(placed)) == sorted(_paths(everything))
        assert [e for e in placed if e in existing] == existing
        # What goes to the top keeps the order it came in, and so does what follows one folder.
        folders = {e["parent_folder"] for e in existing if e["parent_folder"]}
        top = [e for e in new if e["parent_folder"] not in folders]
        assert placed[:len(top)] == top
        for folder in folders:
            joining = [e for e in new if e["parent_folder"] == folder]
            assert [e for e in placed if e in joining] == joining


# --- the Content Manager: the disk scan, the adds, the moves ------------------------------------ #
class _Var:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


@pytest.fixture(autouse=True)
def _no_dialogs():
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
        app.target_folder_var = _Var("HighPriority")
        app.status_var = _Var()
        app.tree = MagicMock()
        app.graduate_btn = MagicMock()
        app.undo_btn = MagicMock()
        app.analyzed_filenames = set()
        app._last_stats_mtime = 0
        app._last_stats_size = 0
        app.last_action = None
        return app


def _write(cm, rel, text_index=0):
    path = os.path.join(cm.data_root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(TEXT[text_index % len(TEXT)] + "\n")
    return path


def _manifest(cm, phases):
    """The library order written directly — {phase: [relative paths, in order]}; the files exist."""
    schedule = {key: [] for key in PHASE.values()}
    for phase, rels in phases.items():
        for index, rel in enumerate(rels):
            _write(cm, rel, index)
            schedule[phase].append(dict(_entry(rel), origin_source="Reset", type="File", status="New"))
    with open(cm.get_manifest_path(), "w", encoding="utf-8") as handle:
        json.dump({"schedule": schedule}, handle, ensure_ascii=False)


def _phase(cm, key):
    with open(cm.get_manifest_path(), encoding="utf-8") as handle:
        return [entry["physical_path"] for entry in json.load(handle)["schedule"].get(key, [])]


def test_files_found_on_disk_are_placed_not_appended(cm):
    """The "noticed" path — files dropped in with Explorer, Extract, a YouTube download, pasted
    text. A new series and a loose file at the top of NOW; a new episode of an interleaved series
    after its last part; a new chapter after its book's last one."""
    _manifest(cm, {"PHASE_1_NOW": INTERLEAVED})
    for rel in ("HighPriority/葬送のフリーレン/第01話.txt", "HighPriority/葬送のフリーレン/第02話.txt",
                "HighPriority/Peko Peko Vlog/vlog03.txt", "HighPriority/HonzukiV1/第02章.txt",
                "HighPriority/メモ.txt"):
        _write(cm, rel)

    cm._sync_disk_to_manifest()

    now = _phase(cm, "PHASE_1_NOW")
    frieren = sorted(p for p in now if "葬送のフリーレン" in p)
    assert set(now[:3]) == {"HighPriority/メモ.txt", *frieren}, "new series and loose file on top"
    assert [p for p in now if "葬送のフリーレン" in p] == frieren, "in the folder's own order"
    assert now[3:] == ["HighPriority/Seihantai/第01話.txt", "HighPriority/Peko Peko Vlog/vlog01.txt",
                       "HighPriority/HonzukiV1/第01章.txt", "HighPriority/HonzukiV1/第02章.txt",
                       "HighPriority/Peko Peko Vlog/vlog02.txt", "HighPriority/Peko Peko Vlog/vlog03.txt",
                       "HighPriority/雑談.txt"]


def test_a_new_season_folder_goes_to_the_top_and_each_tab_is_placed_on_its_own(cm):
    """陰の実力者-2 is new: the top of NOW, not the end of 陰の実力者-1 (the user's P2). And a new
    series dropped into Soon lands at the top of Soon, leaving NOW alone."""
    _manifest(cm, {"PHASE_1_NOW": ["HighPriority/Seihantai/第01話.txt",
                                   "HighPriority/陰の実力者/陰の実力者-1/第01話.txt"],
                   "PHASE_2_SOON": ["LowPriority/BOM/Alma/Alma_1.txt"]})
    _write(cm, "HighPriority/陰の実力者/陰の実力者-2/第01話.txt")
    _write(cm, "LowPriority/ReZeroV1/第01話.txt")

    cm._sync_disk_to_manifest()

    assert _phase(cm, "PHASE_1_NOW") == ["HighPriority/陰の実力者/陰の実力者-2/第01話.txt",
                                          "HighPriority/Seihantai/第01話.txt",
                                          "HighPriority/陰の実力者/陰の実力者-1/第01話.txt"]
    assert _phase(cm, "PHASE_2_SOON") == ["LowPriority/ReZeroV1/第01話.txt", "LowPriority/BOM/Alma/Alma_1.txt"]


def test_a_library_with_no_order_yet_comes_out_as_it_always_did(cm):
    """No manifest (a first run, or a damaged one set aside): every file is new, and the order is
    the disk walk's — exactly what appending produced."""
    rels = ["HighPriority/HonzukiV1/第01章.txt", "HighPriority/HonzukiV1/第02章.txt",
            "HighPriority/Seihantai/第01話.txt"]
    for rel in rels:
        _write(cm, rel)
    walk = []
    for root, _dirs, files in os.walk(os.path.join(cm.data_root, "HighPriority")):
        walk += [os.path.relpath(os.path.join(root, f), cm.data_root).replace("\\", "/") for f in files]

    cm._sync_disk_to_manifest()

    assert _phase(cm, "PHASE_1_NOW") == walk


def test_add_folder_merging_into_a_series_and_a_new_book_and_a_loose_file(cm):
    """The Content Manager's own adds share the rule: merging new chapters into HonzukiV1 puts them
    after its last chapter; a brand-new book and a loose file go to the top."""
    _manifest(cm, {"PHASE_1_NOW": ["HighPriority/Seihantai/第01話.txt", "HighPriority/HonzukiV1/第01章.txt",
                                   "HighPriority/Peko Peko Vlog/vlog01.txt"]})
    _write(cm, "HighPriority/HonzukiV1/第02章.txt")
    _write(cm, "HighPriority/深夜特急/ch01.txt")
    loose = _write(cm, "HighPriority/メモ.txt")

    cm._add_paths_to_manifest([os.path.join(cm.data_root, "HighPriority", "HonzukiV1")], "HighPriority")
    cm._add_paths_to_manifest([os.path.join(cm.data_root, "HighPriority", "深夜特急")], "HighPriority")
    cm._add_paths_to_manifest([loose], "HighPriority")

    assert _phase(cm, "PHASE_1_NOW") == ["HighPriority/メモ.txt", "HighPriority/深夜特急/ch01.txt",
                                          "HighPriority/Seihantai/第01話.txt", "HighPriority/HonzukiV1/第01章.txt",
                                          "HighPriority/HonzukiV1/第02章.txt", "HighPriority/Peko Peko Vlog/vlog01.txt"]


def _run(cm, op, paths, tier):
    cm.target_folder_var.set(tier)
    cm.tree.selection.return_value = ["row"]
    with patch.object(cm, "_resolve_items_to_paths", return_value=[str(p) for p in paths]):
        getattr(cm, op)()


def test_a_demoted_series_lands_at_the_top_of_soon_or_after_its_own_folder_there(cm):
    """The user's P4: moved content goes to the top of the tab it lands in — and a part of a series
    whose folder is already in that tab goes after that folder's last item, as any new file does."""
    _manifest(cm, {"PHASE_1_NOW": ["HighPriority/HonzukiV1/第02章.txt", "HighPriority/ReZeroV1/第01話.txt"],
                   "PHASE_2_SOON": ["LowPriority/BOM/Alma/Alma_1.txt", "LowPriority/HonzukiV1/第01章.txt",
                                    "LowPriority/Kaguya-sama/第01話.txt"]})

    _run(cm, "demote_content", [os.path.join(cm.data_root, "HighPriority", "ReZeroV1", "第01話.txt"),
                                os.path.join(cm.data_root, "HighPriority", "HonzukiV1", "第02章.txt")],
         "HighPriority")

    assert _phase(cm, "PHASE_2_SOON") == ["LowPriority/ReZeroV1/第01話.txt", "LowPriority/BOM/Alma/Alma_1.txt",
                                           "LowPriority/HonzukiV1/第01章.txt", "LowPriority/HonzukiV1/第02章.txt",
                                           "LowPriority/Kaguya-sama/第01話.txt"]
    assert _phase(cm, "PHASE_1_NOW") == []


def test_a_graduated_series_lands_at_the_top_of_now_in_the_order_selected(cm):
    """Soon -> NOW: the two series arrive at the top, in the order they were selected."""
    _manifest(cm, {"PHASE_1_NOW": ["HighPriority/Seihantai/第01話.txt"],
                   "PHASE_2_SOON": ["LowPriority/ReZeroV1/第01話.txt", "LowPriority/Kaguya-sama/第01話.txt"]})

    _run(cm, "graduate_content", [os.path.join(cm.data_root, "LowPriority", "Kaguya-sama", "第01話.txt"),
                                  os.path.join(cm.data_root, "LowPriority", "ReZeroV1", "第01話.txt")],
         "LowPriority")

    assert _phase(cm, "PHASE_1_NOW") == ["HighPriority/Kaguya-sama/第01話.txt", "HighPriority/ReZeroV1/第01話.txt",
                                          "HighPriority/Seihantai/第01話.txt"]
