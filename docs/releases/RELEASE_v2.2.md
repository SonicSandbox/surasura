# Surasura v2.2 - Release Notes

## Summary
- **順 Junban** — put the new cards waiting in your Anki deck into Surasura's learn order
- **🔄 Known words straight from Anki** — sync live from a running Anki, no deck files
- **🔍 Search your report** — any word, every sentence that uses it, and its other forms
- **✍ Words spelled the way you read them** — 引きずる, not the dictionary's 引き摺る
- **繁简 Chinese in one script** — read a mixed Simplified/Traditional library as either
- **📺 bilibili.tv transcripts** — no account needed
- **✂ Cleaner anime sentences**, and a round of safety and reliability fixes

> **One thing will look different after you update.** Two subtitle-parsing fixes change how anime lines
> are split into sentences, so your first **Generate Journey** is a one-time full re-analysis. Your
> library, known words, order and settings are untouched — your example sentences just get better.

## 順 Junban — Put Your Anki Backlog in Surasura's Order (New)
Mine as much as you like with Anki Miner (or anything else). Then press **順** and the new cards waiting in your Anki deck are re-sorted into Surasura's learn order — the words that matter most for *your* library come up first. Anki keeps the cards; Surasura just decides the order.

The **順** button sits at the bottom of the dashboard (switch it off under **Settings → Language & Parsing → Enable Anki reordering**). Needs Anki open with the free **AnkiConnect** add-on.

- **Only New Cards Move**: cards you're reviewing, learning or have suspended are never touched — your schedule is safe. Nothing is added, deleted or rescheduled.
- **Preview First, Always**: the window shows the exact new order before anything is written — every card, its new position, and which ones Surasura doesn't know (those keep their current order, at the back). **Reorder** only unlocks once you've seen the preview for what's selected.
- **One Deck or All of Them**: reorder a single deck (subdecks included) or every deck as one queue.
- **Two Orders**: **As I'll meet it** follows your NOW → Soon → 6+ months journey; **By leverage** puts the highest-payoff words first regardless of when you'll see them.
- **Only the Words You Want**: narrow a run to words marked ☆ high-leverage, ⚖ lopsided or 文 reading.
- **Leave a Word Out**: click any row in the preview (or press Space) to drop it from this run. It keeps its current place, and the rest renumber instantly.
- **Optional Card Touch-ups** (all off until you turn them on): tag the notes it moves (with `Surasura::star` / `::lopsided` / `::reading` sub-tags if you like), add the word's frequency number to a field, or add an example sentence from your own content — only into an empty field, or appended.
- **Undo That Actually Works**: Anki keeps no undo for this, so Surasura saves every card's position before writing. **Restore previous order** puts everything back exactly — including tags and fields it touched, and your own values in any field it overwrote, even after later runs.
- **Interrupted Runs Are Safe**: if Anki closes partway through, your original order stays saved, and Junban asks you to restore it before reordering again — so a retry can never overwrite your only way back.

## 🔄 Known Words Straight From Anki
The **Anki** button now reads your known words **live from Anki** — no more exporting a deck file. Open Anki, press **Anki** in Surasura, and press **Sync now**.

- **Only What You've Actually Studied**: a card you've never reviewed isn't a word you know, so new cards are left alone. Suspended cards are left out too, unless you tick **Include suspended cards**.
- **Pick Your Decks**: the first time, Surasura picks every deck you've studied cards in — remove any that aren't vocabulary with ✕, and add more from the list below them.
- **Pick the Word Field — or Don't**: *Auto* reads each note type's first field, which is where Anki Miner and most vocab decks keep the word. You can name a field instead, and read a second one too. The window shows which field each note type resolves to, so a wrong choice is obvious.
- **It Only Ever Adds**: new words are added to what you already have — words from Migaku or Jiten stay. Nothing is duplicated, and nothing is ever removed.
- **Fast**: after the first sync, Surasura only looks at cards you've studied since last time.
- **Sync Automatically**: tick **Sync automatically when Anki is running** (also in Settings → Data & System). Open Anki, open Surasura, and your known words catch up on their own.
- **Start Over From Anki**: **Replace with Anki…** rebuilds your known words from Anki alone. It tells you exactly how many you'll go from and to before doing anything, backs up your current list first, and **Restore previous** puts it back.
- **No Anki Open? Still Works**: **Import an .apkg file instead…** is the old deck-file import, as before.

