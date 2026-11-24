# Surasura 3.0.18 — the new journey page, a review loop from your phone, the simple Swap

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**Journey ↗ opens a new page: swap a sentence, add a card and play a line right there. Flag a card on your phone
and Surasura acts on it. Delete a card and Surasura asks why.**

[Download `Surasura-3.0.18-setup.exe`](#download) · [On 3.0.0 to 3.0.17?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## What's better

- **The new journey page:** *Journey ↗* opens a new page for your words.
  - **⇄** swaps a word's sentence and **Add now** makes its card, right on the page.
  - **▶** plays a line, a line from an .mkv video too, in a fraction of a second.
  - The sentence where you'll first meet a word is marked (a switch hides it). Episodes you pre-study are marked,
    on the page and on the window's stones.
  - Night or Light, word and sentence sizes, sentences per word (1–10 or All) and your own keys: the page's ⚙, or
    *Settings › App › Journey*.
  - The old page's ignored words carry over (never over a word you know).
- **The review loop, from your phone:** flag a card in Anki to tell Surasura what to do with its word — *✓ Known*,
  *⇄ Swap* or *✕ Ignore*. Surasura reads the flags at the next sync (*From your phone: 3 known · 2 to swap · 1
  ignored*, with Undo). Pick which colour means what in *Settings › Anki & mining › Your daily loop*.
- **A deleted card asks why:** delete one of Surasura's cards in Anki and Surasura asks — *Known*, *Ignore*,
  *Parsing mistake* (the word is wrong, or only this sentence) or *Bad card* (it gets another sentence).
- **The simple Swap:** a swapped word gets a new card from another sentence; the old card is suspended (tagged
  `surasura::swapped`). Undo puts the old card back. A sentence you swapped away from never comes back for that
  word. A word your library says only once waits until a new episode or book says it again.
- **Add now goes first:** a card you ask for from the journey comes first among your new cards.
- **One word standard — Known · Ignore:** the Blacklist joins the Ignore list once, at the first start (a copy is
  kept, nothing is lost). *Your words* has two tabs, Ignore and Known. One setting, *Count as known in Anki*, and a
  red or green flag never counts as known. New arrivals' *Ignore* is now *Remove*; the report's *Ignore* is now
  *Hide* (this page only).
- **Tidy:** when Connect's never-studied cards pass 1.5× your card limit, the extra ones are deleted, a copy saved
  and read back first, with Undo. *Put back…* in Settings undoes any of the last 10 tidies. Tidy never takes a card
  you studied, changed, flagged, suspended or moved into a deck of your own.
- **One study order:** Connect and Junban follow the same order (*Settings › Level › Study order*), and *Cards for
  every new word* makes a card for each new word, not only your list's. Junban never sets aside Surasura's own cards.
- **Card sentences: Best or Nearest:** Best takes the clearest sentence in your library for each card; Nearest keeps
  the episode's own line.
- **Books and audiobooks:** a book paired with its audiobook gives cards from its chapters, with audio, and the
  chapters you've heard count as heard. A book's new version: *Replace* keeps the parts you read (with Undo), a
  removed book frees its audiobook, and a whole book can be removed or renamed at once.
- **Your path:** four stages — On board → First episode → Automate → Make it yours. Each step's button does the
  step right there; the ✦ panel is one list.
- **Gentler on the machine:** the window draws first, then the background work starts, one heavy job at a time on a
  small PC. Starting a review in Anki pauses card making at the next card, so your review card is never redrawn.
- **Furigana and pitch:** Backfill fills a card's missing furigana and pitch, and Connect's cards always get both.
- **Connect, sharper:** a list word met only inside a rare compound gets its card from that line; *Words it won't
  mine again…* says why a word got no card; a level raise never re-mines after Connect is switched off and on.
- **Smaller changes:** Search opens a New arrival or a Goal title at its hit · Current's card badge and *N new* keep
  their figures across a restart · Up next's hover shows how much you knew when you added an item and when you
  finished it · hato updates itself once a day, and Settings shows whether it's up to date · Piyo has produce rounds
  (you write the sentence) · sentences you flag on the journey can go with *Send report*, each with a tick · closing
  Surasura never shows a Critical Error box · Junban reads a kana card's word in its own sentence · a YouTube
  playlist's rest line stays readable in the bar · a show's new episodes never stack in reverse.

Thanks to **Mattias** for the idea and first version of Piyo's produce rounds.

## Before | Now

| | Before (3.0.17) | Now (3.0.18) |
| :-- | :-- | :-- |
| **Journey ↗** | The old page | The new page: ⇄, Add now and ▶ on every line |
| **A bad card** | Delete it in Anki; no reason asked | Flag it or delete it: Surasura asks, then swaps or ignores |
| **A better sentence for a word** | Make the card again by hand | ⇄ Swap: a new card, the old one suspended |
| **Ignore list and Blacklist** | Two lists | One Ignore list |
| **Too many unstudied cards** | Connect waited | Tidy deletes the extra, with a copy and Undo |
| **Reviewing while cards are made** | The review card could redraw | Card making pauses |

## Updating

**On 3.0.0 to 3.0.17?** Surasura offers 3.0.18 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are. Your Blacklist's words join your Ignore list at the first start (a copy is kept).

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.18-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
   your 2.5 folder is left exactly as it was.
2. Add your shows' and books' folders in setup — a 2.x tier keeps its place (NOW → Current, 6+ Months → Goal).
3. Your first Generate re-reads your library once. After that, the usual short ones.

Stop using 2.5 once 3.0 runs (the two could write the same files). Everything new in 3.0:
[the 3.0.0 notes](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0) · what came since:
[3.0.1](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.1) ·
[3.0.2](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.2) ·
[3.0.3](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.3) ·
[3.0.4](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.4) ·
[3.0.5](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.5) ·
[3.0.6](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.6) ·
[3.0.7](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.7) ·
[3.0.8](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.8) ·
[3.0.9](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.9) ·
[3.0.10](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.10) ·
[3.0.11](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.11) ·
[3.0.12](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.12) ·
[3.0.13](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.13) ·
[3.0.14](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.14) ·
[3.0.15](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.15) ·
[3.0.16](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.16) ·
[3.0.17](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.17).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- **Listening rounds** are Japanese only, and need the AI voice (beta) installed.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.18-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
