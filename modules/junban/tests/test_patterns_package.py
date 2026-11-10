# SPDX-License-Identifier: GPL-3.0-or-later
"""パターン data packages (`patterns_package.py`, Patterns_Spec.md §18) — the shared database others
download, and the user's own databases carried to another computer.

What this file guards, most costly first:

  * **Nothing half-installed.** Every file is checked against its sha256 before any replaces what is
    there; a damaged package, a tampered download, a package naming anything but a パターン database —
    all change nothing and leave nothing behind.
  * **Only ever パターン databases**, written only to this computer's data folder (never a path from the
    zip).
  * **The download is pinned**: a file that doesn't match the published sha256 is refused. It never
    goes online here — the transport is replaced.

Real databases (the builder's own writer) with real Japanese rows; the data folder is the conftest's
sandbox.
"""
import json
import os
import zipfile
from unittest import mock

import pytest

from modules.junban import backfill, patterns_build as pb, patterns_package as pp
from modules.junban.patterns_store import open_store


def _db(folder, name, word="探検", reading="タンケン", count=40):
    """A real, small パターン database: one word and its line of frames."""
    path = os.path.join(folder, name)
    pb.write_rows(path, [(word, reading, word, "名詞", count)], [(word, word, reading, count)],
                  [(word, reading, "frame", "〜家", 12, 8.5, "F1")], {"floor": 12, "tokens": 1000})
    return path


def _installed():
    folder = pp.destination()
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def test_a_package_carries_its_databases_to_another_computer(tmp_path):
    # The user's case: pack the personal databases here, install them there — byte for byte, and
    # readable by the store the Backfill window opens.
    here = tmp_path / "here"
    here.mkdir()
    paths = [_db(str(here), "patterns_ja_conversational.db"), _db(str(here), "patterns_ja_balanced.db", "囲む", "カコム")]
    package = pp.pack(paths, str(tmp_path / "personal.zip"), kind="personal")
    assert pp.read_manifest(package)["kind"] == "personal"

    assert pp.install(package) == ["patterns_ja_conversational.db", "patterns_ja_balanced.db"]
    assert _installed() == ["patterns_ja_balanced.db", "patterns_ja_conversational.db"]
    for path in paths:
        with open(path, "rb") as a, open(os.path.join(pp.destination(), os.path.basename(path)), "rb") as b:
            assert a.read() == b.read()
    store = open_store(language="ja", name="balanced")
    try:
        assert store.word("囲む", "カコム")[2] == 40
    finally:
        store.close()


def test_a_newer_package_replaces_what_is_there(tmp_path):
    os.makedirs(pp.destination(), exist_ok=True)
    _db(pp.destination(), "patterns_ja_shared.db", count=20)
    package = pp.pack([_db(str(tmp_path), "patterns_ja_shared.db", count=90)], str(tmp_path / "shared.zip"),
                      kind="shared")
    pp.install(package)
    store = open_store(language="ja", name="shared")
    try:
        assert store.word("探検", "タンケン")[2] == 90
    finally:
        store.close()


def test_a_damaged_package_changes_nothing_and_leaves_nothing_behind(tmp_path):
    # Two files, the second damaged: the first must not be put in place either.
    good = _db(str(tmp_path), "patterns_ja_conversational.db")
    bad = _db(str(tmp_path), "patterns_ja_balanced.db")
    package = pp.pack([good, bad], str(tmp_path / "p.zip"))
    with zipfile.ZipFile(package) as zf:
        manifest = json.loads(zf.read(pp.MANIFEST))
        contents = {name: zf.read(name) for name in zf.namelist() if name != pp.MANIFEST}
    manifest["files"][1]["sha256"] = "0" * 64                  # as if the file were damaged in transit
    with zipfile.ZipFile(package, "w") as zf:
        for name, data in contents.items():
            zf.writestr(name, data)
        zf.writestr(pp.MANIFEST, json.dumps(manifest))
    with pytest.raises(pp.PackageError, match="damaged"):
        pp.install(package)
    assert _installed() == []                                     # no database, no .part file


@pytest.mark.parametrize("name", ["settings.json", "../patterns_ja.db", "patterns_ja.db.exe", "KnownWord.json"])
def test_a_package_naming_anything_but_a_patterns_database_is_refused(tmp_path, name):
    # Only ever パターン databases, and never where the zip says: a package is not an installer.
    # Its checksum is right, so only the name can refuse it.
    import hashlib
    package = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr(name, b"x")
        zf.writestr(pp.MANIFEST, json.dumps({"surasura": "patterns", "files": [
            {"name": name, "sha256": hashlib.sha256(b"x").hexdigest()}]}))
    with pytest.raises(pp.PackageError, match="damaged or not a"):
        pp.install(package)
    assert _installed() == []
    assert not os.path.exists(os.path.join(os.path.dirname(pp.destination()), "patterns_ja.db"))


