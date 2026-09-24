# Setup and Usage Tutorial

## What are we doing?
-> Importing your **existing knowledge**

-> Adding your **personal immersion library**

-> Creating your **personal frequency list**

-> Learning your highest-leverage words, episode by episode *(chapter by chapter)*

> Surasura shows you the exact words worth your time. In the perfect order.

## 1. Import Known Vocabulary
First, import your existing knowledge. The analyzer uses this to calculate your known % and skip words you already know.

*   **Migaku / Jiten / Anki** — pull known words straight from your decks or exports.
*   **Anki, live** — with Anki open (and the AnkiConnect add-on), press **Anki → Sync now**. Only cards you've studied count, and it can keep itself up to date automatically. Tick **Generate when Anki adds known words** there too, and your list catches up on its own in the background.
*   **Edit Ignore List** — hand-exclude words you never want suggested.

![Import Known Vocabulary Interface](assets/images/tutorial/import_vocab.png)

## 2. Import Content
Press **Import Content** to open the Content Manager — one place to add and organize everything.

*   **📁 Add files & Folders** — drop in ready `.txt` / `.md` / `.srt` / `.ass`
*   **📖 Extract (EPUB / Anki)** — turn an EPUB or Anki deck into clean, split text.
*   **▶ YouTube** *(optional)* — pull transcripts straight from YouTube.


![Content Manager: Add Content and the tier tabs](assets/images/tutorial/content_manager.png)

## 3. Order Your Library
Your library is split into three tabs. 

Added content lands in the tab you're on. **Order matters** — drag files (and use ▲▼) into the order you'll actually immerse.

