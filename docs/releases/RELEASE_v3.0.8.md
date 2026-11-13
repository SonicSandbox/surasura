# Surasura 3.0.8 — audiobooks that join their book, an update Piyo doesn't block, and a second pick for an episode's video

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**The audiobook you pick for a book now joins that book. Piyo's helper steps aside for an update by itself. An episode linked to the wrong video can pick again.**

[Download `Surasura-3.0.8-setup.exe`](#download) · [On 3.0.0 to 3.0.7?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## 1 · A book's audiobook joins the book

- **The audiobook folder you pick for a book joins that book**, whatever its files are called. Before, it could land
  in *New arrivals* as a title of its own.
- **Pick its audiobook…** also lists an audiobook paired with a copy of the same book, so **a wrong pairing can be
  fixed**. Undo puts it back.

## 2 · Updates with Piyo running

- **Piyo's helper** (the connection your AI app keeps to Surasura) **steps aside by itself** once an update is ready.
  You no longer have to close it by hand.

## 3 · An episode linked to the wrong video

- **Change its video…** on the *Not timed* card and the episode's ⋯ lets you pick the right video. Its timing is
  checked again, and Undo puts the old link back.

## Before | Now

| | Before (3.0.7) | Now (3.0.8) |
| :-- | :-- | :-- |
| **A book's audiobook folder** | Could land in New arrivals | Joins the book |
| **A wrong audiobook pairing** | Stuck | Fixed with Pick its audiobook… |
| **Updating with Piyo open** | Close its helper by hand | It steps aside by itself |
| **An episode on the wrong video** | No way to pick again | Change its video… |

## Updating

**On 3.0.0 to 3.0.7?** Surasura offers 3.0.8 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are.

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.8-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.7](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.7).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.8-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
