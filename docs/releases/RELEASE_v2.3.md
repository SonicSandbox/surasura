# Surasura v2.3 - Release Notes

## Summary
- **🧩 Anki Backfill** - Including: adding 2 sentences from your library and Pattern (collocations, particles, pairings)
- **🔹 'Patterns' Backfill** - Highest freq collocations, word pairings and particles for every word, built by balancing a variety of modern corpora (ie: ~を, ~が, compound nouns, etc)
- **順 Junban, reorder your whole backlog** - updated to include phrases + [Anki Miner](https://github.com/0xzerolight/anki_miner) relevant parsing
- **📖 Surasura Corpus** - Build & export a yomitan dictionry that includes sentences for every word in your library
- **🧱 Parsing adjustments** - 新幹線, 可能性 and お茶 stay one word; verb / adj counted as one word
- **🔄 Automatic Generate on Anki known-words sync** - Generate when Anki adds known words, and an "In Anki" label

**Visual adjustments**:
- Anki icon in Journey view if word already in your backlog
- Fixed content manager deletion freezes (due to visual redrawing on every deletion)
- Blue glow on 'Generate' if library if out of date

> **One thing will look different after you update.** Every verb and adjective is now counted as one word
> across all its forms, and words keep their prefixes and suffixes (新幹線, 可能性), so your first
> **Generate Journey** is a one-time full re-analysis. Your library, known words, order and settings are
> untouched — your list just stops splitting words in two.

## 🧩 Anki Backfill — Fill Your Cards From Surasura (New)
A new window fills fields on your Anki cards from what Surasura knows. Open it from the **Anki** window
(**Backfill cards…**) or from Junban (**Backfill…**). It's there while Junban is switched on. Needs Anki open
with the free **AnkiConnect** add-on.

<img src="https://raw.githubusercontent.com/SonicSandbox/surasura/main/docs/assets/images/releases/v2.3/anki_backfill.png" width="780" alt="Anki Backfill after a preview: what goes into each card">

- **パターン — How the Word Is Used**: a few short lines per card:
  - the two particles it goes with, on their side of the word, as a share of all its uses — `を〜 24%` on
    利用する means 24 of every 100 times you meet it, を comes right before it;
  - its own forms, one per line (囲まれる 62%, 利用できる 7%);
  - four words it pairs with, written the way the text says them (目を覚ます · 目の前 · 死亡が確認される);
  - what often goes around it (〜家 · 〜隊 · 〜会).

<img src="https://raw.githubusercontent.com/SonicSandbox/surasura/main/docs/assets/images/releases/v2.3/patterns_card.png" width="600" alt="A card's パターン lines: particles, forms, what goes around it, and the words it pairs with">

- **Only What's Really the Word's Own**: a pairing shows when it turns up in at least three separate places —
  different episodes, books or articles — and is strongly tied to the word, so one show's catchphrase,
  "という", or "その / この" in front of almost anything don't take the space. Adverbs get lines too (再度 →
  再度確認する · 再度見直す). When a word is rare in the data behind its lines, they're marked "thin" — a card
  template can show it (an amber パターン label, for instance); no text is added to your card.
- **例文 — Two More Sentences**: from your own shows and books. Every other word in them is one you already
  know, and neither is your card's own sentence or one almost like it. They come from different episodes
  when they can, and between two equally easy ones, the sentence that shows the word's top pairing wins.
- **Preview, Then Fill**: pick a deck and **All** or **New only**. The preview shows exactly what goes into
  each card and how many notes it will fill, and the ⓘ says why the rest wait. Nothing already in a field is
  touched unless you tick **Replace**, and **Restore** puts back what was there.
- **Your Fields, Your Note Types**: a field named `Patterns` (or `ExampleSentences` for 例文) is found by
  itself; otherwise choose the field, note type by note type. **Copy card style** gives any note type the
  look of the パターン lines, and a **?** on every row explains each line with an example.
- **Get the Data**: **Get data…** downloads Surasura's shared word-pair data once (32 MB), made from
  RealPersonaChat, Aozora Bunko, Japanese Wikipedia and modern Japanese news from the Leipzig Corpora
  Collection (counted only: no sentences), under CC BY-SA 4.0. Your own library's part is built the first
  time you press **Build & preview**, in about a minute.
- **Chinese Cards Too**: パターン and 例文 fill Chinese cards, Simplified or Traditional, each in the card's own
  script — the measure word it takes (书 → 本〜 94%), the little word before it (满意 → 对〜 43%), its forms
  (累 → 很累 · 太累), four word pairs (电话 → 打电话 · 接到电话) and what goes around it (桌子 → 〜上 · 〜下面). **Get
  data…** downloads the shared Chinese set once (9 MB), made from Tatoeba, KdConv, Chinese Wikipedia,
  Chinese Wikinews and Leipzig's Chinese news (counted only), under CC BY-SA 4.0.
