# Surasura (スラスラ)🇯 - Readability Analyzer
![License](https://img.shields.io/badge/license-MIT-blue.svg) ![Python](https://img.shields.io/badge/python-3.9+-blue.svg)

*For Intermediate-Advanced learners.* 

![Results](docs/assets/images/img_readability_results.PNG)

A tool to analyze (Japanese) text based on:
- known vocabulary
- your immersion content 
- word frequency

After analyzing, it will generate a study plan with multiple examples. Easy sentence mining for Migaku or Yomichan.

## 🎯 Why? - The Diminishing Returns of Vocab

**The only frequency list that matters is the one based on YOUR watch / read list.**

Otherwise you're wasting time learning words you'll just forget.

This is a tool to help you:

- Eliminate lookups with *immersive Pre-Study*

- Say no to 'some day' words - *Every word is on your watch-list*

- Acquire fast with the only *words you'll need over and over again*

- Sentence-mine easily with *multiple examples for each word*

- Bridge the gap between *digital mining and analog reading*


Use Surasura to know every word you learn is immediately relevant to your goals.

## ⚡ Features

- 🗄️ **Migaku Integration**: Import your known words directly from Migaku.

- 📖 **EPUB Extractor**: Extract and split text from Japanese EPUBs.

- 🔤 **Advanced Analyzer**: Tokenize text using Fugashi/Unidic-lite and calculate comprehension scores.

- 📊 **Vocab List Dashboard**: Generates an interactive HTML dashboard to learn and add words to Migaku or Anki.

- 🎨 **Themes**: Multiple themes to customize your learning experience.

- 🧘 **Zen Mode**: A distraction-free mode for focused learning.

- ⌨️ **Hotkey Navigation**: Navigate between word cards with hotkeys (Left/Right).

- 📚 **Physical Book Support**: Add the EPUB, study, and immerse without ever needing to look up a word again.

## 📥 Latest Release Zip

Download the latest release zip file from the [Releases page](https://github.com/SonicSandbox/readability-analyzer/releases).

> **Quick Start:** Download -> Extract -> Run Exe

## Install packages yourself
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. (Windows only) Ensure `tkinterdnd2` is installed for GUI features.

## Screenshots

| Dashboard Overview | Zen Mode |
| :---: | :---: |
| ![Dashboard](docs/assets/images/img_readability_gui.PNG) | ![Zen Mode](docs/assets/images/img_readability_results_zen.PNG) |


## 🚀 Usage
1. Launch the master dashboard: Download and run the Exe file or:
   ```bash
   python app/main.py
   ```
2. Use the **Migaku Word List Importer** to set up your known words.

3. Place your text files in the corresponding folders:

- data/HighPriority: Content you are consuming today.

- data/LowPriority: Content for next week or next month.

- data/GoalContent: Aspirations or "someday" books.

4. Click **Run Analysis** to generate your reports.

5. View results via **View Vocab Journey**.

## Directory Structure
- `app/`: Core application scripts.
- `scripts/`: Shared utilities and converters.
- `templates/`: HTML templates for visualization.
- `data/`: Input text files (TXT, SRT).
- `User Files/`: Configuration and frequency lists.
- `results/`: Generated CSVs and HTML reports.

## 🤝 Support & Issues

Encountered a bug or have a feature request? Please search the [Issues](https://github.com/SonicSandbox/readability-analyzer/issues) page to see if it's already being worked on. If not, feel free to open a new issue.

## 💡 Motivation
*I was tired of learning words I never see, and I also like reading physical books. Otherwise, mining from physical books is a pain.* Surasura solves that friction.

## 📜License

Distributed under the MIT License. See `LICENSE` for more information.