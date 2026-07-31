"""Zip import + the narrowed content-file filter + double-click-to-open (Content Manager).

A zip is a CONTAINER, not content: `add_files` unpacks it into one ordered group instead of copying
the archive (which the analyzer could never read). These tests cover the real hazards — archives
whose names are CP932 (every Japanese subtitle pack), path-traversal members, and an archive with
nothing usable in it.
"""

import json
import os
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app.content_importer_gui import ContentImporterApp
from app.path_utils import is_content_file


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
def app_instance(tmp_path):
    data_root = tmp_path / "data" / "ja"
    for sub in ("HighPriority", "LowPriority", "GoalContent"):
        (data_root / sub).mkdir(parents=True)

    with patch.object(ContentImporterApp, "__init__", lambda self, root, language='ja': None):
        app = ContentImporterApp(None, language="ja")
        app.root = MagicMock()
        app.data_root = str(data_root)
        app.language = "ja"
        app.target_folder_var = MockStringVar("HighPriority")
        app.status_var = MockStringVar()
        app.tree = MagicMock()
        app.graduate_btn = MagicMock()
        app.undo_btn = MagicMock()
        app.analyzed_filenames = set()
        app._last_stats_mtime = 0
        app._last_stats_size = 0
        app.get_manifest_path = lambda: str(data_root / "master_manifest.json")
        return app


# Real subtitle cues — a zip of .srt episodes is the canonical case for this feature.
SRT_EPISODE = (
    "1\n00:00:01,000 --> 00:00:03,500\n"
    "また会えるとは思わなかった。\n\n"
    "2\n00:00:04,000 --> 00:00:07,200\n"
    "この街には、まだ秘密が残っている。\n"
)


def _make_zip(path, members):
    """Write a zip. members = {archive_name: bytes|str}."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))


def _phase(app, key="PHASE_1_NOW"):
    """Manifest rows for a phase. A missing manifest means nothing was ever tracked."""
    path = app.get_manifest_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [e["physical_path"] for e in json.load(f)["schedule"].get(key, [])]


# --- the narrowed content filter --------------------------------------------------------------- #
def test_content_filter_accepts_only_what_the_analyzer_reads():
    """.epub/.html/.pdf used to be tracked, then silently skipped at analysis — dead library rows."""
    for good in ("ep01.srt", "chapter.txt", "notes.md", "signs.ass", "EP02.SRT"):
        assert is_content_file(good), f"{good} must be importable"
    for bad in ("book.epub", "page.html", "page.htm", "doc.pdf", "subs.vtt", "pack.zip"):
        assert not is_content_file(bad), f"{bad} must NOT be registered as content"


# --- happy path -------------------------------------------------------------------------------- #
def test_zip_unpacks_into_one_group_in_order(app_instance, tmp_path):
    """A season pack becomes one group, chapters in archive order, tracked in the manifest."""
    zip_path = tmp_path / "深夜特急 第1期.zip"
    _make_zip(zip_path, {f"ep{i:02d}.srt": SRT_EPISODE for i in range(1, 6)})

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    dest = tmp_path / "data" / "ja" / "HighPriority" / "深夜特急 第1期"
    assert dest.is_dir(), "the archive should unpack into a folder named after it"
    assert sorted(p.name for p in dest.iterdir()) == [f"ep{i:02d}.srt" for i in range(1, 6)]
    assert (dest / "ep01.srt").read_text(encoding="utf-8") == SRT_EPISODE

    tracked = _phase(app_instance)
    assert tracked == [f"HighPriority/深夜特急 第1期/ep{i:02d}.srt" for i in range(1, 6)]


def test_zip_preserves_nested_folder_structure(app_instance, tmp_path):
    """Nested folders inside the archive are kept (a book's volumes stay grouped)."""
    zip_path = tmp_path / "全集.zip"
    _make_zip(zip_path, {
        "巻1/ch01.txt": "少年は静かに扉を開けた。",
        "巻1/ch02.txt": "朝の光が窓から差し込んでいる。",
        "巻2/ch01.txt": "雨が降り始めた。傘を持っていない。",
    })

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    root = tmp_path / "data" / "ja" / "HighPriority" / "全集"
    assert (root / "巻1" / "ch01.txt").exists()
    assert (root / "巻2" / "ch01.txt").exists()
    assert "雨が降り始めた" in (root / "巻2" / "ch01.txt").read_text(encoding="utf-8")


def test_cp932_member_names_are_recovered(app_instance):
    """Japanese subtitle packs made on Japanese Windows store names as CP932 with NO UTF-8 flag;
    zipfile hands those back decoded as cp437 (mojibake). We must round-trip them.

    Tested at the decode level because zipfile's writer force-sets the UTF-8 flag for any non-ASCII
    name, so a non-flagged CP932 archive can't be produced through its normal API."""
    info = zipfile.ZipInfo("第01話.srt".encode("cp932").decode("cp437"))
    info.flag_bits = 0                       # exactly what a Japanese-Windows archiver writes
    assert app_instance._zip_member_name(info) == "第01話.srt"

    # UTF-8 bytes written without the flag (some Linux zip tools) must also come back clean.
    info2 = zipfile.ZipInfo("陰の実力者.srt".encode("utf-8").decode("cp437"))
    info2.flag_bits = 0
    assert app_instance._zip_member_name(info2) == "陰の実力者.srt"

    # A properly flagged UTF-8 name is passed through untouched.
    info3 = zipfile.ZipInfo("第02話.srt")
    info3.flag_bits |= 0x800
    assert app_instance._zip_member_name(info3) == "第02話.srt"


def test_zip_with_japanese_names_imports_end_to_end(app_instance, tmp_path):
    """Modern archivers flag names as UTF-8 — the common case must work through the whole flow."""
    zip_path = tmp_path / "字幕.zip"
    _make_zip(zip_path, {"第01話.srt": SRT_EPISODE, "第02話.srt": SRT_EPISODE})

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    dest = tmp_path / "data" / "ja" / "HighPriority" / "字幕"
    assert sorted(p.name for p in dest.iterdir()) == ["第01話.srt", "第02話.srt"]


# --- edge cases ------------------------------------------------------------------------------- #
def test_zip_with_no_supported_content_leaves_nothing_behind(app_instance, tmp_path):
    """An archive of ebooks/images must not create an empty folder or a manifest row."""
    zip_path = tmp_path / "本棚.zip"
    _make_zip(zip_path, {"本.epub": b"PK-not-really", "cover.jpg": b"\xff\xd8\xff", "readme.pdf": b"%PDF"})

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    assert not (tmp_path / "data" / "ja" / "HighPriority" / "本棚").exists()
    assert _phase(app_instance) == []


def test_empty_zip_is_handled(app_instance, tmp_path):
    """A zero-entry archive must not crash or leave a folder."""
    zip_path = tmp_path / "空.zip"
    _make_zip(zip_path, {})

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    assert not (tmp_path / "data" / "ja" / "HighPriority" / "空").exists()


def test_zip_slip_members_cannot_escape_the_destination(app_instance, tmp_path):
    """A member named '../../evil.txt' must never be written outside the unpack folder."""
    zip_path = tmp_path / "悪意.zip"
    _make_zip(zip_path, {
        "../../escaped.txt": "これは書かれてはいけない。",
        "safe.txt": "こちらは正常なファイルです。",
    })

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    dest = tmp_path / "data" / "ja" / "HighPriority" / "悪意"
    assert (dest / "safe.txt").exists(), "legitimate members still import"
    assert not (tmp_path / "data" / "escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "data" / "ja" / "escaped.txt").exists()


def test_nested_zip_is_not_imported(app_instance, tmp_path):
    """A .zip inside a .zip isn't content — we don't recurse (and never register the archive)."""
    zip_path = tmp_path / "入れ子.zip"
    _make_zip(zip_path, {"inner.zip": b"PK\x03\x04", "ok.txt": "その手紙には名前がなかった。"})

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    dest = tmp_path / "data" / "ja" / "HighPriority" / "入れ子"
    assert [p.name for p in dest.iterdir()] == ["ok.txt"]


def test_corrupt_zip_reports_and_does_not_crash(app_instance, tmp_path, mock_messagebox):
    zip_path = tmp_path / "壊れた.zip"
    zip_path.write_bytes(b"this is definitely not a zip archive")

    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(zip_path)]):
        app_instance.add_files()

    assert mock_messagebox.showerror.called
    assert not (tmp_path / "data" / "ja" / "HighPriority" / "壊れた").exists()