- **Japanese and Chinese Side by Side**: every note type has a language — set it next to its field. A note
  type whose cards have kana is Japanese by itself, and one with no language set is never filled, so Chinese
  lines never land on a Japanese card, even for words both languages share (問題 / 问题).

## 順 Junban — Your Whole Backlog, Your List First
Junban used to order only the cards whose word was on your list. Now every new card gets a place — and your
list still comes first.

<img src="https://raw.githubusercontent.com/SonicSandbox/surasura/main/docs/assets/images/releases/v2.3/junban.png" width="780" alt="Junban's preview: list words and frequent phrases first, each with why">

- **Your List First**: every card whose word is on your list leads, in your journey's order or by leverage.
  A word your list cut off as too rare waits behind all of them.
- **Frequent Phrases Count Too**: half of a mined backlog is phrases — ことが出来る, 事になる, その気になる —
  which your list can never hold. Junban finds each one whole in your library, and one you meet as often as
  your list's own words is placed as if it were on your list.
- **The Rest, Easiest First**: every other card is placed by the sentence it was mined from — fewest new
  words first. Words you already know go last.
- **Your Choice for the Rest**: under **Cards not on your list**, tick **Tag**, **Flag purple** and/or
  **Suspend** for every card placed after your list. The preview says how many each will touch, and
  **Restore previous order** undoes all of it — only the cards Junban suspended are unsuspended. Junban never
  deletes a card.
- **Same Word, Other Spelling**: when a card's word may be a word on your list written another way (引き伸ばす
  and 引き延ばす), Junban asks instead of guessing — and remembers your answer.
- **i+1 First** (off until you tick it): a card whose sentence still holds a word from your list you'd learn
  after it gets that word's card brought right before it, so you learn one, then the other.
- **Always From an Up-to-Date List**: when something has changed since your last Generate, **Preview order**
  becomes **Generate & preview**, so a reorder never follows an old list.
- **The Preview Says Why**: "list #412", "phrase · 1,342× · the episode you first meet it in", "i+1",
  "2 unknown", "known" — and when many cards come from an episode that isn't in your library, it names it.
- **Example Sentences Moved to Anki Backfill**: Junban's old "Add an example sentence" option is now
  **例文**, which adds two from your whole library to any card.

## 📖 Surasura Corpus — Your Own Sentences, Inside Yomitan (New)
Export your library as a Yomitan dictionary. Import it once, and hovering any word in your browser shows —
beside your other dictionaries — up to eight of the best sentences for it from your own shows, books and
videos.

**Settings → 🧮 Data & System → Export Sentence Dictionary**, then in Yomitan: **Settings → Dictionaries →
Import**.

<img src="https://raw.githubusercontent.com/SonicSandbox/surasura/main/docs/assets/images/releases/v2.3/surasura_corpus_export.png" width="289" alt="Settings, Data &amp; System: Export Sentence Dictionary">

- **Every Word in Your Library**: not just your study list, so you can see how your own content uses the
  words you already know too.
- **Best Sentences First**: the fewest words you don't know yet, a good length (your own **Ideal Sentence
  Range**), and never more than two from the same episode when others have the word.
- **Where Each Sentence Came From — Your Choice**: a short source name under each sentence, or a clean
  popup. Your answer is remembered.
- **Finds the Word However It's Written**: hover 辿り着いた and you get 辿り着く's sentences.
- **Quick**: about 10 seconds for a 2,000-file library, in the background. Made from your own files, for your
  own study — it stays on your computer. To refresh it, delete the old "Surasura Corpus (ja)" in Yomitan
  and import the new one.

## 🧱 Whole Words — Prefixes and Suffixes Stay On
Japanese word splitters cut prefixes and suffixes off a word: 新幹線 was counted as 新 + 幹線, 可能性 as 可能 +
性. So your list offered 幹線 and 可能 — never the word your content actually says. Now a word stays whole
whenever the whole is a real dictionary word.

<img src="https://raw.githubusercontent.com/SonicSandbox/surasura/main/docs/assets/images/releases/v2.3/whole_words_search.png" width="600" alt="Search in the report: お茶 is one word, in its own card and in other words' sentences">

- **The Word Your Content Says**: 新幹線, 可能性, 不自然, 違和感, 利用者, 子供っぽい, お願い — one word each, with the
  reading a dictionary gives it: 日本人 is にほんじん, not にっぽんにん.
