# Surasura v2.1 - Release Notes

## Summary
- **Sentence Sources** — every example sentence can say where it came from, and take you there
- **文 Reading Words** — words you'll meet in text but essentially never hear, marked and filterable
- **Always Include a Sentence With Audio** — so every word you *can* hear, you can study by ear
- Smarter example sentences (reinforces what you just learned)
- Zip import, double-click to open, and a Content Manager that finally tells you the truth about your order
- Two significant sentence-quality fixes: anime subtitles and runaway transcript lines
- A round of ordering, marker and export fixes

> **Two things will look different after you update.** The subtitle fix changes how sentences are
> split, so your first **Generate Journey** is a one-time full re-analysis. Your **✦ / ⚖** markers
> will also shift — they now follow where content is actually *scheduled* instead of an old folder
> note. Your library, known words, order and settings are untouched.

## 🔎 Sentence Sources (New, Optional)
Off by default — turn it on under **Settings → Experience & UI → "Sentence source"**.

- **A Badge on Every Sentence**: A small, muted marker sits just after each example sentence — in the main report, the extra collapsed sentences, and **Zen Mode**. Choose **Off**, **Icon only**, **File name**, or **Icon + file name**. Icons match the content: 🎬 subtitles, ▶ YouTube, 📖 book chapters from Extract, 📄 plain text.
- **Hover to Place It**: Hovering shows the file *and* the group it belongs to (`深夜特急/本_01.txt`), not a wall of drive path. For `.srt` and `.ass` sources it also gives the moment the line is spoken — `ep01.srt @ 6:34`.
- **Click to Copy, Shift-Click to Jump**: A click copies the full absolute path, ready for Explorer. **Shift-click opens the source file and scrolls straight to that exact sentence, highlighted** — like a Ctrl+F that runs on load.
- **YouTube Sentences Open the Video at That Moment**: Clicking a ▶ badge opens the video **at the second the line is spoken** — a real link, so middle-click and "copy link address" behave normally. Shift-click opens the transcript instead, at the same sentence.
- **⏱ Backfill for Older Transcripts**: A new button in the YouTube window fetches cue times for transcripts you downloaded before this existed. **Only captions are re-fetched — your transcripts are never rewritten.** It works in paced batches, tells you how long it will take, stops itself if YouTube starts throttling, and picks up where it left off next time.
- **Sources in Your Anki Cards**: **Generate Sentence List** gains `Source 1` and `Source 2` columns, appended *after* the existing ones — an Anki note type you've already mapped keeps working exactly as before.
- **Purely Additive**: Word selection, scores, occurrence counts, coverage and the progressive report are byte-for-byte identical with the badge on or off.

## 文 Reading Words (New)
Some words you meet constantly in books and essentially never hear — 佇む, 囁く, 眼差し, 口調. A listening card for one of those is wasted effort, and until now nothing told you which they were.

- **A 文 Marker on Read-Only Words**: Sits alongside ✦ and ⚖ rather than replacing them — a word can be both high-leverage *and* read-only, and you want to know both.
- **It Answers a Concrete Question**: "How long would I have to listen before hearing this once?" The line sits at **one encounter per 60 hours of listening** — about five a year at a heavy immersion pace — and it's a single setting you can move.
- **Your Own Watching Overrules the Estimate**: If a word turns up often enough in *your* subtitles and transcripts, the marker comes off. The reverse never happens — not hearing a word is weak evidence, so your library can only ever *remove* a marker, never add one.
- **Series Vocabulary Doesn't Count**: A name or piece of jargon confined to one story isn't reading vocabulary. Words are only marked when they appear across several different works — and the check switches itself off on a small library.
- **Show Only What You'll Read — or Only What You'll Hear**: The **Show** filter (⇅, or `s`) gains **文** and **No 文**. Plan a reading session with one, an anime session with the other.
- **Export a Reading-Words List**: **Settings → Data & System → Export Reading Words** offers the same three formats as the ordinary export — **Migaku**, **Yomichan / Yomitan**, or a plain word list. Loaded beside your other dictionaries, the presence of a rank *is* the answer. It goes deeper than the report, including read-only words below your commonness band.
- **Silence Where There's Doubt**: Most words get no marker at all. It only speaks when it's confident.
- **Nothing Is Downloaded and Nothing Slows Down**: The comparison against spoken Japanese is worked out before release and shipped as a compact table, so your machine only does a lookup.

