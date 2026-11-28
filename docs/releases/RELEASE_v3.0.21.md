# Surasura 3.0.21 — *Add sound*, cards left to study, a start that opens at once, new words for mined episodes

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**Cards without sound get their own line's audio with one press. The window opens at once, even after an update.
Connect gives the episodes it already mined their new words, and ⇄ works on every subtitle line.**

[Download `Surasura-3.0.21-setup.exe`](#download) · [On 3.0.0 to 3.0.20?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

> ⚠️ **Your library is read again once after the update.** The first Generate takes longer, once: about
> 1 min 26 s instead of 11 s on a 2,000-file library (about 14 min instead of 1 min on 20,000 files). After
> that, the usual short ones. The first sync with Anki also reads all your cards once.

## What's better

- ***Add sound*** (*Settings › Anki & mining › Card sound*): cards without sentence audio get the sound of their own
  line — from your episode, from the audiobook, or the same sentence in another episode — with one press, and one Undo.
  The count beside it says how many cards can get sound now.
  - A book card with no sound is made as a sentence card; it becomes your usual card once it has sound.
- **The AI voice (beta)** reads the cards that have no real sound, line by line: four voices, and a listen-back check.
  It reads only cards due soon, while the PC is quiet. The first time cards wait for it, *Needs you* offers
  **Set it up**. *Remove all AI audio…* takes its clips off again (your own audio stays).
- **The window opens at once**, even right after an update: it shows your last screen with its numbers faded, then
  fresh ones. On a 20,000-file library, about 4.0 s → 1.2 s after an update (an ordinary start
  0.9 s).
- **The green card number counts the cards still left to study**, so it falls as you learn them (✓ when none are
  left). Its tip still shows your record.
- **New words for episodes already mined:** when your list grows, Connect mines the new words of the episodes it
  already mined, by itself. Or press ***Mine the new words*** on an episode's or a show's ⋯. Words Anki Miner already
  turned down aren't asked for again.
- **⇄ and *Add now* work on every subtitle line**, with or without its video, and whatever *Play a line's own audio*
  says. A swap whose video isn't on this computer waits in *Needs you*, which asks where it is (*Find videos*).
  - *Add now* on a word that already has a card gives that card the new line, as ⇄ does.
  - Either press starts Connect when it isn't running.
- **Words (Japanese):**
  - A studied card written in kana alone counts for the word its own sentence shows: かなう in a 敵う sentence makes
    敵う known, not 叶う.
  - A set phrase inside a longer one counts too (いい加減, にしても, といえば, 気が付く…).
  - A plain-kana つかれた (もうつかれた) is 疲れる, "be tired", no longer 突く; 嘘つかれた reads as before.
- **Fixes:**
  - Quitting right after an update no longer leaves a background worker running that held the program folder at
    the next update.
  - The pitch accent sits on its kana at every size and clears the word.
  - The journey's *Pre-studied* chip fits on one line again.
  - A show's songs, left out of your list, are left out of the rarity numbers and the list's floor too.
  - A hato episode with no show joins the show whose videos sit beside it.
  - Settings' level numbers update by themselves after a sync, a Known / Ignore mark, a Generate or a new file.
  - A Chinese library with no manifest gets its library store at its next Generate.
  - Anki Miner starts once, not three times, when Settings › Anki & mining opens and before *Add sound*.
- **Speed:** Generate takes a little longer than in 3.0.20 (20,000 files: 64.8 s instead of 62.5 s;
  2,000 files: 11.4 s instead of 11.0 s): it offers more sentence lines, from the new set phrases.

## Before | Now

| | Before (3.0.20) | Now (3.0.21) |
| :-- | :-- | :-- |
| **Cards without sound** | Stay silent | *Add sound*: their own line, the audiobook, or the AI voice (beta) |
| **The window after an update** (20,000 files) | 4.0 s to open | 1.2 s, at your last screen |
| **The green card number** | Cards made | Cards still left to study |
| **Episodes already mined** | Mined once | New words added as your list grows, or *Mine the new words* |
| **⇄ on a line without its video** | Not offered | Waits in *Needs you* for the video |

## Updating

**On 3.0.0 to 3.0.20?** Surasura offers 3.0.21 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are. Your library is read again once: the first Generate takes longer, once
(about 1 min 26 s instead of 11 s on 2,000 files).

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.21-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.19](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.19) ·
[3.0.20](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.20).

<details>
<summary><b>Everything in 3.0.21, in detail</b></summary>

**Card sound** (*Settings › Anki & mining › Card sound*)
- *Add sound* and its count: a card with no sentence audio gets, in this order, its own line cut from your episode,
  the line from its audiobook (a book lined up with one), or the same sentence from another episode. One press, one
  Undo (newest first, and only where the card still holds what was written).
