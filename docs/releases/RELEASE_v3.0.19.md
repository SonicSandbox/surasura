# Surasura 3.0.19 — one sentence choice everywhere, a much faster Generate, *Make my new cards again…*

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**Every word's sentence is now chosen one way, from your whole library: for your cards, Swap, your list and the
journey. Generate takes a quarter to a third less time, and Surasura can make your never-studied cards again.**

[Download `Surasura-3.0.19-setup.exe`](#download) · [On 3.0.0 to 3.0.18?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

> ⚠️ **Your library is read again once after the update.** The first Generate takes longer, once: about
> 1 min 45 s instead of 11 s on a 2,000-file library. After that, the usual short ones.

## What's better

- **One sentence choice, everywhere:** your cards, *⇄ Swap*, your list and the journey now pick each word's sentence
  the same way, from every episode and book in your library.
  - It weighs a sentence's length, the other new words in it, where the word sits, whether it has audio, and what
    you've already seen.
  - A short line is no longer thrown out; a line outside your length ranks lower the further out it is.
  - **Length** now defaults to 14–25 characters (*Settings › Sentences › Length*). If you never changed it, yours
    moves to 14–25. Your own pick is kept.
  - Your list's and journey's sentences can change once, to the ones your cards would get.
- **Faster** (3.0.18 and 3.0.19 timed side by side on the same libraries):
  - **Generate:** a 2,000-file library 15.0 → 11.5 s, 20,000 files 99.7 → 62.3 s.
  - ***Only i+1*:** 2,000 files 15.3 → 11.5 s.
  - **Less memory:** Generate's peak on 2,000 files 1,286 → 541 MB, on 20,000 files 2,373 → 1,498 MB.
  - **Opening a big library:** a 20,000-file library shows its numbers sooner (5.3 → 3.6 s), and its longest pause
    while it opens is 818 → 97 ms. The window's first numbers no longer race the rest of the start.
  - **The window:** a big library answers you sooner while it starts, its first key move shows its numbers sooner,
    and the redraw after a move is quicker.
  - **The journey:** a new word's meanings show much sooner; on a big library the page after a move draws faster;
    its first render is a little quicker.
  - **Connect:** Best's mine is a little faster for an episode (45.8 s against 49.5 s on the build before this
    change), with the same cards; Nearest is quicker too. A known-words sync and its Undo are quicker.
- ***Make my new cards again…*** (*Settings › Anki & mining*, under *Tidy waiting cards*):
  deletes Surasura's cards you've never studied, and Connect makes them again with the new sentence choice.
  - Never a card with a review. A card you study on your phone in the meantime is kept: Anki syncs before and after.
  - A copy of every deleted card is kept first, your edits with it. *Put back…* brings them all back.
  - A card you deleted yourself stays gone.
  - Connect makes them again as it mines, up to *Keep up to N new cards waiting* (same section). Raise that number
    first to get more back at once.
- **Send report is one easy button** for helping improve Surasura: *Send report* is ready as soon as there's anything
  to send — a note, the sentences you flagged, your swaps, or the cards you didn't want (word, sentence and why; no
  card ids), each with a tick.
- **Fixes:**
  - A book with no audiobook no longer makes an audio card with nothing to play: under the audio card type it makes
    a sentence card. A book the AI voice reads keeps the audio card.
  - Best's mine without the speech model could end with 0 cards (3.0.17 and 3.0.18). Fixed.
  - *Sort again* and *Put back* work while Connect is only waiting; they wait only while it is making cards.
  - A long show name now fits the journey's rail and headers, cut with …, the full
    name on hover.
  - Two files with the same name in different folders are counted apart, and *↗* opens the right one.
  - Two subtitle lines that start together: *⇄* and *Add now* take the line that says your word, and *▶* plays the
    one that ends last.
  - A set-aside episode no longer marks a same-named episode of another show.
  - Words: a song or sign line drawn one character at a time reads as its words (お願い); A棟, Ｂ組, x軸 no longer
    give 棟, 組, 軸 as words of their own.
- **Retired:** the old journey page and Zen. *Journey ↗* is the new page; a saved Zen look opens as Night.

## Before | Now

| | Before (3.0.18) | Now (3.0.19) |
| :-- | :-- | :-- |
| **A word's sentence** | Cards, list and journey each chose their own | One choice for all of them |
| **Generate, 2,000 files** | 15.0 s | 11.5 s |
| **Generate, 20,000 files** | 99.7 s | 62.3 s |
| **A 20,000-file library, numbers on screen** | 5.3 s | 3.6 s |
| **Best's mine, one episode** | — | A little faster, the same cards |
| **New cards made with the old choice** | Delete them by hand | *Make my new cards again…*, with a copy and *Put back…* |
| **A book card with no sound** | An audio card with nothing to play | A sentence card |
| **Send report** | A written report | One button for a note, flags, swaps and unwanted cards |

## Updating

**On 3.0.0 to 3.0.18?** Surasura offers 3.0.19 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are. Your library is read again once: the first Generate takes longer, once
(about 1 min 45 s instead of 11 s on a 2,000-file library).

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.19-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.17](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.17) ·
[3.0.18](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.18).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- **Listening rounds** are Japanese only, and need the AI voice (beta) installed.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.19-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
