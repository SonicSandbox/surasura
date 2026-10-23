"""S3.1 row 3.1.6: gaps the Haiku mutant list found in the 2.x -> 3.0 import (tests/test_import_2x.py holds the rest,
and its helpers build the old install here too: real Japanese and Chinese content, every root a temp folder)."""
import codecs
import os

import pytest

from app import import_2x, locks, path_utils
from tests.test_import_2x import (JUNBAN, _old_install, _root, _sha, _tree, _write,  # noqa: F401
                                  roaming)                                             # (roaming: a fixture)


def test_a_library_reached_through_a_junction_into_the_old_folder_is_refused(tmp_path, roaming):
    # The same-folder check compares REAL paths: a library folder reached through a junction that points into the old
    # 2.x folder is inside it all the same. Compared as written, the import would copy the old library into itself,
    # and the old folder — the user's way back to 2.x — would no longer be byte-identical. (A dry run: nothing is
    # written whatever the answer.)
    _winapi = pytest.importorskip("_winapi")
    old = _old_install(tmp_path, store=False)
    link = str(tmp_path / "近道")
    _winapi.CreateJunction(old, link)
    try:
        result = import_2x.run_import(old, os.path.join(link, "3.0 library"), dry_run=True)
        assert result["status"] == "refused" and result["reason"] == "same_folder"
    finally:
        os.rmdir(link)                                     # the junction only, never what it points at


@pytest.mark.parametrize("only", ["User Files", "data"])
def test_a_folder_holding_either_library_folder_is_a_2x_library(tmp_path, only):
    # A 2.x library is `User Files\` OR `data\` (the module's rule): a 2.x folder whose other half was moved or
    # deleted still holds the user's words or content, and must be offered for import, never refused as "not 2.x".
    folder = tmp_path / "旧すらすら"
    (folder / only / "ja").mkdir(parents=True)
    assert import_2x.is_2x_folder(str(folder)) is True
    assert import_2x.check_source(str(folder))["reason"] != "not_2x"


def test_a_comment_only_list_saved_with_a_bom_is_not_content(tmp_path):
    # Notepad saves UTF-8 with a byte order mark: a new library's IgnoreList opened and saved there, still comments
    # only, is the empty list the library's start wrote. Read without the BOM's rule its first line is no comment, and
    # the import would refuse the fresh folder as "already holds a library".
    lists = tmp_path / "新しいライブラリ" / "User Files" / "ja"
    lists.mkdir(parents=True)
    (lists / "IgnoreList.txt").write_bytes(codecs.BOM_UTF8 + b"# Add words to ignore here (one per line)\r\n")
    assert import_2x.library_content(str(tmp_path / "新しいライブラリ")) is None


def test_a_settings_file_that_isnt_utf_8_is_copied_byte_for_byte_never_converted(tmp_path, roaming):
    # A 2.x settings.json hand-edited in a Shift_JIS editor (a deck named 冒険) is not UTF-8: read strictly it is "not
    # readable as settings" and copied exactly as it is. Read with replacement characters it would be converted and
    # written back with the deck's name turned to U+FFFD — the user's setting lost.
    old = _old_install(tmp_path, store=False, languages=("ja",), settings=False)
    raw = ('{"junban_url": "%s", "anki_deck": "冒険::映画"}' % JUNBAN).encode("cp932")
    _write(os.path.join(old, "settings.json"), raw)
    result = import_2x.run_import(old, _root())
    assert result["settings"] == "copied as is"
    assert _sha(path_utils.get_settings_path()) == _sha(os.path.join(old, "settings.json"))


def test_the_settings_import_lets_go_of_the_settings_lock(tmp_path, roaming):
    # Importing into this program's own library writes its settings.json under the `settings` lock, which every
    # Surasura program takes to save its settings: held on after the import, the next save waits it out and fails.
    old = _old_install(tmp_path, store=False, languages=("ja",), settings=False)
    _write(os.path.join(old, "settings.json"), '{"language": "ja", "junban_url": "%s"}' % JUNBAN)
    result = import_2x.run_import(old, _root())
    assert result["settings"] == "converted"
    assert not locks.held_here("settings")


