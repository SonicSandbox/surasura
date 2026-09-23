"""Graduate / Demote / Remove must not leave folders behind or strand metadata
(Bugfix_Batch_2026-09-22_Spec.md, Fix A).

- Graduating 100 of 200 files (5 whole folders) left 5 empty folders in the tier; Remove only removed
  a file's immediate parent, and only when completely empty.
- Two files are not content but belong to it: a transcript's cue sidecar `<stem>.surasura.json`
  (the report's ▶ timestamps) and a folder's producer marker `.surasura_source.json` (what makes an
  Extract folder read as a book). A move carried the content file only, so a moved transcript opened
  at 0:00 and a moved book chapter read as 📄 text instead of 📖 book.

Now metadata travels with its file, an emptied folder goes as a whole (its leftovers follow the
content, or go to the trash in one dated folder), and Undo puts the tree back exactly.

Headless Content Manager, built like tests/test_library_file_safety.py, on a real data/ + User Files/
layout with real Japanese books, subtitles and a YouTube transcript.
"""

import json
import os
import re
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
    # The layout ensure_data_setup() creates.
    for sub in ("HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed", ".trash"):
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


# Real content, in the shapes a learner's library holds.
CHAPTER = "吾輩は猫である。名前はまだ無い。\nどこで生れたかとんと見当がつかぬ。\n"
EPISODE = "1\n00:00:01,000 --> 00:00:03,500\nまた会えるとは思わなかった。\n"
TRANSCRIPT = "日本語の勉強、今日から始めましょう。\nまずは毎日少しずつ聞くことが大切です。\n"
VIDEO = "日本語の勉強法 [k3GuCkTa3V4]"
SIDECAR = {"video_id": "k3GuCkTa3V4", "url": "https://www.youtube.com/watch?v=k3GuCkTa3V4",
           "title": "日本語の勉強法",
           "cues": [["日本語の勉強、今日から始めましょう。", 1.5], ["まずは毎日少しずつ聞くことが大切です。", 4.2]]}
MARKER = {"source_type": "epub", "origin": "吾輩は猫である.epub"}
COVER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01" + b"\x00" * 32 + b"\xff\xd9"   # the user's own file

PHASE = {"HighPriority": "PHASE_1_NOW", "LowPriority": "PHASE_2_SOON", "GoalContent": "PHASE_3_LATER"}

# (operation, the tier it runs in, where the files land — None: the trash)
OPERATIONS = [
    pytest.param("remove_files", "HighPriority", None, id="remove"),
    pytest.param("graduate_content", "LowPriority", "HighPriority", id="graduate"),
    pytest.param("demote_content", "HighPriority", "LowPriority", id="demote"),
]
MOVES = OPERATIONS[1:]


def _tier(cm, name):
    return os.path.join(cm.data_root, name)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode, kw = ("wb", {}) if isinstance(content, bytes) else ("w", {"encoding": "utf-8"})
    with open(path, mode, **kw) as f:
        f.write(content)
    return path


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _book(folder, chapters=3, marker=True, cover=False):
    """An Extract-made book: chNN.txt + its producer marker (+ the user's cover.jpg)."""
    paths = [_write(os.path.join(folder, f"ch{i:02d}.txt"), CHAPTER) for i in range(1, chapters + 1)]
    if marker:
        _write(os.path.join(folder, ".surasura_source.json"), json.dumps(MARKER, ensure_ascii=False))
    if cover:
        _write(os.path.join(folder, "cover.jpg"), COVER)
    return paths


def _transcript(folder, name=VIDEO, text=TRANSCRIPT, sidecar=SIDECAR):
    """A downloaded transcript and its cue sidecar ('foo.txt' -> 'foo.surasura.json')."""
    txt = _write(os.path.join(folder, name + ".txt"), text)
    _write(os.path.join(folder, name + ".surasura.json"), json.dumps(sidecar, ensure_ascii=False))
    return txt


def _run(cm, op, paths, tier):
    """Select `paths` (as the resolved selection) in `tier` and run the operation."""
    cm.target_folder_var.set(tier)
    cm.tree.selection.return_value = ["row"]
    with patch.object(cm, "_resolve_items_to_paths", return_value=[str(p) for p in paths]):
        getattr(cm, op)()


