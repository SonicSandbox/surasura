# Surasura v1.5 - Release Notes

## 🎮 Content Manager & UX
- **Manual Reordering**: Added **▴** and **▾** buttons to the Content Manager to manually move files and folders up or down in the list.
- **Target Days Estimation**: New toggle to show "Target Days" in the report! This estimates how many days it will take to reach your target coverage based on your configurable **Words Per Day** learning speed.
- **Enhanced Graduation Tooltip**: The "Graduate" button now features a descriptive multi-line tooltip explaining the priority tiers:
    - **NOW**: Graduate consumed content to your vocabulary.
    - **Soon**: Move content into your NOW queue.
    - **6+ Months**: Advance content into the "Soon" category.
- **Persistence by Design**: All manual reordering (via buttons or drag-and-drop) is automatically persisted across sessions.

## ⚙️ Backend & Japanese Support
- **Japanese Term Sanitization Toggle**: Added a runtime toggle in Advanced Settings to strip hyphen/space suffixes (e.g., "-iris", "-spirit") during analysis for better dictionary matching.
- **Improved Katakana Detection**: Refined Katakana logic to include the prolonged sound mark (ー), ensuring words like `ユーザー` and `コーヒー` are correctly handled as pure Katakana for Yomitan.
- **Universal Sanitization for Exports**: All exported frequency lists (Yomitan, Migaku, JSON) now automatically sanitize terms, ensuring 100% dictionary hit rates right out of the box.
- **Flat Zip Compression**: Frequency list exports now use flat zip compression, fixing an issue where nested directories could break Yomitan imports.
- **Harmonized Readings**: Standardized reading scripts across the exporter and analyzer to ensure consistent matching for terms with mixed Katakana/Hiragana readings.
- **Reliable Order Management**: Backend reordering logic now correctly handles recursive parent updates for more stable persistence.

## 🧘 Zen Mode Overhaul
- **Distraction-Free Reading**: Completely redesigned Zen Mode for maximum focus.
    - **Minimalist Header**: Sticky header with left-aligned, bold white file names and a subtle separator.
    - **Files First**: Content is organized by file, with per-file progress bars and stats.
- **Enhanced Progress Bar**:
    - **Target Tracking**: Progress bars now show **Baseline**, **Start**, and **Target** percentages right in the header.
    - **Unified Indentation**: Context sentences feature a single, continuous vertical line for a cleaner look.
- **Performance & Polish**:
    - **Smart Rendering**: Implemented `content-visibility: auto` to drastically improve scrolling performance for large lists.
    - **Cursor Control**: Hidden text cursors and blinking carets for a more "app-like" reading experience, while still allowing text selection for copying.
    - **Crash Protection**: Added global error handling to catch and display issues immediately instead of showing a black screen.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Breaking Changes
- None reported.

## Known Issues
- Yomitan exported dictionary works, but not all terms are found. Bug unknown

## Usage Tutorial

[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)
---
## UPDATE INSTRUCTIONS
> Download, Unzip
- Move your User files (Ignore list, freq list, blacklist, graduatedList) to User Files/LANGUAGE/  
- Move your data files to Data Files/LANGUAGE/  
