# Surasura FAQ

Welcome to the Surasura FAQ! If you can't find the answer you're looking for here, please check our [Tutorial](Tutorial.md) or open an issue on our GitHub repository.

## Table of Contents
- [Core Concepts](#core-concepts)
- [UI & Features](#ui--features)
- [Workflows & Integrations](#workflows--integrations)
- [Troubleshooting & Support](#troubleshooting--support)

---

### Core Concepts

**What is the actual difference between the "Now," "Soon," and "6 Months" timelines?**
These timelines affect sorting and weighting. "Now" content appears first, receives a higher priority icon, and ranks higher when exporting your frequency list.

**Are the generated sentences exactly "i+1"?**
Yes. It will find the best i+1 sentences in your content based on your settings. It scans your entire library and identifies the best options.

---

### UI & Features

**What is the exact purpose of the "Extract / Splice" tool?**
To split large files, like massive EPUBs or Anki decks, into manageable chapters. This saves you from having to use third-party conversion tools. It lives inside the **Content Manager**, under **📖 Extract (EPUB / Anki)**.

**There used to be two buttons — "Generate Journey" and "View Vocab Journey". Where did they go?**
They're now a single **Generate Journey** button. If anything has changed since your last run it re-analyzes; if nothing has, it simply reopens your existing report instantly. Changing only the theme or Zen limit re-renders the report without re-analyzing.

**Can I see which file an example sentence came from?**
Yes — turn on **Settings → Experience & UI → "Sentence source"**. Each example sentence then gets a small marker showing its source: hover for the file (and, for subtitles, the timestamp), click to copy the full path, and shift-click to open the file at that exact sentence. For a YouTube transcript, clicking opens the video at the moment the line is spoken.

**Does graduating content mark *all* words in that media as "Known"?**
No, it only marks the specific words listed in your analysis results.

---

### Workflows & Integrations

**How are people actually studying with Surasura? Do I study inside the app?**
After they've added known words and content -> Run analysis.

Then in the Vocab Journey Web Page they:

1. Go word by word for each file
2. Read the definition using Yomitan / Migaku 
3. Read and understand each i+1 sentence
4. Add their favorite sentence to SRS
5. Repeat for all words in the file
6. Immerse in that content for max gains

**How can I export my personalized frequency list?**
1. Upload all content + Known Words
2. Run Analysis
3. Export Frequency List in Advanced Settings (Bottom right Icon)

**How can I export my words alongside their context sentences?**
When exporting, Surasura includes the context sentence. You can format this export (like a CSV) to map directly to the sentence fields in Migaku or Anki.

**Once I add words to Anki/Migaku, will they keep showing up in Surasura the next day?**
If you mark a word as "Known", "Ignore" or graduate it in Surasura, it will be excluded from your future priority lists. However, your daily spaced repetition (SRS) is handled entirely by Anki or Migaku.

Note: A single Surasura could guide you for months without needing to re-generate.

**Can Surasura pick up the words I've learned in Anki by itself?**
Yes. Press **Anki**, choose your decks and press **Sync now** — then tick **Sync automatically when Anki is running**. Whenever Anki is open, Surasura adds the words from cards you've studied since last time. New (unstudied) cards are never counted as known, and nothing is ever removed. It needs the AnkiConnect add-on.

**Is there a way to bulk-download YouTube transcripts to feed into Surasura?**
Yes. Open the **Content Manager** and press **▶ YouTube**, then paste any number of links — single videos, pasted lists, or whole playlists. Clean `.txt` transcripts land in your **Processed** folder and in the tab you're on. (This is an optional feature; if you don't see the button, enable it under **Settings → Language & Parsing**.)

For anime subtitles specifically, Surasura doesn't fetch those — grab them from a subtitle site (there's an **Anime subtitles ↗** link in the Content Manager) and add them like any other file.

**Can I use Bilibili?**
Yes — **bilibili.tv** links (episodes, whole seasons, uploads) work in the same box, with no account. Shows there are licensed per country, so an episode that isn't available in your region says so instead of downloading. **bilibili.com** links aren't supported: that site only gives subtitles to signed-in users. Look for the same show on bilibili.tv instead.

---

### Troubleshooting & Support

**Why am I seeing Japanese words in my Chinese frequency results?**
Check your Advanced Settings. Ensure that "Chinese" is checked as your target language and that "Japanese" is completely unchecked.

**My Chinese content mixes Simplified and Traditional. Why does 学习 show up separately from 學習?**
Because they're written differently, Surasura counts them as two words unless you tell it otherwise. Go to **Settings → 🌐 Language & Parsing → Script** (shown when Chinese is selected) and pick **Simplified (简体)** or **Traditional (繁體)**. Everything — content, known words, lists — is then read in that one script, so each word counts once and a known word matches in either script. Your files are never changed; pick **As-is** to go back. Simplified → Traditional can occasionally choose the wrong character in a rare context, and it uses standard forms (爲, 裏) rather than Taiwan's (為, 裡).

**What file formats does Surasura currently support?**
Analysis reads `.txt`, `.md`, `.srt` and `.ass`. You can also drop in a **`.zip`** — Surasura unpacks the supported files inside it and adds them as one ordered group. EPUBs and Anki decks go through the built-in **📖 Extract (EPUB / Anki)** tool, which converts and splits them into text first.

**I found a bug or have a feature idea. Where do I report it?**
We'd love to hear it! Please open an issue directly on our [GitHub Issues page](https://github.com/SonicSandbox/surasura/issues).