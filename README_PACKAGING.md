# Packaging ReadabilityAnalyzer

This guide explains how to package the Readability Analyzer application into a standalone executable.

## Prerequisites

1.  Python 3.10+
2.  Dependencies installed:
    ```bash
    pip install -r requirements.txt
    pip install pyinstaller pyinstaller-hooks-contrib auto-py-to-exe
    ```
    Note: `tkinterdnd2` and `unidic-lite` are tricky dependencies.

## Structure

*   `app_entry.py`: The entry point script that handles dispatching to different modules (Analyzer, Importer, etc.).
*   `package_app.py`: A Python script that automates the PyInstaller build and organizes the output folder.
*   `app/path_utils.py`: Utility module to handle paths in both source and frozen (packaged) modes.

## How to Build

Run the following command in the project root:

```bash
python package_app.py
```

This will:
1.  Clean previous builds.
2.  Run PyInstaller on `app_entry.py`.
3.  Create a `dist/ReadabilityAnalyzer_v1.0` folder.
4.  Copy existing `User Files` and create necessary `data` directories.

## Troubleshooting

### "IndexError: tuple index out of range" during build
This generic PyInstaller error often indicates a mismatch with bytecode analysis, often caused by complex packages like `pandas` or generated packages.
*   Try: `pip install --upgrade pyinstaller`
*   Try: clearing `__pycache__` folders.
*   If consistent, try excluding specific hidden imports in `package_app.py` or reinstalling Python.

### Missing Dependencies in EXE
If the app runs but crashes claiming "Module not found", you may need to add it to `--hidden-import` in `package_app.py`.

### Path Issues
If the app cannot find files, ensure `app/path_utils.py` is correctly differentiating between `sys._MEIPASS` (bundled resources) and local paths.
