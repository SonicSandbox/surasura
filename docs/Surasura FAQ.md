# Surasura FAQ

Welcome to the Surasura FAQ! If you can't find the answer you're looking for here, please check our [Tutorial](Tutorial.md) or open an issue on our GitHub repository.

## Table of Contents
- [Core Concepts](#core-concepts)
- [UI & Features](#ui--features)
- [Workflows & Integrations](#workflows--integrations)
- [Troubleshooting & Support](#troubleshooting--support)

---

### Core Concepts

**What is the actual difference between the "NOW," "Soon," and "6+ months" timelines?**
These timelines affect sorting and weighting. NOW content appears first, receives a higher priority icon, and ranks higher when exporting your frequency list.

**Are the generated sentences exactly "i+1"?**
As close as your content allows. Surasura scans your whole library and picks the sentences with the fewest other unknown words — counting the words you'll have learned earlier in your journey as known. The first sentence is always the one where you first meet the word, even when it isn't i+1. If you want *only* true i+1 sentences, turn on **Settings → 🧠 Sentences & Logic → Only include i+1 sentences**; words without one are then left out.

**Does Surasura go online? What leaves my computer?**
Your content, known words and analysis never leave your computer — everything is worked out on your own machine. Surasura only goes online for:
- a quick check on GitHub for a newer version, each time you open it;
- an anonymous usage ping when you open it (app version, system, language, how many times you've opened it, and a random install ID — never your words or files). Turn it off with **Settings → 🧮 Data & System → Enable Anonymous Telemetry**; a completed update still sends one "updated" notice, with a throwaway ID instead of yours;
- features you start yourself: the Jiten import, YouTube / bilibili.tv transcripts (the downloader fetches its `yt-dlp` helper on first use), and links you click in the report.

Anki sync talks only to the Anki running on your own computer.

---

### UI & Features

**What is the exact purpose of the "Extract / Splice" tool?**
To split large files, like massive EPUBs or Anki decks, into manageable chapters. This saves you from having to use third-party conversion tools. It lives inside the **Content Manager**, under **📖 Extract (EPUB / Anki)**.

**There used to be two buttons — "Generate Journey" and "View Vocab Journey". Where did they go?**
They're now a single **Generate Journey** button. If anything has changed since your last run it re-analyzes; if nothing has, it simply reopens your existing report instantly. Changing only the theme or Zen limit re-renders the report without re-analyzing. The button shows which it will be: a thin blue border means something has changed since your last Generate, and a small ✓ on its right edge means your journey is up to date.

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

**Can I see my own sentences while reading online?**
Yes. **Settings → 🧮 Data & System → Export Sentence Dictionary** makes a Yomitan dictionary, "Surasura Corpus", from your library. Import it in Yomitan (**Settings → Dictionaries → Import**), and hovering a word shows up to eight of the best sentences for it from your own shows, books and videos, alongside your other dictionaries. You choose before each export whether to show where each sentence came from; either way, hovering a sentence names its file. Export again whenever you've added content — delete the old copy in Yomitan first, since Yomitan won't import a second dictionary with the same name.

**Can Surasura pick up the words I've learned in Anki by itself?**
Yes. Press **Anki**, choose your decks and press **Sync now** — then tick **Sync automatically when Anki is running**. Whenever Anki is open, Surasura adds the words from cards you've studied since last time. New (unstudied) cards are never counted as known, and nothing is ever removed. It needs the AnkiConnect add-on.

**Can my list update itself when I learn words in Anki?**
Yes. In the **Anki** window, tick **Generate when Anki adds known words**. When a sync brings in words you now know, Generate runs by itself in the background: it doesn't open the report, runs at most every 10 minutes, and waits while the Content Manager, an import or another Generate is running. New episodes never set it off — you may want to order them first.

**Can I see which words I already have Anki cards for?**
Yes. Once you've chosen decks in the **Anki** window, every word a new card is already waiting for gets a small card icon in the report, the **Show** menu gains **In Anki** and **Not in Anki**, and each episode says how many of its words are already in Anki. The Anki window shows how many new cards are waiting. Switch the icon off under **Settings → 📊 Experience & UI → Label backlogged Anki words**.

**What does 順 Junban do with the Anki cards that aren't on my list?**
It still gives each one a place: after your list, easiest sentence first, and words you already know last. You can also act on them — under **Also update the cards → Cards not on your list**, tick any of **Tag**, **Flag purple** and **Suspend**. Nothing ticked (the default) changes only their order. Junban never deletes a card, and **Restore previous order** undoes all of it, unsuspending only the cards Junban suspended — never ones you suspended yourself. To treat a word on your list as not on it, click it in the preview.

**Junban asks "Same word as one on your list?" — what is that?**
A card's word can be a word on your list spelled another way: 引き伸ばす on your card, 引き延ばす on your list; 豹変する on the card, 豹変 on your list. Junban won't guess — it shows each one with its reading and the sentence from your card. Tick the ones that are the same word and they move up with your list's words; the rest stay where their sentence puts them. Your answers are kept when you press **Reorder**, so a word is only asked about once, and **earlier answers** lets you change one.

**Why does Junban say my list is out of date?**
Your library, your known words or a setting has changed since your last Generate, so the order would follow an old list. **Preview order** turns into **Generate & preview**: press it, and Surasura brings your list up to date in the background (the report doesn't open), then shows the new order. **Reorder** is available again once it has.

**Why does Junban put phrases like ことが出来る with my list's words?**
Your list counts words one at a time, so a phrase can never be on it — yet phrases are often half of a mined backlog. Junban finds each one whole in your library, and one you meet as often as your list's own words is placed with them, in the episode you first meet it. Untick **Phrases** in the Junban window to put them with the rest. (Japanese only.)

**Is there a way to bulk-download YouTube transcripts to feed into Surasura?**
Yes. Open the **Content Manager** and press **▶ YouTube**, then paste any number of links — single videos, pasted lists, or whole playlists. Clean `.txt` transcripts land in your **Processed** folder and in the tab you're on. (This is an optional feature; if you don't see the button, enable it under **Settings → Language & Parsing**.)

For anime subtitles specifically, Surasura doesn't fetch those — grab them from a subtitle site (there's an **Anime subtitles ↗** link in the Content Manager) and add them like any other file.

**Can I use Bilibili?**
Yes — **bilibili.tv** links (episodes, whole seasons, uploads) work in the same box, with no account. Shows there are licensed per country, so an episode that isn't available in your region says so instead of downloading. **bilibili.com** links aren't supported: that site only gives subtitles to signed-in users. Look for the same show on bilibili.tv instead.

---

### Troubleshooting & Support

**Why am I seeing Japanese words in my Chinese frequency results?**
First check the language: the flag at the bottom of the dashboard (or **Settings → 🌐 Language & Parsing**) should be Chinese. Each language has its own library, so also check that no Japanese files ended up in your Chinese library — open the **Content Manager** with Chinese selected and look through the tabs.

**My Chinese content mixes Simplified and Traditional. Why does 学习 show up separately from 學習?**
Because they're written differently, Surasura counts them as two words unless you tell it otherwise. Go to **Settings → 🌐 Language & Parsing → Script** (shown when Chinese is selected) and pick **Simplified (简体)** or **Traditional (繁體)**. Everything — content, known words, lists — is then read in that one script, so each word counts once and a known word matches in either script. Your files are never changed; pick **As-is** to go back. Simplified → Traditional can occasionally choose the wrong character in a rare context, and it uses standard forms (爲, 裏) rather than Taiwan's (為, 裡).

**What file formats does Surasura currently support?**
Analysis reads `.txt`, `.md`, `.srt` and `.ass`. You can also drop in a **`.zip`** — Surasura unpacks the supported files inside it and adds them as one ordered group. EPUBs and Anki decks go through the built-in **📖 Extract (EPUB / Anki)** tool, which converts and splits them into text first.

**I found a bug or have a feature idea. Where do I report it?**
We'd love to hear it! Please open an issue directly on our [GitHub Issues page](https://github.com/SonicSandbox/surasura/issues).