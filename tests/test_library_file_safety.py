"""The Content Manager must never destroy library content or the library order (CLAUDE.md §4).

Three holes, each found by reading the code, none of which ever failed a test before:

1. Add Files copied straight over a same-named file already in the section, and Undo then deleted
   the "added" path — so both the old file and the new one were gone.
2. `.trash` is purged 30 days after each file's MODIFIED time, and a move keeps the time the file
   had. Removing anything last edited over a month ago got it purged at the very next Generate.
   Two same-named files removed in the same second also shared one trash name.
3. A manifest that couldn't be parsed was treated as empty, and the next save wrote a fresh
   folder-order manifest over the user's arranged order with no copy kept. A manifest re-saved
   from Notepad (BOM) counted as unparseable.

Headless Content Manager, built like tests/test_zip_import.py, on a real data/ + User Files/ layout.
"""

import json
import os
import re
import time
from unittest.mock import MagicMock, patch

import pytest

from app import analyzer
from app.content_importer_gui import ContentImporterApp
from app.path_utils import cleanup_trash_async


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
    for sub in ("HighPriority", "LowPriority", "GoalContent"):
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


# Real subtitle cues and prose — the same shapes a learner's library holds.
EP_A = "1\n00:00:01,000 --> 00:00:03,500\nまた会えるとは思わなかった。\n"
EP_B = "1\n00:00:02,000 --> 00:00:04,000\nこの街には、まだ秘密が残っている。\n"
CHAPTER = "吾輩は猫である。名前はまだ無い。\nどこで生れたかとんと見当がつかぬ。\n"

SIXTY_DAYS_AGO = time.time() - 60 * 24 * 3600


def _tier(tmp_path, name="HighPriority"):
    return tmp_path / "data" / "ja" / name


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _phase(cm, key="PHASE_1_NOW"):
    with open(cm.get_manifest_path(), "r", encoding="utf-8") as f:
        return [e["physical_path"] for e in json.load(f)["schedule"].get(key, [])]


# ---------------------------------------------------------------------------------------------- #
# 1. Add Files never overwrites
# ---------------------------------------------------------------------------------------------- #
def _add(cm, *paths):
    with patch("app.content_importer_gui.filedialog.askopenfilenames",
               return_value=[str(p) for p in paths]):
        cm.add_files()


def test_adding_a_same_named_file_keeps_the_one_already_in_the_section(cm, tmp_path):
    tier = _tier(tmp_path)
    _write(tier / "第01話.srt", EP_A)
    incoming = _write(tmp_path / "downloads" / "第01話.srt", EP_B)

    _add(cm, incoming)

    assert (tier / "第01話.srt").read_text(encoding="utf-8") == EP_A, "the existing file was overwritten"
    assert (tier / "第01話 (2).srt").read_text(encoding="utf-8") == EP_B
    assert "HighPriority/第01話 (2).srt" in _phase(cm)


def test_adding_an_identical_file_again_is_skipped_not_duplicated(cm, tmp_path, mock_messagebox):
    tier = _tier(tmp_path)
    _write(tier / "第01話.srt", EP_A)
    incoming = _write(tmp_path / "downloads" / "第01話.srt", EP_A)

    _add(cm, incoming)

    assert sorted(os.listdir(tier)) == ["第01話.srt"]
    assert "1 already present" in mock_messagebox.showinfo.call_args[0][1]


def test_undo_after_a_name_clash_removes_only_the_new_copy(cm, tmp_path):
    tier = _tier(tmp_path)
    _write(tier / "第01話.srt", EP_A)
    _add(cm, _write(tmp_path / "downloads" / "第01話.srt", EP_B))

    cm.undo_last_action()

    assert sorted(os.listdir(tier)) == ["第01話.srt"]
    assert (tier / "第01話.srt").read_text(encoding="utf-8") == EP_A


# ---------------------------------------------------------------------------------------------- #
# 2. Removal starts the 30-day trash clock, and trash names never collide
# ---------------------------------------------------------------------------------------------- #
def _remove(cm, *paths):
    cm.tree.selection.return_value = ["row"]
    with patch.object(cm, "_resolve_items_to_paths", return_value=[str(p) for p in paths]):
        cm.remove_files()


