"""S3.1 rows 3.1.1 (D15-D18): the build's one configuration, read by the spec and the packager, and the checks a build
must pass. The spec is parsed (ast) or executed with PyInstaller's build steps stubbed, never run for real; the
post-build checks run on small folders shaped like a built program."""
import ast
import json
import os
import sys
import types
from unittest.mock import patch

import pytest

import package_app

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(PROJECT, "packaging", "Surasura.spec")
UPDATER_SPEC = os.path.join(PROJECT, "packaging", "updater.spec")
CONFIG = os.path.join(PROJECT, "packaging", "build_config.json")


def _source(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(autouse=True)
def _tsubasa_as_pinned(monkeypatch):
    """The build's tsubasa gates (T1 B) see the pinned tsubasa-sync installed and a whole tsubasa.exe, so each test
    below proves its own step; tests/test_tsubasa_bundle.py proves the gates."""
    pin = package_app.tsubasa_pin()
    monkeypatch.setattr(package_app, "tsubasa_installed", lambda: pin)
    monkeypatch.setattr(package_app, "tsubasa_version_of", lambda exe: (0, f"tsubasa {pin}"))


def _dispatch_targets():
    """Every module app_entry.py's main() and _qt_window() import to run a command (`from app import analyzer` ->
    app.analyzer, `from app.qt import shell` -> app.qt.shell, `from app import main as dashboard` -> app.main)."""
    tree = ast.parse(_source(os.path.join(PROJECT, "app_entry.py")))
    targets = set()
    for func in tree.body:
        if isinstance(func, ast.FunctionDef) and func.name in ("main", "_qt_window"):
            for node in ast.walk(func):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in ("app", "modules"):
                    targets.update(f"{node.module}.{alias.name}" for alias in node.names)
    return targets


def _spec_hiddenimports():
    """Every string the spec puts into `hiddenimports`: its list, each `+=` and each `.append(...)`."""
    names = set()
    for node in ast.walk(ast.parse(_source(SPEC))):
        value = None
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "hiddenimports"
                                                for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "hiddenimports":
            value = node.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append" \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "hiddenimports":
            value = node.args[0] if node.args else None
        if value is not None:
            names.update(c.value for c in ast.walk(value) if isinstance(c, ast.Constant) and isinstance(c.value, str))
    return names


# --- the dispatch table -> hiddenimports (D17) ----------------------------------------------------------------------------

def test_every_dispatch_target_is_a_hidden_import():
    targets = _dispatch_targets()
    # A guard on the guard: the parse found the table (a renamed function would find nothing and pass).
    assert {"app.analyzer", "app.library_store", "app.arrivals_worker", "app.qt.shell", "app.main",
            "modules.junban.patterns_build"} <= targets
    missing = targets - _spec_hiddenimports()
    assert not missing, f"app_entry.py dispatches to modules the spec doesn't name in hiddenimports: {sorted(missing)}"


def test_the_2x_import_and_the_graduatedlist_merge_ride_in_the_build():
    # The window's first-run page imports both inside a function, and app_entry.py dispatches to neither, so the table
    # test above can't see them: row 3.1.9b's frozen build had neither in its bundle.
    for module in ("app.import_2x", "app.graduated_merge"):
        assert os.path.isfile(os.path.join(PROJECT, *module.split(".")) + ".py"), module
        assert module in _spec_hiddenimports(), f"{module} is not in Surasura.spec's hiddenimports"


def test_the_window_and_its_qt_modules_are_named_and_the_cli_keeps_excluding_pyqt6():
    source = _source(SPEC)
    names = _spec_hiddenimports()
    assert "app.qt.shell" in names and "PyQt6.sip" in names
    cli = source[source.index("cli_a = Analysis("):source.index("cli_pyz = PYZ(")]
    assert "'PyQt6'" in cli


# --- UPX off everywhere (D15, E12) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("spec", [SPEC, UPDATER_SPEC], ids=["Surasura.spec", "updater.spec"])
def test_upx_is_off_in_every_build_step(spec):
    upx = [kw.value for node in ast.walk(ast.parse(_source(spec))) if isinstance(node, ast.Call)
           for kw in node.keywords if kw.arg == "upx"]
    assert upx and all(isinstance(v, ast.Constant) and v.value is False for v in upx)


@pytest.mark.parametrize("spec", [SPEC, UPDATER_SPEC], ids=["Surasura.spec", "updater.spec"])
def test_every_exe_and_collect_names_upx_off_itself(spec):
    """PyInstaller refuses --noupx beside a .spec file (a makespec option), so the spec is the one switch: every EXE
    and COLLECT says upx=False in so many words, never left to a default, so a UPX on PATH is never used (E12)."""
    calls = [node for node in ast.walk(ast.parse(_source(spec))) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id in ("EXE", "COLLECT")]
    assert calls and all(any(kw.arg == "upx" for kw in call.keywords) for call in calls)


# --- no settings.json read by the build (D15) -------------------------------------------------------------------------------

def test_the_spec_names_no_settings_json():
    strings = [n.value for n in ast.walk(ast.parse(_source(SPEC))) if isinstance(n, ast.Constant)
               and isinstance(n.value, str)]
    assert "build_config.json" in strings
    assert not [s for s in strings if "settings.json" in s]


def _run_spec(tmp_path, config, settings):
    """The whole spec executed in a scratch project (PyInstaller's steps stubbed, recording every Analysis)."""
    root = tmp_path / "project"
    (root / "app").mkdir(parents=True)
    (root / "packaging").mkdir()
    (root / "app" / "__init__.py").write_text(_source(os.path.join(PROJECT, "app", "__init__.py")), encoding="utf-8")
    (root / "modules" / "koe").mkdir(parents=True)
    (root / "app" / "qt").mkdir()
    (root / "app" / "qt" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "qt" / "shell.py").write_text("# 窓\n", encoding="utf-8")
    if config is not None:
        (root / "packaging" / "build_config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    analyses = []

    class _Analysis:
        def __init__(self, scripts, **kw):
            analyses.append(kw)
            self.pure, self.scripts, self.binaries, self.datas = [], [], [], kw["datas"]

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda name: ([], [], [])
    fakes = {"PyInstaller": types.ModuleType("PyInstaller"), "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
             "PyInstaller.utils.hooks": hooks}
    code = compile(_source(SPEC), "Surasura.spec", "exec")
    here = os.getcwd()
    os.chdir(root)
    try:
        with patch.dict(sys.modules, fakes):
            exec(code, {"Analysis": _Analysis, "PYZ": lambda *a, **k: None, "EXE": lambda *a, **k: None,
                        "COLLECT": lambda *a, **k: None, "__name__": "__main__"})
    finally:
        os.chdir(here)
    return analyses


def test_a_settings_json_that_enables_everything_changes_nothing(tmp_path):
    """The build machine's settings.json (every 2.x build toggle on) bundles nothing the build config leaves out."""
    config = json.loads(_source(CONFIG))
    config["modules"].update(junban=False, youtube_downloader=False, koe=False)
    main, _cli, _tsubasa = _run_spec(tmp_path, config, {"enable_junban": True, "enable_youtube_transcripts": True,
                                               "enable_youtube_preview": True, "enable_reels": True})
    for module in ("modules.junban", "modules.youtube_downloader", "modules.koe", "modules.reels",
                   "modules.immersion_architect"):
        assert module in main["excludes"]
    assert "modules.junban.patterns_build" not in main["hiddenimports"]


def test_the_shipped_config_bundles_what_2_5_0_shipped(tmp_path):
    main, _cli, _tsubasa = _run_spec(tmp_path, json.loads(_source(CONFIG)), {})
    for module in ("modules.junban", "modules.youtube_downloader", "modules.koe"):
        assert module not in main["excludes"]
    for module in ("modules.reels", "modules.immersion_architect"):
        assert module in main["excludes"]
    assert "modules.junban.patterns_build" in main["hiddenimports"]


def test_no_build_config_bundles_no_optional_module(tmp_path):
    main, _cli, _tsubasa = _run_spec(tmp_path, None, {"enable_junban": True})
    for module in ("modules.junban", "modules.youtube_downloader", "modules.koe", "modules.reels"):
        assert module in main["excludes"]


@pytest.mark.skipif(not __import__("importlib.util").util.find_spec("PyQt6"), reason="PyQt6 is not installed")
def test_the_window_gets_five_qt_modules_and_their_licences(tmp_path):
    main, cli, _tsubasa = _run_spec(tmp_path, json.loads(_source(CONFIG)), {})
    kept = {"PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtNetwork", "PyQt6.QtSvg"}
    assert kept <= set(main["hiddenimports"]) and not kept & set(main["excludes"])
    for unused in ("PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtMultimedia", "PyQt6.QtPdf", "PyQt6.uic"):
        assert unused in main["excludes"]
    assert {"app.qt", "app.qt.shell"} <= set(main["hiddenimports"])
    licence_dests = {dest for _src, dest in main["datas"] if dest.startswith("licenses/")}
    assert {"licenses/PyQt6", "licenses/PyQt6-Qt6"} <= licence_dests
    assert "PyQt6" in cli["excludes"]


# --- build_config.json's shape ------------------------------------------------------------------------------------------

def test_the_build_config_reads_and_carries_the_floors():
    config = package_app.load_build_config()
    assert config["modules"] == {"junban": True, "koe": True, "youtube_downloader": True, "reels": False,
                                 "immersion_architect": False}
    assert config["python_min"] == "3.11.4" and config["sqlite_min"] == "3.51.3"
    assert config["upx"] is False
    assert config["qt_modules"] == ["QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg"]
    assert config["data_name"] == "Surasura"
    assert [p["name"] for p in config["parts"]] == ["app", "qt", "dict", "tsubasa", "runtime"]
    assert config["parts"][-1]["paths"] == [""]


def test_the_vendored_sqlite_is_the_recorded_one_and_its_readme_says_where_from():
    config = package_app.load_build_config()
    dll = os.path.join(PROJECT, *config["sqlite_dll"].split("/"))
    assert package_app._sha256(dll) == config["sqlite_dll_sha256"]
    readme = _source(os.path.join(PROJECT, "packaging", "sqlite", "README.md"))
    assert config["sqlite_dll_sha256"] in readme and "https://sqlite.org/" in readme
    version = package_app.sqlite_version_of(dll)
    assert version and version in readme
    assert package_app._version_tuple(version) >= package_app._version_tuple(config["sqlite_min"])


@pytest.mark.parametrize("change", [
    {"modules": {"junban": True}},
    {"upx": True},
    {"python_min": "three"},
    {"data_name": "../Surasura"},
    {"data_name": "スラスラ"},
    {"qt_modules": []},
    {"parts": [{"name": "app", "paths": ["Surasura.exe"]}]},          # no catch-all last
    {"release": {"min_from": "3.0.0"}},
])
def test_a_wrong_build_config_stops_the_build(tmp_path, change):
    config = json.loads(_source(CONFIG))
    config.update(change)
    path = tmp_path / "build_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        package_app.load_build_config(str(path))


def test_each_program_file_falls_in_its_part():
    parts = package_app.load_build_config()["parts"]
    cases = {"Surasura.exe": "app", "updater.exe": "app", "_internal/base_library.zip": "app",
             "_internal/templates/web_app.html": "app", "_internal/build_stamp.json": "app",
             "_internal/PyQt6/Qt6/bin/Qt6Core.dll": "qt", "_internal/licenses/PyQt6/LICENSE": "qt",
             "_internal/unidic_lite/dicdir/sys.dic": "dict", "_internal/jieba/dict.txt": "dict",
             "_internal/defaults/ja/frequency_list_ja_global50k.csv": "dict",
             "tsubasa.exe": "tsubasa", "_internal/tsubasa/data/aliases.tsv.gz": "tsubasa",
             "_internal/numpy/core/_multiarray_umath.cp311-win_amd64.pyd": "runtime",
             "_internal/sqlite3.dll": "runtime", "_internal/python311.dll": "runtime",
             "_internal/templatesX/a.html": "runtime"}                  # a folder rule matches the folder only
    assert {path: package_app.part_of(path, parts) for path in cases} == cases


# --- the post-build checks (D15-D18): `python package_app.py --check dist\Surasura` ----------------------------------------

def _program(tmp_path, qt=True, licences=True):
    folder = tmp_path / "Surasura"
    internal = folder / "_internal"
    internal.mkdir(parents=True)
    for exe in package_app.PROGRAM_EXES:
        (folder / exe).write_bytes(b"MZ")
    config = package_app.load_build_config()
    (internal / "sqlite3.dll").write_bytes(open(os.path.join(PROJECT, *config["sqlite_dll"].split("/")), "rb").read())
    package_app.write_build_stamp(str(folder), "3.0.0", "20261012T000000Z-0a1b2c3d", "Surasura", "0123456789abcdef")
    if qt:
        (internal / "PyQt6").mkdir()
        for module in ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg"):
            (internal / "PyQt6" / f"{module}.pyd").write_bytes(b"MZ")
        (internal / "PyQt6" / "sip.cp311-win_amd64.pyd").write_bytes(b"MZ")
        if licences:
            for dist in ("PyQt6", "PyQt6-Qt6"):
                (internal / "licenses" / dist).mkdir(parents=True)
                (internal / "licenses" / dist / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE\n", encoding="utf-8")
    return folder, config


def _restamp(folder, change):
    path = folder / "_internal" / "build_stamp.json"
    stamp = json.loads(path.read_text(encoding="utf-8"))
    change(stamp)
    path.write_text(json.dumps(stamp), encoding="utf-8")


def test_a_whole_program_passes_every_check(tmp_path):
    folder, config = _program(tmp_path)
    failures, facts = package_app.check_program(str(folder), config)
    assert failures == []
    assert facts["exes"] == ["Surasura.exe", "surasura-cli.exe", "tsubasa.exe", "updater.exe"]
    assert package_app._version_tuple(facts["sqlite"]) >= (3, 51, 3)
    assert facts["stamp"] == {"version": "3.0.0", "build_id": "20261012T000000Z-0a1b2c3d", "data_name": "Surasura",
                              "install_shape": "0123456789abcdef"}


@pytest.mark.parametrize("damage, expected", [
    (lambda f: (f / "Setup.exe").write_bytes(b"MZ"), "programs at the top"),
    (lambda f: (f / "updater.exe").unlink(), "programs at the top"),
    (lambda f: (f / "tsubasa.exe").unlink(), "programs at the top"),          # T1 B: tsubasa ships in every build
    (lambda f: (f / "Surasura.exe").rename(f / "surasura.exe"), "programs at the top"),
    (lambda f: (f / "settings.json").write_text("{}", encoding="utf-8"), "library"),
    (lambda f: (f / "User Files").mkdir(), "library"),
    (lambda f: (f / "data").mkdir(), "library"),
    (lambda f: (f / "results").mkdir(), "library"),
    (lambda f: (f / "_internal" / "PyQt6" / "QtWebEngineCore.pyd").write_bytes(b"MZ"), "doesn't use"),
    (lambda f: (f / "_internal" / "sqlite3.dll").write_bytes(b"not a dll"), "sqlite3.dll"),
    (lambda f: (f / "_internal" / "build_stamp.json").write_text('{"version": "3.0.0"}', encoding="utf-8"), "stamp"),
    # An earlier 3.x's stamp (no install shape), and a shape that isn't 16 hex: the update check couldn't compare it.
    (lambda f: _restamp(f, lambda s: s.pop("install_shape")), "stamp"),
    (lambda f: _restamp(f, lambda s: s.update(install_shape="0123456789ABCDEF")), "stamp"),
    (lambda f: _restamp(f, lambda s: s.update(install_shape="0123456789abcde")), "stamp"),
    # The real data name in another case: on Windows its folders are the real install's.
    (lambda f: _restamp(f, lambda s: s.update(data_name="surasura")), "stamp"),
    # A top-level entry no update owns: the next one-click update would leave it behind (U-S2 / IK-8).
    (lambda f: (f / "LICENSE.txt").write_text("MIT\n", encoding="utf-8"), "OWNED_ENTRIES"),
    (lambda f: (f / "plugins" / "語彙").mkdir(parents=True), "OWNED_ENTRIES"),
])
def test_each_damage_fails_its_check(tmp_path, damage, expected):
    folder, config = _program(tmp_path)
    damage(folder)
    failures, _facts = package_app.check_program(str(folder), config)
    assert any(expected in f for f in failures), failures


def _stubbed_build(tmp_path, monkeypatch, release, updater_builds=True, needs_installer=False, real_release=False,
                   **build_args):
    """build(release) with PyInstaller stubbed — each spec "builds" a tiny file where the real one would; the updater's
    fails when `updater_builds` is False — the SQLite swap stubbed, and the checks and the release's file list
    recording the program folder they read (`real_release`: the real `_build_release`). -> (the specs frozen, in
    order; {"checked" / "listed": the names seen, "release": the release's keyword arguments, "returned": what
    build() returned})."""
    import subprocess
    (tmp_path / "app").mkdir()
    with open(os.path.join(PROJECT, "app", "build_info.py"), "rb") as f:
        (tmp_path / "app" / "build_info.py").write_bytes(f.read())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(package_app, "get_version", lambda: "3.0.0")
    monkeypatch.setattr(package_app, "_python_version", lambda: (3, 11, 4))
    frozen, seen = [], {}

    def pyinstaller(cmd, **kwargs):
        frozen.append(os.path.basename(cmd[-1]))
        if frozen[-1] == "Surasura.spec":
            (tmp_path / "dist" / "Surasura" / "_internal").mkdir(parents=True)
            for exe in ("Surasura.exe", "surasura-cli.exe", "tsubasa.exe"):
                (tmp_path / "dist" / "Surasura" / exe).write_bytes(b"MZ")
        elif updater_builds:
            (tmp_path / "dist" / "updater.exe").write_bytes(b"MZ updater")
        return subprocess.CompletedProcess(cmd, 0 if updater_builds or frozen[-1] == "Surasura.spec" else 1)

    def checks(final, config):
        seen["checked"] = sorted(os.listdir(final))
        return [], {}
    monkeypatch.setattr(package_app.subprocess, "run", pyinstaller)
    monkeypatch.setattr(package_app, "swap_sqlite", lambda final, config: None)
    monkeypatch.setattr(package_app, "check_program", checks)
    if not real_release:
        monkeypatch.setattr(package_app, "_build_release",
                            lambda final, *a, **k: seen.update(release=k) or
                            seen.setdefault("listed", sorted(os.listdir(final))))
    monkeypatch.setattr(os, "startfile", lambda path: None, raising=False)
    seen["returned"] = package_app.build(release=release, skip_tests=True, needs_installer=needs_installer,
                                         **build_args)
    return frozen, seen


@pytest.mark.parametrize("release", [False, True])
def test_every_build_freezes_updater_exe_before_its_checks_and_its_file_list(tmp_path, monkeypatch, release):
    """updater.exe is the swapper a 3.x program's next update runs (S3.1 D9): every build freezes it — a test build
    too, not only --release — and puts it in the program before the checks, the zip, the installer and the release's
    parts list read the folder."""
    frozen, seen = _stubbed_build(tmp_path, monkeypatch, release)
    assert frozen == ["Surasura.spec", "updater.spec"]
    assert "updater.exe" in seen["checked"]
    assert ("updater.exe" in seen["listed"]) if release else ("listed" not in seen)


def test_a_build_whose_updater_exe_fails_stops_before_its_checks(tmp_path, monkeypatch, capsys):
    frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False, updater_builds=False)
    assert frozen == ["Surasura.spec", "updater.spec"] and seen == {"returned": False}
    assert "Build failed: every build needs updater.exe." in capsys.readouterr().out


@pytest.mark.parametrize("needs_installer", [False, True])
def test_a_build_stamps_its_install_shape_and_hands_the_override_to_its_release(tmp_path, monkeypatch,
                                                                               needs_installer):
    """The program carries the .iss's shape in its stamp — what its next update compares with the release's (S3.1
    D7) — and --needs-installer reaches the release's update.json as given."""
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=True, needs_installer=needs_installer)
    stamp = json.loads((tmp_path / "dist" / "Surasura" / "_internal" / "build_stamp.json").read_text(encoding="utf-8"))
    assert stamp["install_shape"] == package_app.install_shape()
    assert seen["release"]["needs_installer"] is needs_installer


def test_a_build_puts_the_repos_license_at_the_top_byte_for_byte_in_the_app_part(tmp_path, monkeypatch):
    """Settings › App reads its licence line from the LICENSE beside the program (app/credits.py): the build's step 3
    copies the repo's LICENSE to the top of the program folder as it is, before the checks read the folder, and the
    release sends it in the app part with README.md (left out, it would fall into runtime, "")."""
    with open(os.path.join(PROJECT, "LICENSE"), "rb") as f:
        licence = f.read()
    (tmp_path / "LICENSE").write_bytes(licence)
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False)
    assert seen["returned"] is True and "LICENSE" in seen["checked"]
    assert (tmp_path / "dist" / "Surasura" / "LICENSE").read_bytes() == licence
    assert package_app.part_of("LICENSE", package_app.load_build_config()["parts"]) == "app"


