# Packaging Surasura

This guide explains how to package Surasura into a standalone Windows app with PyInstaller.

## Prerequisites

1.  Python 3.9+ (the shipped builds bundle Python 3.11).
2.  Dependencies installed:
    ```bash
    pip install -r requirements.txt
    pip install pyinstaller
    ```

## Structure

*   `app_entry.py`: The entry point. It dispatches to each tool (analyzer, importers, indexer, …) by command word, so one `Surasura.exe` runs them all.
*   `package_app.py`: Automates the build — test gate, PyInstaller, output folder, zips.
*   `packaging/Surasura.spec`: The PyInstaller spec for the app (bundled data, hidden imports, which optional modules to include).
*   `packaging/updater.spec`: The spec for `updater.exe`, the small helper that applies in-app updates.
*   `app/path_utils.py`: Resolves paths in both source and frozen (packaged) modes.

## How to Build

Run from the project root:

```bash
python package_app.py              # build the app into dist/Surasura/
python package_app.py --zip        # ... and dist/Surasura_v<version>.zip
python package_app.py --release    # ... plus updater.exe and the auto-update files
```

A build:
1.  Runs the test suite first — `tests/` plus the suite of every optional module being bundled — and stops if anything fails (`--skip-tests` overrides this; not recommended).
2.  Deletes the previous `dist/` and `build/`, then runs PyInstaller (its log goes to `debug/build_log.txt`).
3.  Lays out `dist/Surasura/`: `Surasura.exe` and `_internal/`, a clean `settings.json` built from the defaults, starter `User Files/` (lists and the bundled frequency list — never anyone's known words), empty `data/` tiers, and `results/`.

**Which optional modules ship** is decided by the toggles in the repo's own `settings.json` (for example `enable_youtube_transcripts`, `enable_junban`), which `packaging/Surasura.spec` reads at build time.

## Release builds

*   `--release` also builds `updater.exe` and emits `Surasura_app_v<version>.zip` (the small in-app update) and `update.json`, which installed copies read from GitHub to decide how to update.
*   `--full-update` marks a release that must be installed manually (a new Python, new dependencies, or other runtime changes): it emits `update.json` without an app package and advances `packaging/runtime_baseline.txt`.

The full release procedure (version bump, release notes, which of the two to choose, publishing) is in the maintainer's release checklist.

## Troubleshooting

### "IndexError: tuple index out of range" during build
This generic PyInstaller error often indicates a mismatch with bytecode analysis, often caused by complex packages like `pandas` or generated packages.
*   Try: `pip install --upgrade pyinstaller`
*   Try: clearing `__pycache__` folders.

### Missing Dependencies in EXE
If the app runs but crashes claiming "Module not found", the module is probably only imported by name at runtime. Add it to `hiddenimports` in `packaging/Surasura.spec`.

### Path Issues
If the app cannot find files, ensure `app/path_utils.py` is correctly differentiating between `sys._MEIPASS` (bundled resources) and the folder next to `Surasura.exe` (user data).
