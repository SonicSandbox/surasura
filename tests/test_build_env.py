"""The release build bundles only what it means to (Minato-BE, 2026-11-10). PyInstaller took DLLs from the build
machine's PATH — a local build from Git Bash carried Git for Windows' OpenSSL (ucrt64\\bin) for Qt's TLS, GitHub's
runner a UCRT and MFC copy — and froze pytest into Surasura.exe and the CLI (numpy.testing, pandas._testing and anyio
name it inside functions). The freeze now runs on a clean PATH, every Analysis excludes build_config's never_bundle, and
--check refuses a DLL that is no byte copy of the build Python's, its packages' or the repo's, and a never_bundle name."""
import json
import os
import shutil
import sys

import pytest

import package_app
from tests.test_packaging_config import (CONFIG, FROZEN, _program, _run_spec, _source, _stand_in_archives,  # noqa
                                         _stubbed_build, _tsubasa_as_pinned, fake_site, FREEZE_PATHS)

GIT_UCRT = r"C:\Program Files\Git\ucrt64\bin"


def test_the_freeze_runs_on_this_pythons_folders_and_windows_alone():
    # A Git Bash PATH, its key in the case Windows keeps it: Git's ucrt64\bin (its OpenSSL) and a tool's folder go;
    # this Python's folders and Windows' stay, and every other variable is kept as it was.
    environ = {"Path": os.pathsep.join([GIT_UCRT, r"C:\Program Files\Git\usr\bin", r"C:\Tools\UCRT Redist"]),
               "SystemRoot": r"C:\Windows", "PYTHONPATH": r"H:\site\tsubasa", "APPDATA": r"H:\env\Roaming"}
    env = package_app.freeze_env(environ)
    assert "Path" not in env and env["PYTHONPATH"] == r"H:\site\tsubasa" and env["APPDATA"] == r"H:\env\Roaming"
    folders = env["PATH"].split(os.pathsep)
    assert not {GIT_UCRT, r"C:\Program Files\Git\usr\bin", r"C:\Tools\UCRT Redist"} & set(folders)
    assert folders[0] == os.path.dirname(sys.executable)
    assert sys.base_prefix in folders and os.path.join(sys.base_prefix, "DLLs") in folders
    assert folders[-3:] == [r"C:\Windows\System32", r"C:\Windows", r"C:\Windows\System32\Wbem"]
    assert len(folders) == len(set(folders))                       # a venv's prefix is listed once
    # No SystemRoot in the environment (a stripped one): Windows' usual folder.
    assert r"C:\Windows\System32" in package_app.freeze_env({"PATH": GIT_UCRT})["PATH"].split(os.pathsep)


@pytest.mark.parametrize("release", [False, True])
def test_both_freezes_run_with_the_clean_path(tmp_path, monkeypatch, release):
    # The app's spec and updater.exe's: the build's own PATH (Git's ucrt64\bin first, as Git Bash puts it) reaches
    # neither.
    monkeypatch.setenv("PATH", GIT_UCRT + os.pathsep + os.environ.get("PATH", ""))
    frozen, _seen = _stubbed_build(tmp_path, monkeypatch, release)
    assert frozen == ["Surasura.spec", "updater.spec"]
    assert FREEZE_PATHS == [package_app.freeze_env()["PATH"]] * 2
    assert all(GIT_UCRT not in p.split(os.pathsep) for p in FREEZE_PATHS)


# --- every bundled binary is a copy of the build Python's, its packages' or the repo's ----------------------------------

def test_a_program_of_the_build_pythons_own_dlls_passes_and_a_dll_from_elsewhere_is_named(tmp_path, monkeypatch):
    """Real data: DLLs and extension modules copied from this Python's own DLLs folder (as PyInstaller copies them)
    and the repo's vendored SQLite are the build's; Git's OpenSSL (a DLL of a name no Python file has), and one of
    Python's own names whose bytes differ (a namesake found on PATH), are not."""
    monkeypatch.setattr(package_app, "BINARY_ROOTS", None)          # this Python's real folders
    dlls = os.path.join(sys.base_prefix, "DLLs")
    own = sorted(n for n in os.listdir(dlls) if n.lower().endswith((".dll", ".pyd")))[:6]
    if not own:
        pytest.skip("this Python has no DLLs folder of its own")
    folder = tmp_path / "Surasura"
    internal = folder / "_internal"
    (internal / "nested").mkdir(parents=True)
    for name in own:
        shutil.copy2(os.path.join(dlls, name), internal / name)
    shutil.copy2(os.path.join(dlls, own[0]), internal / "nested" / own[0])     # a package's folder keeps its path
    config = package_app.load_build_config()
    shutil.copyfile(os.path.join(os.path.dirname(package_app.BUILD_CONFIG), "..",
                                 *config["sqlite_dll"].split("/")), internal / "sqlite3.dll")
    (internal / "app").mkdir()
    (internal / "app" / "スラスラ.txt").write_text("not a binary: never read\n", encoding="utf-8")
    assert package_app.foreign_binaries(str(folder)) == []
    (internal / "libssl-3-x64.dll").write_bytes(b"MZ\x90\x00 Git for Windows' OpenSSL")
    namesake = bytearray(open(os.path.join(dlls, own[1]), "rb").read())
    namesake[-1] ^= 0xFF                                            # the same size, one byte off
    (internal / "nested" / own[1]).write_bytes(bytes(namesake))
    assert package_app.foreign_binaries(str(folder)) == sorted(["_internal/libssl-3-x64.dll", f"_internal/nested/{own[1]}"])


