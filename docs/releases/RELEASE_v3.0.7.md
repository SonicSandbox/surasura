# Surasura 3.0.7 — steadier presses, moves that save at once, and a guide to what's new

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**A rare crash just after a press is fixed. A move saves at once, even while Surasura is reading your library. A new ✦ shows what changed and the next useful step.**

[Download `Surasura-3.0.7-setup.exe`](#download) · [On 3.0.0 to 3.0.6?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## 1 · Steadier

- A **rare crash just after a press** (a button, a menu, closing setup or the sort screen) is fixed at its cause, in
  every place it could happen.
- **A move saves at once**, even while Surasura is reading your library in the background. Before, it could wait
  a noticeable moment.

## 2 · ✦ What's new and *Your path*

- A **✦** beside the **?** in the header glows after an update until you open it. It lists what changed, the things
  for you first, with **Show me** to go straight there. Smaller fixes fold into one line.
- **Your path**: a **Next** card on Current shows one useful step at a time: see a show's words, watch it, get your
  first cards. Later steps (順, Backfill, an audiobook, hato, Piyo) come only once they're useful. **Not now** puts it
  away.
- Everything it reads is already on your PC. Nothing is sent.

## 3 · Clearer setup and Settings, fewer dead ends

- **Settings say what each part does for you**, with plain names first: *Card order* (順 Junban), *Fill your cards*
  (Backfill), *Subtitles for videos without them* (hato). What a part still needs shows only while it's missing,
  with **Show me**.
- **An audiobook brought in alone** is named an audiobook. Surasura offers to read its folder, and *Needs you* asks
  which book it belongs to.
- **A title you removed, added again**, offers **Put back** or **Add as new**, never just "taken". Remove now says
  it stays in *Removed* for 30 days, with a button to open it.
- **A failed Generate** says why in plain words, with **Generate again** and **Report a problem**.
- **Setup** says plainly that your folders are read where they are, never moved or changed. Card order waits for
  Anki instead of asking too early.
- The header's level reads as **about how many words** you know.
- File pickers for shows and books open in your **Videos** folder. The ⋯ menu opens faster at high scaling.

## Before | Now

| | Before (3.0.6) | Now (3.0.7) |
| :-- | :-- | :-- |
| **Right after a press** | A rare crash | Fixed at its cause |
| **A move while the library is read** | Could wait a moment | Saves at once |
| **What changed in an update** | Only in these notes | ✦ in the app, with Show me |
| **An audiobook alone** | "Only text and subtitle files" | Named, and asked which book it is |
| **A removed title added again** | "Taken" | Put back, or Add as new |

## Updating

**On 3.0.0 to 3.0.6?** Surasura offers 3.0.7 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are.

## Coming from 2.5

1. Run **`Surasura-3.0.7-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.6](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.6).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.7-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