def _trash(tmp_path):
    return tmp_path / "data" / "ja" / ".trash"


def _run_trash_cleanup(trash_dir):
    """Run path_utils' purge synchronously — in the app it fires on a daemon thread."""
    with patch("app.path_utils.threading.Thread") as thread:
        cleanup_trash_async(str(trash_dir))
    thread.call_args.kwargs["target"]()


def test_a_removed_old_file_gets_its_full_30_days_in_trash(cm, tmp_path):
    chapter = _write(_tier(tmp_path) / "吾輩は猫である.txt", CHAPTER)
    os.utime(chapter, (SIXTY_DAYS_AGO, SIXTY_DAYS_AGO))   # last edited two months ago

    _remove(cm, chapter)
    [trashed] = list(_trash(tmp_path).iterdir())
    assert trashed.stat().st_mtime > time.time() - 60, "the purge would read the old edit time"

    _run_trash_cleanup(_trash(tmp_path))                 # what the next Generate triggers
    assert trashed.exists(), "a file removed moments ago was purged"


def test_every_file_in_a_removed_folder_is_restamped(cm, tmp_path):
    book = _tier(tmp_path) / "吾輩は猫である"
    for name in ("ch01.txt", "ch02.txt"):
        os.utime(_write(book / name, CHAPTER), (SIXTY_DAYS_AGO, SIXTY_DAYS_AGO))

    _remove(cm, book)

    [trashed_book] = list(_trash(tmp_path).iterdir())
    stamps = [p.stat().st_mtime for p in trashed_book.rglob("*.txt")]
    assert len(stamps) == 2 and min(stamps) > time.time() - 60


def test_the_purge_still_clears_what_was_removed_over_30_days_ago(tmp_path):
    """The purge itself is unchanged — only when its clock starts moved."""
    trash = tmp_path / ".trash"
    stale = _write(trash / "old_20260701.txt", CHAPTER)
    os.utime(stale, (SIXTY_DAYS_AGO, SIXTY_DAYS_AGO))
    fresh = _write(trash / "new_20260922.txt", CHAPTER)

    _run_trash_cleanup(trash)

    assert not stale.exists() and fresh.exists()


def test_same_named_files_removed_together_get_separate_trash_entries(cm, tmp_path):
    """Two seasons' 01.srt, removed in the same second, used to share one trash name — the second
    move landed on the first, and Undo restored the wrong episode."""
    s1 = _write(_tier(tmp_path) / "シーズン1" / "01.srt", EP_A)
    s2 = _write(_tier(tmp_path) / "シーズン2" / "01.srt", EP_B)

    with patch("app.content_importer_gui.datetime") as clock:
        clock.now.return_value.strftime.return_value = "20260922120000"   # the same second
        _remove(cm, s1, s2)

    assert len(list(_trash(tmp_path).iterdir())) == 2

    cm.undo_last_action()
    assert s1.read_text(encoding="utf-8") == EP_A
    assert s2.read_text(encoding="utf-8") == EP_B


# ---------------------------------------------------------------------------------------------- #
# 3. An unusable manifest is never silently replaced
# ---------------------------------------------------------------------------------------------- #
# Deliberately NOT alphabetical, so falling back to folder order is visible.
ARRANGED = {"schedule": {
    "PHASE_1_NOW": [
        {"title": "第02話.srt", "physical_path": "HighPriority/第02話.srt", "parent_folder": "",
         "origin_source": "Manual Import", "type": "File", "status": "New"},
        {"title": "第01話.srt", "physical_path": "HighPriority/第01話.srt", "parent_folder": "",
         "origin_source": "Manual Import", "type": "File", "status": "New"},
    ],
    "PHASE_2_SOON": [], "PHASE_3_LATER": []}}


def _episodes(tmp_path):
    _write(_tier(tmp_path) / "第01話.srt", EP_A)
    _write(_tier(tmp_path) / "第02話.srt", EP_B)


