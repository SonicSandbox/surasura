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
settings_path = os.path.join(project_root, 'settings.json')
hide_satoru = False
enable_youtube = False
enable_preview = False  # default so a missing/corrupt settings.json can't NameError below
enable_reels = False
enable_junban = False
# Default excludes
excluded_modules = ['pandas.tests']

if os.path.exists(settings_path):
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            hide_satoru = settings.get("hide_satoru", False)
            enable_youtube = settings.get("enable_youtube_transcripts", False)
            enable_preview = settings.get("enable_youtube_preview", False)
            enable_reels = settings.get("enable_reels", False)
            enable_junban = settings.get("enable_junban", False)
    except Exception as e:
        print(f"Warning: Could not read settings.json for build configuration: {e}")

if hide_satoru:
    print("BUILD CONFIG: Excluding Immersion Architect module (hide_satoru=True)")
    excluded_modules.append('modules.immersion_architect')

# YouTube Downloader is opt-in: bundled when EITHER the transcript downloader or the
# preview feature is enabled at build time (both live in modules.youtube_downloader).
if not (enable_youtube or enable_preview):
    print("BUILD CONFIG: Excluding YouTube Downloader module (transcripts & preview both off)")
    excluded_modules.append('modules.youtube_downloader')

# Speech (Koe) ships WITH the app rather than being toggled in at build time — it is hidden at
# RUNTIME instead, appearing only for a user who adds "enable_koe" to their settings.json. So the
# only question here is whether the folder exists at all (it is untracked, so an open-source
# checkout simply doesn't have it).
if os.path.isdir(os.path.join(project_root, 'modules', 'koe')):
    print("BUILD CONFIG: Bundling Speech module (hidden unless enable_koe is added to settings.json)")
else:
    print("BUILD CONFIG: Speech module not present - excluding")
    excluded_modules.append('modules.koe')

# Reels is opt-in and gated the same way YouTube is: the toggle that shows the button also decides
# whether the module is bundled. It carries a vendored copy of SubsMatcher, so excluding it keeps
# that out of a build nobody asked it into.
if not enable_reels:
    print("BUILD CONFIG: Excluding Reels module (enable_reels=False)")
    excluded_modules.append('modules.reels')

# Junban (Anki reordering) is opt-in the same way: the toggle that shows the 順 button also decides
# whether the module is bundled. It talks to AnkiConnect over localhost and needs no hiddenimports —
# everything it uses is reached through ordinary imports from modules.junban.
if not enable_junban:
    print("BUILD CONFIG: Excluding Junban module (enable_junban=False)")
    excluded_modules.append('modules.junban')


# -----------------------------------------------------------------------------
# PYINSTALLER CONFIG
# -----------------------------------------------------------------------------

datas = [
    (os.path.join(project_root, 'templates'), 'templates'),
    (os.path.join(project_root, 'scripts'), 'scripts'),
    (os.path.join(project_root, 'app', 'assets'), 'app/assets'),
    # Bundle sample content as a RESOURCE (get_resource('samples')) so 'Test with samples' can seed
    # it on demand. The data/ tiers themselves ship EMPTY (see package_app.py) -> empty-state shows.
    (os.path.join(project_root, 'samples'), 'samples'),
    (os.path.join(project_root, '.env'), '.')
]
binaries = []
# app.reference_data is imported only INSIDE functions (deliberately - it's a 1.3 MB table
# decoded on demand), and the code degrades silently if it's missing: no reading badges, and
# the frequency-list orthography bridge stops working. A silent loss is exactly what a
# hiddenimport is for.
hiddenimports = ['pandas', 'fugashi', 'tkinter', 'ebooklib', 'bs4', 'app.reference_data',
                 'app.anki_connect', 'app.anki_sync', 'app.anki_sync_gui']

# --- Optional-module payloads: only when that module is actually being bundled ---------------
# Both entries below MUST stay inside their gate. Naming a module in hiddenimports while it is
# also in `excludes` is a contradiction PyInstaller resolves by warning and dropping it, which
# would be a silent no-op rather than the guarantee this is here to give.

# Immersion Architect reads (and writes) architect_settings.json through get_resource(), so the
# file has to exist under the bundle root at the same relative path it has in the repo. Without
# it every read falls back to hardcoded defaults and the budget slider silently discards changes.
if not hide_satoru:
    _architect_settings = os.path.join(project_root, 'modules', 'immersion_architect',
                                       'architect_settings.json')
    if os.path.isfile(_architect_settings):
        datas.append((_architect_settings, 'modules/immersion_architect'))

# The vendored SubsMatcher is only ever RUN, never imported by module code, so nothing in the
# import graph points at it and PyInstaller would leave it out. Frozen, it is reached through
# app_entry's `subsync` command, which imports it — but state that here too so the dependency
# survives a refactor of the dispatcher.
if enable_reels:
    hiddenimports.append('modules.reels.vendor.subsync')

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
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Surasura',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(project_root, 'app', 'assets', 'images', 'app_icon.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=BUILD_NAME,
)
