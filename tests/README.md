# Surasura Test Suite

This directory contains the comprehensive test suite for the **Surasura Readability Analyzer**.

## 🚀 How to Run
To run all tests with a single command, execute the following from the project root:

```bash
python run_tests.py
```
*(This script automatically discovers and runs all tests in this folder)*

---

## 📂 Test File Descriptions

### Core Functionality
- **`test_analyzer_snapshot.py`**
  - **Purpose**: Ensures the core analysis logic ("the brain") produces consistent results.
  - **How**: Runs a full analysis purely on sample data and compares the output CSV against a verified "Golden Master" file. If the analysis logic changes (even slightly), this test will fail to alert you.

- **`test_file_integrity.py`**
  - **Purpose**: Checks that the application's file structure is healthy.
  - **How**: Verifies that critical folders (`data/`, `samples/`, `User Files/`) exist for both Japanese and Chinese.

### Integrations
- **`test_migaku_importer.py`**
  - **Purpose**: Verifies that Migaku database exports (`.db` files) are correctly converted to JSON.
  - **How**: Takes a real Migaku DB file from `Test Resources/` and checks if the output JSON contains the expected word counts and fields.

- **`test_anki_loader.py`**
  - **Purpose**: Ensures Anki decks (`.apkg`) can be opened and read.
  - **How**: Extracts a test deck and specifically verifies that we can pull clean text from the card fields (like "Expression"), stripping out HTML and audio tags.

- **`test_jiten_mock.py`**
  - **Purpose**: Tests the Jiten API integration without needing a real API key or internet connection.
  - **How**: Uses "mocks" to simulate a server response and checks if our code correctly parses that response into our format.

### Output
- **`test_html_report.py`**
  - **Purpose**: Verifies the final report generation.
  - **How**: Simulates a finished analysis run and checks if the static HTML generator successfully creates the report file with data injected.

### Unit Tests (Smaller Components)
- **`test_tokenizer_edge_cases.py`**
  - **Purpose**: Stress-tests the language parsers (Japanese & Chinese).
  - **How**: Feeds tricky inputs like empty strings, mixed English/Japanese, emojis, and punctuation-only lines to ensure the app doesn't crash.

- **`test_importer.py`**
  - **Purpose**: Tests the raw file readers.
  - **How**: Checks if text is correctly extracted from `.txt` and `.srt` files (including subtitle timestamp removal).

- **`test_japanese_regression.py`**
  - **Purpose**: Basic sanity checks for Japanese processing.
  - **How**: confirms Kanji detection and basic tokenization rules work as expected.

- **`test_chinese_epub.py`**
  - **Purpose**: Tests Chinese-specific file handling.
  - **How**: Verifies extraction and processing of Chinese EPUB files.

---

## 🛠️ Adding New Tests
1.  Create a new file starting with `test_` (e.g., `test_my_feature.py`).
2.  Add functions starting with `test_`.
3.  Run `python run_tests.py` — it will automatically pick up your new file!
