# Surasura - Readability Analyzer v1.4 Release Notes

## 🎓 New: Content Graduation System
A comprehensive system for managing your learning progress directly from the Content Manager.

- **One-Click Graduation**: Use the **🏆 Graduate** button to move content through priority tiers and eventually into your known vocabulary.
- **Performance Overhaul**:
    - **Infinite Scroll**: Instant load times for massive libraries using true infinite scrolling.
    - **Smart Memory Management**: Improved system resource usage when switching views.
    - **Configurable Chunking**: Added control over loading speeds via `settings.json`.
- **Bulk Folder Graduation**: Recursively scan and extract words from entire folders.

## 🎨 GUI & UX Improvements
- **Clarified Priority Terminology**: Tiers renamed to **NOW content**, **Soon**, and **6+ months**.
- **Dynamic Order Hints**: Smart instructions that update based on the selected tier.
- **Refined Layout**: Iconic action buttons, compact icons, and a new shortcut to your Learned Words list.
- **Integrated Help**: Direct link to the **Tutorial** in the footer and enhanced **Ignore Words** management.
- **Visual Improvements**: Consistent icons and tooltips throughout the interface.

## ⚙️ Backend & Analysis Enhancements
- **Automatic Vocabulary Integration**: `GraduatedList.txt` is now automatically included in your known words.
- **Detailed Word Tracking**: New `word_stats.json` accurately tracks unique words per file.
- **Path Robustness**: Improved reliability across different installation environments.

## 🛠️ Developer & Testing Upgrades
- **Safe Testing Mode**: Added `SURASURA_TEST_ROOT` support for isolated testing.
- **Expanded Test Suite**: Comprehensive coverage of the graduation flow and file management.

> [!IMPORTANT]
> **Zen Mode** has been temporarily removed in this build as it is currently undergoing a complete overhaul. It will return better than ever in a future update!

---
*Happy Learning!*