def test_a_damaged_manifest_is_kept_dated_in_trash_and_the_library_rebuilds(cm, tmp_path,
                                                                             mock_messagebox):
    _episodes(tmp_path)
    damaged = json.dumps(ARRANGED, ensure_ascii=False)[:60]      # cut short mid-write
    with open(cm.get_manifest_path(), "w", encoding="utf-8") as f:
        f.write(damaged)

    cm._sync_disk_to_manifest()

    [kept] = list((tmp_path / "User Files" / "ja" / ".trash").iterdir())
    assert re.fullmatch(r"master_manifest\.\d{8}-\d{6}\.json", kept.name)
    assert kept.read_text(encoding="utf-8") == damaged, "the damaged order must survive intact"
    assert sorted(_phase(cm)) == ["HighPriority/第01話.srt", "HighPriority/第02話.srt"]
    mock_messagebox.showwarning.assert_called_once()


def test_a_manifest_saved_with_a_bom_loads_in_its_arranged_order(cm, tmp_path, mock_messagebox):
    _episodes(tmp_path)
    with open(cm.get_manifest_path(), "w", encoding="utf-8-sig") as f:   # what Notepad writes
        json.dump(ARRANGED, f, ensure_ascii=False)

    cm._sync_disk_to_manifest()

    assert _read_bom_tolerant(cm) == ["HighPriority/第02話.srt", "HighPriority/第01話.srt"]
    assert not (tmp_path / "User Files" / "ja" / ".trash").exists()
    mock_messagebox.showwarning.assert_not_called()


def _read_bom_tolerant(cm):
    with open(cm.get_manifest_path(), "r", encoding="utf-8-sig") as f:
        return [e["physical_path"] for e in json.load(f)["schedule"]["PHASE_1_NOW"]]


def test_an_unreadable_manifest_blocks_every_save_until_it_can_be_read(cm, tmp_path,
                                                                       mock_messagebox):
    """A file held open by antivirus or a sync tool is simulated with a DIRECTORY of that name:
    the path exists but open() raises OSError, with no builtin patched."""
    _episodes(tmp_path)
    os.makedirs(cm.get_manifest_path())

    cm._sync_disk_to_manifest()
    cm._sync_disk_to_manifest()      # a refresh re-reads it — still no write, still one warning

    assert os.path.isdir(cm.get_manifest_path()), "something was written over the unreadable file"
    assert mock_messagebox.showwarning.call_count == 1

    os.rmdir(cm.get_manifest_path())   # once it can be read again, saving resumes
    cm._sync_disk_to_manifest()
    assert sorted(_phase(cm)) == ["HighPriority/第01話.srt", "HighPriority/第02話.srt"]


def test_a_failed_save_leaves_the_previous_manifest_intact(cm, mock_messagebox):
    with open(cm.get_manifest_path(), "w", encoding="utf-8") as f:
        json.dump(ARRANGED, f, ensure_ascii=False)
    cm.load_manifest()

    with patch("app.content_importer_gui.json.dump", side_effect=OSError("disk full")):
        cm.save_manifest({"schedule": {}})

    with open(cm.get_manifest_path(), "r", encoding="utf-8") as f:
        assert json.load(f) == ARRANGED
    assert not os.path.exists(cm.get_manifest_path() + ".tmp")
    mock_messagebox.showerror.assert_called_once()


def test_the_analyzer_follows_a_bom_manifest_instead_of_falling_back_to_folder_order():
    """The Content Manager now reads a BOM manifest; the analysis must agree with it, or Generate
    would silently run in folder order while the library shows the arranged one."""
    root = os.environ["SURASURA_TEST_ROOT"]
    tier = os.path.join(root, "data", "ja", "HighPriority")
    os.makedirs(tier)
    for name, text in (("第01話.srt", EP_A), ("第02話.srt", EP_B)):
        with open(os.path.join(tier, name), "w", encoding="utf-8") as f:
            f.write(text)
    user_files = os.path.join(root, "User Files", "ja")
    os.makedirs(user_files)
    with open(os.path.join(user_files, "master_manifest.json"), "w", encoding="utf-8-sig") as f:
        json.dump(ARRANGED, f, ensure_ascii=False)

    found = analyzer.resolve_found_files("ja", verbose=False)

    assert [os.path.basename(p) for p, _label, _weight, _type in found] == ["第02話.srt", "第01話.srt"]
