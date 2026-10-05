# Surasura v2.5.0 - Release Notes

## Summary
- **Library order saves in a blink** - a drag saves in about 1–2 ms, instead of rewriting the whole order file
- **Crash-safe** - a crash or power cut never leaves your library order half-saved
- **Real Undo** - undo any change you made in the Content Manager this session, one at a time
- **Content Manager stays smooth** - coming back to the window no longer freezes it while it checks your folders
- **Generate answers at once** - its checks run in the background
- **New episodes join their show** - in NOW or Soon, wherever the show already is
- **Graduate and Demote move no files** - the tier is kept by the library itself
- **Updates wait for you** - instead of failing while something is still running
- **Immersion Architect (悟)** - removed (it was deprecated)

> After updating, Surasura moves your library order into its new store once, in the background. Generate gives the
> same word lists as before, and nothing is re-analysed. Afterwards, don't open the Content Manager of an older
> Surasura on the same library.

## The Library Store
Your library order (each file's tier, place and state) now lives in a small database per language, in Surasura's
own folder. `master_manifest.json` stays where it is, and Surasura keeps it up to date as a copy. Older versions and
other tools that read it keep working.

| Before | Now |
| :-- | :-- |
| Every drag rewrote the whole order file (~1.3 MB for 2,000 files) | A drag saves only the rows that moved |
| A crash during a save could leave a half-written file | A change is saved completely or not at all |
| Two windows saving at once could overwrite each other | They take turns, and nothing is lost |
| A drag that changed nothing still rewrote the file | Nothing changed, nothing saved |
| — | The order file is brought up to date in the background, never while you drag |
| — | The last 10 backups of the store are kept beside it |

- **No file is moved, renamed or deleted by the store.** Files move only when you Add or Remove them.
- Folder names, `master_manifest.json`'s shape and `GraduatedList.txt` are all unchanged.
- Japanese and Chinese each get their own store, and both work the same way.

## Undo
| Before | Now |
| :-- | :-- |
| Undo restored a snapshot of the whole order, which erased every change made after it | Undo reverses your changes one at a time, newest first |
| Undo of an Add deleted the copied files for good | They go to `.trash` (kept 30 days) |
| Undo of a Remove could overwrite a newer file of the same name | The file comes back beside it (`name_1.srt`) |
| — | Undo of Reset brings back the exact order from before |
| — | A file changed since (by another window, hato or a sync) is left alone, and Undo tells you so |

## Content Manager
| Before | Now |
| :-- | :-- |
| Graduate and Demote moved files between the tier folders | No file moves: a file can sit in a tab other than its folder's |
| Coming back to the window re-read every library folder (0.1 s at 2,000 files, 0.9 s at 20,000) | That check runs in the background; the window spends about 3 ms |
| A drag redrew everything and re-read the library | Only the tab you're on is redrawn |
| Another window's change showed up after a focus change | It shows within about half a second |
| Dropping an episode on its own group moved it | Nothing moves |
| — | Ctrl-click adds a row to the selection; Shift-click extends it |
| — | Files added to a folder from outside (hato) appear when you come back, at the top of NOW |

- **Reset** re-sorts the files within each tier by show and episode. It never moves a file to another tier, and you
  can undo it.
- A notice under **Import Content** tells you when the library needs you: **Repair**, **Try again**, or "saved by a
  newer Surasura".

## New Files
| Before | Now |
| :-- | :-- |
| A new episode went wherever its folder said | It joins its show in NOW or Soon; a new show goes to the top of NOW |
| — | It's the same rule whether you added the file, it appeared in the folder, or hato sent it |
| hato's drops landed at the top of NOW | Unchanged |

- A renamed file keeps its place, even when only the case changed (`Ep01` → `ep01`).
- A file that disappears is marked missing and stays in its place. When the file comes back, so does the entry.

## Changes Made Outside Surasura
An older Surasura, a sync tool or a hand edit can still change `master_manifest.json`.

| The change | What happens |
| :-- | :-- |
| Small (5 % of the library or less) | Applied quietly |
| Larger | Nothing is applied until you choose **Use that order** or **Keep mine** |
| The file is saved again before you answer | The question is asked again about the newer file |
| The file is unreadable, or isn't a library file | It is set aside in `.trash` and never overwritten |

- Before any outside change is applied, both the store and the file are backed up.

## Repair
- A damaged store opens read-only and offers **Repair**. Generate still works in the meantime.
- Repair rebuilds what it can, sets the damaged files aside rather than deleting them, and backs up your order file
  first.
- If the move to the store fails, Surasura keeps working from `master_manifest.json` as 2.4 did (without Undo).
  Press **Try again**, or the next version tries it for you.

## Generate and the Dashboard
| Before | Now |
| :-- | :-- |
| Pressing Generate first checked every library file, on the window itself | The press answers at once, and the check runs in the background |
| Coming back to the dashboard walked your library folders | That runs in the background; the dashboard spends about 1 ms |
| A graduated file was still tokenized by the background indexer | It's never read again |
| Junban warned "the library changed" after a move and its reverse | It warns only when the order really changed since your last Generate |
| The Generate ✓ checked files only | It also notices new files in your folders (a hato drop clears the ✓) |

- Generate reads the same files in the same order as before: the word lists match byte for byte.
- The report, the sentence dictionary, Anki matching and Junban read the same order.

## Updates
| Before | Now |
| :-- | :-- |
| **Update now** during a Generate, a パターン build or an open Content Manager could fail and leave you a manual download | The update waits and names what's still running, with a **Stop it** button for each and **Stop all and update now** for everything; meanwhile it keeps downloading |
| An update could replace only the program, the report templates and these notes | Each release lists every file it brings, checked by sha256 |
| A failed update was noted in `settings.json` | It's noted in Surasura's own folder: `settings.json` changes only when you change a setting |
| — | Surasura leaves a note naming its data folder, so 3.0 can find your library |

## Speed
Measured on the same PC.

| | 2.4 | 2.5 |
| :-- | --: | --: |
| Save after a drag, 1 file | whole file rewritten | 1.3 ms |
| Save after a drag, 50 files | whole file rewritten | 3.4 ms |
| Save after a drag, 20,000-file library | ~230 ms + two re-reads | ~1.5 ms |
| Drag in NOW, end to end (2,000 / 20,000 files) | — | 9 ms / 16 ms |
| Coming back to the Content Manager (2,000 / 20,000 files) | 0.1 s / 0.9 s | ~3 ms |
| Coming back to the dashboard | walks your folders | ~1 ms |

## Known Limits
- ⚖️ **An older Content Manager on a 2.5 library** shows graduated files in NOW again and can move or rename files
  on Graduate and Demote. 2.5 repairs this on its next start and asks first if the change is big, but avoid it.
- ⚖️ **One library, one machine.** Two PCs syncing one library folder isn't supported.
- ⚖️ **A very large drag** (over ~1,000 files) shows the busy cursor while it saves.
- ⚖️ **The Content Manager still redraws the whole tab** after a drag: ~0.35 s for a 10,000-file tab. The new window
  in 3.0 replaces it.
- ⚖️ **`master_manifest.json` grows slightly** (~2 MB for 2,000 files, up from ~1.3 MB): it now carries the store's
  state too, so a moved Surasura folder can rebuild its store from it.

## Dictionary Data
Unchanged from 2.4. JMdict stays at 2026-09-28 and is next refreshed in 3.0, so 2.5 lists exactly the words 2.4
did.

Every source: **Settings → Data & System → Data credits**.

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
