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
    fake_dist(root, "tsubasa-sync", "0.1.11", {"tsubasa/__init__.py": "", "{info}/licenses/LICENSE":
                                               "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"},
              "GPL-3.0-or-later")
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
                                           "SQLite", "tsubasa-sync", "unidic-lite"]
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
    """A text of fugashi 1.5.2 in a program frozen from fugashi 1.5.3 is the wrong text: the index names the version,
    and a row at another version than the build Python's reads as a part it doesn't name."""
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    index = folder / "_internal" / "licenses" / "INDEX.txt"
    index.write_text(index.read_text(encoding="utf-8").replace("fugashi · 1.5.2 · ", "fugashi · 1.5.1 · "),
                     encoding="utf-8")
    assert package_app.check_licences(str(folder)) == [
        "_internal/licenses/INDEX.txt doesn't name fugashi 1.5.2, which the program carries"]
    # The build Python's fugashi moved on since: --check says the Python differs, never that texts are missing.
    shutil.rmtree(site / "fugashi-1.5.2.dist-info")
    fake_dist(site, "fugashi", "1.5.3", {"fugashi/__init__.py": "", "{info}/licenses/LICENSE": "MIT License\n"},
              "MIT AND BSD-3-Clause")
    failures = package_app.check_licences(str(folder))
    assert len(failures) == 1 and "was written by another Python" in failures[0]


def test_a_row_without_texts_passes_only_as_a_reviewed_exception(tmp_path, site, monkeypatch):
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    assert _index(folder)["SQLite"][3] == [] and package_app.check_licences(str(folder)) == []
    monkeypatch.setattr(package_app, "LICENCE_EXCEPTIONS", {})
    assert [f for f in package_app.check_licences(str(folder)) if "SQLite" in f] == [
        f"_internal/licenses/INDEX.txt names SQLite {_index(folder)['SQLite'][1]} with no licence text, and it is no "
        "reviewed exception"]
    assert package_app.gather_licences(str(folder))[0].startswith("SQLite ")


def test_a_dll_or_module_from_nowhere_stops_the_build_and_fails_the_check(tmp_path, site):
    """A DLL that came from neither this Python, nor a carried package, nor a part with its text (PyInstaller found it
    on the build machine's PATH), or a module frozen in from an editable install with no RECORD, ships under a licence
    nobody looked at."""
    folder = _built(tmp_path)
    (folder / "_internal" / "libiconv-2.dll").write_bytes(b"MZ")
    (folder / "_internal" / "_cffi_like.cp311-win_amd64.pyd").write_bytes(b"MZ")
    FROZEN[package_app.CLI_EXE_NAME] = {"kotoba_tool", "kotoba_tool.split"}
    failures = package_app.gather_licences(str(folder))
    assert len(failures) == 3 and all("found on the build machine's PATH?" in f for f in failures)
    assert package_app.unclaimed(str(folder)) == ["_cffi_like.cp311-win_amd64.pyd", "kotoba_tool", "libiconv-2.dll"]
    # A package's own extension module, Python's own DLLs, its standard library and PyInstaller's folders are claimed.
    fake_dist(site, "cffi-like", "1.0", {"_cffi_like.cp311-win_amd64.pyd": "MZ", "{info}/LICENSE": "MIT\n"})
    (folder / "_internal" / "libiconv-2.dll").unlink()
    FROZEN[package_app.CLI_EXE_NAME] = {"json", "email.parser", "encodings"}
    for name in ("_socket.pyd", "VCRUNTIME140.dll", "_tcl_data"):            # Python's own (its DLLs folder), Tk's
        (folder / "_internal" / name).write_bytes(b"MZ")
    assert package_app.unclaimed(str(folder)) == []
    assert package_app.gather_licences(str(folder)) == [] and package_app.check_licences(str(folder)) == []
    assert _index(folder)["Microsoft Visual C++ runtime"][3] == []              # a reviewed exception: Python's terms
    (folder / "_internal" / "libiconv-2.dll").write_bytes(b"MZ")
    assert len(package_app.check_licences(str(folder))) == 1


def test_a_module_frozen_into_the_command_line_alone_is_carried_and_a_pth_folders_modules_are_its_packages(tmp_path,
                                                                                                          site):
    # surasura-cli.exe has its own Analysis: a library frozen only there ships too. pywin32 puts win32/lib on the path
    # with a .pth: win32con (frozen as a top-level module) is pywin32's.
    fake_dist(site, "pywin32", "312", {"pywin32.pth": "# .pth file for the PyWin32 extensions\nwin32\nwin32\\lib\n"
                                                      "import pywin32_bootstrap\n", "win32/lib/win32con.py": "",
                                       "win32/License.txt": "PSF\n"}, "PSF")
    folder = _built(tmp_path, entries=())
    FROZEN[package_app.CLI_EXE_NAME] = {"six", "win32con"}
    assert package_app.unclaimed(str(folder)) == []
    assert package_app.gather_licences(str(folder)) == []
    assert {"six", "pywin32"} <= set(_index(folder))
    assert _index(folder)["pywin32"][3] == ["pywin32-312/win32/License.txt"]


