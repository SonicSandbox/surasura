# Surasura 3.0.6 — translations from your own AI, YouTube at a safe pace, and 2.x books with their audiobook

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**Your AI can now fill your cards' empty translations through Piyo. YouTube downloads take their time and stop for the day after a bot check. Books 2.x split into `.txt` parts get their audiobook.**

[Download `Surasura-3.0.6-setup.exe`](#download) · [On 3.0.0 to 3.0.5?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## 1 · Translations for your cards, from your own AI

- **Piyo ぴよ** can now hand your AI app (Claude Code, Codex…) the cards that have no translation. Each card comes with
  the line before and after its sentence when Surasura knows the source. Your AI translates them, and Surasura checks
  every answer before it writes anything.
- Only an **empty** translation field is filled. Nothing else on the card changes, and one **Undo** takes it all back.
- No API key and no call from Surasura: the translating is done by the AI you already use.
- **Backfill** says how many cards have no translation, with the next step and *Copy the prompt*.

## 2 · YouTube at a safe pace

- Surasura asks YouTube for **one thing at a time**, with short waits in between, as yt-dlp recommends.
- If YouTube asks *are you a bot*, Surasura **stops asking YouTube for 24 hours** and tells you when it will try again.
  Asking again right away only makes the block last longer. bilibili goes on as usual.
- An age-restricted video is no longer mistaken for the bot check.

## 3 · Books 2.x split into parts get their audiobook

- A book 2.x saved as `.txt` parts (`<title>_01.txt`, `_02.txt` …) is now **one book**. It can be lined up with its
  audiobook, and its cards get the narrator's voice, like an EPUB's.
- It asks once, by the title. *Dismiss* leaves the parts as texts. Your files are only read, never changed.
- A book's ⋯ menu now has **Its audiobook…** for any book that has none yet.

## 4 · Clearer help, fewer dead ends

- Help says plainly when cards are off, or when *Run things by themselves* is off, and opens that switch.
- One name everywhere for the cards Surasura makes: **Cards made for you**.
- *Up Next* says **No video · Link…** for a video it can't find, and the words open *Link…*.
- *New arrivals* says how many short texts were left out.
- *Settings › Piyo* shows your **last round** and how many words it had.
- *Needs you*: a video that isn't timed offers **Check again** first. A word Anki refuses for good offers **Skip this
  word**.
- *Add a folder…* opens at the newest folder Surasura reads (else Videos).

## Before | Now

| | Before (3.0.5) | Now (3.0.6) |
| :-- | :-- | :-- |
| **Cards without a translation** | Filled by hand, or with an add-on and an API key | Your own AI fills them through Piyo, checked, with one Undo |
| **YouTube's bot check** | Asked again and again (the block grew) | One call at a time; a day's pause, said with its time |
| **2.x books in `.txt` parts** | Text-only cards, no audiobook | One book, lined up with its audiobook |
| **The cards' switch** | Four names | *Cards made for you* |

## Updating

**On 3.0.0 to 3.0.5?** Surasura offers 3.0.6 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are.

## Coming from 2.5

1. Run **`Surasura-3.0.6-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
   your 2.5 folder is left exactly as it was.
2. Add your shows' and books' folders in setup — a 2.x tier keeps its place (NOW → Current, 6+ Months → Goal).
3. Your first Generate re-reads your library once. After that, the usual short ones.

Stop using 2.5 once 3.0 runs (the two could write the same files). Everything new in 3.0:
[the 3.0.0 notes](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0) · what came since:
[3.0.1](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.1) ·
[3.0.2](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.2) ·
[3.0.3](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.3) ·
[3.0.4](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.4) ·
[3.0.5](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.5).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.6-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
