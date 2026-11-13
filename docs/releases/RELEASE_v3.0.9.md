# Surasura 3.0.9 — Junban on AnkiConnect Extended, audiobooks that find their way back, and a path you can walk again

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**順 Junban now sorts your cards on AnkiConnect Extended too. A removed audiobook comes back when you pick its folder for the book. *Your path* keeps what you did, so you can try it again.**

[Download `Surasura-3.0.9-setup.exe`](#download) · [On 3.0.0 to 3.0.8?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## 1 · 順 Junban

- **Junban works on AnkiConnect Extended.** Where Extended refuses a card's new position, Junban asks Anki's own
  reposition instead: the same order, and Undo stays exact. Plain AnkiConnect works as before.
- **A Reorder you start picks up where a stopped one left off.** Connect's reorder runs that stopped part way are
  taken over, and one Undo puts the deck back to how it was before all of them.
- **A run on another deck in the way:** one press, *Put that one back, then reorder*. A run file held for a moment
  (by an antivirus or a cloud folder) is read again quietly before you are asked.

## 2 · Audiobooks

- **A removed audiobook comes back** when you pick its folder for its book.
- ***Add the narrator's voice*** now reaches the cards an earlier copy of the book made (a 2.x split `.txt`, say).
- **A book's own transcript is recognised** when the narrator reads the title first.

## 3 · Your path, and quieter screens

- **✦ → Your path keeps the steps you've done**, each with **Show me**, so you can try one again. Steps that can't
  apply yet wait under **NOT YET**; their **?** says when.
- **A ? instead of explainer lines:** the Next card, the path's steps and a few Settings rows keep their one line
  behind a small **?** (hover, Tab, or click). What you need to act on stays in sight.

## Before | Now

| | Before (3.0.8) | Now (3.0.9) |
| :-- | :-- | :-- |
| **Junban on AnkiConnect Extended** | Couldn't sort | Sorts, Undo exact |
| **A stopped reorder run** | Undo it first | A new Reorder takes it over |
| **A removed audiobook, folder picked again** | Nothing came in | It comes back |
| **An earlier copy's cards** | No narrator's voice | *Add the narrator's voice* reaches them |
| **Title read first in the audiobook** | Not that book's | Recognised |
| **A done step on Your path** | Folded away | Kept, with Show me |
| **Explainer lines** | Always in sight | Behind a ? |

## Updating

**On 3.0.0 to 3.0.8?** Surasura offers 3.0.9 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are.

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.9-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.8](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.8).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.9-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
