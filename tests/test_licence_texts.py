"""The bundled software's licence texts (the licence switch, 3.0): package_app.py step 3b reads what a built program
carries — the modules frozen into its three Python programs, the entries of its _internal — matches it to the build
Python's installed distributions, and copies each one's licence texts into _internal/licenses/<name>-<version>/ with an
INDEX.txt; --check refuses a program whose index misses a part, a text, or carries a DLL from nowhere. Each test builds
its own made-up site-packages (a fake dist-info tree) and a small program folder; nothing is frozen for real."""
import os
import shutil
import sys
import zipfile

import pytest

import package_app
from tests.test_packaging_config import FROZEN, _stand_in_archives, _tsubasa_as_pinned, fake_dist, fake_site  # noqa

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MECAB = "MeCab is copyrighted free software by Taku Kudo <taku@chasen.org> (工藤拓) and NTT.\n"


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A site-packages as pip leaves it for the libraries below, and LICENCE_SITE pointed at it."""
    root = tmp_path / "site-packages"
    root.mkdir()
    fake_dist(root, "fugashi", "1.5.2", {"fugashi/__init__.py": "", "fugashi.libs/libmecab.dll": "MZ",
                                         "{info}/licenses/LICENSE": "MIT License\n\nCopyright (c) Paul O'Leary McCann\n",
                                         "{info}/licenses/LICENSE.mecab": MECAB}, "MIT AND BSD-3-Clause")
    fake_dist(root, "unidic-lite", "1.0.8", {"unidic_lite/__init__.py": "", "unidic_lite/dicdir/COPYING":
                                             "UniDic: any of the GPL, the LGPL, or the BSD License.\n",
                                             "unidic_lite/dicdir/sys.dic": "dic",
                                             "{info}/licenses/LICENSE": "MIT License\n"}, "MIT")
    # jieba's sdist installs no licence file: packaging/licenses/jieba/ supplies it.
    fake_dist(root, "jieba", "0.42.1", {"jieba/__init__.py": "", "jieba/dict.txt": "吃 3 v\n"}, "MIT")
    fake_dist(root, "pysrt", "1.1.2", {"pysrt/__init__.py": "", "pysrt/srtfile.py": ""}, "GPLv3")
    # numpy keeps a licence beside its code too, and a module named license.py that is no licence text.
    fake_dist(root, "numpy", "1.25.2", {"numpy/__init__.py": "", "numpy/LICENSE.txt": "BSD 3-Clause\n",
                                        "numpy/_license.py": "", "numpy/license.py": "",
                                        "{info}/LICENSE.txt": "Copyright (c) 2005-2023, NumPy Developers.\n",
                                        "../../Scripts/f2py.exe": "MZ", "__pycache__/x.cpython-311.pyc": ""},
              "BSD-3-Clause")
    # A single-module distribution: its root is the module's name.
    fake_dist(root, "six", "1.17.0", {"six.py": "", "{info}/LICENSE": "Copyright (c) 2010-2024 Benjamin Peterson\n"})
    # Installed, never carried: never listed.
    fake_dist(root, "pytest-cov", "6.0.0", {"pytest_cov/__init__.py": "", "{info}/LICENSE": "MIT\n"})
    fake_dist(root, "pyinstaller", "6.18.0", {"PyInstaller/__init__.py": "", "{info}/licenses/COPYING.txt":
                                              "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n"},
              "GPL-2.0-or-later")
    monkeypatch.setattr(package_app, "LICENCE_SITE", [str(root)])
    return root


def _built(tmp_path, entries=("fugashi", "fugashi.libs", "unidic_lite", "jieba", "app", "templates")):
    """A built program in miniature: its four programs, its _internal entries (folders) and the vendored SQLite."""
    folder = tmp_path / "Surasura"
    internal = folder / "_internal"
    internal.mkdir(parents=True)
    for exe in package_app.PROGRAM_EXES:
        (folder / exe).write_bytes(b"MZ")
    for entry in entries:
        (internal / entry).mkdir()
    config = package_app.load_build_config()
    shutil.copyfile(os.path.join(PROJECT, *config["sqlite_dll"].split("/")), internal / "sqlite3.dll")
    return folder


def _index(folder):
    return {row[0]: row for row in package_app.read_licence_index(str(folder))}


def test_every_carried_part_gets_its_texts_and_a_row_and_nothing_else_is_listed(tmp_path, site):
    """The success path: fugashi (a package and its .libs), unidic-lite (a text beside its dictionary), jieba (its
    text supplied), pysrt (frozen into the program only, its text supplied), six (a module of its own), numpy (frozen
    into tsubasa.exe alone), PyInstaller's bootloader, OpenCC's tables and SQLite (a reviewed exception)."""
    folder = _built(tmp_path)
    FROZEN["Surasura.exe"] = {"app", "app.analyzer", "app.zh_script_data", "pysrt", "pysrt.srtfile", "six"}
    FROZEN["tsubasa.exe"] = {"tsubasa", "numpy", "numpy.core"}
    assert package_app.gather_licences(str(folder)) == []
    rows = _index(folder)
    assert sorted(rows, key=str.lower) == ["fugashi", "jieba", "numpy", "OpenCC", "PyInstaller", "pysrt", "six",
                                           "SQLite", "unidic-lite"]
    assert rows["fugashi"] == ("fugashi", "1.5.2", "MIT AND BSD-3-Clause",
                               ["fugashi-1.5.2/licenses/LICENSE", "fugashi-1.5.2/licenses/LICENSE.mecab"])
    assert rows["unidic-lite"][3] == ["unidic-lite-1.0.8/licenses/LICENSE", "unidic-lite-1.0.8/unidic_lite/dicdir/COPYING"]
    assert rows["numpy"][3] == ["numpy-1.25.2/LICENSE.txt", "numpy-1.25.2/numpy/LICENSE.txt"]   # never license.py
    assert rows["jieba"][3] == ["jieba-0.42.1/LICENSE"] and rows["pysrt"][3] == ["pysrt-1.1.2/LICENCE.txt"]
    assert rows["OpenCC"][:2] == ("OpenCC", "1.4.2") and rows["OpenCC"][3] == ["OpenCC-1.4.2/LICENSE"]
    assert rows["SQLite"][2] == "Public domain" and rows["SQLite"][3] == []
    licences = folder / "_internal" / "licenses"
    # Byte for byte, a non-ASCII text too.
    assert (licences / "fugashi-1.5.2" / "licenses" / "LICENSE.mecab").read_bytes() == \
        (site / "fugashi-1.5.2.dist-info" / "licenses" / "LICENSE.mecab").read_bytes()
    assert (licences / "jieba-0.42.1" / "LICENSE").read_bytes() == \
        open(os.path.join(PROJECT, "packaging", "licenses", "jieba", "LICENSE"), "rb").read()
    assert package_app.check_licences(str(folder)) == []


def test_a_carried_part_without_a_licence_text_stops_the_build_named_and_writes_no_index(tmp_path, site):
    fake_dist(site, "kana-utils", "0.3.0", {"kana_utils/__init__.py": ""}, "UNKNOWN")
    folder = _built(tmp_path, entries=("fugashi", "kana_utils"))
    failures = package_app.gather_licences(str(folder))
    assert len(failures) == 1 and failures[0].startswith("kana-utils 0.3.0 ships with no licence text")
    assert "packaging/licenses/kana-utils/" in failures[0] and "LICENCE_EXCEPTIONS" in failures[0]
    assert package_app.read_licence_index(str(folder)) is None
    assert package_app.check_licences(str(folder)) == [
        "_internal/licenses/INDEX.txt can't be read: the bundled software's licence texts were not gathered (step 3b)"]


def test_a_licence_text_gone_empty_or_a_part_left_out_of_the_index_fails_the_check(tmp_path, site):
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    licences = folder / "_internal" / "licenses"
    (licences / "fugashi-1.5.2" / "licenses" / "LICENSE.mecab").write_bytes(b"")
    (licences / "jieba-0.42.1" / "LICENSE").unlink()
    index = licences / "INDEX.txt"
    index.write_text("".join(line for line in index.read_text(encoding="utf-8").splitlines(keepends=True)
                             if not line.startswith("unidic-lite · ")), encoding="utf-8")
    assert sorted(package_app.check_licences(str(folder))) == [
        "_internal/licenses/INDEX.txt doesn't name unidic-lite 1.0.8, which the program carries",
        "_internal/licenses/fugashi-1.5.2/licenses/LICENSE.mecab, which _internal/licenses/INDEX.txt names, is missing "
        "or empty",
        "_internal/licenses/jieba-0.42.1/LICENSE, which _internal/licenses/INDEX.txt names, is missing or empty"]


def test_an_index_of_an_older_build_python_fails_the_check(tmp_path, site):
    """A text of fugashi 1.5.2 in a program frozen from fugashi 1.5.3 is the wrong text: the index names the version."""
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    shutil.rmtree(site / "fugashi-1.5.2.dist-info")
    fake_dist(site, "fugashi", "1.5.3", {"fugashi/__init__.py": "", "{info}/licenses/LICENSE": "MIT License\n"},
              "MIT AND BSD-3-Clause")
    assert package_app.check_licences(str(folder)) == [
        "_internal/licenses/INDEX.txt doesn't name fugashi 1.5.3, which the program carries"]


def test_a_row_without_texts_passes_only_as_a_reviewed_exception(tmp_path, site, monkeypatch):
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    assert _index(folder)["SQLite"][3] == [] and package_app.check_licences(str(folder)) == []
    monkeypatch.setattr(package_app, "LICENCE_EXCEPTIONS", {})
    assert [f for f in package_app.check_licences(str(folder)) if "SQLite" in f] == [
        f"_internal/licenses/INDEX.txt names SQLite {_index(folder)['SQLite'][1]} with no licence text, and it is no "
        "reviewed exception"]
    assert package_app.gather_licences(str(folder))[0].startswith("SQLite ")


def test_a_dll_from_nowhere_stops_the_build_and_fails_the_check(tmp_path, site):
    """A DLL that came from neither this Python, nor a carried package, nor a part with its text (PyInstaller found it
    on the build machine's PATH) ships under a licence nobody looked at."""
    folder = _built(tmp_path)
    (folder / "_internal" / "libiconv-2.dll").write_bytes(b"MZ")
    (folder / "_internal" / "_cffi_like.cp311-win_amd64.pyd").write_bytes(b"MZ")
    failures = package_app.gather_licences(str(folder))
    assert len(failures) == 2 and all("found on the build machine's PATH?" in f for f in failures)
    assert package_app.stray_binaries(str(folder)) == ["_cffi_like.cp311-win_amd64.pyd", "libiconv-2.dll"]
    # A package's own extension module and Python's own DLLs are no strays.
    fake_dist(site, "cffi-like", "1.0", {"_cffi_like.cp311-win_amd64.pyd": "MZ", "{info}/LICENSE": "MIT\n"})
    (folder / "_internal" / "libiconv-2.dll").unlink()
    (folder / "_internal" / "_socket.pyd").write_bytes(b"MZ")                 # Python's own (its DLLs folder)
    (folder / "_internal" / "VCRUNTIME140.dll").write_bytes(b"MZ")
    assert package_app.stray_binaries(str(folder)) == []
    assert package_app.gather_licences(str(folder)) == [] and package_app.check_licences(str(folder)) == []
    (folder / "_internal" / "libiconv-2.dll").write_bytes(b"MZ")
    assert len(package_app.check_licences(str(folder))) == 1


def test_qts_openssl_from_the_path_ships_with_its_text(tmp_path, site):
    folder = _built(tmp_path)
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        (folder / "_internal" / name).write_bytes(b"MZ")
    assert package_app.gather_licences(str(folder)) == []
    row = _index(folder)["OpenSSL"]
    assert row[2] == "Apache-2.0 (Qt's TLS: libcrypto-3-x64.dll, libssl-3-x64.dll)" and row[3] == ["OpenSSL/LICENSE.txt"]
    assert (folder / "_internal" / "licenses" / "OpenSSL" / "LICENSE.txt").read_text(encoding="utf-8").lstrip() \
        .startswith("Apache License")


@pytest.mark.skipif(not os.path.isfile(os.path.join(sys.base_prefix, "LICENSE.txt")),
                    reason="this Python carries no LICENSE.txt")
def test_python_ships_its_own_licence_whenever_its_dll_does(tmp_path, site):
    folder = _built(tmp_path)
    (folder / "_internal" / f"python3{sys.version_info[1]}.dll").write_bytes(b"MZ")
    assert package_app.gather_licences(str(folder)) == []
    row = _index(folder)["Python"]
    assert row[1] == ".".join(map(str, sys.version_info[:3])) and row[3] == [f"Python-{row[1]}/LICENSE.txt"]
    assert (folder / "_internal" / "licenses" / f"Python-{row[1]}" / "LICENSE.txt").read_bytes() == \
        open(os.path.join(sys.base_prefix, "LICENSE.txt"), "rb").read()


def test_an_empty_program_needs_no_texts_and_a_program_that_cant_be_read_needs_no_bootloader_text(tmp_path, site):
    # Nothing carried: an index of no rows (the header alone) — never a failure for what isn't there.
    folder = _built(tmp_path, entries=())
    (folder / "_internal" / "sqlite3.dll").unlink()
    FROZEN.clear()
    assert package_app.gather_licences(str(folder)) == [] and package_app.read_licence_index(str(folder)) == []
    assert package_app.check_licences(str(folder)) == []


def test_the_index_reader_takes_crlf_comments_and_brackets():
    text = ("# The software Surasura's program bundles · name · version\r\n\r\n"
            "fugashi · 1.5.2 · MIT AND BSD-3-Clause · fugashi-1.5.2/licenses/LICENSE, fugashi-1.5.2/licenses/LICENSE.mecab\r\n"
            "SQLite · 3.53.4 · Public domain · (none: public domain)\r\n"
            "a line that is no row\r\n")
    assert package_app.parse_licence_index(text) == [
        ("fugashi", "1.5.2", "MIT AND BSD-3-Clause",
         ["fugashi-1.5.2/licenses/LICENSE", "fugashi-1.5.2/licenses/LICENSE.mecab"]),
        ("SQLite", "3.53.4", "Public domain", [])]
    assert package_app.parse_licence_index("") == []


def test_the_download_zip_carries_every_text_its_index_names(tmp_path, site):
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    for name in package_app.OWN_LICENCE_FILES:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(PROJECT, *name.split("/")), folder / name)
    archive = shutil.make_archive(str(tmp_path / "Surasura_v3.0.0"), "zip", root_dir=str(tmp_path), base_dir="Surasura")
    assert package_app.check_zip_licences(archive) == []
    with zipfile.ZipFile(archive) as z:
        kept = [(n, z.read(n)) for n in z.namelist() if not n.endswith("jieba-0.42.1/LICENSE")]
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in kept:
            z.writestr(name, data)
    assert package_app.check_zip_licences(archive) == [
        "Surasura_v3.0.0.zip holds no _internal/licenses/jieba-0.42.1/LICENSE"]


