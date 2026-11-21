# Surasura 3.0.17 — a faster start, a pause on every circle, Connect that asks first

<div align="center">

![Mine: the episode's cards come next](https://raw.githubusercontent.com/SonicSandbox/surasura/v3.0.0/docs/assets/images/readme/mine.png)

**The window opens at once and Settings in seconds. Every circle at the bottom left pauses with one click. Connect
asks before it makes your first cards.**

[Download `Surasura-3.0.17-setup.exe`](#download) · [On 3.0.0 to 3.0.16?](#updating) · [Coming from 2.5?](#coming-from-25) · [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0)

</div>

## What's better

- **A faster start:** the first screen shows at once, and Settings opens in seconds.
- **Pause with one click:** click a circle at the bottom left to pause what it runs by itself (it turns purple), click
  again to resume. *Pause all* is in each circle's right-click menu (or Shift-click). A pause holds everything that
  circle starts by itself, stays across a restart, and a half-mined episode carries on where it stopped.
- **Connect asks first:** on a new install, and after updating, nothing is mined until you say yes.
- **Connect only makes cards:** it no longer suspends cards by itself when too many wait. Only cards whose word
  is on your list count toward its limit, and *Needs you* says when cards it made earlier are set aside, with
  *Put back*.
- **Mine again, and the words it won't mine:** an episode's ⋯ has *Mine again*; the words whose cards you deleted in
  Anki are listed, with *Allow again*.
- **Count as known starts as Suspended + Marked:** a card you only suspend (a bad sentence) never counts as known by
  default. A choice you made yourself stays.
- **Settings, tidier:** the sections sit under Cards · Library · App, search stays pinned, a dot marks what you changed,
  and *Reset section* has an Undo. Every tooltip is short.
- **Lighter mining:** Anki Miner cuts as many clips at once as your PC can carry (fewer on battery), and a Beta switch
  runs it at low priority. Connect's own low priority now really takes.
- **Fewer non-words:** sighs, laughs and fillers standing alone (えっ, あはは, 唔) are no longer counted as words, a
  transcript's parentheses read as captions, and song lyrics (OP / ED) stay out of the counts — New arrivals' %
  too — unless you count them. Connect no longer makes cards from a song's lines.
- **Names, sharper:** Surasura takes a show's own clues to its characters' names, so far fewer of its lines are
  mistaken for names, and no word is lost.
- **Episodes stay in order:** a show's episodes always keep episode order, in Current too, and the toasts say where an
  item landed.
- **Cards in the right deck:** Connect's cards go to the deck Surasura shows, and earlier cards in Anki Miner's own deck
  can be moved, with Undo.
- **New arrivals, steadier:** one row per show, a skip clears at once, an unreachable share never freezes it, and hato's
  series folders join their show.
- **Learn two shows at once** (the side-by-side switch's new name): the ✓ chip counts every word of an episode that has
  a card, wherever it was made.
- **Covers:** *Look for a cover again* unlocks a cover, and a plain cover can be chosen.
- **Junban's marks:** a set-aside card loses its purple *later* mark once its word is on your list or studied.
- **Smaller fixes:** Up next's list keeps its place on a click; the video audio check runs once per release, beside the
  mining; *Only i+1* says some of its cards are for words not on your list.

Thanks to **Mattias** for the ideas behind the faster start, episodes keeping their order, and the audio check that
never holds mining up.

## Before | Now

| | Before (3.0.16) | Now (3.0.17) |
| :-- | :-- | :-- |
| **Opening Settings** | Up to 20 s on a big library | Seconds |
| **Pausing mining** | Settings, or a circle's Stop | One click on its circle |
| **First run with Connect on** | Mined as soon as it could | Waits for your yes |
| **Too many new cards waiting** | Connect suspended its own cards, silently | Connect waits; only cards on your list count |
| **A card you only suspend** | Counted as known | Not counted (Suspended + Marked) |
| **A word whose card you deleted** | Never mined again, and no list | Listed, with *Allow again* |
| **えっ / あはは / 唔 on their own** | Counted as words | Not words |
| **A show's new episode in Current** | Could land ahead of an earlier one | Always in episode order |
| **A skip with the share offline** | The window nearly froze | Clears at once |

## Updating

**On 3.0.0 to 3.0.16?** Surasura offers 3.0.17 by itself: press **Update now**. It updates in place; your library,
words and settings stay as they are.

**Piyo's helper running from 3.0.7 or earlier** still holds this one update: the update window asks you to **Stop it**
once. From 3.0.8 on, it steps aside by itself.

## Coming from 2.5

1. Run **`Surasura-3.0.17-setup.exe`** (no admin needed). Your **known words, word lists and settings** come with you;
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
[3.0.16](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.16).

<details>
<summary><b>Known limits</b></summary>

- **Desktop Anki must be open** for cards to be made and ordered. Chinese cards need Anki Miner 3.12 or later.
- **Listening rounds** are Japanese only, and need the AI voice (beta) installed.
- On a **very large library** (20,000+ files), the list can hitch for a moment as a new episode comes in.
- Windows only. The installer isn't signed: Windows may say *Windows protected your PC* → **More info** →
  **Run anyway**.

</details>

## Download

| Windows 10 or 11 | `Surasura-3.0.17-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