def test_the_program_folder_never_vouches_for_itself(tmp_path):
    # A root that holds the program (the repo's dist\, a site on sys.path above it): its own files are no source.
    root = tmp_path / "copy"
    folder = root / "dist" / "Surasura"
    (folder / "_internal").mkdir(parents=True)
    (folder / "_internal" / "libcrypto-3-x64.dll").write_bytes(b"MZ")
    assert package_app.foreign_binaries(str(folder), roots=[str(root)]) == ["_internal/libcrypto-3-x64.dll"]
    (root / "site").mkdir()
    (root / "site" / "libcrypto-3-x64.dll").write_bytes(b"MZ")    # a real copy beside it does
    assert package_app.foreign_binaries(str(folder), roots=[str(root)]) == []


def test_an_empty_program_or_one_without_internal_carries_no_foreign_binary(tmp_path):
    assert package_app.foreign_binaries(str(tmp_path / "nothing"), roots=[str(tmp_path)]) == []
    (tmp_path / "Surasura" / "_internal").mkdir(parents=True)
    assert package_app.foreign_binaries(str(tmp_path / "Surasura"), roots=[]) == []


def test_the_roots_are_this_python_its_path_outside_the_repo_and_packaging(monkeypatch, tmp_path):
    repo = os.path.dirname(os.path.abspath(package_app.__file__))
    site = tmp_path / "tsubasa-site"                                 # the cut's PYTHONPATH site
    site.mkdir()
    above = os.path.dirname(repo)                  # a PYTHONPATH that holds the repo: the drive, the other copies' dist
    monkeypatch.setattr(sys, "path", [repo, str(site), os.path.join(repo, "app"), os.path.join(sys.base_prefix, "Lib"),
                                      above])
    roots = package_app.binary_roots()
    assert above not in roots
    assert os.path.abspath(sys.base_prefix) in roots and str(site) in roots
    assert os.path.join(repo, "packaging") in roots
    assert repo not in roots and os.path.join(repo, "app") not in roots          # never the repo (its dist\)
    assert os.path.join(sys.base_prefix, "Lib") not in roots                    # inside the install: walked once


# --- never_bundle: the test tools and Pygments -----------------------------------------------------------------------------

def test_the_build_config_names_the_test_tools_and_every_analysis_excludes_them(tmp_path):
    never = package_app.load_build_config()["never_bundle"]
    assert {"pytest", "_pytest", "pluggy", "iniconfig", "py", "pygments"} <= set(never)
    analyses = _run_spec(tmp_path, json.loads(_source(CONFIG)), {})
    assert len(analyses) == 3 and all(set(never) <= set(a["excludes"]) for a in analyses)


@pytest.mark.parametrize("frozen, entries, carried", [
    ({"surasura-cli.exe": {"_pytest", "_pytest.outcomes", "_pytest.warning_types"}}, (), ["_pytest"]),
    ({"Surasura.exe": {"app", "pytest", "pluggy._hooks", "pygments.lexers"}}, (), ["pluggy", "pygments", "pytest"]),
    ({}, ("pluggy-1.7.0.dist-info", "iniconfig"), ["iniconfig", "pluggy"]),
    # Names that only start like one: pywin32's, Python's own DLL, pydantic, a module named pytest_like.
    ({"Surasura.exe": {"app", "pydantic", "pytest_like"}}, ("pywin32_system32", "python311.dll", "pyexpat.pyd"), []),
])
def test_a_never_bundle_name_is_found_frozen_or_in_internal(tmp_path, frozen, entries, carried):
    folder, config = _program(tmp_path)
    FROZEN.update(frozen)
    for entry in entries:
        (folder / "_internal" / entry).mkdir()
    assert package_app.never_bundled(str(folder), config["never_bundle"]) == carried
    failures, facts = package_app.check_program(str(folder), config)
    assert facts["never_bundled"] == carried
    assert [f for f in failures if "never_bundle" in f] == ([f"the program carries {carried}, which build_config's "
                                                             "never_bundle keeps out of every build"] if carried else [])


def test_check_from_another_python_names_that_once_and_never_lists_its_binaries(tmp_path, monkeypatch):
    # Another Python's files can't vouch for the build Python's DLLs: check_licences says the Python differs, and the
    # binaries aren't listed one by one (~170 lines that would hide the reason).
    folder, config = _program(tmp_path)
    (folder / "_internal" / "libssl-3-x64.dll").write_bytes(b"MZ")
    assert any("no copy of a file" in f for f in package_app.check_program(str(folder), config)[0])
    monkeypatch.setattr(package_app, "_python_fingerprint", lambda dists: "Python 3.11.9, packages 0000000000000000")
    failures, _facts = package_app.check_program(str(folder), config)
    assert any("was written by another Python" in f for f in failures)
    assert not [f for f in failures if "no copy of a file" in f]
