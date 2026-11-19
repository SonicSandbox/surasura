"""surasura.json's `skipped_folders` (Kura-NA, a Send report of 2026-11-18: hato kept finding subtitles for a folder the
learner skipped in Surasura). One list, Surasura's: the store's skipped folders (*Never read this folder*), told to hato
through the entry it already reads, per language — so a skip (or a *Read again*) reaches hato at its next pass, with no
second list to keep in step by hand.

What a wrong answer costs: hato fetching and handing over a skipped folder's episodes again and again (they then come
back into New arrivals), or — a store busy for a moment read as "nothing skipped" — hato fetching for every skipped
folder until the next refresh. The entry is never held back for the list: over the file's 4 KiB the list is left out
(`register` still refuses a skipped folder's video).

Each test has its own test root (SURASURA_TEST_ROOT) and tools folder; a frozen, installed build is faked as in
test_tools_entry.py. Folder names in Japanese and Chinese, as learners' download folders often are.
"""
import json
import os
import sqlite3
import sys

import pytest

from app import library_store as ls
from app import path_utils, tools_entry
from tests.test_library_store_support import library, write_manifest


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "データ根"
    r.mkdir()
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(r))
    return r


@pytest.fixture
def tools(tmp_path, monkeypatch):
    folder = tmp_path / "tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    install = tmp_path / "スラスラ"
    install.mkdir()
    (install / "Surasura.exe").write_bytes(b"MZ")
    (install / "surasura-cli.exe").write_bytes(b"MZ")
    lib = tmp_path / "ライブラリ"
    lib.mkdir()
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "installed_library", lambda: str(lib))
    monkeypatch.setattr(sys, "executable", str(install / "Surasura.exe"))
    return install


def _store(language):
    data_dir, user_files_dir, doc = library(language, shows=0, loose=0)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store(language, data_dir, user_files_dir)


def _source(tmp_path, *names):
    """A downloads folder read as a source, with the folders `names` inside it -> (source, [those folders])."""
    src = tmp_path / "ダウンロード"
    inside = [src / n for n in names]
    for f in inside:
        f.mkdir(parents=True)
    return str(src), [str(f) for f in inside]


def _entry(tools):
    return json.loads((tools / "surasura.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_skip_and_its_read_again_reach_the_entry_at_the_next_refresh(root, tools, frozen, tmp_path, language):
    src, (inside,) = _source(tmp_path, {"ja": "ダウンロード中", "zh": "下载中"}[language])
    with _store(language) as s:
        s.add_source(src)
        s.skip_folder(inside)
        (folder,) = [f["id"] for f in s.skipped_folders()]
    assert tools_entry.refresh({}) is True
    assert _entry(tools)["skipped_folders"] == {language: [os.path.normpath(inside)]}
    with ls.open_store(language, path_utils.get_data_path(language), path_utils.get_user_files_path(language)) as s:
        s.read_folder_again(folder)
    assert tools_entry.refresh({}) is True
    assert _entry(tools)["skipped_folders"] == {language: []}


def test_a_store_that_cant_be_read_now_keeps_the_list_the_entry_had(root, tools, frozen, tmp_path, monkeypatch):
    """A busy moment is never read as "nothing skipped": the entry keeps its list until the store answers."""
    src, (inside,) = _source(tmp_path, "Downloading")
    with _store("ja") as s:
        s.add_source(src)
        s.skip_folder(inside)
    assert tools_entry.refresh({}) is True
    real = sqlite3.connect

    def busy(target, *a, **kw):
        if "mode=ro" in str(target):
            raise sqlite3.OperationalError("database is locked")
        return real(target, *a, **kw)
    monkeypatch.setattr(sqlite3, "connect", busy)
    assert tools_entry.refresh({"connect_enabled": True}) is True            # (another field moved: written)
    assert _entry(tools)["skipped_folders"] == {"ja": [os.path.normpath(inside)]}


def test_no_store_yet_lists_nothing_for_that_language(root, tools, frozen):
    (root / "User Files" / "ja").mkdir(parents=True)
    assert tools_entry.entry({})["skipped_folders"] == {}


def test_too_many_skipped_folders_for_the_small_file_leave_the_list_out_never_the_entry(root, tools, frozen,
                                                                                         tmp_path):
    src, folders = _source(tmp_path, *[f"季節 {n:03d} の長いフォルダの名前 · Season folder {n:03d}" for n in range(60)])
    with _store("ja") as s:
        s.add_source(src)
        for f in folders:
            s.skip_folder(f)
    assert tools_entry.refresh({}) is True
    got = _entry(tools)
    assert "skipped_folders" not in got and got["verbs"] == ["status"]
    assert len((tools / "surasura.json").read_bytes()) <= tools_entry.MAX_BYTES


@pytest.mark.parametrize("odd", ["データ#根", "c%41d 根"])
def test_a_store_path_with_a_hash_or_a_percent_is_read(tools, frozen, tmp_path, monkeypatch, odd):
    """The store file is opened read-only by a URI: a `#` or `%` in its path (a learner's folder name) must neither
    drop `mode=ro` (and make an empty stray file) nor fail the open — the list is read."""
    r = tmp_path / odd
    r.mkdir()
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(r))
    src, (inside,) = _source(tmp_path, "Downloading")
    with _store("ja") as s:
        s.add_source(src)
        s.skip_folder(inside)
    assert tools_entry.entry({})["skipped_folders"] == {"ja": [os.path.normpath(inside)]}

