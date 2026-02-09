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
BUILD_NAME = f'Surasura_v{APP_VERSION}'

print(f"Building {BUILD_NAME}...")

# -----------------------------------------------------------------------------
# PYINSTALLER CONFIG
# -----------------------------------------------------------------------------

datas = [
    (os.path.join(project_root, 'templates'), 'templates'), 
    (os.path.join(project_root, 'scripts'), 'scripts'), 
    (os.path.join(project_root, 'app', 'assets'), 'app/assets')
]
binaries = []
hiddenimports = ['pandas', 'fugashi', 'tkinter', 'ebooklib', 'bs4']
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
    excludes=['pandas.tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=BUILD_NAME,
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