def test_the_command_line_hands_needs_installer_to_the_build(monkeypatch):
    """--needs-installer (the release's manual override, S3.1 D7) reaches build(): package_app.py's __main__ block run
    in the module's namespace with build() recorded."""
    source = _source(os.path.join(PROJECT, "package_app.py"))
    block = compile(source[source.index('if __name__ == "__main__":'):], "package_app.py", "exec")
    for argv, expected in ((["--release"], False), (["--release", "--needs-installer"], True)):
        seen = {}
        monkeypatch.setattr(sys, "argv", ["package_app.py", *argv])
        with pytest.raises(SystemExit):
            exec(block, dict(vars(package_app), __name__="__main__", build=lambda **k: seen.update(k) or True))
        assert seen["release"] is True and seen["needs_installer"] is expected


@pytest.mark.parametrize("built, code", [(True, 0), (False, 1)])
def test_a_failed_build_exits_1_and_a_built_one_0(monkeypatch, built, code):
    """the workflow's step and any script that runs package_app.py read its exit code; a build that stopped
    ("Build failed", "Build aborted") exited 0 and the step went green."""
    source = _source(os.path.join(PROJECT, "package_app.py"))
    block = compile(source[source.index('if __name__ == "__main__":'):], "package_app.py", "exec")
    monkeypatch.setattr(sys, "argv", ["package_app.py", "--skip-tests"])
    with pytest.raises(SystemExit) as stop:
        exec(block, dict(vars(package_app), __name__="__main__", build=lambda **k: built))
    assert stop.value.code == code


