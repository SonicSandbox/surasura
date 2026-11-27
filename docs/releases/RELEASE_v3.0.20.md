# Surasura 3.0.20 — a first run that doesn't make you wait, *Mine only episodes I've pre-studied*, hato's honest update

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**Setup now reads your library behind its own steps and asks how you'd like to start, small or full. Connect can wait
for the episodes you've pre-studied, and hato's update says what it's really doing.**

[Download `Surasura-3.0.20-setup.exe`](#download) · [On 3.0.0 to 3.0.19?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

> ⚠️ **Your library is read again once after the update.** The first Generate takes longer, once: about
> 1 min 27 s instead of 11 s on a 2,000-file library. After that, the usual short ones.

## What's better

- **A first run that doesn't make you wait:**
  - **What are you watching right now?** Setup shows your shows as posters, newest first, with
    *Search your shows*. Pick one and say *I'm on episode* N: the episodes you've already seen get no cards.
  - Your library is read **behind** setup's steps, not under one cover. The read takes as long, but
    on a 2,000-file library the 87 s under one cover becomes at most 5.5 s at *What are you watching right now?*,
    then at most 82 s at *Your list*, less the time you spend on the pages in between.
  - **How would you like to start?** After *Your list*, choose **Try it small** (your next 3 episodes, up to 50 cards
    waiting), **Full start** (your next 20 episodes, up to 300: the start you had before, picked for you) or
    **Pre-studied only**. *Start* makes your first cards.
  - **Ready for more?** Started small? When those cards are nearly studied, Surasura asks once:
    *Next 20 episodes* or *Keep it small*.
- ***Mine only episodes I've pre-studied*** (*Settings › Anki & mining*, above *Keep up to*; off by default): Connect
  makes an episode's cards by itself only once you've marked it pre-studied in the journey. A waiting episode's stone
  says why. *Mine now* still makes them at once.
- **hato's update tells the truth:** the hato row in Settings says *updating…* only while hato really installs. A
  downloaded update that waits for you reads *ready in hato* (hover: open hato to install it). **With hato 1.5.0**,
  released beside this update, Surasura has hato install it quietly by itself.
- **A clearer Soon line:** the line between Current and Soon is a thin Surasura-coloured line that fades to the right,
  in Night and Light. The journey's show picker uses the same line.
- **Fixes from your Send reports:**
  - Removing a deck clears its *N waiting*. Changing decks (in Anki, *Set up again* or Anki Miner's setup) refreshes
    the *Decks* row and its count.
  - Connect and the card order count the same known words as your list.
  - *Make my new cards again…* with Anki closed says Anki isn't open, and that nothing was deleted.
- **Faster:** after each card Connect makes, your known words are read again in 0.18 s instead of 0.84 s, and the card
  order's re-sort reads them in 0.07 s instead of 0.44 s (2,000 files, 11,000 known words). Generate and the window
  are as fast as in 3.0.19.
- **Also fixed:**
  - Closing during *Still finishing*: once everything it named has finished, the window closes by itself.
  - The window's saved first screen is no longer lost now and then (a virus scan holding the file): the start stays
    quick.
  - A ▶ clip is no longer cut twice.
  - Words: a verb stem + つかれる is one word (歩き疲れる, 喋り疲れる); 棟 after a word is part of it (研究棟, B棟), no
    longer the word むね.

## Before | Now

| | Before (3.0.19) | Now (3.0.20) |
| :-- | :-- | :-- |
| **Setup's library read** (2,000 files) | About 87 s under one cover | ≤ 5.5 s at *What are you watching right now?*, then ≤ 82 s at *Your list*, less your time on the pages between |
| **Your first cards** | 20 episodes, up to 300 waiting | *Try it small*, *Full start* or *Pre-studied only* |
| **Cards only for pre-studied episodes** | — | *Mine only episodes I've pre-studied* |
| **hato's downloaded update** | *updating…* for days | *ready in hato*, or installed quietly with hato 1.5.0 |
| **Known words read after each new card** | 0.84 s | 0.18 s |

## Updating

**On 3.0.0 to 3.0.19?** Surasura offers 3.0.20 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are. Your library is read again once: the first Generate takes longer, once
(about 1 min 27 s instead of 11 s on 2,000 files).

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

**hato:** update hato to 1.5.0 too (hato offers it by itself) for the quiet install.

## Coming from 2.5

1. Run **`Surasura-3.0.20-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
   your 2.5 folder is left exactly as it was.
2. Add your shows' and books' folders in setup — a 2.x tier keeps its place (NOW → Current, 6+ Months → Goal).
3. Your library is read while you go through setup's steps. After that, the usual short Generates.

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
[3.0.18](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.18) ·
[3.0.19](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.19).

<details>
<summary><b>Everything in 3.0.20, in detail</b></summary>

**Setup (the first run)**
- The order: language → what you know → your shows → card order → cards made for you → *Watching now* (and the sort)
  → *Your list* → *How would you like to start?*
- *What are you watching right now?*: your shows as posters in a row, newest first and the newest
  picked; *Search your shows*; *I'm on episode*; *None of these* (after a pick, that show stays at the top of
  Current); ← → to choose, Enter to go on.
- The library is read behind the steps: the scan before *Watching now*, the words before *Your list*.
  *Finish later* during the read stops between files; the window reads the rest. *Use every core* is still on the
  loading step. Setup reopens on the step after the furthest one you reached.
- *How would you like to start?* shows only while *Make cards* waits for a yes and Connect is on. Your list's numbers
  fill in while it's made (*Making your list · N %*). *Try it small*: next 3 episodes, up to 50 waiting. *Full start*:
  20 episodes, up to 300 (picked by default). *Pre-studied only*: the full start with *Mine only episodes I've
  pre-studied* on. *Skip* leaves *Make cards* in *Needs you*.
- *Ready for more?* appears on *Needs you* only after *Try it small*, once 10 or fewer of its cards
  wait in Anki. *Next 20 episodes* raises *Keep up to* to 300 (never lowers a higher number) and mines your next 20.
  *Keep it small* ends it for good. Moving the line in Settings takes the card away.

***Mine only episodes I've pre-studied***
- On: every mine Connect starts by itself waits for the journey's pre-studied mark (Current's top, a show's earlier
  episodes, a gap's *Make their cards*, the first run's cards). A press still mines: *Mine now*, *Mine anyway*, ⇄,
  *Add now*, *Make my new cards again…*.
- A mark, an Undo or the switch wakes Connect at once. A waiting episode is never dropped. One switch for every
  language. Off: nothing changes, your list included.

**hato**
- *updating…* only while hato is installing (hover: hato is installing it by itself, quietly). A downloaded release
  waiting for a press in hato's window: *ready in hato* (hover: open hato to install it).
- With hato 1.5.0, Surasura asks hato's quiet install, the same rules as hato's daily run.

**The window**
- The Current / Soon line: 1 px, cyan → blue → purple, fading to the right; the word *Soon* is in its hover. The
  journey picker's tier headings carry it.
- *Still finishing* (closing while, say, *Tidying your library* runs) goes away once every job it named has ended, and
  the window closes as Quit. A job still running keeps it asking.
- *What's new* opens as quickly with every release's notes as with a few: its first layout no longer walks every
  release (17 releases' notes: 5.4 → 1.3 ms).
- The saved first screen (`window_cache`) is read and saved patiently while a scan or the old reader holds the file.

**Connect and Anki**
- Removing a deck clears its *N waiting*; a deck change from the Anki window, *Set up again* or Anki Miner's setup
  refreshes the *Decks* row and reads the count again.
- After each card Connect makes, the known words are read 0.84 → 0.18 s; the card order's re-sort 0.44 → 0.07 s
  (2,000 files, about 11,000 known words; 3.0.19 and 3.0.20 timed side by side).
- Connect's sentence pick and the card order now count exactly the known words Generate counts (they used to read
  them without the library's name tables). Your Anki order or a sentence pick can differ from 3.0.19's where those
  words matter.
- *Make my new cards again…* with Anki closed: "Anki isn't open (or isn't answering): open it, then try again. Nothing
  was deleted."
- Known words, settings and name tables are read once per Generate instead of again and again.
- A ▶ clip is no longer cut twice when two presses meet.

**Words (Japanese)**
- A verb stem + つかれる is one word: 歩き疲れる, 待ち疲れる, 喋り疲れる.
- 棟 right after a word is part of it (研究棟, B棟), no longer the word むね.
- These two rules re-read every library once (engine 52, store 32).

**The same as 3.0.19** (timed side by side): Generate on 2,000 and 20,000 files, the redraw after a move, a small
Chinese library, opening a 20,000-file library, and memory.

</details>

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- **Listening rounds** are Japanese only, and need the AI voice (beta) installed.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.20-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