## 🔊 Always Include a Sentence With Audio (New, Optional)
Off by default — turn it on under **Settings → Sentences & Logic**.

- **A Word's Examples Can All Come From Books**: Five perfect sentences and not one you could listen to. With this on, a slot goes to a sentence that *does* have audio.
- **It Never Costs You Quality**: The audio sentence still has to earn its place — candidates are ranked by how many other unknown words they contain first, so an i+1 example always beats a merely convenient one. In strict i+1 mode the slot is left alone rather than filled with something worse.
- **YouTube First**: Where two candidates are equally good the clickable one wins — YouTube, then subtitles, then text.
- **A Bonus, Not a Promotion**: Only the final example can change, so your best sentences keep their places. On a ~1,900-file library it lifted words with at least one audio example from 2,164 to 2,698 — without a single sentence being downgraded to get there. It costs no measurable time.

## 🧠 Smarter Example Sentences
- **Sentences That Reinforce What You Just Learned**: When two candidates are otherwise equally good — same i+1 cost, same length — the engine prefers the one whose *other* words you met recently, so an example revisits vocabulary from the same episode or chapter instead of something from months ago.
- **Strictly a Tiebreaker**: It can never promote a harder or worse-sized sentence. Your first example is still the word's own original sentence.

## 🧭 Library & Content
- **Zip Files Can Be Added Directly**: Drop a `.zip` into **Add files** and Surasura unpacks the supported content into one ordered group named after the archive, preserving folder structure. A season pack of subtitles becomes one book-like group in the right order. Japanese filenames stored the old Windows way come through readable instead of as mojibake, and archives that try to write outside the destination are refused.
- **Double-Click to Open**: Double-clicking an item opens it in your default application; double-clicking a group opens its folder.
- **No More Untouchable Library Rows**: The importer used to accept `.epub`, `.html`, `.pdf` and `.vtt` files the analyzer would then silently skip. The importer, analyzer and background indexer now share one definition of content (`.txt`, `.md`, `.srt`, `.ass`), so they can't disagree. Ebooks and web pages go through **Extract**, which converts them properly — nothing is removed from your existing library.
- **Subtitle Link Now Points at jimaku.cc**.

## 📋 Report
- **Completed Files Collapse Out of the Way**: Files you've marked complete gather into a collapsed **"▸ Completed (N)"** section at the **top** of the sidebar. One click expands it, and they stay fully openable — no more scrolling past dozens of finished episodes. Remembered per language.
- **Opens Where You Left Off**: The report no longer opens on a completed file. Marking one complete still advances you to the next unfinished file first, *then* files it away.

## ✂️ Subtitle Sentences Are Readable Again (Fix)
Example sentences from anime subtitles could run to **hundreds of characters**, stringing a dozen lines together with stray `➡` arrows and doubled `｡。` punctuation. On one real episode the longest "sentence" was **409 characters**; it is now **51**, and the average dropped from 21 to 12.

Anime subs use the *halfwidth* `｡`, which was missing from the sentence-boundary list — so their sentence endings never registered. Terminators glued to an adjacent symbol were skipped for the same reason, and the `➡` continuation marker (which means "this line carries on") was being treated as text, stranding fragments like *"our final objective is…"*. Those halves now join into one complete sentence. Chinese gets the same handling; books, transcripts and pasted text were already correct.

> **Your saved settings could not have received this on their own** — a `settings.json` replaces the shipped defaults wholesale, so the essential characters are now merged in on load. Your own additions are kept.

## 📏 Runaway Sentences Are Windowed (Fix)
Some sentences really *are* enormous — a podcast or YouTube transcript is often near-unpunctuated speech, and one real transcript line ran **317 characters**. A word's own sentence is deliberately exempt from the length cap (it's the fallback that guarantees every word has *an* example), so those landed on cards intact.