@pytest.mark.parametrize("release", [False, True])
def test_build_returns_true_when_it_built(tmp_path, monkeypatch, release):
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release)
    assert seen["returned"] is True


@pytest.mark.parametrize("folder", ["dist", "build"])
def test_a_tree_that_cant_be_removed_stops_the_build_before_freezing(tmp_path, monkeypatch, capsys, folder):
    """an earlier build's dist\\Surasura still open (its Surasura running, a window on it) can't be removed; kept
    silently, its files would ride into the new build's zip and parts. The build stops, naming the folder and why."""
    import shutil
    (tmp_path / folder / "Surasura").mkdir(parents=True)
    (tmp_path / folder / "Surasura" / "Surasura.exe").write_bytes(b"MZ an earlier build")
    real = shutil.rmtree

    def held(path, *a, **k):
        if os.path.basename(os.path.normpath(path)) == folder:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(path, *a, **k)
    monkeypatch.setattr(package_app.shutil, "rmtree", held)
    frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False)
    assert frozen == [] and seen == {"returned": False}
    out = capsys.readouterr().out
    assert f"Build aborted: {tmp_path / folder} can't be removed" in out and "being used by another process" in out
    assert (tmp_path / folder / "Surasura" / "Surasura.exe").read_bytes() == b"MZ an earlier build"


