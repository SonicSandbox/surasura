# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os
import sys

# Paths are now relative to the spec file location (packaging/)
# We need to go up one level to reach the project root.
# When running from project root via package_app.py, use absolute path to be safe
# CWD is root, so abspath('.') gives root
project_root = os.path.abspath('.')

# -----------------------------------------------------------------------------
# DYNAMIC VERSION LOGIC
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# DYNAMIC VERSION LOGIC
# -----------------------------------------------------------------------------
def get_version():
    """Reads the version from app/__init__.py without importing the package."""
    init_path = os.path.join(project_root, 'app', '__init__.py')
    with open(init_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
    return "0.0"

APP_VERSION = get_version()
# Stable, version-agnostic install-folder name so it never goes stale after an in-place update
# (the version lives in the app title bar + the release page). The DOWNLOAD zip stays versioned.
BUILD_NAME = 'Surasura'

print(f"Building {BUILD_NAME}...")

# -----------------------------------------------------------------------------
# BUILD SETTINGS (Conditionality)
# -----------------------------------------------------------------------------
import json
# S3.1 D15: what ships comes from packaging/build_config.json, one file in the repo — never the build machine's
# settings.json. A missing or unreadable config bundles no optional module (package_app.py refuses to build first).
config_path = os.path.join(project_root, 'packaging', 'build_config.json')
build_config = {}
modules = {}
# Default excludes
excluded_modules = ['pandas.tests']

try:
    with open(config_path, 'r', encoding='utf-8') as f:
        build_config = json.load(f)
    modules = build_config.get("modules") or {}
except Exception as e:
    print(f"Warning: Could not read packaging/build_config.json: {e}")
if not isinstance(modules, dict):
    modules = {}
enable_youtube = modules.get("youtube_downloader") is True
enable_koe = modules.get("koe") is True
enable_reels = modules.get("reels") is True
enable_junban = modules.get("junban") is True

# The Immersion Architect (悟) is deprecated (RD-D9) and out of every build from 2.5 on: kept on disk with
# its own suite, dormant. The dashboard's button hides itself when the import fails. Revival steps:
# docs/agent instructions/Immersion_architect_feature.md (its header).
print("BUILD CONFIG: Excluding Immersion Architect module (sunset, RD-D9)")
excluded_modules.append('modules.immersion_architect')

# YouTube Downloader (transcripts and the preview both live in modules.youtube_downloader): bundled when the build
# config names it; its runtime toggles still hide it from a user who hasn't turned it on.
if not enable_youtube:
    print("BUILD CONFIG: Excluding YouTube Downloader module (build_config: youtube_downloader off)")
    excluded_modules.append('modules.youtube_downloader')

# Speech (Koe) ships WITH the app when the build config names it — it is hidden at RUNTIME instead, appearing only
# for a user who adds "enable_koe" to their settings.json — and when its folder exists (it is untracked, so an
# open-source checkout simply doesn't have it).
if enable_koe and os.path.isdir(os.path.join(project_root, 'modules', 'koe')):
    print("BUILD CONFIG: Bundling Speech module (hidden at runtime unless the user adds enable_koe)")
else:
    print("BUILD CONFIG: Speech module off or not present - excluding")
    excluded_modules.append('modules.koe')

# Reels (sunset 2026-09-22): bundled only if the build config ever names it again. It carries a vendored copy of
# SubsMatcher, so excluding it keeps that out of a build nobody asked it into.
if not enable_reels:
    print("BUILD CONFIG: Excluding Reels module (build_config: reels off)")
    excluded_modules.append('modules.reels')

# Junban (Anki reordering): bundled when the build config names it; the runtime toggle shows its 順 button. It talks
# to AnkiConnect over localhost; its one hidden import is its own `junban_patterns` command, inside the gate below.
if not enable_junban:
    print("BUILD CONFIG: Excluding Junban module (build_config: junban off)")
    excluded_modules.append('modules.junban')


# -----------------------------------------------------------------------------
# PYINSTALLER CONFIG
# -----------------------------------------------------------------------------

datas = [
    (os.path.join(project_root, 'templates'), 'templates'),
    (os.path.join(project_root, 'scripts'), 'scripts'),
    (os.path.join(project_root, 'app', 'assets'), 'app/assets'),
    # Bundle sample content as a RESOURCE (get_resource('samples')) so 'Test with samples' can seed
    # it on demand. The program folder ships no library (S3.1 D15): the library's data/ tiers start empty.
    (os.path.join(project_root, 'samples'), 'samples'),
    (os.path.join(project_root, '.env'), '.')
]
binaries = []
# app.reference_data is imported only INSIDE functions (deliberately - it's a 1.3 MB table
# decoded on demand), and the code degrades silently if it's missing: no reading badges, and
# the frequency-list orthography bridge stops working. A silent loss is exactly what a
# hiddenimport is for. app.zh_script_data is the same case: without it the Chinese Script setting
# silently reads everything as written; so are app.katakana_data, app.name_data and app.jmdict_data (app/names.py:
# without them names and a story's own kanji terms stay in pieces), and app.phrases / app.phrase_data (without them
# the list silently holds no set phrases). app.library_store too (2.5, Library_Store_Spec §7): every caller imports
# it inside a function, and without it the app would quietly run in JSON mode and the `library_maintain` helper
# would fail.
hiddenimports = ['pandas', 'fugashi', 'tkinter', 'ebooklib', 'bs4', 'app.reference_data', 'app.library_store',
                 'app.anki_connect', 'app.anki_sync', 'app.anki_sync_gui',
                 'app.zh_script', 'app.zh_script_data', 'app.names', 'app.katakana_data', 'app.name_data',
                 'app.jmdict_data', 'app.phrases', 'app.phrase_data', 'app.one_kanji_data']
# Every command app_entry.py dispatches to (S3.1 D17; tests/test_packaging_config.py reads app_entry.py and fails while
# one is missing here): the window, the dashboard and each helper subcommand the programs start.
hiddenimports += ['app.analyzer', 'app.epub_importer', 'app.migaku_db_importer_gui', 'app.jiten_db_importer_gui',
                  'app.static_html_generator', 'app.migaku_converter', 'app.jiten_converter',
                  'app.content_importer_gui', 'app.frequency_list_gui', 'app.anki_db_importer_gui', 'app.indexer',
                  'app.arrivals_worker', 'app.sentence_corpus', 'app.telemetry', 'app.main', 'app.qt.shell',
                  'app.replan_preview', 'app.services.word_lists']
# The 2.x -> 3.0 import and the GraduatedList merge (S3.1 D11-D13): the window's first-run page imports them inside a
# function, so nothing at the top of the import graph names them (row 3.1.9b found both missing from a build).
hiddenimports += ['app.import_2x', 'app.graduated_merge']
# The 3.0 window's tools (W3.4 row 2): the .apkg known-words import and Extract, each a child of the window that
# app_entry.py imports inside its branch.
hiddenimports += ['app.anki_db_import', 'app.extract']

# --- The window's PyQt6 (S3.1 D17): app.qt and five Qt modules, every other PyQt6 module excluded -------------------
# The window (app/qt/) is reached only through a function-level import in app_entry.py; naming it and its modules keeps
# it in the build. Every other PyQt6 extension module the installed wheel carries (WebEngine, Qml, Multimedia, 3D, …)
# is excluded, so neither it nor the Qt DLLs it alone needs ship. PyQt6's and Qt's licence notices ride in
# _internal\licenses\<distribution>\ (PyQt6 GPL v3, Qt LGPL v3, PyQt6-sip).
import importlib.util
qt_modules = build_config.get("qt_modules") if isinstance(build_config, dict) else None
if not isinstance(qt_modules, list) or not qt_modules:
    qt_modules = ['QtCore', 'QtGui', 'QtWidgets', 'QtNetwork', 'QtSvg']
qt_excludes = []
qt_spec = importlib.util.find_spec('PyQt6')
if qt_spec is not None and qt_spec.submodule_search_locations:
    qt_folder = list(qt_spec.submodule_search_locations)[0]
    for qt_name in sorted(os.listdir(qt_folder)):
        qt_module = qt_name.split('.')[0]
        if qt_name.endswith('.pyd') and qt_module.startswith('Q') and qt_module not in qt_modules:
            qt_excludes.append('PyQt6.' + qt_module)
    qt_excludes += ['PyQt6.uic', 'PyQt6.lupdate']
    for qt_root, _qt_dirs, qt_files in os.walk(os.path.join(project_root, 'app', 'qt')):
        for qt_file in sorted(qt_files):
            if qt_file.endswith('.py'):
                rel = os.path.relpath(os.path.join(qt_root, qt_file[:-3]), project_root)
                hiddenimports.append(rel.replace(os.sep, '.').replace('.__init__', ''))
    hiddenimports += ['PyQt6.sip'] + ['PyQt6.' + m for m in qt_modules]
    from importlib import metadata as qt_metadata
    for qt_dist in ('PyQt6', 'PyQt6-Qt6', 'PyQt6-sip'):
        try:
            dist = qt_metadata.distribution(qt_dist)
        except qt_metadata.PackageNotFoundError:
            continue
        for dist_file in dist.files or []:
            if os.path.basename(str(dist_file)).upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
                datas.append((str(dist.locate_file(dist_file)), 'licenses/' + qt_dist))
else:
    print("BUILD CONFIG: PyQt6 is not installed - the window falls back to the Tk dashboard")

# --- Optional-module payloads: only when that module is actually being bundled ---------------
# Both entries below MUST stay inside their gate. Naming a module in hiddenimports while it is
# also in `excludes` is a contradiction PyInstaller resolves by warning and dropping it, which
# would be a silent no-op rather than the guarantee this is here to give.

# The vendored SubsMatcher is only ever RUN, never imported by module code, so nothing in the
# import graph points at it and PyInstaller would leave it out. Frozen, it is reached through
# app_entry's `subsync` command, which imports it — but state that here too so the dependency
# survives a refactor of the dispatcher.
if enable_reels:
    hiddenimports.append('modules.reels.vendor.subsync')

# Junban's own subcommand (`junban_patterns`, app_entry.py): the Anki Backfill window's library build.
if enable_junban:
    hiddenimports.append('modules.junban.patterns_build')

# The transcripts preview's scoring child (`youtube_preview`, app_entry.py): the 3.0 window runs it as its own process.
if enable_youtube:
    hiddenimports.append('modules.youtube_downloader.preview')

tmp_ret = collect_all('unidic_lite')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [os.path.join(project_root, 'app_entry.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules + qt_excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# UPX is off everywhere (S3.1 D15, E12): it can corrupt Qt's DLLs and feeds antivirus false positives;
# every EXE / COLLECT says upx=False (PyInstaller refuses --noupx beside a .spec file).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Surasura',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(project_root, 'app', 'assets', 'images', 'app_icon.ico')],
)

# -----------------------------------------------------------------------------
# surasura-cli.exe: the headless command line (P0.3 02-contract §1, §8), a console program beside Surasura.exe
# sharing its _internal\. Its own slim Analysis — no Tk, pandas or Qt can reach it — so it adds one small file, not a
# second copy of the app. A frozen program ignores the caller's PYTHONUTF8 / PYTHONUNBUFFERED: the OPTIONS set both.
# -----------------------------------------------------------------------------
cli_a = Analysis(
    [os.path.join(project_root, 'app', 'cli', '__main__.py')],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules + ['tkinter', '_tkinter', 'tkinterdnd2', 'pandas', 'numpy', 'PyQt6',
                                 'requests', 'app.main', 'app.telemetry', 'app.static_html_generator'],
    noarchive=False,
    optimize=0,
)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [('X utf8', None, 'OPTION'), ('u', None, 'OPTION')],
    exclude_binaries=True,
    name='surasura-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(project_root, 'app', 'assets', 'images', 'app_icon.ico')],
)

# -----------------------------------------------------------------------------
# tsubasa.exe: tsubasa's command line (T1 B, 2026-10-21), a console program beside Surasura.exe sharing its _internal\,
# built from the tsubasa-sync package requirements.txt pins (packaging/tsubasa_entry.py, its console script written out).
# Connect runs it as its own program and never imports it (K1). Its own slim Analysis, like surasura-cli's: tsubasa's
# code rides inside tsubasa.exe, its name tables in _internal\tsubasa\ (tsubasa's own PyInstaller hook, found through
# its pyinstaller40 entry point: no datas here), numpy is the one the app already ships. package_app.py refuses a build
# whose installed tsubasa-sync or whose tsubasa.exe --version isn't the pinned one.
# -----------------------------------------------------------------------------
tsubasa_spec = importlib.util.find_spec('tsubasa')
tsubasa_icon = os.path.join(list(tsubasa_spec.submodule_search_locations)[0], 'data', 'tsubasa.ico') \
    if tsubasa_spec is not None and tsubasa_spec.submodule_search_locations else None
tsubasa_datas = []
try:                                        # its licence notice (GPL-3.0-or-later), beside PyQt6's: from its metadata
    from importlib import metadata as tsubasa_metadata
    for dist_file in tsubasa_metadata.distribution('tsubasa-sync').files or []:
        if os.path.basename(str(dist_file)).upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
            tsubasa_datas.append((str(tsubasa_metadata.distribution('tsubasa-sync').locate_file(dist_file)),
                                  'licenses/tsubasa-sync'))
except Exception as e:
    print(f"BUILD CONFIG: tsubasa-sync's licence notice not found ({e})")
tsubasa_a = Analysis(
    [os.path.join(project_root, 'packaging', 'tsubasa_entry.py')],
    pathex=[],
    binaries=[],
    datas=tsubasa_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules + ['tsubasa.gui', 'tsubasa.dev', 'tkinter', '_tkinter', 'tkinterdnd2', 'pandas',
                                 'PyQt6', 'requests', 'app', 'modules'],
    noarchive=False,
    optimize=0,
)
tsubasa_pyz = PYZ(tsubasa_a.pure)
tsubasa_exe = EXE(
    tsubasa_pyz,
    tsubasa_a.scripts,
    [],
    exclude_binaries=True,
    name='tsubasa',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[tsubasa_icon] if tsubasa_icon and os.path.isfile(tsubasa_icon) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    cli_exe,
    cli_a.binaries,
    cli_a.datas,
    tsubasa_exe,
    tsubasa_a.binaries,
    tsubasa_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=BUILD_NAME,
)
