# -*- mode: python ; coding: utf-8 -*-
# Standalone updater.exe — the swapper (updater_helper.py): after the app exits it swaps the program's entries for a
# release's assembled ones, proves them, and draws the update splash (raw Win32, no Qt / Tk); `--selftest out.json`
# proves a build can draw it. From 3.0 the NEW release's copy runs, copied out of the staged program (S3.1 D9), so it
# ships inside every 3.x program folder and in its `app` part.
#
# It is a onefile exe that imports NOTHING from app/ (so it can never lock the files it
# replaces) and pulls in no heavy deps — hence the aggressive excludes below keep it small.
# console=False: a console flashing mid-update is what the splash replaces. upx=False: UPX stays off (S3.1 D15). The
# icon is the app's: the splash draws its mark from this exe's own icon.
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
    upx=False,
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