def _fail_zip(*a, **k):
    raise OSError(28, "No space left on device")


def test_a_release_whose_full_zip_fails_stops_before_its_update_json(tmp_path, monkeypatch, capsys):
    """a release goes out with its full zip; without it the build stops before the release's files."""
    monkeypatch.setattr(package_app.shutil, "make_archive", _fail_zip)
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=True)
    assert seen["returned"] is False and "release" not in seen
    out = capsys.readouterr().out
    assert "Build failed: a release needs its full zip." in out and "Zip Archive:" not in out


def test_a_test_builds_failed_zip_only_warns_and_names_no_zip(tmp_path, monkeypatch, capsys):
    # Without --release the zip is a convenience: the build goes on, but never points at a zip that wasn't made.
    monkeypatch.setattr(package_app.shutil, "make_archive", _fail_zip)
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False, zip_output=True)
    assert seen["returned"] is True
    out = capsys.readouterr().out
    assert "Warning: Could not create zip archive" in out and "Zip Archive:" not in out


def test_a_made_zip_is_named_at_the_end(tmp_path, monkeypatch, capsys):
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=False, zip_output=True)
    assert seen["returned"] is True and (tmp_path / "dist" / "Surasura_v3.0.0.zip").is_file()
    assert f"Zip Archive: {tmp_path / 'dist' / 'Surasura_v3.0.0.zip'}" in capsys.readouterr().out


