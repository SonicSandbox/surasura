import os
import pytest
from unittest.mock import patch, MagicMock

# Content importer imports messagebox/filedialog at module load; the autouse fixture below
# mocks messagebox so no dialog blocks the tests.


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
        mock.askyesno.return_value = True  # user confirms the merge
        yield mock


from app.content_importer_gui import ContentImporterApp


@pytest.fixture
def app_instance(tmp_path):
    data_root = tmp_path / "data" / "ja"
    for sub in ("HighPriority", "LowPriority", "GoalContent"):
        (data_root / sub).mkdir(parents=True)

    # Skip the real GUI __init__, then wire only the attributes add_folder touches.
    with patch.object(ContentImporterApp, "__init__", lambda self, root, language="ja": None):
        app = ContentImporterApp(None, language="ja")
        app.data_root = str(data_root)
        app.language = "ja"
        app.target_folder_var = MockStringVar("HighPriority")
        app.status_var = MockStringVar()
        app.undo_btn = MagicMock()
        # Isolate the file-merge from the manifest / tree machinery.
        app.load_manifest = MagicMock(return_value={"schedule": {}})
        app.add_to_manifest = MagicMock()
        app.set_undo_action = MagicMock()
        app.refresh_file_list = MagicMock()
    return app, data_root


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_reimport_merges_and_never_destroys_existing(app_instance, tmp_path):
    """Re-importing a same-named folder must MERGE, not delete (finding content-importer-01).
    Existing files are preserved; an identical incoming file is skipped; a same-named file with
    different content is kept as a de-duped copy; new files (incl. .md) are added."""
    app, data_root = app_instance

    existing = data_root / "HighPriority" / "Show"
    _write(existing / "ep1.txt", "ORIGINAL EPISODE ONE 日本語")
    _write(existing / "keep.txt", "KEEP ME 日本語")
    _write(existing / "same.txt", "IDENTICAL 日本語")

    source = tmp_path / "incoming" / "Show"
    _write(source / "ep1.txt", "DIFFERENT VERSION 日本語")   # name clash, different content
    _write(source / "same.txt", "IDENTICAL 日本語")          # name clash, identical content
    _write(source / "ep2.txt", "EPISODE TWO 日本語")          # brand new
    _write(source / "notes.md", "# メモ\nMarkdown notes")     # brand new, .md (content-importer-03)

    with patch("app.content_importer_gui.filedialog.askdirectory", return_value=str(source)):
        app.add_folder()

    # Pre-existing content is untouched.
    assert (existing / "ep1.txt").read_text(encoding="utf-8") == "ORIGINAL EPISODE ONE 日本語"
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "KEEP ME 日本語"
    # New files were added (including the markdown file).
    assert (existing / "ep2.txt").exists()
    assert (existing / "notes.md").exists()
    # The conflicting, different-content file was kept as a copy — not overwritten.
    assert (existing / "ep1 (2).txt").read_text(encoding="utf-8") == "DIFFERENT VERSION 日本語"
    # The identical file was NOT duplicated.
    assert not (existing / "same (2).txt").exists()
    # The new files were registered in the manifest.
    assert app.add_to_manifest.called


def test_md_is_a_supported_content_type(app_instance):
    """The Add Files picker advertises Markdown, so is_content_file must accept it
    (finding content-importer-03)."""
    app, _ = app_instance
    assert app.is_content_file("notes.md") is True
    assert app.is_content_file("chapter.MD") is True
