# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview's "add to the front of NOW" with the library store (2.5; Library_Store_Spec §7, §10 WP-L7 #1, #6).

Store mode: the transcripts are copied into HighPriority and go in with ONE `insert` at the top of NOW — no other
file moves, the rest of the order is kept. Read-only mode (a damaged store) refuses, copying nothing. JSON mode (no
store yet): the manifest as before, its replace under the store's copy lock, so a second process holding the lock
makes it wait. Every proof runs for Japanese and Chinese, on a temp SURASURA_TEST_ROOT (the suite's conftest).
"""
import os
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import pytest

from app import library_store as ls
from modules.youtube_downloader import preview as pv
from tests.test_library_store_support import (LANGUAGES, library, names, read_doc, roots, subprocess_env,
                                              write_manifest)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(autouse=True)
def _no_helper(monkeypatch):
    """The real helper is a detached process; a test records the ask instead."""
    calls = []
    monkeypatch.setattr(ls, "spawn_maintain", lambda language, *extra: calls.append((language,) + extra))
    return calls


def _transcript(language):
    """A downloaded transcript, named as yt-dlp names them, outside the library."""
    word = names(language)[7]
    src = os.path.join(tempfile.mkdtemp(), f"{word} - {names(language)[8]} [dQw4w9WgXcQ].txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(word + "\n")
    return src


def _paths(language):
    data_dir, user_files_dir = roots(language)
    return (patch.object(pv, "get_data_path", return_value=data_dir),
            patch.object(pv, "get_user_files_path", return_value=user_files_dir))


def _files(root):
    return sorted(os.path.relpath(os.path.join(r, n), root) for r, _d, fs in os.walk(root) for n in fs)


@pytest.mark.parametrize("language", LANGUAGES)
def test_store_mode_adds_the_transcript_with_one_insert_at_the_top_of_now(language, _no_helper):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    with ls.open_store(language, data_dir, user_files_dir) as store:
        before = {t: [e["physical_path"] for _i, e, _a in store.ordered(t)] for t in ls.ANALYSED}
    files_before = _files(data_dir)
    src = _transcript(language)
    a, b = _paths(language)
    with a, b, patch.object(ls.Store, "insert", autospec=True, side_effect=ls.Store.insert) as insert:
        added = pv.commit_to_front([src], language)
    name = os.path.basename(src)
    assert added == [name]
    assert insert.call_count == 1, "one store command"
    with ls.open_store(language, data_dir, user_files_dir) as store:
        after = {t: [e["physical_path"] for _i, e, _a in store.ordered(t)] for t in ls.ANALYSED}
    # 3.0's Soon line stays at its count (L3.1, G2.2-1): the row that was NOW's last crosses it to the top of Soon
    assert after["now"] == ["HighPriority/" + name] + before["now"][:-1]
    assert after["soon"] == before["now"][-1:] + before["soon"] and after["goal"] == before["goal"]
    assert _files(data_dir) == sorted(files_before + [os.path.join("HighPriority", name)]), "no other file moved"
    assert _no_helper == [(language,)], "the copy is left to the helper"


@pytest.mark.parametrize("language", LANGUAGES)
def test_read_only_mode_refuses_and_copies_nothing(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test")
    copy, files_before = read_doc(user_files_dir), _files(data_dir)
    a, b = _paths(language)
    with a, b, pytest.raises(pv.PreviewError, match="repaired"):
        pv.commit_to_front([_transcript(language)], language)
    assert read_doc(user_files_dir) == copy and _files(data_dir) == files_before


HOLD = ("import sys, time; sys.path.insert(0, %r)\n"
        "from app import library_store as ls\n"
        "lock = ls._copy_lock(ls.library_db_path(%r, %r))\n"
        "assert lock.acquire(5, 0.001)\n"
        "open(%r, 'w').close()\n"
        "time.sleep(0.8)\n"
        "lock.release(); lock.close()\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_json_mode_waits_for_the_copy_lock_another_process_holds(language, tmp_path):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    assert pv._library_mode(language, data_dir) == "json"
    flag = str(tmp_path / "held")
    holder = subprocess.Popen([sys.executable, "-c", HOLD % (REPO, language, data_dir, flag)], env=subprocess_env())
    src = _transcript(language)
    a, b = _paths(language)
    try:
        deadline = time.monotonic() + 30
        while not os.path.exists(flag) and time.monotonic() < deadline:
            time.sleep(0.01)
        t0 = time.monotonic()
        with a, b:
            pv.commit_to_front([src], language)
        waited = time.monotonic() - t0
    finally:
        holder.wait(30)
    assert waited > 0.3, f"saved after {waited:.3f} s while another process held the copy lock"
    now = read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"]
    assert now[0]["physical_path"] == "HighPriority/" + os.path.basename(src)
    assert [e["physical_path"] for e in now[1:]] == [e["physical_path"] for e in doc["schedule"]["PHASE_1_NOW"]]
