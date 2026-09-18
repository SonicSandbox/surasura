# -*- mode: python ; coding: utf-8 -*-
# Standalone updater.exe — the tiny helper that swaps app/ + templates/ after the app exits.
# Built ONLY on a release (see package_app.py --release), NOT part of a normal/dev build.
#
# It is a onefile exe that imports NOTHING from app/ (so it can never lock the files it
# replaces) and pulls in no heavy deps — hence the aggressive excludes below keep it small.
import os

project_root = os.path.abspath('.')

a = Analysis(
    [os.path.join(project_root, 'updater_helper.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'app', 'modules',
        'pandas', 'numpy', 'fugashi', 'jieba', 'unidic_lite',
        'lxml', 'bs4', 'pysrt', 'ebooklib', 'requests', 'tkinter',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(project_root, 'app', 'assets', 'images', 'app_icon.ico')],
)
