"""S3.1 row 3.1.0 (app/path_utils.py): gaps the Haiku mutant list found in the installed layout (tests/
test_path_layout.py holds the rest). Every folder is a temp folder; nothing reaches a real root."""
import json
import os

from app import path_utils
from tests.test_path_layout import (_defaults, _library_note, _outside_pytest,  # noqa: F401
                                    bases, program)                                     # (fixtures, used by name)


def test_with_the_library_offline_no_default_list_is_copied_and_nothing_is_made(tmp_path, program, monkeypatch):
    # An installed program whose library folder is offline (a NAS, an unplugged drive) must never create it, nor an
    # empty library in its place: copying a bundled default list into it would make the folder, and the next start
    # would take that empty folder for the user's library.
    _outside_pytest(monkeypatch)
    library = tmp_path / "NAS" / "すらすら"
    _library_note(program, str(library))
    _defaults("ja", {"frequency_list_ja_global50k.csv": "Term,Rank\n冒険,1520\n準備,840\n"})
    assert path_utils.copy_default_lists("ja") == []
    assert not os.path.exists(library) and not os.path.exists(library.parent)


def test_a_library_note_whose_paths_carry_spaces_around_them_is_still_read(tmp_path):
    # library.json names where the user's library lives: if its paths can't be read, an installed program runs
    # portable, as if the library were gone. Spaces around a path (an editor, a script) are not part of it — the note is
    # read as the paths it names, stripped, never refused as "relative".
    program = str(tmp_path / "Programs" / "すらすら")
    library = str(tmp_path / "ライブラリ 図書館")
    os.makedirs(program)
    note = tmp_path / "library.json"
    note.write_text(json.dumps({"install": "  " + program + " ", "library": "\t" + library + "  "}), encoding="utf-8")
    assert path_utils._read_library_note(str(note), program) == os.path.normpath(library)


def test_a_default_list_that_cant_be_copied_is_reported_and_the_others_still_copy(monkeypatch, capsys):
    # A new library's default lists are copied one by one; one refused (a file another program holds, a folder's
    # permissions) is a warning, never the end of the library's setup: the next list is still copied.
    _defaults("ja", {"Blacklist.txt": "# ja Blacklist\n",
                     "IgnoreList.txt": "# Add words to ignore here (one per line)\n為る\n"})
    real = path_utils.shutil.copy2

    def refusing(src, dst, *args, **kwargs):
        if os.path.basename(src) == "Blacklist.txt":
            raise PermissionError(13, "access denied", dst)
        return real(src, dst, *args, **kwargs)
    monkeypatch.setattr(path_utils.shutil, "copy2", refusing)
    assert path_utils.copy_default_lists("ja") == ["IgnoreList.txt"]
    assert "Blacklist.txt" in capsys.readouterr().out
