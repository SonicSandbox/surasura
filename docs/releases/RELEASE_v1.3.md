# Surasura - Readability Analyzer v1.3 Release Notes

## Major Updates
- **New Database Importer**: Seamlessly import your vocab directly from Anki and Migaku! No more manual CSV wrangling.
- **Full Chinese Support**: Now fully supports Chinese (Simplified & Traditional) via Jieba segmentation.
- **Telemetry**: Added anonymous usage statistics to help us improve the app (Optional/Opt-out available).
- **Aesthetics**: Complete UI overhaul with a modern, dark-themed design.
- **Performance**: Significant improvements in analysis speed and responsiveness.
- **Smart Sentence Selection**: The analyzer now prioritizes sentences with ideal length (neither too short nor too long) for better context.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.
3. (Optional) If you have a `.env` file for telemetry, place it in the same folder (for dev builds) or it will be built-in for release builds.

## Breaking Changes
- The database format has been updated to support multiple languages. Old `user_config.json` files may be reset.
- `frequency_list_global50k.csv` is now the default frequency list.

## Known Issues
- None reported.

---
*Happy Learning!*
