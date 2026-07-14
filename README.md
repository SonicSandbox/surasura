# <img src="docs/assets/images/icon_512.png" width="40" height="40"> Surasura (スラスラ) - The Immersion Architect
![License](https://img.shields.io/badge/license-MIT-blue.svg) ![Python](https://img.shields.io/badge/python-3.9+-blue.svg)

*For Intermediate-Advanced learners. Supports Japanese & Chinese...* 

![Results](docs/assets/images/img_readability_results.PNG)

## Your map to seamless immersion

> **The only frequency list that matters is the one based on YOUR watch / read list.**

A tool that generates THAT list, and gives you the episode-by-episode (or chapter) *highest-leverage* order order based on:

- your known vocabulary
- your immersion content 
- your word frequency

After analyzing, it will generate a study plan with curated examples. 
Optimizes the order you learn words. Easy sentence mining for Anki or Migaku.

## 🎯 Why? - The Diminishing Returns of Vocab

> **The only frequency list that matters is the one based on YOUR watch / read list.**

Otherwise you're wasting time learning words you'll just forget.

Useful if you:

- Hit 4500+ words

- Have limited immersion time

- Are tired of adding words you'll never see

- Want to see mulitple examples and pick the best one

- Enjoy seeing your progress %

- Like using physical books / YouTube


Use Surasura to know every word you learn is immediately relevant to your content goals.

### 🏆 Features

- 🗄️ **Migaku, Anki & Jiten Sync**: Import known words from Migaku, Anki Decks or Jiten.moe.

- 📖 **EPUB & Anki Extractor**: Extract and split text from Japanese EPUBs or Anki decks.

- 🎬 **YouTube Transcripts**: Pull clean, analysis-ready transcripts from YouTube videos and playlists straight into your library.

- 🔤 **Advanced Analyzer**: Tokenize text using Fugashi/Unidic-lite and calculate comprehension scores.

- 🧮 **Progress Tracking**: Track your progress % before AND after watching/reading.

- 🧘 **Zen Mode**: A distraction-free mode for focused learning.

- 📊 **Vocab List Dashboard**: Generates an interactive HTML dashboard to learn and add words to Migaku or Anki.

- 🎨 **Enhanced Themes**: Multiple curated themes (Zen Focus, Midnight Vibrant, etc.).

- 🇨🇳 **Multi-Language Support**: Now also supports Chinese (Simplified & Traditional) via Jieba segmentation.

- 📚 **Physical Book Support**: Add the EPUB, study, and immerse without ever needing to look up a word again.

- 🚀 **Custom Freq List**: Generate your own frequency list from your immersion content. Supports **Migaku** (JSON), **Yomitan** (Zip with readings), and plain text formats.

- 🎚️ **Commonness Slider**: Dial in how deep to go — from only the most common words to everything but one-offs — with a live word-count and coverage preview.


### Current Limitations
- Only executable for Windows (macOS/Linux can run from source)
- Occasional Wacky Parsing

## 📥 Latest Release Zip

Download the latest release zip file from the [Releases page](https://github.com/SonicSandbox/surasura/releases).

> **Quick Start:** Download -> Extract -> Run `Surasura.exe`

## Screenshots
> Dashboard with Migaku extension

![Results](docs/assets/images/img_readability_results_Migaku_extension.PNG)


| Dashboard Overview | Zen Mode |
| :---: | :---: |
| ![Dashboard](docs/assets/images/img_readability_gui.PNG) | ![Zen Mode](docs/assets/images/img_readability_results_zen.PNG) |

## 🚀 Get Started

1. Run `Surasura.exe` to launch the dashboard.

2. **Import Known Vocabulary** to sync your known words from Migaku, Anki, or Jiten.

3. **Import Content** — open the Content Manager and add your files:


- **Extract** an EPUB / Anki deck
- Pull a **YouTube** transcript

Drag them into your immersion order across the **NOW · Soon · 6+ months** tabs:

- **NOW**: what you're consuming today (next ~2 weeks).

- **Soon**: your medium-term list (within 6 months).

- **6+ months**: aspirations / "someday" content.

   *(New library? Tap **Test with samples** to try it instantly.)*

4. **Generate Journey** — build your personalized word list and open the interactive report.


## 🛠️ Running from Source
If you prefer to run Surasura from source rather than using the pre-built executable:

### 1. Requirements
- Python 3.9 or higher.
- (Windows only) Ensure `tkinter` is installed (usually bundled with Python).

### 2. Setup
1. Clone the repository: `git clone https://github.com/SonicSandbox/surasura.git`
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### 3. Launching
Run the master entry point:
```bash
python app_entry.py
```
This dispatcher ensures the correct environment is set up and launches the main dashboard.

## 🛠️ Building the Application
To create your own standalone executable:

1. Ensure you have the dev dependencies installed:
   ```bash
   pip install pyinstaller
   ```
2. Run the build script:
   ```bash
   python package_app.py
   ```
This cleans previous builds, runs PyInstaller with the correct configuration, and creates a ready-to-use package in `dist/Surasura_v<version>`.

## 📂 Project Structure
- `app/`: Core application scripts and GUI modules.
- `app_entry.py`: Main entry point and dispatcher.
- `package_app.py`: Build and packaging script.
- `scripts/`: Shared utilities and data conversion scripts.
- `templates/`: HTML templates for visualization.
- `data/`: Input text files (Place your TXT/SRT files here).
- `User Files/`: Configuration and frequency lists.
- `results/`: Generated CSVs and HTML reports.


## ❓ Q&A / FAQ

If you have any questions or are running into issues, please check out the [Q&A / FAQ Guide](https://github.com/SonicSandbox/surasura/blob/main/docs/Surasura%20FAQ.md).

## 🤝 Support & Issues

Encountered a bug or have a feature request? Please search the [Issues](https://github.com/SonicSandbox/surasura/issues) page to see if it's already being worked on. If not, feel free to open a new issue.

## 💡 Motivation
*I was tired of learning words I never see, and I also like reading physical books. Otherwise, mining from physical books is a pain.* Surasura solves that friction.

## 📜License

Distributed under the MIT License. See `LICENSE` for more information.
