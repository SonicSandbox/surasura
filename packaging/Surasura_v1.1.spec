# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

# Paths are now relative to the spec file location (packaging/)
# We need to go up one level to reach the project root.
project_root = '..'

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
    name='Surasura_v1.1',
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
    name='Surasura_v1.1',
)
