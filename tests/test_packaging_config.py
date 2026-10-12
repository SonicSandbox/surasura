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
    main, _cli = _run_spec(tmp_path, config, {"enable_junban": True, "enable_youtube_transcripts": True,
                                               "enable_youtube_preview": True, "enable_reels": True})
    for module in ("modules.junban", "modules.youtube_downloader", "modules.koe", "modules.reels",
                   "modules.immersion_architect"):
        assert module in main["excludes"]
    assert "modules.junban.patterns_build" not in main["hiddenimports"]


def test_the_shipped_config_bundles_what_2_5_0_shipped(tmp_path):
    main, _cli = _run_spec(tmp_path, json.loads(_source(CONFIG)), {})
    for module in ("modules.junban", "modules.youtube_downloader", "modules.koe"):
        assert module not in main["excludes"]
    for module in ("modules.reels", "modules.immersion_architect"):
        assert module in main["excludes"]
    assert "modules.junban.patterns_build" in main["hiddenimports"]


def test_no_build_config_bundles_no_optional_module(tmp_path):
    main, _cli = _run_spec(tmp_path, None, {"enable_junban": True})
    for module in ("modules.junban", "modules.youtube_downloader", "modules.koe", "modules.reels"):
        assert module in main["excludes"]


@pytest.mark.skipif(not __import__("importlib.util").util.find_spec("PyQt6"), reason="PyQt6 is not installed")
def test_the_window_gets_five_qt_modules_and_their_licences(tmp_path):
    main, cli = _run_spec(tmp_path, json.loads(_source(CONFIG)), {})
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
    assert [p["name"] for p in config["parts"]] == ["app", "qt", "dict", "runtime"]
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
             "_internal/sqlite3.dll": "runtime", "_internal/python311.dll": "runtime",
             "_internal/templatesX/a.html": "runtime"}                  # a folder rule matches the folder only
    assert {path: package_app.part_of(path, parts) for path in cases} == cases


# --- the post-build checks (D15-D18): `python package_app.py --check dist\Surasura` ----------------------------------------

def _program(tmp_path, release=True, qt=True, licences=True):
    folder = tmp_path / "Surasura"
    internal = folder / "_internal"
    internal.mkdir(parents=True)
    for exe in package_app.PROGRAM_EXES if release else ("Surasura.exe", "surasura-cli.exe"):
        (folder / exe).write_bytes(b"MZ")
    config = package_app.load_build_config()
    (internal / "sqlite3.dll").write_bytes(open(os.path.join(PROJECT, *config["sqlite_dll"].split("/")), "rb").read())
    package_app.write_build_stamp(str(folder), "3.0.0", "20261012T000000Z-0a1b2c3d", "Surasura")
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


def test_a_whole_program_passes_every_check(tmp_path):
    folder, config = _program(tmp_path)
    failures, facts = package_app.check_program(str(folder), config, release=True)
    assert failures == []
    assert facts["exes"] == ["Surasura.exe", "surasura-cli.exe", "updater.exe"]
    assert package_app._version_tuple(facts["sqlite"]) >= (3, 51, 3)
    assert facts["stamp"] == {"version": "3.0.0", "build_id": "20261012T000000Z-0a1b2c3d", "data_name": "Surasura"}


@pytest.mark.parametrize("damage, expected", [
    (lambda f: (f / "Setup.exe").write_bytes(b"MZ"), "programs at the top"),
    (lambda f: (f / "updater.exe").unlink(), "programs at the top"),
    (lambda f: (f / "Surasura.exe").rename(f / "surasura.exe"), "programs at the top"),
    (lambda f: (f / "settings.json").write_text("{}", encoding="utf-8"), "library"),
    (lambda f: (f / "User Files").mkdir(), "library"),
    (lambda f: (f / "data").mkdir(), "library"),
    (lambda f: (f / "results").mkdir(), "library"),
    (lambda f: (f / "_internal" / "PyQt6" / "QtWebEngineCore.pyd").write_bytes(b"MZ"), "doesn't use"),
    (lambda f: (f / "_internal" / "sqlite3.dll").write_bytes(b"not a dll"), "sqlite3.dll"),
    (lambda f: (f / "_internal" / "build_stamp.json").write_text('{"version": "3.0.0"}', encoding="utf-8"), "stamp"),
])
def test_each_damage_fails_its_check(tmp_path, damage, expected):
    folder, config = _program(tmp_path)
    damage(folder)
    failures, _facts = package_app.check_program(str(folder), config, release=True)
    assert any(expected in f for f in failures), failures


def test_a_test_build_has_two_programs_and_no_updater(tmp_path):
    folder, config = _program(tmp_path, release=False)
    assert package_app.check_program(str(folder), config, release=False)[0] == []
    (folder / "updater.exe").write_bytes(b"MZ")
    assert package_app.check_program(str(folder), config, release=False)[0]


def test_missing_qt_licences_fail_the_folder_and_the_zip(tmp_path):
    import shutil
    folder, config = _program(tmp_path, licences=False)
    failures, _ = package_app.check_program(str(folder), config, release=True)
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
    assert package_app.check_program(str(folder), config, release=True)[0] == []


def test_the_build_stamp_is_canonical_json(tmp_path):
    (tmp_path / "_internal").mkdir()
    path = package_app.write_build_stamp(str(tmp_path), "3.0.0", "id-1", "Surasura-test")
    data = open(path, "rb").read()
    assert data == package_app.canonical_json(json.loads(data))
    assert json.loads(data)["data_name"] == "Surasura-test"


@pytest.mark.parametrize("name, ok", [("Surasura", True), ("Surasura-test", True), ("Surasura_2", True),
                                      ("", False), ("a/b", False), ("..", False), ("テスト", False), (None, False)])
def test_a_data_name_is_a_plain_folder_name(name, ok):
    assert package_app.valid_data_name(name) is ok


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