def test_a_file_that_is_not_a_package_says_so(tmp_path):
    for content in (b"not a zip at all", None):
        path = str(tmp_path / "other.zip")
        if content is None:
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("readme.txt", "hello")               # a zip, but no manifest
        else:
            with open(path, "wb") as f:
                f.write(content)
        with pytest.raises(pp.PackageError, match="not a Surasura パターン package"):
            pp.install(path)
    with pytest.raises(pp.PackageError):
        pp.pack([str(tmp_path / "other.zip")], str(tmp_path / "x.zip"))   # packing, too: databases only


def test_the_shared_download_is_refused_unless_it_is_the_published_file(tmp_path):
    # Never online: the transport copies a local package. A file that is not the pinned one is refused
    # and nothing is installed; the published one installs; the download's folder is gone either way.
    package = pp.pack([_db(str(tmp_path), "patterns_ja_shared.db")], str(tmp_path / "patterns_ja_shared.zip"),
                      kind="shared")
    folders = []

    def fake_download(url, dest, progress_cb=None, timeout=60):
        assert url == pp.SHARED_URL
        folders.append(os.path.dirname(dest))
        with open(package, "rb") as src, open(dest, "wb") as out:
            out.write(src.read())
        if progress_cb:
            progress_cb(1, 1)
        return dest

    with mock.patch("app.updater.download", side_effect=fake_download):
        with pytest.raises(pp.PackageError, match="did not match"):
            pp.get_shared()
        assert _installed() == []
        with mock.patch.object(pp, "SHARED_SHA256", pp._sha256(package)):
            assert pp.get_shared() == ["patterns_ja_shared.db"]
    assert _installed() == ["patterns_ja_shared.db"]
    assert not any(os.path.exists(folder) for folder in folders)


def test_no_connection_is_a_message_not_a_crash():
    with mock.patch("app.updater.download", side_effect=OSError("getaddrinfo failed")):
        with pytest.raises(pp.PackageError, match="Could not download"):
            pp.get_shared()


def test_the_shared_download_names_a_commit_never_a_branch():
    # A branch moves: an app pinned to `main` would fetch the NEXT data version the day it is committed,
    # and refuse it (its sha256 is pinned too) — every older app's download would break at once. A
    # commit never changes, so each app version keeps the file it was built for (RELEASE.md).
    import re
    assert re.fullmatch(r"https://raw\.githubusercontent\.com/SonicSandbox/surasura/[0-9a-f]{40}/"
                        r"release_assets/patterns/patterns_ja_shared\.zip", pp.SHARED_URL)
    assert re.fullmatch(r"[0-9a-f]{64}", pp.SHARED_SHA256)


def test_the_window_knows_which_data_is_here():
    # "Get data…" while no general database is here; "Build & preview" while the library's own is not.
    folder = pp.destination()
    os.makedirs(folder, exist_ok=True)
    assert (backfill.general_ready("ja"), backfill.data_ready("ja")) == (False, False)
    _db(folder, "patterns_ja_shared.db")
    assert (backfill.general_ready("ja"), backfill.data_ready("ja")) == (True, False)
    _db(folder, "patterns_ja.db")
    assert (backfill.general_ready("ja"), backfill.data_ready("ja")) == (True, True)


def test_the_window_asks_again_for_data_an_older_builder_made():
    # Patterns_Quality_Spec §8.3a: an older builder keyed words the old way (不自然 was 不 + 自然), so its
    # database is no data — the window offers "Get data…" / "Build & preview" again, for Chinese's builder 1
    # too. (Until the sweep of 2026-09-25 only is_current itself was tested, never the window's two checks.)
    from modules.junban import patterns_zh as pz
    folder = pp.destination()
    os.makedirs(folder, exist_ok=True)

    def write(name, word, language, version):         # a fresh file each time: write_rows only creates
        path = os.path.join(folder, name)
        if os.path.exists(path):
            os.remove(path)
        pb.write_rows(path, [word], [], [], {"floor": 12, "language": language, "builder_version": version})

    for name, language, word, old, new in (
            ("patterns_ja_shared.db", "ja", ("探検", "タンケン", "探検", "名詞", 40), pb.BUILDER_VERSION - 1,
             pb.BUILDER_VERSION),
            ("patterns_zh_shared.db", "zh", ("问题", "", "问题", "n", 100), 1, pz.BUILDER_VERSION)):
        for version, ready in ((old, False), (new, True)):
            write(name, word, language, version)
            assert backfill.general_ready(language) == ready, (language, version)
    for version, ready in ((pb.BUILDER_VERSION - 1, False), (pb.BUILDER_VERSION, True)):
        write("patterns_ja.db", ("探検", "タンケン", "探検", "名詞", 40), "ja", version)
        assert backfill.data_ready("ja") == ready, version
