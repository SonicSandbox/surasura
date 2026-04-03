# Surasura v1.9 - Release Notes

## Summary
- Redesigned Content Importer UI
- Anki / SRS Sentence Exporter
- Robust Undo System & Persistent Trash
- New Demote Action 
- Emoji-Grouped Settings
- Live Background Polling

## 📥 Content Importer Enhancements
- **Redesigned UI**: Overhauled the management toolbar with a more consolidated, professional layout with improved scanability.
- **Robust Undo System (⎌)**: Integrated a global undo handler for the Content Importer. All major actions can now be instantly reversed.
- **New Action "📉 Demote"**: Added a dedicated demote button to move items backward in priority.
- **Persistent .trash & Safety**: Removed items are now moved to a hidden `.trash` directory within your data folder, allowing for safe recovery via Undo. Background maintenance automatically purges files over 30 days old.
- **Add Graduated Words**: Users can now toggle whether "Graduating" a NOW-priority file automatically adds its vocabulary to the global `GraduatedList.txt`.
- **Live Background Polling**: The Content Importer automatically detects updates to analysis results every 4 seconds.

## ⚙️ Settings & System Upgrades
- **Anki / SRS Sentence Exporter**: Export your generated priority list into a CSV format mapped for spaced-repetition software (Anki/Migaku). It intelligently extracts Index, Word, Reading, Sentences, Tier, and Sources.
- **Reorganized Advanced Settings**: Emoji-grouped settings (🌐, 📊, 🧠, 🧮) into intuitive sections for faster scanability.
- **Legacy Cleanup**: Removed final legacy fallback logic for `_order.json`. Library ordering is exclusively handled by `master_manifest.json`.

## Engine & Backend Optimizations
- **Manifest Snapshots**: Ensures undoing complex operations restores the exact previous library state perfectly.
- **Dynamic Tooltips**: Updated Undo button with dynamic tooltips stating the specific action that will be reversed.
- **Hierarchical Path Resolution**: Refactored move/graduate/demote engine to preserve relative subfolder structures.

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