- A book's card with no sound is made as a sentence card under the audio card; *Add sound* makes it the audio card
  again once it has sound.
- The AI voice (beta): *Use the AI voice (beta) for cards with no real sound*; four voice packs; cards voiced line by
  line; a listen-back check. It voices only cards due within Card sound's window, while the PC is quiet. Its credit
  lines are in *Credits*.
- The first time cards wait for the voice, *Needs you* shows a one-time card: *Set it up* (its size first, the
  voices, your choices and a test) or *Not now*.
- *Remove all AI audio…*: a count first, then the AI voice's clips come off your cards; a copy of each is kept, and
  Undo puts them back. Your own audio and real sound stay. The order of AI clips is kept even when two are written
  within one clock step, so the count is right.
- Anki Miner starts once, not three times, when setup looks again, when Settings › Anki & mining opens and before
  *Add sound*; Card sound's audiobook step starts none of its own when the press already started one.

**The start**
- The window opens at the cached first screen, numbers faded, and an update's numbers come from the plan's first
  line until Generate's fresh ones arrive. 20,000-file library, built, side by side with 3.0.20: 4.0 s →
  1.2 s to the open window after an update; 0.9 s on an ordinary start.
- Quitting right after an update no longer leaves a background worker running (it held the program folder at the
  next update); a crash or Task Manager also ends the indexer.
- The covers scan at the start reads less (source markers only where a folder has two books to choose between; each
  folder listed once). The first frame itself is unchanged.

**The journey and Connect**
- The green number on the card chip counts cards still left to study (✓ at none); its tip keeps the record.
- New words for mined episodes: when your list grows, each mined episode still ahead gets a job for only its newly
  listed words, under *Keep up to*. *Mine the new words* (an episode's ⋯, a show's ⋯) goes first, past the cap. Words
  Anki Miner already turned down for the episode aren't asked for again.
- ⇄ and *Add now* on every subtitle line: the line is found in its subtitle at the press. Without the video the swap
  queues: Connect's job waits on *No video*, and *Needs you* asks where it is. *Play a line's own audio* governs ▶ only.
  A subtitle whose record names no video finds the one Connect already knows for it.
- *Add now* on a word Connect already made a card for gives that card the new line (the press becomes its ⇄) instead
  of turning it down.
- A ⇄ or *Add now* press starts Connect when it is on and not running; presses in a row start it once.
- The end card's *Pre-studied* chip stays on one line (its stone had no size and pushed the words onto three).
- The pitch graph sits on its kana at every size, 6 px clear of the word; the keys sheet says *Shift is left free for
  Yomitan.*
- A hato episode with no show joins the show whose videos sit beside it; ones already filed under a "Season NN"
  title are moved back once, with one Undo.

**Words and Generate**
- Set phrases inside longer ones count (いい加減, にしても, といえば, 気が付く…); an inner phrase in a sentence you
  know is known.
- A plain-kana つかれた counts as 疲れる; where the words before it are what a つく verb takes (嘘つかれた,
  不意をつかれた), it reads as before.
- A show's songs, left out of the list, are left out of the Rarity readout, Automatic rarity and the list's floor.
- A studied Japanese card written in kana alone counts for the word its own sentence shows: かなう in a 敵う
  sentence makes 敵う known, 叶う and 適う stay unknown. A kana card with no sentence kept reads as before. The first
  known-words sync after the update is a full one: it keeps each kana card's sentence, and writes nothing to Anki.
- These rules read every library again once (engine 56, store 33).
- After a later update that changes only how words are read, the first Generate is shorter: 20,000 files
  71.1 → 63.7 s, about 450 MB less memory (side by side with 3.0.20). After a set-phrase rule change,
  103.2 → 90.5 s.
- A warm Generate no longer re-checks every song file. A Generate opens the library store fewer times, and reads
  your known words once.
- New arrivals run the song rule once per show when a stored show is read again.
- A Chinese (or any) library with no manifest gets its library store at its next Generate.

**Settings**
- The level numbers update by themselves after a sync, a Known / Ignore mark, a Generate or a new file, and no longer
  re-read on a move.
- Settings › Anki & mining builds sooner when you go straight to it.

**Timed side by side with 3.0.20:** a warm Generate on 2,000 files 11.0 → 11.4 s, on 20,000 files 62.5 → 64.8 s
(10 runs each in two bookings; 3.0.19 read 11.7 s and 64.2 s beside them); the window after an update 4.0 → 1.2 s.

</details>

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made, ordered and given sound. Chinese cards need Anki Miner 3.12 or
  later.
- **The AI voice** is a beta and Japanese only; its one-time install is large.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.21-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