An over-long sentence is now **windowed around the word you're studying**, with `…` marking each cut. Cuts land on clause boundaries rather than a fixed character count, the word is always inside the window, and nothing is hidden — hover to see the untrimmed original, and the shift-click deep link still jumps to the full line. The **Listen** button reads what you see. It is **display-only**: no re-analysis, and your exports still carry the full sentence.

## 🛠️ Fixes
- **Common Words No Longer Show as "Outside" Any Frequency List**: する — the most common verb in Japanese — reported as *Outside*, and it was far from alone. The tokenizer returns a kanji dictionary form (為る, 矢張り, 其れ) while frequency lists store the ordinary spelling (する, やっぱり, それ), and nothing bridged the two. On a ~4 million token library this affected **3,050 words accounting for roughly 14% of every token**. Scores and word order were never affected — this was the Tier badge and the Tier field in Anki exports.
- **✦ and ⚖ Markers Now Follow Your Schedule**: A file's tier was read from a historical note about which *folder* it sat in, not from where it is actually scheduled — and content added through the Content Manager carried no tier there at all, so it counted as "6+ months" whichever tab you dropped it into. Both now come from the schedule. On a library built purely through the Content Manager, no marker could previously fire at all. **Expect your ✦/⚖ assignments to shift on the next run.**
- **Promoting or Demoting a Group No Longer Shuffles It**: Moving a multi-chapter book between tiers reordered its contents randomly. The move now preserves the exact order you had.
- **Moving One Part of a Split Folder No Longer Grabs the Rest**: Selecting one block of a folder and pressing ▲ moved it correctly but then lit up *every* block of that folder, so a second press moved the lot. Dragging had the same fault, and dropping onto a block landed items against the folder's *first* block instead of the one under the cursor. The mouse and the ▲▼ keys finally agree.
- **Split Folders Say So**: A folder whose files aren't consecutive in your order now reads **`Bleach (2 of 7)`** instead of several blocks all called `Bleach`. This is normal and always has been — your order lives in the manifest and is deliberately independent of the folders on disk. **Nothing has changed about your library; you can now see it.**
- **"Nothing To Export" Now Says So**: The reading-words export opened a format picker even when no read-only words had been found, then failed several clicks later with a generic message. It now checks for actual rows and explains up front.
- **Words Per Day Now Updates the Report**: Changing **Words Per Day** or **Show Target Days** left the old estimate on screen until something else forced a redraw. Both now re-render — with no re-analysis.

## ⚙️ Under the Hood
- **The Spoken-Language Comparison Ships Precomputed**: Whether a word belongs to speech or text depends only on reference corpora and the tokenizer, both fixed at build time — so that work happens before release and the app carries a compact table. Your machine never loads a corpus. The corpora themselves are never shipped.
- **Deep Links Are Verified, Not Guessed**: A stored sentence isn't identical to the text in the file (spacing is dropped, cue endings added, Latin characters stripped). Rather than guessing, Surasura checks candidate snippets against the real file and offers a link only when one appears there **exactly once** — so a link can never scroll you to the wrong line. It only runs when the badge is switched on.
- **Source Badges Cost Nothing to Re-Render**: The mapping is worked out once and remembered, so changing theme or Zen limit doesn't redo it. On a ~1,900-file library a re-render with badges on went from **3.9s to 2.0s**. The memory is dropped for any file whose contents change.
- **Presentation vs. Analysis, Properly Separated**: The report re-renders — without re-analyzing — when any setting it *displays* changes, and the engine and dashboard read that from one shared function so they can't disagree.
- **Engine Revision Stamp**: Results now carry an engine-revision marker, so an engine change can no longer serve the previous report from cache.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** This is a one-click in-app update. You'll see **⬆ Update available** at the bottom-left of the dashboard — click **Update now** and Surasura reopens on v2.1. Your known words, ignore/blacklist/graduated lists, content, results, settings and library order are never touched.

If you're on **v1.9 or earlier**, or you'd rather update by hand:

- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating manually.
