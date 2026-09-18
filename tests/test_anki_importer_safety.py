"""Data-safety fixes in the `.apkg` importer (`app/anki_db_importer_gui.py`, spec §5.8 / WP-K7).

**Why:** the `.apkg` path stays as the offline fallback, and before these fixes it could destroy the
user's known words in four quiet ways — each of them passed every existing test:

  * a KnownWord.json it could not parse was silently replaced by an Anki-only list (I4);
  * the write was a plain `open(..., 'w')`, so a crash mid-dump left half a file (I5);
  * every word it found was forced to KNOWN — including words the user had deliberately IGNORED;
  * the header was rebuilt from scratch, dropping Migaku's `databaseFile` and anything else.

`update_known_words` is exercised unbound on a tiny stand-in (it only reads `self.language`), so the
data rules are tested without a window. The window checks (colour, tooltips, the explanatory line,
the error shown on a corrupt file) share ONE Tk root for the whole file (`testing.md` §5.4).

Real Japanese entries taken from `tests/Test Resources/ja/KnownWord.json` (a real Migaku export).
"""
import json
import os
import tkinter as tk
from types import SimpleNamespace
from unittest import mock

import pytest

from app import anki_db_importer_gui as importer
from app.anki_db_importer_gui import AnkiImporterApp
from app.path_utils import get_user_files_path


def _known_path():
    return os.path.join(get_user_files_path("ja"), "KnownWord.json")


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def migaku_file(ja_resources_dir):
    """A slice of the real Migaku export — one entry per status — in the sandboxed User Files/ja/."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    picked = {}
    for w in data["words"]:
        picked.setdefault(w["knownStatus"], w)
    data["words"] = [picked[s] for s in ("KNOWN", "LEARNING", "UNKNOWN", "IGNORED")]
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    with open(_known_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _update(words):
    AnkiImporterApp.update_known_words(SimpleNamespace(language="ja"), words)


def _load():
    with open(_known_path(), encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Data rules
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("content", ['{"words": [{"dictForm": "冒険"', '"冒険"', '{"words": "冒険"}'])
def test_an_unparseable_known_file_is_never_overwritten(content):
    """I4: previously the parse error was swallowed and the file replaced with Anki-only words."""
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    with open(_known_path(), "w", encoding="utf-8") as f:
        f.write(content)
    before = _read_bytes(_known_path())
    with pytest.raises(ValueError, match="nothing was changed"):
        _update({("冒険", "ボウケン")})
    assert _read_bytes(_known_path()) == before


def test_ignored_words_stay_ignored_and_only_learning_or_unknown_are_upgraded(migaku_file):
    """An IGNORED word is a deliberate user decision; an .apkg that happens to contain it must not
    undo it. LEARNING/UNKNOWN words found in the deck are genuinely known now."""
    by_status = {w["knownStatus"]: w for w in migaku_file["words"]}
    _update({(w["dictForm"], w["secondary"]) for w in migaku_file["words"]})

    after = {(w["dictForm"], w["secondary"]): w["knownStatus"] for w in _load()["words"]}
    for status, expected in (("KNOWN", "KNOWN"), ("LEARNING", "KNOWN"),
                             ("UNKNOWN", "KNOWN"), ("IGNORED", "IGNORED")):
        w = by_status[status]
        assert after[(w["dictForm"], w["secondary"])] == expected, status


def test_unknown_top_level_keys_and_existing_order_are_preserved(migaku_file):
    _update({("冒険", "ボウケン"), ("準備", "ジュンビ")})
    data = _load()
    assert data["databaseFile"] == migaku_file["databaseFile"], "Migaku's header key survives"
    assert [w["dictForm"] for w in data["words"][:4]] == [w["dictForm"] for w in migaku_file["words"]]
    assert {w["dictForm"] for w in data["words"][4:]} == {"冒険", "準備"}
    assert data["statistics"]["totalWords"] == 6


def test_a_failed_write_leaves_the_original_file_and_no_temp_files(migaku_file):
    """I5: a crash mid-dump must not leave half a KnownWord.json for the analyzer to choke on."""
    before = _read_bytes(_known_path())

    def dies_midway(obj, f, **kw):
        f.write('{"words": [')
        raise OSError("disk full")

    with mock.patch.object(importer.json, "dump", dies_midway):
        with pytest.raises(OSError):
            _update({("冒険", "ボウケン")})
    assert _read_bytes(_known_path()) == before
    assert os.listdir(get_user_files_path("ja")) == ["KnownWord.json"]


def test_a_missing_file_is_created(tmp_path):
    _update({("冒険", "ボウケン")})
    data = _load()
    assert [w["dictForm"] for w in data["words"]] == ["冒険"]
    assert data["words"][0]["knownStatus"] == "KNOWN"


# --------------------------------------------------------------------------- #
# The window (one Tk root for the whole file)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def window():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    tips = []
    real = importer.ToolTip

    def recording(widget, text):
        tips.append((widget, text))
        return real(widget, text)

    with mock.patch.object(importer, "ToolTip", recording):
        app = AnkiImporterApp(root, language="ja")
    yield app, tips
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_text_colour_follows_the_gui_guideline():
    assert importer.TEXT_COLOR == "#e0e0e0"


def test_browse_and_generate_have_tooltips(window):
    app, tips = window
    tipped = {str(widget): text for widget, text in tips}
    assert tipped.get(str(app.browse_btn)), "Browse needs a tooltip"
    assert tipped.get(str(app.extract_btn)), "Generate needs a tooltip"
    assert "ignored" in tipped[str(app.extract_btn)].lower()


def test_the_window_says_it_imports_every_note(window):
    app, _tips = window
    texts = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except tk.TclError:
                pass
            walk(child)

    walk(app.root)
    assert "Imports every note in the file. To import only studied cards, use Sync from Anki." in texts


def test_generate_on_a_corrupt_known_file_shows_an_error_and_writes_nothing(window):
    """The end-to-end path a user takes: the error is shown, the file is untouched, the window stays."""
    app, _tips = window
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    with open(_known_path(), "w", encoding="utf-8") as f:
        f.write('{"words": [{"dictForm": "冒険"')
    before = _read_bytes(_known_path())

    app.anki_notes = [(1, "冒険\x1f冒険の準備はできていますか？")]
    app.anki_model_map = {1: ["Expression", "Sentence"]}
    app.anki_field_var.set("Expression")
    app.file_path_var.set(_known_path())          # any existing path; process_extraction only needs non-empty
    with mock.patch.object(importer.messagebox, "showerror") as showerror, \
         mock.patch.object(importer.messagebox, "askyesno", return_value=True):
        app.process_extraction()

    assert showerror.called and "nothing was changed" in showerror.call_args[0][1]
    assert _read_bytes(_known_path()) == before
    assert app.root.winfo_exists()
