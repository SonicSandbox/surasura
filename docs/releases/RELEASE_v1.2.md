# Surasura v1.2 - Release Notes

## 🚀 Massive Update

Significant milestone for Surasura: focusing on integration, customization, and quality of life improvements.

### ✨ New Features

#### 1. Order Your Immersion Content
Take control of your learning sequence. In the **Content Manager**, you can now drag and drop files and folders to set the exact order you plan to study them. Surasura will respect this order when generating your Vocabulary Journey.

#### 2. Import Immersion Decks from Anki
As an alternative to subtitles / VN text, You can now import your Anki `.apkg` files directly. Extract sentences from any field and treat them as source text for analysis. 
> [!TIP]
> This isn't to study your existing words, but to use as source text for analysis.

#### 3. Upload Personal Frequency Lists
Compare your immersion data with global frequency lists. You can now upload any Yomitan-style CSV frequency list in the Advanced Settings.
*Credit to [mattias](https://github.com/mattias) for inspiration, code, and frequency data structures.*

#### 4. Jiten Known-Words Sync
Synchronize your "Known Words" directly from Jiten.moe. Enter your API key in the new Jiten Sync tool to bring your progress over instantly.
*Special thanks to [mattias](https://github.com/mattias) for the Jiten integration support.*

#### 5. Major Parsing Improvements
The tokenizer has been refined to better handle complex Japanese structures, ensuring more accurate lemma extraction and fewer "false negatives" in your known words list.

#### 6. Quality of Life (QoL) Improvements
- **Onboarding Tutorial**: A new guide to help new users understand the "Surasura Way" of immersion-based learning.
- **Improved UI**: Streamlined buttons, better tooltips, and a more responsive dashboard.
- **Upload Entire Files**: Easier bulk-importing of content into your library.
- **Journey Word Count**: See exactly how many words you're learning across your entire content library.

### 🐞 Bug Fixes
- **Min Frequency Corrected**: Fixed an issue where the minimum frequency filter wasn't correctly applied in certain edge cases.
- **Stability Improvements**: Various fixes for file handling and memory usage during large batch processing.

---
*Stay consistent, and enjoy your スラスラ journey!*
