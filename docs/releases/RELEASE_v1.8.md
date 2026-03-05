# Surasura v1.8 - Release Notes

## Summary
- i+1 only toggle
- Adjust ideal sentence length
- Hotkeys (ignore + audio)
- Audio for initial sentence
- Adjust ex sentence #
- Significant algorithm optimizations


## 📙 Context & Export Bound Control
- Added **"Only include i+1 sentences"** toggle. When enabled, words without an i+1 sentence context (sentences with exactly 1 unknown word) will be excluded from the analysis export.
- Added variable **"Max Example Sentences (Contexts)"** boundary to the Advanced Settings. The app natively exports and visualizes up to this dynamically customized count per-word allowing higher-volume sentence mining through the CSV.
- Added configurable **"Ideal sentence range"** (`min` and `max` character lengths) to the Advanced Settings, allowing precise control over what context sentences are prioritized.
- Ensured context selection ranks sentences chronologically such that the first valid context for a word throughout your reading material is reliably preserved.

## ⌨️ Advanced Hotkeys & UX Improvements
- **Ignore Hotkey**: Added a `z` hotkey to quickly ignore the currently active word in the main views, moving the selection to the next word automatically.
- **Context-Aware Audio Playback**: The audio button (and `v` hotkey) now plays the full context sentence rather than just the isolated word, significantly improving listening immersion.
- **Audio Overlap Prevention**: Implemented absolute audio cancellation; starting a new playback immediately interrupts the previous one to prevent queuing and overlapping speech.
- **New Toggle: "Hide Native Audio Button"**: Added a setting to allow users to remove the audio playback icons from generated reports for a cleaner, visual-only experience.
- **Improved Settings UX**: Reorganized the Advanced Settings window to place Target Language and language-specific options at the top for faster access.
- **Redesigned Hotkey Info**: The help tooltip now features a clean, multi-line layout with better readability and comprehensive coverage of all navigation keys.

## ⚙️ Engine Optimizations
- **Efficient Data Encoding (HTML)**: Implemented a compressed JSON payload structure for static HTML reports, mapping word keys to array rows. This reduces final file sizes by 40-50% and accelerates initial browser parsing.
- **High-Performance Zen Decompression**: Integrated a fast decompression handler into minimalist templates to support compressed data payloads without compromising client-side rendering speed.
- **Theme Token Normalization**: Standardized theme internal IDs to slugified tokens (e.g., `zen-focus`). This ensures valid `DOMTokenList` interactions and prevents JavaScript initialization errors.
- **Dangling Japanese Quote Remediation**: Adjusted the `JapaneseTokenizer` to cleanly strip lingering `」`, `』`, and `”` marks that orphan onto the beginning of subsequent lines when text parsing splits at boundaries before a dialogue enclosure.
- **i+1 Candidate Caching**: Replaced brute-force array sorting and duplicate checks with a singular cost bounds evaluation loop. Drops >80% of array reallocation overhead for high-frequency words during document scanning.
- **Early Evaluation Exit**: Simulated text progression explicitly breaks early to skip calculating remaining sentence evaluations once 3 perfectly-sized i+1 sentences are secured.
- **i+1 Exclusion Tracking**: Added a `Words Evaluated & Skipped` metric to the `file_statistics.txt` output dynamically whenever strict i+1 mode is enabled, providing clear visibility into export size discrepancies.
- **Short-Circuit Phase 2 Scans**: The engine's core iteration loops now short-circuit and aggressively break parsing the instant it identifies an invalid unknown token inside strict i+1 mode, saving tens of thousands of superfluous dictionary checks.
- **Logic Validation Bounds**: Integrated native UI trace listeners on the `min_chars` and `max_chars` spinboxes to actively intercept and auto-correct logically impossible ranges before backend execution occurs.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> Download, Unzip
- Move your User files (Ignore list, freq list, blacklist, graduatedList) to User Files/LANGUAGE/  
- Move your data files to Data Files/LANGUAGE/  

**Note: Back up your User Files and Data Files before updating. The Manifest update may overwrite your file order (located in __order.json)**