def test_a_build_stops_at_its_licence_texts(tmp_path, monkeypatch, capsys):
    from tests.test_packaging_config import _stubbed_build
    monkeypatch.setattr(package_app, "gather_licences", lambda final: ["kana-utils 0.3.0 ships with no licence text"])
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False)
    assert seen["returned"] is False and "checked" not in seen
    assert "Build failed:\n  kana-utils 0.3.0 ships with no licence text" in capsys.readouterr().out


def test_the_supplied_texts_are_their_upstreams_and_the_readme_says_from_where():
    folder = os.path.join(PROJECT, "packaging", "licenses")
    readme = open(os.path.join(folder, "README.md"), encoding="utf-8").read()
    texts = {}
    for name in sorted(os.listdir(folder)):
        if os.path.isdir(os.path.join(folder, name)):
            assert f"`{name}/`" in readme, name
            for file in os.listdir(os.path.join(folder, name)):
                texts[f"{name}/{file}"] = open(os.path.join(folder, name, file), encoding="utf-8").read()
    assert sorted(texts) == ["OpenCC/LICENSE", "OpenSSL/LICENSE.txt", "jieba/LICENSE", "pysrt/LICENCE.txt"]
    assert "Copyright (c) 2013 Sun Junyi" in texts["jieba/LICENSE"]
    assert "GNU GENERAL PUBLIC LICENSE" in texts["pysrt/LICENCE.txt"] and "Version 3, 29 June 2007" in texts["pysrt/LICENCE.txt"]
    for name in ("OpenCC/LICENSE", "OpenSSL/LICENSE.txt"):
        assert texts[name].lstrip().startswith("Apache License") and "Version 2.0, January 2004" in texts[name]


