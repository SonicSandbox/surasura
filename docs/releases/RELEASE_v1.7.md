# Surasura v1.7 - Release Notes

## 🎮 Improved Content Management
- **Single Manifest Source of Truth**: The Content Manager now uses a single `master_manifest.json` to handle all ordering and grouping. This significantly improves stability and eliminates the need for complex physical file system restructuring during reordering.
- **Hierarchy-Preserving Graduation**: When graduating content between priority buckets, Surasura now preserves your folder structures, making it easier to manage large libraries of light novels or anime series.
- **UI Performance**: Fixed several redundancies in the Content Manager that were causing multiple unnecessary list refreshes, resulting in a snappier UI.

## 📺 Enhanced Subtitle Support
- **Native ASS/SSA Support**: You can now import and analyze `.ass` and `.ssa` subtitle files directly. 
- **Smart Extraction**: The subtitle processor automatically filters out styling tags (e.g., `{\pos(10,20)}`) and non-target language text, leaving you with clean content for analysis.

## 🛠️ Backend & Infrastructure
- **Future-Ready Module Architecture**: Restructured internal settings management to seamlessly support optional advanced modules while maintaining a clean core experience.

## ✨ v1.7 Bug Fixes
- **Priority List Word Count**: The Priority List tab now correctly displays the total word count and visible subset at the top of the report.
- **Zen Mode Optimization**: Launching Zen Mode now correctly respects the word limit settings during analysis for a focused experience.

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

**Note: Back up your User Files and Data Files before updating. The Manifest update may overwrite your file order (located in __order.json)**