def test_a_release_with_an_unusable_signing_key_fails_and_writes_no_update_json(tmp_path, monkeypatch, capsys):
    """SURASURA_SIGNING_KEY_FILE names a key that can't be used (here a hex key cut short): the release named a
    key, so it must never go out unsigned — the build fails and writes no update.json, no part."""
    key = tmp_path / "keys" / "surasura.hex"
    key.parent.mkdir()
    key.write_bytes(b"0123456789abcdef0123456789abcdef")
    monkeypatch.setenv(package_app.SIGNING_KEY_ENV, str(key))
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=True, real_release=True)
    assert seen["returned"] is False
    assert not list((tmp_path / "dist").glob("update.json*")) and not list((tmp_path / "dist").glob("surasura_part_*"))
    out = capsys.readouterr().out
    assert "can't be used" in out and "Build failed" in out and "0123456789abcdef" not in out


def test_a_release_with_no_key_named_is_still_written_unsigned(tmp_path, monkeypatch, capsys):
    # Today's behaviour, kept: no key named at all (a test build's release) -> update.json without a signature, said
    # loudly; a 3.x install is only told of it.
    monkeypatch.delenv(package_app.SIGNING_KEY_ENV, raising=False)
    _frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=True, real_release=True)
    assert seen["returned"] is True
    assert (tmp_path / "dist" / "update.json").is_file() and not (tmp_path / "dist" / "update.json.sig").exists()
    assert "NOT signed" in capsys.readouterr().out


def test_a_build_whose_iss_cant_be_read_stops_before_freezing(tmp_path, monkeypatch, capsys):
    def unreadable(path=None):
        raise FileNotFoundError("packaging/surasura.iss")
    monkeypatch.setattr(package_app, "install_shape", unreadable)
    frozen, seen = _stubbed_build(tmp_path, monkeypatch, release=True)
    assert frozen == [] and seen == {"returned": False}
    assert "Build aborted: packaging/surasura.iss can't be read" in capsys.readouterr().out


