# Surasura 3.0.16 — shows mined from the first episode, steadier updates

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**Connect mines a show from its first episode, and an update that was cancelled or cut off never blocks the next
one.**

[Download `Surasura-3.0.16-setup.exe`](#download) · [On 3.0.0 to 3.0.15?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## What's better

- **Connect mines a show from its first episode:** put any episode in line and its earlier unmined episodes come
  with it, earlier seasons too, first episode first.
- **⛏ Mine instead of the hourglass:** an episode Connect won't mine by itself shows a Mine button, so you can start
  it with one press.
- **Junban stays still when nothing moved:** coming back to the window no longer re-runs it when nothing changed.
- **Cleaner card audio:** when a word is on several lines, Connect cuts its card from a line nobody else talks over.
- **Side by side stays put:** no flicker and no order change after Connect mines an episode.
- **Steadier updates:** a cancelled or interrupted update never blocks the next one, a dropped download picks up
  where it stopped, the update says what it's waiting for, and a network failure says so plainly, with **Try again**.

Thanks to **Mattias** for the ideas behind Junban staying still and the cleaner card audio.

## Before | Now

| | Before (3.0.15) | Now (3.0.16) |
| :-- | :-- | :-- |
| **A show whose first episodes were already in line** | Mined from a later episode on | Mined from episode 1 |
| **An episode Connect won't mine by itself** | An hourglass | A ⛏ Mine button |
| **Coming back to the window, nothing changed** | Junban ran again | Nothing runs |
| **A word on several lines** | Any line, even one talked over | A line nobody talks over |
| **Side by side after Connect mines an episode** | A flicker, the order moved twice | No flicker, no move |
| **Update now after a cancelled update** | Could fail with WinError 183 | Updates |
| **A dropped download** | The update failed | It picks up where it stopped |
| **No connection** | A raw error | Plain words and **Try again** |

## Updating

**On 3.0.0 to 3.0.15?** Surasura offers 3.0.16 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are.

**Did an update stop with WinError 183?** 3.0.16 gets past it: press **Update now** again.

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.16-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.15](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.15).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- **Listening rounds** are Japanese only, and need the AI voice (beta) installed.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.16-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