def _landed(cm, dest, tier, path):
    """Where `path` lands under the destination tier (same place inside the tier)."""
    return os.path.join(_tier(cm, dest), os.path.relpath(path, _tier(cm, tier)))


def _snapshot(root):
    """Every directory, and every file with its bytes, under `root` — what Undo must put back."""
    snap = {}
    for r, _dirs, files in os.walk(root):
        rel = os.path.relpath(r, root)
        snap[rel + os.sep] = None
        for name in files:
            snap[os.path.join(rel, name)] = _read(os.path.join(r, name))
    return snap


def _manifest(cm):
    with open(cm.get_manifest_path(), "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------------------------- #
# Emptied folders go
# ---------------------------------------------------------------------------------------------- #
def test_graduating_a_whole_folder_leaves_no_empty_folder_behind(cm):
    """Soon -> NOW for a whole book: the book's folder must not stay behind, empty, in Soon."""
    book = os.path.join(_tier(cm, "LowPriority"), "こころ")
    chapters = _book(book, marker=False)
    cm._sync_disk_to_manifest()

    _run(cm, "graduate_content", chapters, "LowPriority")

    assert not os.path.exists(book), "an empty folder was left behind in Soon"
    assert all(os.path.isfile(_landed(cm, "HighPriority", "LowPriority", p)) for p in chapters)


@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_nested_series_folders_are_removed_once_empty(cm, op, tier, dest):
    """シリーズ/シーズン1/… and シリーズ/シーズン2/…: once both seasons are gone, the series folder
    goes too — Remove used to take only a file's immediate parent, Graduate/Demote nothing at all."""
    series = os.path.join(_tier(cm, tier), "シリーズ")
    episodes = [_write(os.path.join(series, season, f"第{n:02d}話.srt"), EPISODE)
                for season in ("シーズン1", "シーズン2") for n in (1, 2)]
    cm._sync_disk_to_manifest()

    _run(cm, op, episodes, tier)

    assert not os.path.exists(series), f"left behind: {sorted(os.listdir(series))}"
    assert os.path.isdir(_tier(cm, tier))


@pytest.mark.parametrize("op, tier, dest", MOVES)
def test_a_partly_graduated_folder_keeps_its_remaining_files(cm, op, tier, dest):
    """Guard (passes before and after the fix): a folder that still holds content is left exactly as
    it is — its other chapters, its marker and the user's own files untouched."""
    book = os.path.join(_tier(cm, tier), "吾輩は猫である")
    chapters = _book(book, chapters=4, cover=True)
    cm._sync_disk_to_manifest()
    staying = {name: _read(os.path.join(book, name))
               for name in ("ch03.txt", "ch04.txt", ".surasura_source.json", "cover.jpg")}

    _run(cm, op, chapters[:2], tier)

    assert sorted(os.listdir(book)) == sorted(staying)
    assert all(_read(os.path.join(book, name)) == data for name, data in staying.items())


@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_tier_roots_are_never_removed(cm, op, tier, dest):
    """Moving every loose file out of a tier empties the tier folder itself — it must stay. (Remove
    used to rmdir it as an "empty parent"; Graduate/Demote never removed folders, so they pass both
    ways.)"""
    episodes = [_write(os.path.join(_tier(cm, tier), f"第{n:02d}話.srt"), EPISODE) for n in (1, 2, 3)]
    cm._sync_disk_to_manifest()

    _run(cm, op, episodes, tier)

    assert os.path.isdir(_tier(cm, tier)) and os.listdir(_tier(cm, tier)) == []
    for name in ("HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed", ".trash"):
        assert os.path.isdir(_tier(cm, name))


# ---------------------------------------------------------------------------------------------- #
# Metadata travels with its file
# ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_a_transcripts_timestamp_file_moves_with_it(cm, op, tier, dest):
    """Without its sidecar a moved transcript's ▶ links open the video at 0:00."""
    channel = os.path.join(_tier(cm, tier), "日本語チャンネル")
    txt = _transcript(channel)
    _write(os.path.join(channel, "第02話.txt"), CHAPTER)      # the channel folder keeps content
    cm._sync_disk_to_manifest()
    text_bytes, sidecar_bytes = _read(txt), _read(os.path.splitext(txt)[0] + ".surasura.json")

    _run(cm, op, [txt], tier)

    assert not os.path.exists(os.path.splitext(txt)[0] + ".surasura.json"), "the sidecar stayed behind"
    if dest:
        landed = _landed(cm, dest, tier, txt)
        assert _read(landed) == text_bytes
        assert _read(os.path.splitext(landed)[0] + ".surasura.json") == sidecar_bytes
    else:
        trash = os.path.join(cm.data_root, ".trash")
        [trashed] = [n for n in os.listdir(trash) if n.endswith(".txt")]
        assert _read(os.path.join(trash, os.path.splitext(trashed)[0] + ".surasura.json")) == sidecar_bytes


@pytest.mark.parametrize("op, tier, dest", MOVES)
def test_a_transcripts_timestamp_file_is_renamed_with_it_on_a_name_clash(cm, op, tier, dest):
    """The destination already holds a transcript of that name (a re-download), so the moved one gets
    a new name — and its sidecar must take the same new name, or the report can't find it. The one
    already there, and its sidecar, stay untouched."""
    moving = _transcript(_tier(cm, tier))
    other_text = "昨日とは違う録音です。\n"
    other_sidecar = dict(SIDECAR, cues=[["昨日とは違う録音です。", 0.8]])
    existing = _transcript(_tier(cm, dest), text=other_text, sidecar=other_sidecar)
    cm._sync_disk_to_manifest()
    moving_bytes, sidecar_bytes = _read(moving), _read(os.path.splitext(moving)[0] + ".surasura.json")
    existing_bytes = _read(existing)

    _run(cm, op, [moving], tier)

    stem = re.escape(VIDEO)
    [renamed] = [n for n in os.listdir(_tier(cm, dest)) if re.fullmatch(stem + r"_\d+\.txt", n)]
    assert _read(os.path.join(_tier(cm, dest), renamed)) == moving_bytes
    assert _read(os.path.join(_tier(cm, dest), renamed[:-4] + ".surasura.json")) == sidecar_bytes
    assert _read(existing) == existing_bytes
    assert json.loads(_read(os.path.splitext(existing)[0] + ".surasura.json")) == other_sidecar


@pytest.mark.parametrize("whole", [True, False], ids=["whole-book", "some-chapters"])
@pytest.mark.parametrize("op, tier, dest", MOVES)
def test_a_book_folders_source_marker_travels_to_the_new_tab(cm, op, tier, dest, whole):
    """Without the marker the destination can't tell a book chapter from a note: the source badge
    read 📄 text instead of 📖 book. A whole book takes its marker along (exactly one — never a
    second, renamed copy); a partly moved book leaves its marker for the chapters still there."""
    book = os.path.join(_tier(cm, tier), "吾輩は猫である")
    chapters = _book(book)
    cm._sync_disk_to_manifest()
    moving = chapters if whole else chapters[:1]

    _run(cm, op, moving, tier)

    landed = _landed(cm, dest, tier, moving[0])
    assert cm._detect_source_type(landed) == "epub"
    new_home = os.path.dirname(landed)
    assert json.loads(_read(os.path.join(new_home, ".surasura_source.json"))) == MARKER
    assert [n for n in os.listdir(new_home) if n.startswith(".surasura_source")] == [".surasura_source.json"]
    rows = {e["physical_path"]: e for e in _manifest(cm)["schedule"][PHASE[dest]]}
    assert rows[os.path.relpath(landed, cm.data_root).replace("\\", "/")]["source_type"] == "epub"
    if not whole:
        assert json.loads(_read(os.path.join(book, ".surasura_source.json"))) == MARKER


# ---------------------------------------------------------------------------------------------- #
# Leftovers follow the content, or go to the trash dated
# ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("op, tier, dest", MOVES)
def test_leftover_files_follow_a_graduated_or_demoted_folder(cm, op, tier, dest):
    """The user's own cover.jpg is not content, but it is theirs: when the whole folder moves, it
    moves with it — nothing is thrown away and nothing stays behind."""
    series = os.path.join(_tier(cm, tier), "ハイキュー")
    episodes = [_write(os.path.join(series, f"第{n:02d}話.srt"), EPISODE) for n in (1, 2, 3)]
    _write(os.path.join(series, "cover.jpg"), COVER)
    cm._sync_disk_to_manifest()

    _run(cm, op, episodes, tier)

    assert not os.path.exists(series)
    assert _read(_landed(cm, dest, tier, os.path.join(series, "cover.jpg"))) == COVER


def test_removing_a_whole_folder_sends_its_leftovers_to_trash_dated(cm):
    """Remove moves the leftovers of an emptied folder into ONE dated folder in the trash, whose
    30-day clock starts now (they keep their old modified times otherwise)."""
    book = os.path.join(_tier(cm, "HighPriority"), "吾輩は猫である")
    chapters = _book(book, cover=True)
    old = time.time() - 60 * 24 * 3600
    os.utime(os.path.join(book, "cover.jpg"), (old, old))      # a cover saved two months ago
    cm._sync_disk_to_manifest()

    _run(cm, "remove_files", chapters, "HighPriority")

    assert not os.path.exists(book)
    trash = os.path.join(cm.data_root, ".trash")
    [dated] = [n for n in os.listdir(trash) if os.path.isdir(os.path.join(trash, n))]
    assert re.fullmatch(r"吾輩は猫である_\d{14}", dated)
    kept = os.path.join(trash, dated)
    assert sorted(os.listdir(kept)) == [".surasura_source.json", "cover.jpg"]
    assert _read(os.path.join(kept, "cover.jpg")) == COVER
    assert os.path.getmtime(os.path.join(kept, "cover.jpg")) > time.time() - 60, \
        "the 30-day purge would read the cover's old modified time"


def test_graduating_now_into_graduated_keeps_the_folder_together(cm):
    """NOW -> Graduated archives a finished series: episodes, their timestamps, the book marker and
    the user's cover all end up together in Graduated/<series>/, and nothing remains in NOW."""
    series = os.path.join(_tier(cm, "HighPriority"), "日本語の勉強")
    episodes = [_write(os.path.join(series, f"第{n:02d}話.txt"), CHAPTER) for n in (1, 2)]
    episodes.append(_transcript(series))
    _write(os.path.join(series, "cover.jpg"), COVER)
    _write(os.path.join(series, ".surasura_source.json"), json.dumps(MARKER, ensure_ascii=False))
    cm._sync_disk_to_manifest()

    _run(cm, "graduate_content", episodes, "HighPriority")

    assert not os.path.exists(series)
    archived = os.path.join(_tier(cm, "Graduated"), "日本語の勉強")
    assert sorted(os.listdir(archived)) == sorted(
        [".surasura_source.json", "cover.jpg", "第01話.txt", "第02話.txt",
         VIDEO + ".txt", VIDEO + ".surasura.json"])
    assert _manifest(cm)["schedule"]["PHASE_1_NOW"] == []


# ---------------------------------------------------------------------------------------------- #
# Undo puts the tree back exactly
# ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("op, tier, dest", OPERATIONS)
def test_undo_restores_files_and_metadata_exactly(cm, op, tier, dest):
    """Every file with the same bytes, every folder (an empty one inside a moved book included), the
    same manifest — and nothing the action created is left over: no marker copy, no destination
    folder, no dated folder in the trash."""
    root = _tier(cm, tier)
    series = [_write(os.path.join(root, "シリーズ", season, f"第{n:02d}話.srt"), EPISODE)
              for season in ("シーズン1", "シーズン2") for n in (1, 2)]
    _write(os.path.join(root, "シリーズ", "cover.jpg"), COVER)
    book = _book(os.path.join(root, "吾輩は猫である"), cover=True)
    os.makedirs(os.path.join(root, "吾輩は猫である", "特典"))          # an empty folder of the user's
    partial = _book(os.path.join(root, "こころ"), chapters=2)         # only one chapter moves
    channel = os.path.join(root, "日本語チャンネル")
    video = _transcript(channel)
    cm._sync_disk_to_manifest()
    before, manifest_before = _snapshot(cm.data_root), _manifest(cm)

    _run(cm, op, series + book + partial[:1] + [video], tier)
    assert _snapshot(cm.data_root) != before
    cm.undo_last_action()

    after = _snapshot(cm.data_root)
    assert sorted(set(after) - set(before)) == [], "left over after Undo"
    assert sorted(set(before) - set(after)) == [], "missing after Undo"
    assert after == before, "a file came back with different bytes"
    assert _manifest(cm) == manifest_before