- **Only Real Words**: names and one-offs (三回目, 3年生, a character's name + 人) stay as they were.
- **Honorific Words Are Words**: 母さん, お母さん, 皆さん, お嬢さん, 神様, お客様 — each with its own reading. A name
  with さん (田中さん) and plurals (子供たち) stay split.
- **お and ご Where That's How People Say It**: お茶, お菓子, お金, お祭り, お湯 are words; お名前, お仕事 and お部屋
  stay お + a word you already know.
- **One Word, However It's Written**: おすすめ, お勧め and オススメ are one word, and so are おやすみ and お休み, ご存じ
  and ご存知. Know one and you know them all.
- **A Word You Can Read Through One You Know**: when you know 利用, 利用者 stays on your list — it has its own
  reading to learn — but lower down, and it doesn't make a sentence harder: a sentence whose only other new
  word is 利用者 still counts as i+1.
- **Everything Agrees**: the list, your known words, 🔍 Search, the Surasura Corpus, Anki Backfill, Junban
  and the "In Anki" label all see the same whole words.
- On the library this was measured against, 584 whole words joined the list (新幹線, 奥さん, 無意味, 中学校,
  不可能, 自転車 …); 86.4% of its example sentences are i+1 (86.2% before).

## 🔤 One Card per Word
A verb or adjective used to get a separate card for each way it was conjugated: 辿り着いた, 辿り着く and 辿り着けば
were three cards, each ranked on a fraction of how often you meet the word. Now each word is one card,
counted across all its forms — and words none of whose forms cleared the cut-off on their own (立ち入る, 取り消す)
now reach your list. The reading shows the dictionary form (タドリツク). 上手 as じょうず and 上手 as かみて are still
two cards.

## 🔄 Your List Keeps Up With Anki

<img src="https://raw.githubusercontent.com/SonicSandbox/surasura/main/docs/assets/images/releases/v2.3/anki_generate_option.png" width="275" alt="The Anki window: Generate when Anki adds known words, and your backlog">

- **Generate When Anki Adds Known Words** (in the **Anki** window, off until you tick it): when the Anki sync
  brings in words you now know, Generate runs by itself in the background — at most every 10 minutes, never
  while the Content Manager or another Generate is running.
- **The Generate Button Tells You**: a thin blue border when something has changed since your last Generate,
  and a small ✓ when your journey is up to date.
- **Words Already Waiting in Anki Are Labelled**: every word a new card is already waiting for gets a small
  card icon, and **Show** gains **In Anki** and **Not in Anki**. Switch it off under Settings → 📊 Experience &
  UI → **Label backlogged Anki words**.
- **See Your Backlog at a Glance**: the **Anki** window says how many new cards are waiting in your decks, and
  every Anki option now lives there.

## ⚡ Bulk Remove, Graduate and Demote in Seconds
Selecting a lot of files in the **Content Manager** and pressing **Remove**, **Graduate** or **Demote** used to
freeze the window. Now **3,000 files take about 2.5 seconds**, with a running count in the status line, one
message at the end for any file that couldn't be moved, and a question that counts files, not rows.

## 🧹 Moving Content Keeps It Together
- **New Content Lands at the Top** of its tab — and a new episode of a series that's already there goes right
  after that series' last episode.
- **No Empty Folders Left Behind** after Graduate, Demote or Remove; the tab folders themselves always stay.
- **Your Own Files Come Along**: cover images and notes follow a moved folder; a moved transcript keeps its
  timing file, so ▶ still opens the video at the right moment; an EPUB chapter keeps its 📖 badge.
- **Undo Puts Everything Back**, exactly as it was.

## 🛠️ Fixes
- **No More Verse Numbers in Example Sentences**: 「13そこでモーサヤは…」 is now 「そこでモーサヤは…」 — a number
  that counts something (「3人で」「5番目」) stays.
- **No 文 Badge Borrowed From Japanese on Chinese Words**: a Chinese word written like a Japanese one (描写,
  研究) was judged by the Japanese word's spoken frequency. Chinese words carry no 文 badge now.
- **A Chinese Note Type Is Never Taken for Japanese Over a Name**: Chinese writes a foreign name with ・
  (约翰・列侬), and Anki Backfill counted that dot as Japanese kana. It stays "Language?" until you set it.
- **The YouTube Preview Ranks Like Your List**, and switching it on or off no longer costs a full
  re-analysis.
- **Update Problems Explain Themselves**: when an in-app update can't download, Surasura now says why, and a
  failed update leaves `debug/update_report.txt` you can attach to a bug report.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** This is a one-click in-app update. You'll see **⬆ Update available** at the
> bottom-left of the dashboard — click **Update now** and Surasura reopens on v2.3. Your known words,
> ignore/blacklist/graduated lists, content, results, settings and library order are never touched.

If you're on **v1.9 or earlier**, or you'd rather update by hand:

- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating manually.
