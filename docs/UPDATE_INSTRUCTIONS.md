# How to Update Surasura - Readability Analyzer

## ⚠️ Important: Protect Your Data
Before updating, **always backup your `User Files` folder**. This folder contains your personal database (`KnownWord.json`) and ignore list.

## Update Instructions

1.  **Backup Your Data**:
    *   Navigate to your current Surasura folder.
    *   Copy the `User Files` folder to a safe location (e.g., Desktop).

2.  **Download New Version**:
    *   Download the latest release zip file (e.g., `Surasura_v1.x.zip`).
    *   Extract it to a new location.

3.  **Restore Your Data (Migration to v1.2+)**:
    *   Open the new Surasura folder.
    *   Navigate into `User Files`. You will see language folders like `ja` (Japanese) and `zh` (Chinese).
    *   **Open the language folder matching your previous usage** (likely `ja`).
    *   **Delete** the default `KnownWord.json` and `IgnoreList.txt` inside that language folder.
    *   **Copy** your backed-up `KnownWord.json` and `IgnoreList.txt` (from Step 1) into this language folder.
    *   **Note**: If you had other files like frequency lists in your old `User Files`, check if they are already bundled in the new version. If not, copy them to the main `User Files` folder.

4.  **Launch**:
    *   Run `Surasura.exe`.
    *   Verify your known words are loaded correctly in the dashboard (ensure the correct language is selected in settings).

## Release Notes
Check the `RELEASE_*.md` files or the GitHub Releases page for details on what's new in each version.

## Issues & Contributions
If you encounter any issues or have suggestions, please open an issue on the [GitHub repository](https://github.com/SonicSandbox/surasura).
