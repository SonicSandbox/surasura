# How to Update Surasura

An update changes only the program. **Your library, known words, word lists and settings are never touched.**

## In the app (recommended)

1. A new version shows as **Update ready** in the bottom bar. It never interrupts you: click it when you're ready.
2. **Update now**: only the parts that changed are downloaded, each one checked. Surasura closes and opens again by
   itself on the new version; if the new one doesn't start, the old one comes back.
3. Not now? **Later** keeps it in the bar. **Skip this version** doesn't offer it again (the next one comes as usual);
   **Settings › App › Offer vX again** brings it back. **What's new ↗** opens its notes.

- **Settings › App › Check for updates**: off, Surasura asks GitHub nothing at start.
- **Settings › App › Update automatically**: one-click updates for small releases. A big release always downloads by
  hand: **Download** opens its page.
- An update that can't finish (no internet) leaves your version running, and one cut off (a power cut) finishes or
  undoes itself at your next sign-in. What went wrong is noted in
  `%LOCALAPPDATA%\Houseki\Surasura\update\update_report.txt`: if it keeps happening, send **Report a problem** or
  attach it to an issue on [GitHub](https://github.com/SonicSandbox/surasura/issues).

## By hand

Download the latest **`Surasura-X.Y.Z-setup.exe`** from the
[Releases page](https://github.com/SonicSandbox/surasura/releases) and run it (no admin needed). Your library and
settings stay where they are.

## Where your things are

| What | Where |
| :-- | :-- |
| The program | `%LOCALAPPDATA%\Programs\Surasura` |
| Your library: known words and word lists (`User Files\<language>\`) | the folder you chose at install (default `Documents\Surasura`) |
| Your settings (`settings.json`) and the word index | `%APPDATA%\Houseki\Surasura\` |
| Surasura's own files (your library's order, covers, logs) | `%LOCALAPPDATA%\Houseki\Surasura\` |

- Your shows and books stay in their own folders: Surasura reads them where they are.
- Coming from 2.x: at its first start Surasura 3.0 copies your known words, word lists and settings over, and leaves
  your 2.x folder exactly as it was. Add your shows' folders again in setup.

## Release Notes

See the [Releases page](https://github.com/SonicSandbox/surasura/releases) for what's new in each version.
