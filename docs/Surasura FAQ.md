# Surasura FAQ

Welcome to the Surasura FAQ! If you can't find the answer you're looking for here, please check our [Tutorial](Tutorial.md) or open an issue on our GitHub repository.

## Table of Contents
- [Core Concepts](#core-concepts)
- [UI & Features](#ui--features)
- [Workflows & Integrations](#workflows--integrations)
- [Troubleshooting & Support](#troubleshooting--support)

---

### Core Concepts

**What is the difference between Current, Soon and Goal?**
They tell Surasura when you'll watch or read each title, and your list follows. **Current** is your order: Up Next on top, then the **Soon** line; what you'll meet first weighs the most. **Goal**, at its foot, is someday, in no order: its words still count, but less. **Finished** is a record: a source of sentences, never counted. (Surasura 2.x called them NOW, Soon and 6+ months.)

**Are the generated sentences exactly "i+1"?**
As close as your content allows. Surasura scans your whole library and picks the sentences with the fewest other unknown words — counting the words you'll have learned earlier in your journey as known. A word you can read through one you already know — 利用者 when you know 利用 — doesn't count against a sentence either (it still has its own place on your list, at half its score). The first sentence is always the one where you first meet the word, even when it isn't i+1. If you want *only* true i+1 sentences, turn on **Settings › Sentences › Only i+1 sentences**; words without one are then left out.

**Does Surasura go online? What leaves my computer?**
Your content, known words and analysis never leave your computer — everything is worked out on your own machine. Surasura only goes online for:
- a quick check on GitHub for a newer version each time you open it (and, while Connect is on, for a new Anki Miner once a day). Turn it off with **Settings › App › Check for updates**;
- an anonymous usage ping when you open it (app version, system, language, how many times you've opened it, and a random install ID — never your words or files). Turn it off with **Settings › App › Anonymous usage counts**; off, nothing is sent, a completed update included;
- covers and a show's airing status from AniList, and video thumbnails from YouTube, only while **Download covers** is on (Settings › Connections);
- features you start yourself: the Jiten import, YouTube / bilibili.tv transcripts (the downloader fetches its `yt-dlp` helper on first use), Anki Miner's installer, *Install AnkiConnect for me* (from AnkiWeb), subtitles or a speech model for a video without subtitles (after your yes), a YouTube title's video when its cards are made (deleted after), and links you click in the journey;
- **Send report**, only when you press it and then *Send* (Report a problem, the bug at the top right): your saved reports with Surasura's logs and settings, and your last lists if ticked, with your Windows name, PC name, home folder, Anki profile names and emails written as `<you>`, `<pc>`, `<email>`… first. The window shows exactly what goes before anything is sent. It goes to Surasura's own receiver, is kept privately for 90 days, seen only by Surasura's developer, then deleted; to have one deleted sooner, give its #ID on [Discord](https://surasura.dev/app/discord). It never carries the anonymous install ID, and works with the ping off. The receiver keeps no IP address; Cloudflare, which runs it, sees your connection's address as it does for the update check.

Anki sync talks only to the Anki running on your own computer (which may then run its own AnkiWeb sync: **Settings › Anki & mining › More options › Sync Anki after tomorrow's cards change**).

---

### UI & Features

**What is the Extract tool for?**
To turn an Anki deck's sentences, an EPUB, or a long text or subtitle file into parts you can add. It lives under **+ Add › EPUB or Anki deck…**. An EPUB you add directly is already split by chapter.

**Where is the Generate Journey button?**
In 3.0 it is two: **Generate** (top) builds your list, and **Journey ↗** opens it. Generate shows ✓ when nothing in your library, your known words or your settings has changed since your last run.

**Can I see which file an example sentence came from?**
Yes — pick a look in **Settings › Journey › Where a sentence came from**. Each example sentence then gets a small marker showing its source: hover for the file (and, for subtitles, the timestamp), click to copy the full path, and shift-click to open the file at that exact sentence. For a YouTube transcript, clicking opens the video at the moment the line is spoken.

**Does moving a show to Finished mark its words as known?**
No. A finished show stops pushing your list around and stays a source of sentences; only the words you know (from Anki, an import, or marked known) count as known. Checking an episode's stone takes the words only it used off your list.

---

### Workflows & Integrations

**How are people actually studying with Surasura? Do I study inside the app?**
After setup (known words + library), press **Generate**, then open **Journey ↗**. There they:

1. Go word by word through the next episode
2. Read the definition using Yomitan / Migaku
3. Read and understand each i+1 sentence
4. Study the word's card in Anki (**Mine** makes them, or add your favourite sentence yourself)
5. Watch or read that episode, then check its stone

**How can I export my personalized frequency list?**
**Settings › Export › Frequency list** (for Migaku, Yomitan or a text file), after a Generate.

**How can I export my words alongside their context sentences?**
**Settings › Export › Sentence list for Anki**: a CSV of your list with its sentences, ready to map to your Anki or Migaku fields.

**Once I add words to Anki/Migaku, will they keep showing up in Surasura the next day?**
If you mark a word as "Known" or "Ignore" in Surasura, it will be excluded from your future priority lists. However, your daily spaced repetition (SRS) is handled entirely by Anki or Migaku.

**Can I see my own sentences while reading online?**
Yes. **Settings › Export › Sentence dictionary for Yomitan** makes a Yomitan dictionary, "Surasura Corpus", from your library. Import it in Yomitan (**Settings → Dictionaries → Import**), and hovering a word shows up to eight of the best sentences for it from your own shows, books and videos, alongside your other dictionaries. You choose before each export whether to show where each sentence came from; either way, hovering a sentence names its file. Export again whenever you've added content — delete the old copy in Yomitan first, since Yomitan won't import a second dictionary with the same name.

**Can Surasura pick up the words I've learned in Anki by itself?**
Yes. In **Settings › Known words › Decks** (*Anki…*), choose your decks and press **Sync now** — then tick **Keep in sync while Anki is open**. Whenever Anki is open, Surasura adds the words from cards you've studied since last time. New (unstudied) cards are never counted as known, and nothing is ever removed. It needs the AnkiConnect add-on.

**Can my list update itself when I learn words in Anki?**
Yes. Tick **Settings › Known words › Re-generate when new words come in**. When a sync brings in words you now know, Generate runs by itself in the background: it doesn't open the journey, runs at most every 10 minutes, and waits while an import or another Generate is running. New episodes never set it off — you may want to order them first.

**Can I see which words I already have Anki cards for?**
Yes. Once you've chosen decks (**Settings › Known words › Decks**), every word a new card is already waiting for gets a small card icon in the journey, the **Show** menu gains **In Anki** and **Not in Anki**, and each episode says how many of its words are already in Anki. The bottom bar shows how many new cards are waiting (*Anki · N waiting*). Switch the icon off under **Settings › Journey › Label words already in Anki**.

**What does 順 Junban do with the Anki cards that aren't on my list?**
It still gives each one a place: after your list, easiest sentence first, and words you already know last. You can also act on them — under **Also update the cards → Cards not on your list**, tick any of **Tag**, **Flag purple** and **Suspend**. Nothing ticked (the default) changes only their order. Junban never deletes a card, and **Undo the last reorder** takes it back, unsuspending only the cards Junban suspended — never ones you suspended yourself. To treat a word on your list as not on it, click it in the preview.

**Junban asks "Same word as one on your list?" — what is that?**
A card's word can be a word on your list spelled another way: 引き伸ばす on your card, 引き延ばす on your list; 豹変する on the card, 豹変 on your list. Junban won't guess — it shows each one with its reading and the sentence from your card. Tick the ones that are the same word and they move up with your list's words; the rest stay where their sentence puts them. Your answers are kept when you press **Reorder**, so a word is only asked about once, and **earlier answers** lets you change one.

**What does "i+1 first" do in the Junban window?**
It makes sure a card on your list is readable when it comes up. If the sentence on the card has another word from your list that you'd only learn later, Junban brings that word's card right before it — as long as that card is readable there itself — so you learn it first, then the card. If it can't (the word has no card, or its card needs something later too), the card waits with the cards that have more new words. A name counts like any other word (turn on **Settings › Language & Parsing › Ignore names** and names never hold a card back); words too rare to be on your list never do. It never chains: a card brought forward never brings anything else. Off until you tick it.

**Why does Junban say my list is out of date?**
Your library, your known words or a setting has changed since your last Generate, so the order would follow an old list. **Preview order** turns into **Generate & preview**: press it, and Surasura brings your list up to date in the background (the journey doesn't open), then shows the new order. **Reorder** is available again once it has.

**Why does Junban put phrases like ことが出来る with my list's words?**
Your list counts words one at a time, so a phrase can never be on it — yet phrases are often half of a mined backlog. Junban finds each one whole in your library, and one you meet as often as your list's own words is placed with them, in the episode you first meet it. Untick **Phrases** in the Junban window to put them with the rest. (Japanese only.)

**What do the percentages in a card's パターン mean — and why is the label sometimes amber?**
A percentage is the share of *all* the word's uses: `を〜 24%` on 利用する means that 24 of every 100 times the word is used, を comes right before it. (On a Chinese card, the measure-word line is the share of the times the word is counted: `本〜 94%` on 书.) Pairings show only when they turn up in at least three separate places in the data — different episodes, books or articles, or unrelated sentences — so one show's catchphrase doesn't become the word's pattern. When the word was seen fewer than 50 times in the data the lines came from — your library, or Surasura's shared set — Anki Backfill marks the lines "thin": they are still real uses, just few of them, so read them as a hint. A card template can show that mark (an amber パターン label, for instance); a template that doesn't know it simply ignores it, and no text is ever added to your card for it.

**Is there a way to bulk-download YouTube transcripts to feed into Surasura?**
Yes. Press **+ Add › YouTube or bilibili…**, then paste any number of links — single videos, pasted lists, or whole playlists. Their transcripts come into your library and wait in **New arrivals**; a playlist comes in whole, in its own order.

For a video without subtitles, **Needs you** offers **Find them with hato** (with hato installed: jimaku.cc, with your key); otherwise grab them from a subtitle site and add them like any other file.

**Can I use Bilibili?**
Yes — **bilibili.tv** links (episodes, whole seasons, uploads) work in the same box, with no account. Shows there are licensed per country, so an episode that isn't available in your region says so instead of downloading. **bilibili.com** links aren't supported: that site only gives subtitles to signed-in users. Look for the same show on bilibili.tv instead.

---

### Troubleshooting & Support

**Why am I seeing Japanese words in my Chinese frequency results?**
First check the language: **Settings › Content › Language** should be Chinese. Each language has its own library, so also check that no Japanese files ended up in your Chinese library — look through Current, New arrivals and Finished with Chinese selected.

**My Chinese content mixes Simplified and Traditional. Why does 学习 show up separately from 學習?**
Because they're written differently, Surasura counts them as two words unless you tell it otherwise. Go to **Settings › Language & Parsing › Script** (shown when Chinese is selected) and pick **Simplified** (简体) or **Traditional** (繁體). Everything — content, known words, lists — is then read in that one script, so each word counts once and a known word matches in either script. Your files are never changed; pick **As written** to go back. Simplified → Traditional can occasionally choose the wrong character in a rare context, and it uses standard forms (爲, 裏) rather than Taiwan's (為, 裡).

**What file formats does Surasura currently support?**
- Text and subtitles: `.txt`, `.md`, `.srt`, `.ass`, `.ssa`.
- A video with its subtitle beside it, or with a Japanese subtitle track inside it (MKV, MP4).
- EPUBs, split by chapter. 🎧 Audiobooks: an `.m4b`, or a folder of chapter MP3s, joined to its book.
- An Anki deck's sentences: **+ Add › EPUB or Anki deck…**.

**I found a bug or have a feature idea. Where do I report it?**
We'd love to hear it! In the app: **Report a problem** (the bug icon, top right). Or open an issue on our [GitHub Issues page](https://github.com/SonicSandbox/surasura/issues), or tell us on [Discord](https://surasura.dev/app/discord).