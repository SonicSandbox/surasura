# Surasura v2.5.0 - Release Notes

> ⚠️ **After updating, don't open an older Surasura's (2.4.0 or earlier) Content Manager on this library.** It can
> show graduated files in NOW again, and move or rename files on Graduate and Demote. The next 2.5 start puts it
> right, and asks you first before a big change.

## Summary
- **Instant Library re-order** - a drag saves in about 1–2 ms, instead of rewriting the whole order file
- **Crash-safe** - files saved pre-and-post move with redundancy
- **Undo upgrades** - More robust, handles multiple undos in content manager
- **Content Manager stays smooth** - coming back to the window no longer freezes it while it checks your folders
- **New episodes join their show** - in NOW or Soon, wherever the show already is
- **Graduate and Demote move no files** - the tier is kept by the library itself
- **Updates wait for you** - instead of failing while something is still running

> On its first start, 2.5 moves your library order into its new store, once, in the background. Generate gives the
> same word lists as before, and nothing is re-analysed.

## Library Order
| Before | Now |
| :-- | :-- |
| Every drag rewrote the whole order file (~1.3 MB for 2,000 files) | A drag saves only the rows that moved |
| A crash during a save could leave a half-written file | A crash leaves the order before or after the move, never a mix |
| Graduate and Demote moved files between the tier folders | No file moves: the tier lives in the library store |

- `master_manifest.json` stays, kept up to date as a second copy, so older versions and tools that read it still work.
- A damaged store offers **Repair**, which backs up first and never deletes anything.

## Undo
| Before | Now |
| :-- | :-- |
| Undo restored one snapshot, erasing every change made after it | Undo reverses your changes one at a time, newest first |
| Undo of an Add deleted the copied files | They go to `.trash` (kept 30 days) |

## Content Manager
| Before | Now |
| :-- | :-- |
| Coming back to the window re-read every folder (0.9 s at 20,000 files) | That check runs in the background |
| A new episode went wherever its folder said | It joins its show in NOW or Soon; a new show goes to the top of NOW |

- Ctrl-click adds a row to the selection; Shift-click extends it.

## Updates
| Before | Now |
| :-- | :-- |
| **Update now** during a Generate or an open Content Manager could fail | The update waits, names what's still running, and offers **Stop it** |

## Also
- The **悟** (Immersion Architect) button is gone: the module was deprecated.
- ⚖️ **One library, one machine.** Two PCs syncing one library folder isn't supported.
- Dictionary data is unchanged from 2.4 (JMdict 2026-09-28); every source: **Settings → Data & System → Data
  credits**.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md) · [How Parsing Works](https://github.com/SonicSandbox/surasura/blob/main/docs/How%20Parsing%20Works.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** One-click in-app update: **⬆ Update available** at the bottom-left of the dashboard →
> **Update now**. Your known words, lists, content, results, settings and library order are never touched.

Updating by hand (always available):
1. *(Optional)* Back up your `User Files` folder somewhere safe.
2. Download **`Surasura_v2.5.0.zip`** and extract it to a new folder.
3. Copy your **`User Files`** folder, your **`data`** folder **and your `settings.json`** from the old folder into
   the new one, replacing the new ones. `settings.json` holds every setting you changed; the new folder comes with a
   fresh one.
4. Run `Surasura.exe` from the new folder.

On **v1.9 or earlier**, also move your **User Files** into `User Files/<language>/` and your **content** into
`data/<language>/`.