def test_missing_qt_licences_fail_the_folder_and_the_zip(tmp_path):
    import shutil
    folder, config = _program(tmp_path, licences=False)
    failures, _ = package_app.check_program(str(folder), config)
    assert sum("licenses/" in f for f in failures) == 2
    shutil.make_archive(str(tmp_path / "Surasura_v3.0.0"), "zip", root_dir=str(tmp_path), base_dir="Surasura")
    assert len(package_app.check_zip_licences(str(tmp_path / "Surasura_v3.0.0.zip"))) == 2
    for dist in ("PyQt6", "PyQt6-Qt6"):
        (folder / "_internal" / "licenses" / dist).mkdir(parents=True)
        (folder / "_internal" / "licenses" / dist / "LICENSE").write_text("LGPL\n", encoding="utf-8")
    shutil.make_archive(str(tmp_path / "Surasura_v3.0.0"), "zip", root_dir=str(tmp_path), base_dir="Surasura")
    assert package_app.check_zip_licences(str(tmp_path / "Surasura_v3.0.0.zip")) == []


def test_a_program_without_qt_needs_no_qt_licences(tmp_path):
    folder, config = _program(tmp_path, qt=False)
    assert package_app.check_program(str(folder), config)[0] == []


def test_every_document_a_build_puts_at_the_top_is_owned_by_the_updater(tmp_path):
    """U-S2 / IK-8: a one-click update moves only app.updater.OWNED_ENTRIES (and what the new release names), so the
    documents the build copies to the top (README.md, UPDATE_INSTRUCTIONS.md, RELEASE_NOTES.md, LICENSE) must be
    owned: else the update after the one that stops shipping one would leave it behind."""
    folder, config = _program(tmp_path)
    for name in ("README.md", "UPDATE_INSTRUCTIONS.md", "RELEASE_NOTES.md", "LICENSE"):
        (folder / name).write_text("# すらすら 3.0\n", encoding="utf-8")
    failures, _facts = package_app.check_program(str(folder), config)
    assert failures == []
    (folder / "NOTES.md").write_text("# 語彙\n", encoding="utf-8")
    failures, _facts = package_app.check_program(str(folder), config)
    assert [f for f in failures if "OWNED_ENTRIES" in f and "NOTES.md" in f] == failures


def test_the_build_stamp_is_canonical_json(tmp_path):
    (tmp_path / "_internal").mkdir()
    path = package_app.write_build_stamp(str(tmp_path), "3.0.0", "id-1", "Surasura-test", "fedcba9876543210")
    data = open(path, "rb").read()
    assert data == package_app.canonical_json(json.loads(data))
    assert json.loads(data)["data_name"] == "Surasura-test"
    assert json.loads(data)["install_shape"] == "fedcba9876543210"


@pytest.mark.parametrize("name, ok", [("Surasura", True), ("Surasura-test", True), ("Surasura_2", True),
                                      ("", False), ("a/b", False), ("..", False), ("テスト", False), (None, False)])
def test_a_data_name_is_a_plain_folder_name(name, ok):
    assert package_app.valid_data_name(name) is ok


@pytest.mark.parametrize("name", ["surasura", "SURASURA", "SuraSura"])
def test_the_real_name_in_another_case_is_refused_wherever_the_real_name_gates(tmp_path, name):
    """Windows' folders ignore case, so `--data-name surasura` would install into the real
    %LOCALAPPDATA%\\Programs\\Surasura and write the real Houseki\\Surasura\\library.json, its uninstall would remove
    the real program's files, and its mutex (case-sensitive) wouldn't be the real one's."""
    assert package_app.valid_data_name(name)                          # a plain folder name on its own ...
    assert not package_app.valid_data_name(name, "Surasura")          # ... but the real install's folders
    assert package_app.valid_data_name("Surasura", "Surasura") and package_app.valid_data_name("Surasura-test",
                                                                                                "Surasura")
    with pytest.raises(ValueError):
        package_app.installer_defines("3.0.0", name, str(tmp_path), "Surasura")


def test_a_build_named_the_real_name_in_another_case_stops_before_freezing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(package_app, "get_version", lambda: "3.0.0")
    monkeypatch.setattr(package_app.subprocess, "run", lambda *a, **k: pytest.fail("nothing is frozen"))
    assert package_app.build(skip_tests=True, data_name="surasura") is False
    assert "in another case" in capsys.readouterr().out


def test_default_lists_go_to_internal_defaults_never_a_library(tmp_path, monkeypatch):
    """The bundled lists leave the program folder's User Files\\ (D15) for _internal\\defaults\\<lang>\\."""
    for lang, names in package_app.DEFAULT_LISTS.items():
        (tmp_path / "User Files" / lang).mkdir(parents=True)
        for name in names:
            (tmp_path / "User Files" / lang / name).write_text("食べる,1\n" if lang == "ja" else "吃,1\n",
                                                                encoding="utf-8")
    (tmp_path / "User Files" / "jiten_freq_Anime.zip").write_bytes(b"PK")
    final = tmp_path / "dist" / "Surasura"
    (final / "_internal").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    written = package_app.copy_default_lists(str(final))
    assert "_internal/defaults/ja/frequency_list_ja_global50k.csv" in written
    assert "_internal/defaults/ja/jiten_freq_Anime.zip" in written
    assert "_internal/defaults/zh/IgnoreList.txt" in written
    assert not (final / "User Files").exists()


# --- the install shape (S3.1 D7): what only the installer can change ------------------------------------------------------

ISS = os.path.join(PROJECT, "packaging", "surasura.iss")
FILES_LINE = 'Source: "{#ProgramDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs\n'


def _shape(tmp_path, text, raw=None):
    path = tmp_path / "variant.iss"
    path.write_bytes(raw if raw is not None else text.encode("utf-8"))
    return package_app.install_shape(str(path))