def test_data_credits_lists_the_bundled_software_from_the_programs_index(tmp_path, site, monkeypatch):
    """Settings › App › Data credits: from source the note alone (it points at the folder); in a built program, every
    row of its INDEX.txt, each with its version and licence."""
    from app import credits, path_utils
    assert credits.software_note() == credits.SOFTWARE_NOTE and "_internal\\licenses" in credits.SOFTWARE_NOTE
    folder = _built(tmp_path)
    FROZEN["Surasura.exe"] = {"app", "app.zh_script_data", "pysrt"}
    assert package_app.gather_licences(str(folder)) == []
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "_MEIPASS", str(folder / "_internal"), raising=False)
    assert ("fugashi", "1.5.2", "MIT AND BSD-3-Clause") in credits.bundled()
    note = credits.software_note()
    assert note.startswith(credits.SOFTWARE_NOTE + "\n\nBundled with this program (_internal\\licenses\\INDEX.txt)\n")
    for line in ("  fugashi 1.5.2 — MIT AND BSD-3-Clause", "  pysrt 1.1.2 — GPLv3", "  SQLite ", "  OpenCC 1.4.2 — "):
        assert line in note, line
    assert note in credits.all_credits() and credits.all_credits().endswith("\n\n" + credits.CONTENT_NOTE)
    (folder / "_internal" / "licenses" / "INDEX.txt").unlink()
    assert credits.bundled() == [] and credits.software_note() == credits.SOFTWARE_NOTE
