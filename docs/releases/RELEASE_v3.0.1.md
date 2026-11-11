# Surasura 3.0.1

A fix release on top of 3.0. New to 3.0? [See everything that's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0).

## What's better

| | Before (3.0.0) | Now (3.0.1) 🛡️ |
| :-- | :-- | :-- |
| **Windows Defender** | With *Controlled folder access* on, Windows could quietly block Surasura from saving your library in **Documents** | New installs keep the library in **`C:\Users\<you>\Surasura`**, outside the folders Defender guards |
| **A blocked save** | Saves failed without saying why | Surasura says Windows is blocking it and offers **Move my library to C:\Users\<you>\Surasura** or **Allow Surasura in Windows Security** |
| **Finishing a show** | Anki's card order waited for the next Generate (13 s on a small library, almost 2 minutes on a big one) | Anki's order moves **in seconds** |
| **A card's reading** | Could differ from the line (a phrase's dictionary reading) | Matches the line as it's written (いい感じ → いいかんじ, 日本 → にほん) |
| **⋯ → Goal** | Could feel a little slow at high display scaling | Under 16 ms at every scale, up to 250 % |

- **Your library is never moved without you.** An existing library in Documents stays where it is and keeps working.
  Move it only if you want to: **Move my library** copies every file and checks it before switching, and one
  **Undo** points back at the old folder.
- The installer tells you when Controlled folder access is on, and why it suggests the new folder.
- Behind it: test-reliability fixes, so releases like this one ship sooner.

## Updating

- **On 3.0.0?** Surasura offers 3.0.1 by itself. Press **Update now**.
- **Coming from 2.5?** Run **`Surasura-3.0.1-setup.exe`** (no admin needed). Your **known words, word lists and
  settings** come with you, and your 2.5 folder is left exactly as it was. Your first Generate re-reads your library
  once. [What's new in 3.0](https://github.com/SonicSandbox/surasura/releases/tag/v3.0.0#coming-from-25)

## Download

| Windows 10 or 11 | `Surasura-3.0.1-setup.exe` (below) |
| :-- | :-- |

The installer isn't signed: if Windows says *Windows protected your PC*, choose **More info → Run anyway**.

Surasura 3.0 is free software (GPL-3.0-or-later): its source is on [GitHub](https://github.com/SonicSandbox/surasura).
Every bundled library's licence text ships with it (`_internal\licenses`, listed in *Settings › App › Data credits*).

**Questions, ideas, bugs:** [the Surasura Discord](https://surasura.dev/app/discord) · **Report a problem** in the app ·
[the README](https://github.com/SonicSandbox/surasura#readme)