def _edit(text, old, new):
    assert text.count(old) == 1, old          # a guard on the guard: the edit lands where it says
    return text.replace(old, new)


def test_the_install_shape_is_16_hex_of_the_shipped_iss():
    shape = package_app.install_shape()
    assert len(shape) == 16 and all(c in "0123456789abcdef" for c in shape)
    assert package_app.install_shape(ISS) == shape


@pytest.mark.parametrize("change", [
    lambda t: t.replace("\n", "\r\n"),                                                   # a checkout's CRLF
    lambda t: _edit(t, "[Setup]\n", "\n\n[Setup]\n\n"),                                  # blank lines
    lambda t: _edit(t, "[Setup]\n", "[Setup]\n; 新しい説明: a comment\n"),                 # a ; comment
    lambda t: _edit(t, "PrivilegesRequired=lowest\n", "  PrivilegesRequired=lowest   \n"),   # outer spaces
    lambda t: _edit(t, "[Code]\n", "[Code]\n// a Pascal comment\n"),
    lambda t: _edit(t, "{ The library named in library.json, for the uninstaller's last message ('' when it can't "
                       "be read). }", "{ The library library.json names (reworded). }"),        # a { } comment line
    lambda t: _edit(t, FILES_LINE, FILES_LINE.replace("ignoreversion ", "ignoreversion restartreplace ")),
    lambda t: _edit(t, FILES_LINE, FILES_LINE + 'Source: "extra.dll"; DestDir: "{app}"\n'),
    lambda t: _edit(t, "[Files]\n", "[FILES]\n"),                                        # Inno's sections: any case
], ids=["CRLF", "blank lines", "; comment", "outer spaces", "// comment", "{ } comment", "a [Files] flag",
        "a [Files] line", "[FILES]"])
def test_comments_spacing_line_ends_and_files_never_move_the_shape(tmp_path, change):
    text = open(ISS, encoding="utf-8").read()
    assert _shape(tmp_path, change(text)) == package_app.install_shape(ISS)


def test_a_byte_order_mark_never_moves_the_shape(tmp_path):
    with open(ISS, "rb") as f:
        assert _shape(tmp_path, "", raw=b"\xef\xbb\xbf" + f.read()) == package_app.install_shape(ISS)


@pytest.mark.parametrize("change", [
    lambda t: _edit(t, "AppPublisher=SonicSandbox\n", "AppPublisher=Houseki\n"),
    lambda t: _edit(t, '[Icons]\nName: "{autoprograms}\\{#AppName}"', '[Icons]\nName: "{userdesktop}\\{#AppName}"'),
    lambda t: _edit(t, 'Type: files; Name: "{app}\\RELEASE_NOTES.md"\n',
                    'Type: files; Name: "{app}\\RELEASE_NOTES.md"\nType: files; Name: "{app}\\NOTES.md"\n'),
    lambda t: _edit(t, "  Result := Trim(ExpandConstant('{param:LIBRARY|}'));",
                    "  Result := ExpandConstant('{param:LIBRARY|}');"),
    lambda t: _edit(t, "[Code]\n", "[Code]\n{$DEFINE TRACE}\n"),                         # a directive, not a comment
    lambda t: _edit(t, "  NoteFailed: Boolean;\n", "  NoteFailed: Boolean;\n  { a } Spare: Boolean; { b }\n"),
    lambda t: _edit(t, FILES_LINE, FILES_LINE + '\n[InstallDelete]\nType: files; Name: "{app}\\old.dll"\n'),
], ids=["[Setup]", "[Icons]", "[UninstallDelete]", "[Code]", "{$ directive", "code between { }",
        "a section after [Files]"])
def test_what_only_the_installer_can_change_moves_the_shape(tmp_path, change):
    text = open(ISS, encoding="utf-8").read()
    assert _shape(tmp_path, change(text)) != package_app.install_shape(ISS)


# --- the package proof's paths and the merge gate that waits for it (D19) -------------------------------------------------

PACKAGE_YML = os.path.join(PROJECT, ".github", "workflows", "package.yml")
PR_MERGE_YML = os.path.join(PROJECT, ".github", "workflows", "pr-merge.yml")


def _package_paths():
    """package.yml's `on.pull_request.paths`, in order."""
    lines = _source(PACKAGE_YML).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "paths:")
    paths = []
    for line in lines[start + 1:]:
        if not line.strip().startswith('- "'):
            break
        paths.append(line.strip()[3:-1])
    return paths


def _proof_paths():
    """pr-merge.yml's PROOF_PATHS (a folded scalar: its lines joined by spaces), as words."""
    lines = _source(PR_MERGE_YML).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "PROOF_PATHS: >-")
    indent = len(lines[start]) - len(lines[start].lstrip())
    words = []
    for line in lines[start + 1:]:
        if not line.strip() or len(line) - len(line.lstrip()) <= indent:
            break
        words += line.split()
    return words


def test_the_package_proof_runs_on_everything_it_proves():
    # Review P item 6: a pull request changing the command line, the stamp's module, the smoke script or the workflows
    # themselves never started the proof, and the merge gate then found no run and passed.
    paths = _package_paths()
    for path in ("packaging/**", "package_app.py", "updater_helper.py", "app/updater.py", "app/update_checker.py",
                 "app_entry.py", "app/build_info.py", "app/cli/**", "scripts/cli_smoke.py",
                 ".github/workflows/package.yml", ".github/workflows/pr-merge.yml"):
        assert path in paths, path


def test_the_merge_gate_knows_the_same_paths_as_the_proof():
    """GitHub can't share one list between a workflow's `paths` and another's shell, so the list is written twice:
    pr-merge.yml's PROOF_PATHS must be package.yml's `paths`, the same strings in the same order."""
    assert _proof_paths() == _package_paths()