## 🔍 Search Your Report
A new **🔍** tab next to **Priority List**. Type any word and see it at once — press **/** from anywhere to jump straight in.

- **The Word Itself First**: its card(s), exactly as the other views show them.
- **Every Sentence That Uses It**: below, every other word whose example sentences contain what you typed, with the match highlighted.
- **Its Other Forms Too**: search 食べる and you also get the sentences that say 食べた or 食べて, in their own clearly labelled group — only forms that really occur in your content, never guesses.
- **Hiragana or Katakana, Either Works**: たべる finds タベル.
- **Click to Follow**: click any word in the results to search for it instead.

## ✍ Words Spelled the Way You Read Them
The report and every export now show a word the way your content actually **writes** it, not the dictionary's headword: 引きずる instead of 引き摺る, ある instead of 有る, 須藤 instead of スドウ.

- On the library this was measured against, **nearly one word in four** was being shown with a spelling the content itself never used.
- It carries through to Migaku, Yomitan, Anki and word-list exports — and it's what lets Junban match the 引きずる on your card.
- Nothing about how words are counted changed — いう, 言う and 言える are still one verb.

## 繁简 Chinese: One Script for Your Whole Library (New)
Mixing Simplified and Traditional content no longer splits your words in two. Until now 学习 and 學習 were two unrelated words: their counts split, and a known word in one script didn't count for the other.

Pick a script under **Settings → 🌐 Language & Parsing → Script** (it appears when Chinese is your language): **As-is**, **Simplified (简体)** or **Traditional (繁體)**.

- **Everything Reads in One Script**: your content, known words, ignore / blacklist / graduated lists and frequency lists. Each word is one row with its full count, whichever script it was written in.
- **Your Files Are Never Changed**: the conversion happens when Surasura reads them. Switch back to **As-is** at any time and everything is exactly as before.
- **Better Word Splitting for Traditional Text**: Traditional content is split into words through its Simplified form, which the word splitter knows far better — 經濟關係 now splits as 經濟 + 關係.
- **Links Still Find the Sentence**: with **Sentence source** on, a converted sentence still opens your file at the right place, in its original wording.
- **Good to know**: Simplified → Traditional isn't always one-to-one (发 can be 發 or 髮) — common words are handled by phrase, but a rare context can still pick the wrong character. Traditional uses standard character forms (爲, 裏, 衆), which can differ from Taiwan's (為, 裡, 眾). Switching script re-reads your library once, in the background.

## 📺 bilibili.tv Transcripts (New)
The transcript downloader now takes **bilibili.tv** links alongside YouTube, in the same box: a single episode, a whole season, or an upload.

- **No Account, No Login**: bilibili.tv serves its subtitles, Chinese Simplified and Traditional included, to anyone — wherever a show is licensed for your region.
- **Your Region's Catalogue**: an episode that isn't available where you are simply says **"not available in your region"**, and a members-only one says so too, instead of silently downloading nothing.
- **Proper Sentences**: Chinese subtitles don't end lines with punctuation, so each subtitle line becomes its own sentence — the same way Surasura already reads subtitle files.
- **A Season Is a Folder**: paste a season link and every episode lands in one folder named after the show.
- **The Badge Opens the Episode**: with **Sentence source** on, a bilibili.tv sentence shows 📺 — hover to see the moment it's spoken, click to open the episode. **Preview against library** takes bilibili.tv links too.
- **bilibili.com Isn't Supported**: that site only gives subtitles to signed-in users, so its links are turned away with a pointer to bilibili.tv.

## ✂ Cleaner Anime Sentences
Two parsing fixes to how subtitle lines become sentences, which is why the first Generate Journey after updating is a full re-analysis.

- **Speaker Labels No Longer Leave a Bracket Behind**: a name carrying furigana — `（風太郎(ふうたろう)）` — used to be stripped only as far as its inner bracket, leaving a stray `）` glued to the front of the line. It reached example sentences and exports alike. Now the whole label goes.
- **Netflix's Dash Now Joins the Line**: `―` at the end of a cue means "this sentence continues", the same as the `➡` fansubs use, but it was treated as ordinary text and a full stop was added after it — cementing a fragment. Measured on a real episode, 3.4% of cues were affected.

## 🛠️ Fixes
- **Deck-File Import Is Safer**: the `.apkg` importer no longer overwrites a known-words file it couldn't read, writes the file in one step so an interruption can't leave it half-written, and keeps words you marked Ignored as ignored instead of turning them into known words.
- **Settings Fit Smaller Screens**: the Settings window is two independent columns, so every group fits on a 720px-tall screen.
- **A Link That Can't Be Read Now Says Why**: a private, unavailable or region-locked video used to end the download with just "No videos found".
- **Adding a Preview to the Front of NOW Can't Wipe Your Order**: if your library order file couldn't be read at that moment (locked by antivirus or sync, or edited in Notepad), the preview's entries used to replace it entirely. Now nothing is added and the order is left untouched.
- **Very Long YouTube Titles Keep Their Video ID**: long names were cut through the `[id]`, which broke the duplicate check and could let two similar videos overwrite each other.
- **Chinese "Reinforce Seg" Applies Everywhere**: the background word index now uses the same setting as a full run, so the commonness preview matches your report.
- **A Rare Start-up Race in the Word Index**: two Surasura processes starting at the same moment could both try to create the index and one would fail. Harmless, but it could fail a run for no reason.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** This is a one-click in-app update. You'll see **⬆ Update available** at the bottom-left of the dashboard — click **Update now** and Surasura reopens on v2.2. Your known words, ignore/blacklist/graduated lists, content, results, settings and library order are never touched.

If you're on **v1.9 or earlier**, or you'd rather update by hand:

- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating manually.