def test_a_word_list_in_another_encoding_is_the_users_content(tmp_path):
    # A 3.0 library whose IgnoreList the user saved in Shift_JIS, holding real words, is a library holding content:
    # unreadable as UTF-8 is not "comments only". Taken for empty, the import would copy 2.x's list over the user's.
    lists = tmp_path / "ライブラリ" / "User Files" / "ja"
    lists.mkdir(parents=True)
    path = lists / "IgnoreList.txt"
    path.write_bytes("# 無視する言葉\r\n冒険\r\n為る\r\n".encode("cp932"))
    assert import_2x.library_content(str(tmp_path / "ライブラリ")) == str(path)


def test_an_old_folder_inside_the_chosen_library_is_refused(tmp_path, roaming):
    # The same-folder refusal goes both ways: a library folder that HOLDS the old one (Documents, when 2.x was
    # unzipped to Documents\Surasura) would take the old program folder into the library's own tree. It is refused
    # before anything is written, as the library inside the old folder is.
    documents = tmp_path / "ドキュメント"
    old = _old_install(documents, store=False)
    before = _tree(str(documents))
    result = import_2x.run_import(old, str(documents))
    assert result["status"] == "refused" and result["reason"] == "same_folder"
    assert _tree(str(documents)) == before and import_2x.read_import_note() is None


def test_a_resumed_import_copies_again_a_file_that_changed_since_whatever_its_size(tmp_path, roaming):
    # A resumed import keeps only the copies already WHOLE — the same bytes as the old file (sha256), never just the
    # same size: the import's record lists each file by the old file's sha256, so a copy changed meanwhile (here
    # one character for another) would be recorded as a copy it isn't.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    done, there = [], set(_tree(_root()))
    import_2x.run_import(old, _root(), progress=lambda s, d, t: done.append(d) if s == "files" else None,
                         cancel=lambda: len(done) >= 2)
    copied = sorted(p for p in set(_tree(_root())) - there if os.path.isfile(os.path.join(old, p)))
    content = [p for p in copied if os.path.basename(p) == "IgnoreList.txt"]      # a word list, never merged
    assert len(copied) == 2 and content
    changed = os.path.join(_root(), content[0])
    raw = open(changed, "rb").read()
    open(changed, "wb").write(raw[:-1] + (b"?" if raw[-1:] != b"?" else b"!"))
    assert os.path.getsize(changed) == len(raw)
    resumed = import_2x.run_import(old, _root())
    assert resumed["status"] == "done" and resumed["counts"]["kept"] == 1
    assert open(changed, "rb").read() == raw


def test_a_copy_the_disk_refuses_fails_the_import_saying_so(tmp_path, roaming, monkeypatch):
    # A write refused mid-import (a full disk, a file held, access denied) is an OSError, not the import's own
    # ImportFailed: it ends the import as "failed" with a sentence and an incomplete record, never as an exception
    # out of run_import (the window and the command line would show a traceback, and the record would still say
    # nothing went wrong).
    import shutil
    old = _old_install(tmp_path, store=False, languages=("ja",))
    real = shutil.copy2

    def refused(src, dst, **kw):
        if src.endswith("IgnoreList.txt"):
            raise PermissionError(13, "simulated: access denied", dst)
        return real(src, dst, **kw)
    monkeypatch.setattr(shutil, "copy2", refused)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "failed" and "access denied" in result["message"]
    note = import_2x.read_import_note()
    assert note["complete"] is False and note["status"] == "failed"


def test_a_settings_file_holding_a_list_is_copied_as_is_never_read_as_settings(tmp_path, roaming):
    # A 2.x settings.json whose JSON is a list (a hand edit that kept only the deck names) is valid JSON but no
    # settings: it is "copied as is", byte for byte, and the import record says so. Taken as settings it would be
    # reported as "copied" — the record telling the user their settings came across — and handed to the settings
    # conversion, which reads it as a dict.
    old = _old_install(tmp_path, store=False, languages=("ja",), settings=False)
    raw = '["冒険::映画", "日本語::文"]'.encode("utf-8")
    _write(os.path.join(old, "settings.json"), raw)
    result = import_2x.run_import(old, _root())
    assert result["status"] == "done" and result["settings"] == "copied as is"
    assert _sha(path_utils.get_settings_path()) == _sha(os.path.join(old, "settings.json"))
    assert import_2x.read_import_note()["settings"] == "copied as is"