def _git_bash():
    """Git for Windows' bash (never WSL's, which `bash` on PATH may be), or /bin/bash elsewhere; None when missing."""
    import shutil
    if sys.platform != "win32":
        return shutil.which("bash")
    git = shutil.which("git")
    places = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git")]
    if git:
        places = [os.path.dirname(os.path.dirname(git)), os.path.dirname(os.path.dirname(os.path.dirname(git)))] + places
    for root in places:
        for rel in (("usr", "bin", "bash.exe"), ("bin", "bash.exe")):
            if os.path.isfile(os.path.join(root, *rel)):
                return os.path.join(root, *rel)
    return None


def _merge_script():
    """The merge step's `run: |` block, dedented."""
    lines = _source(PR_MERGE_YML).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "run: |")
    indent = len(lines[start]) - len(lines[start].lstrip()) + 2
    block = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        block.append(line[indent:])
    script = "\n".join(block) + "\n"
    assert "${{" not in script                     # all it reads comes through the step's env
    return script


# `gh` as the merge step meets it, answering from FAKE_* (what --jq would have printed) and logging every call: a shell
# function, so no real gh (and no network) is ever reached.
FAKE_GH = r'''
gh() {
  echo "gh $*" >> "$GH_LOG"
  case "$*" in
    "pr view"*) echo "$FAKE_BASE abc123 false true";;
    *workflows/pr.yml/runs*) echo "11 completed success";;
    *actions/runs/11/jobs*) echo "success";;
    *"actions/runs?"*) echo "$FAKE_PROOF";;
    *contents/.github/workflows/package.yml*)
      if [ "$FAKE_YML" = error ]; then echo "gh: Bad Gateway (HTTP 502)" >&2; return 1; fi
      for ref in $FAKE_YML; do
        case "$*" in *"ref=$ref "*) echo ".github/workflows/package.yml"; return 0;; esac
      done
      echo "gh: Not Found (HTTP 404)" >&2; return 1;;
    *pulls/7/files*) if [ "$FAKE_FILES" = error ]; then return 1; fi; printf '%s\n' "$FAKE_FILES";;
    "pr merge"*|"pr edit"*) ;;
    *) echo "unexpected: gh $*" >&2; return 9;;
  esac
}
'''

BASH = _git_bash()


@pytest.mark.skipif(not BASH, reason="no bash on this PC")
@pytest.mark.parametrize("proof, files, yml, base, merged", [
    # No run on the head and the pull request touches the proof's paths: it hasn't started yet -> refused.
    ("none - -", "packaging/surasura.iss", "abc123 3.0-dev", "3.0-dev", False),
    ("none - -", "docs/a b.md\napp/cli/contract.py", "abc123 3.0-dev", "3.0-dev", False),
    ("none - -", ".github/workflows/pr-merge.yml", "3.0-dev", "3.0-dev", False),     # the head predates package.yml
    # Nothing of the proof's touched (a name that only starts like one is not one of them) -> merged.
    ("none - -", "docs/すらすら.md\npackaging_notes.md\napp/updater.py.orig", "abc123 3.0-dev", "3.0-dev", True),
    # 2.x-dev has no package.yml at all: nothing would ever run, so nothing is waited for.
    ("none - -", "packaging/Surasura.spec", "", "2.x-dev", True),
    # A run on the head: it decides, whatever is touched.
    ("22 completed success", "packaging/surasura.iss", "abc123 3.0-dev", "3.0-dev", True),
    ("22 in_progress -", "docs/x.md", "abc123 3.0-dev", "3.0-dev", False),
    # A question the gate can't answer refuses.
    ("none - -", "error", "abc123 3.0-dev", "3.0-dev", False),
    ("none - -", "package_app.py", "error", "3.0-dev", False),
], ids=["touched", "touched among others", "base has it", "untouched", "2.x-dev", "passed", "running",
        "files unreadable", "package.yml lookup fails"])
def test_the_merge_gate_waits_for_a_proof_that_has_not_started(tmp_path, proof, files, yml, base, merged):
    """Review P item 7: "no package proof run" passed as "nothing to prove" even when the pull request touched the
    proof's paths and its run simply wasn't listed yet. The merge step's own shell runs here (bash -e, as Actions runs
    it) with `gh` answering as GitHub would after --jq: merged = `gh pr merge` called; refused = the label taken off,
    exit 1. The jq filters themselves are not run (GitHub's answers are stood in for)."""
    import subprocess
    script = tmp_path / "merge.sh"
    script.write_text(FAKE_GH + _merge_script(), encoding="utf-8", newline="\n")
    log = tmp_path / "gh.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "GITHUB_"))}
    env.update(GH_LOG=str(log).replace("\\", "/"), PR="7", REPO="example/surasura", LABELLED="abc123",
               PROOF_PATHS=" ".join(_proof_paths()), FAKE_PROOF=proof, FAKE_FILES=files, FAKE_YML=yml,
               FAKE_BASE=base)
    proc = subprocess.run([BASH, "-e", str(script).replace("\\", "/")], env=env, capture_output=True, timeout=60)
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    output = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert "unexpected" not in output, output
    if merged:
        assert proc.returncode == 0 and "gh pr merge 7" in calls and "--remove-label" not in calls, output
    else:
        assert proc.returncode == 1 and "gh pr merge" not in calls and "--remove-label reviewed" in calls, output
    if (proof, merged) == ("none - -", False) and "error" not in (files, yml):
        assert "the package proof hasn't started yet" in output