*   **NOW**: what you're consuming *today* and over the next ~2 weeks. *(Order matters a lot.)*
*   **Soon**: your medium-term list (within 6 months). *(Order matters a little.)*
*   **6+ months**: someday / aspirational content. *(Order doesn't matter.)*

> Include as much as you like — the analysis handles it comfortably, as long as the timeframes reflect your real plans.

![Library tabs with drag-to-reorder](assets/images/tutorial/library_tabs.png)

## 4. Choose How to Generate
Two modes drive the word list:

1.  **By Commonness** *(RECOMMENDED)* — a slider from **Core** (only the most common words) to **Native** (everything but one-offs). Slide to include rarer words; a live preview shows the word count and coverage % you'd reach.

2.  **Target % Coverage** — include enough words to hit a coverage % of your content. *(Still ordered by leverage.)*

![The By Commonness slider with live preview](assets/images/tutorial/commonness_slider.png)

## 5. Generate Your Journey
Press **Generate Journey** to build your list and see the report.

If no changes, it reuses the last analysis, so theme tweaks are instant.

The button tells you which it will be: a thin blue border means something has changed since your last Generate (your library, your known words or a setting); a small ✓ on its right edge means your journey is up to date.

![Generate Journey](assets/images/tutorial/generate_journey.png)

## 6. Understanding the Output
The report orders words by real payoff across *your* library:

*   **Order to Learn** — suggested order, by importance.
*   **Frequency** — how often the word appears in your content.
*   **Star (Priority)** ✦ — high-leverage words you'll see throughout all of your content.
*   **Lopsided** ⚖ — words you'll see a lot in the next 2 weeks, but rarely after.
*   **Reading word** 文 — a word you'll meet in text but will rarely *hear*, so it's worth a reading-first card.
*   **In Anki** (a small card icon) — a new card for this word is already waiting in your Anki deck. Shown once you've chosen decks in the **Anki** window; switch it off under **Settings → 📊 Experience & UI → Label backlogged Anki words**.
*   **Show filter** (⇅) — focus the list on **All**, **✦** only, **No ✦**, **文** only, or **No 文** — and **In Anki** / **Not in Anki** when you have an Anki backlog.
*   **🔍 Search** — a tab beside **Priority List** (press **/** from anywhere): any word, and every sentence that uses it.
*   **Mark Complete** (✓) — tick off a file you've finished; it advances you to the next.
*   **Ignore Word / Other Freq Lists** — exclude words, or see tags from imported frequency lists.

![The Vocab Journey report](assets/images/tutorial/report_output.png)

## 7. Graduating Content
Once you've learned a file's vocabulary AND *consumed it*, **Graduate** it. This keeps your analysis fresh and honest about your progress.

*   **Move to Known** — words in graduated content become "Known" and drop out of future journeys. You've conquered them!
*   **Progressive Graduation** — as goals shift, promote content into sooner tabs (e.g. **Soon → NOW**).

![Graduation Interface](assets/images/tutorial/graduation.png)

## Additional Features

### Splitting Content (Extract)
Big EPUBs and Anki decks are best split into episode- / chapter-sized files. **📖 Extract (EPUB / Anki)** handles it:

*   Set a split length (or split into N parts) — clean `.txt` chunks land in **Processed** *and* your active tab.
*   For Anki decks, pick the field to pull text from.

![The Extract / Splitting tool](assets/images/tutorial/splitting_interface.png)

### YouTube Downloader *(optional)*
Feed Surasura straight from YouTube. Press **▶ YouTube** in the Content Manager:

*   Paste any links — single videos, pasted lists, or full playlists.
*   Choose the caption language, and optionally **keep timestamps**.
*   Clean `.txt` transcripts drop into **Processed** and your active tab, ready to analyze.

> A one-time acknowledgment is required before your first download.

![The YouTube transcript downloader](assets/images/tutorial/youtube_downloader.png)

### YouTube Preview *(optional)*
"Try before you watch." Press **▷** next to **Generate Journey**:

*   Paste a video (or playlist) link to see its Vocab Journey scored against *your* library — how much you already know, and exactly what it would teach you — with no full re-run.
*   For a playlist, each video is scored on its own so you can compare head-to-head.
*   Like it? One checkbox adds the transcript to the front of **NOW** for future runs.

![Preview a video against your library](assets/images/tutorial/youtube_preview.png)

### 🔍 Search Your Report
Open the **🔍** tab (or press **/** anywhere in the report) and type a word:

*   The word's own card comes first, then every other word whose example sentences contain it.
*   Search 食べる and you also get sentences that say 食べた or 食べて — only forms that really occur in your content.
*   Hiragana or katakana both work, and clicking any result searches for that word instead.

### Where a Sentence Came From
Turn on **Settings → 📊 Experience & UI → Sentence source** and each example sentence gets a small badge:

*   Hover to see the file (and, for subtitles, the moment it's spoken); click to copy its path.
*   For a YouTube transcript, clicking opens the video at that moment; shift-click opens the transcript.

### 📖 Your Own Sentences in Yomitan
**Settings → 🧮 Data & System → Export Sentence Dictionary** turns your library into a Yomitan dictionary, "Surasura Corpus":

*   Import it in Yomitan (**Settings → Dictionaries → Import**), then hover a word while reading online: up to eight of the best sentences from your own content appear beside its definitions.
*   Every word in your library gets an entry — best sentences first, at your **Ideal Sentence Range** (Settings → 🧠 Sentences & Logic).
*   Before each export, choose whether to show where each sentence came from. Off keeps the popup clean — hovering a sentence still names its file.
*   To refresh it after adding content, export again, delete the old copy in Yomitan, then import the new one.

### Look Up a Word (⌕)
Each card has a **⌕** button (or press **\\**) that searches the word on Nadeshiko for more real-world sentences. Choose anime, live action, YouTube or everything under **Settings → 📊 Experience & UI → Lookup examples from**, or hide the button there.

### 順 Junban — Put Your Anki Backlog in Order *(optional)*
Mine as much as you like, then press **順** at the bottom of the dashboard: the **new** cards waiting in your Anki deck are re-sorted into Surasura's learn order. Needs Anki open with the AnkiConnect add-on.

*   Only new cards move — reviews, learning and suspended cards are never touched.
*   **Your list first**: cards whose word is on your list lead, in the order you'll meet them. Phrases you meet as often as your list's words (ことが出来る, その気になる) come with them — untick **Phrases** to leave them with the rest.
*   **Then everything else**, easiest first: cards whose sentence has no other new word, then the fewest new words. Words you already know go last. Untick **List first** to mix the words your list cut off in where your journey meets them.
*   You always see a preview of the new order before anything is written. The **why** column says where each card goes; greyed rows are the cards not on your list.
*   **Click a word on your list** to take it off: it goes with the cards not on your list. Click a greyed card to leave it where it is. Click again to undo.
*   **Cards not on your list** — under **Also update the cards**, tick any of **Tag**, **Flag purple** and **Suspend**, or none (the default). Junban never deletes a card.
*   **Restore previous order** puts everything back exactly as it was — the order, the flags and the tag — and unsuspends only the cards Junban suspended.
*   **Same word, other spelling?** When a card's word may be a word on your list written another way — 引き伸ばす on the card, 引き延ばす on your list — a short list above the preview asks, with the reading and the card's sentence. Tick the ones that are the same word; nothing moves unless you do. Your answers are kept when you press Reorder, so each word is asked about once.
*   **i+1 first** (off until you tick it): a card whose own sentence still has a word from your list that you'd learn after it gets that word's card brought right before it — when that card is itself i+1 there — so you learn it first. Otherwise the card waits with the cards of more new words. Names never count.
*   **Your list out of date?** If your library, known words or settings have changed since your last Generate, **Preview order** becomes **Generate & preview**: one press brings your list up to date and shows the new order. Reorder waits until then.
*   The **Anki** window shows how many new cards are waiting in your backlog.