def test_zip_and_plain_files_can_be_added_together(app_instance, tmp_path):
    """Mixed selection: the loose file is copied, the archive is unpacked."""
    loose = tmp_path / "メモ.txt"
    loose.write_text("「もう一度だけ話を聞かせてくれ」と彼は言った。", encoding="utf-8")
    zip_path = tmp_path / "束.zip"
    _make_zip(zip_path, {"a.srt": SRT_EPISODE})

    with patch("app.content_importer_gui.filedialog.askopenfilenames",
               return_value=[str(loose), str(zip_path)]):
        app_instance.add_files()

    high = tmp_path / "data" / "ja" / "HighPriority"
    assert (high / "メモ.txt").exists()
    assert (high / "束" / "a.srt").exists()


# --- double-click to open ---------------------------------------------------------------------- #
def test_double_click_opens_the_file(app_instance, tmp_path):
    target = tmp_path / "data" / "ja" / "HighPriority" / "第01話.srt"
    target.write_text(SRT_EPISODE, encoding="utf-8")

    app_instance.tree.identify_row.return_value = "row1"
    app_instance.tree.item.side_effect = lambda i, opt=None, **kw: [str(target)] if opt == "values" else {}
    app_instance.open_path_in_system = MagicMock(return_value=True)

    app_instance.on_item_double_click(MagicMock(y=10))

    app_instance.open_path_in_system.assert_called_once_with(str(target))


def test_double_click_on_group_opens_its_folder(app_instance, tmp_path):
    book = tmp_path / "data" / "ja" / "HighPriority" / "深夜特急"
    book.mkdir(parents=True)
    (book / "ch01.txt").write_text("少年は静かに扉を開けた。", encoding="utf-8")

    def get_children(parent=""):
        return ["grp"] if parent == "" else (["c0"] if parent == "grp" else [])

    def tree_item(item_id, opt=None, **kw):
        if opt == "values":
            return ["GROUP:深夜特急"] if item_id == "grp" else [str(book / "ch01.txt")]
        return {}

    app_instance.tree.identify_row.return_value = "grp"
    app_instance.tree.get_children.side_effect = get_children
    app_instance.tree.item.side_effect = tree_item
    app_instance.open_path_in_system = MagicMock(return_value=True)

    app_instance.on_item_double_click(MagicMock(y=10))

    app_instance.open_path_in_system.assert_called_once_with(str(book))


def test_double_click_on_missing_file_is_reported_not_crashed(app_instance, tmp_path):
    ghost = str(tmp_path / "data" / "ja" / "HighPriority" / "gone.txt")
    app_instance.tree.identify_row.return_value = "row1"
    app_instance.tree.item.side_effect = lambda i, opt=None, **kw: [ghost] if opt == "values" else {}
    app_instance.open_path_in_system = MagicMock()

    app_instance.on_item_double_click(MagicMock(y=10))

    app_instance.open_path_in_system.assert_not_called()
    assert "no longer on disk" in app_instance.status_var.get()