def test_check_from_another_python_says_so_instead_of_reading_its_versions_as_missing_texts(tmp_path, site,
                                                                                            monkeypatch):
    # INDEX.txt names its Python by version and its packages' fingerprint — never a path (a path names the build
    # machine's user). --check from a Python with other packages says which, and checks the texts alone.
    folder = _built(tmp_path)
    assert package_app.gather_licences(str(folder)) == []
    text = (folder / "_internal" / "licenses" / "INDEX.txt").read_text(encoding="utf-8")
    assert package_app.BUILD_PYTHON_MARK + package_app._python_fingerprint(package_app.installed_distributions()) in text
    assert sys.executable not in text and os.path.expanduser("~") not in text
    fake_dist(site, "six-extra", "0.1", {"six_extra/__init__.py": "", "{info}/LICENSE": "MIT\n"})
    failures = package_app.check_licences(str(folder))
    assert len(failures) == 1 and "was written by another Python" in failures[0]
    (folder / "_internal" / "licenses" / "jieba-0.42.1" / "LICENSE").unlink()
    assert len(package_app.check_licences(str(folder))) == 2                  # the texts are still checked


def test_a_licence_that_would_break_the_index_stops_the_build(tmp_path, site):
    fake_dist(site, "kana-utils", "0.3.0", {"kana_utils/__init__.py": "", "{info}/LICENSE": "MIT\n"}, "MIT · BSD")
    folder = _built(tmp_path, entries=("kana_utils",))
    assert package_app.gather_licences(str(folder)) == [
        "kana-utils's licence or a text's name holds ' · ' or ', ', which INDEX.txt can't carry"]


def test_qts_openssl_from_the_path_is_claimed_by_nobody(tmp_path, site):
    # A local build from Git Bash once carried Git for Windows' OpenSSL for Qt's TLS (PyInstaller found it on PATH,
    # Minato-BE 2026-11-10): the freeze now runs on a clean PATH, and a copy that still gets in stops the build here.
    folder = _built(tmp_path)
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        (folder / "_internal" / name).write_bytes(b"MZ")
    assert package_app.unclaimed(str(folder)) == ["libcrypto-3-x64.dll", "libssl-3-x64.dll"]
    assert len(package_app.gather_licences(str(folder))) == 2


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
    assert sorted(texts) == ["OpenCC/LICENSE", "PyQt6-Qt6/Qt-third-party-notices.txt", "jieba/LICENSE",
                             "pysrt/LICENCE.txt"]
    # Qt's own third-party components (Minato-SM), for the Qt the build takes: each named, each licence text in it.
    qt = texts["PyQt6-Qt6/Qt-third-party-notices.txt"]
    assert qt.startswith("Qt 6.11.2 ") and "scripts/build_qt_notices.py" in qt
    for component, text in (("PCRE2", "qtbase/src/3rdparty/pcre2/LICENCE.md"), ("Freetype 2", "FreeType Project"),
                            ("HarfBuzz-NG", "qtbase/src/3rdparty/harfbuzz-ng/COPYING"), ("LibPNG", "PNG Reference"),
                            ("LibJPEG-turbo", "Independent JPEG Group"), ("Data Compression Library (zlib)",
                                                                         "Jean-loup Gailly"),
                            ("MD4C", "qtbase/src/3rdparty/md4c/LICENSE.md"), ("WebP (libwebp)", "Google Inc"),
                            ("TIFF Software Distribution (libtiff)", "Sam Leffler"), ("XSVG", "qtsvg/src/svg/"),
                            ("Unicode Character Database (UCD)", "UNICODE LICENSE V3")):
        assert f"\n{component}\n" in qt and text in qt, component
    assert "Pixman" not in qt and "Wayland" not in qt and "Catch2" not in qt   # not in the Windows parts it carries
    assert "Copyright (c) 2013 Sun Junyi" in texts["jieba/LICENSE"]
    assert "GNU GENERAL PUBLIC LICENSE" in texts["pysrt/LICENCE.txt"] and "Version 3, 29 June 2007" in texts["pysrt/LICENCE.txt"]
    for name in ("OpenCC/LICENSE",):
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
