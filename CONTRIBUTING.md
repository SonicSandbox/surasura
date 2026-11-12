# Contributing to Surasura

Thank you for sending a change. Pull requests are welcome; open an issue first for anything large.

This page is written so that you, or the AI assistant writing your change with you, can follow it step by step.
If an assistant helps you, point it at this file first.

## Licence of your contribution

Surasura is released under the GNU General Public License, version 3 or later (`LICENSE`). By sending a contribution
(a pull request, a patch or any other change) you agree that it is released under that licence, together with the
additional permission in `LICENSE-EXCEPTION.md`, **and** you grant
SonicSandbox a perpetual, worldwide, non-exclusive, royalty-free, irrevocable licence to use, copy, modify and
distribute your contribution under any other licence as well. You keep the copyright to your work. You confirm that
the contribution is your own, or that you have the right to submit it under these terms.

## Set up

1. Python 3.10 or higher, on Windows 10 or 11 (Surasura is Windows only for now).
2. `git clone https://github.com/SonicSandbox/surasura.git`, then `pip install -r requirements.txt`.
3. `python app_entry.py` opens the window. It keeps its library and settings in your user profile, so try changes
   on a library you don't mind changing, or with setup's **Try it with samples first**.

## Where things live

| Path | What it holds |
| :--- | :--- |
| `app_entry.py` | The one entry point: the window, and every helper program the window starts |
| `app/qt/` | The window (PyQt6). It paints what the services say and decides nothing itself |
| `app/services/` | The window's logic, without Qt |
| `app/` | The engine: reading subtitles and books into words (Japanese with fugashi and UniDic, Chinese with jieba), the word lists, the library store, Anki, the settings |
| `app/connect/` | Making Anki cards with Anki Miner, by itself |
| `app/cli/` | `surasura-cli`, the command line other programs call, and Piyo, the practice chat for your own AI |
| `modules/` | Optional parts (順 Junban, the YouTube downloader). Surasura runs without them |
| `templates/` | The journey page's HTML |
| `tests/` | The tests; real Japanese and Chinese sample data is in `tests/Test Resources/ja` and `zh` |
| `docs/` | The user guide, the FAQ, *How Parsing Works*, the release notes |

## The rules a change must meet

- **Small, in the style of its file.** Match the naming, spacing and comments of the code around it. The smallest
  change that solves the problem cleanly is the right one: no new framework, no abstraction for later.
- **No new dependency.** Use the standard library and what `requirements.txt` already has. A change that needs a new
  package needs an issue first.
- **Offline and private.** Surasura runs on the learner's computer and keeps their content there. Never add a call
  to the internet, telemetry, or anything that sends a learner's words, files or cards anywhere.
- **The learner's data is theirs.** Never delete, rewrite or reorder a learner's files, known words or word lists.
  Anything that moves their content must be undoable.
- **Paths and settings** go through `app/path_utils.py` and `app/settings_manager.py`: never a hard-coded folder,
  never the current folder. A file the learner gives Surasura is read with `path_utils.read_text`, never a bare
  `open(..., encoding="utf-8")`.
- **Japanese and Chinese both.** Anything that reads text into words handles both languages.
- **In the window:** every colour and size from the theme, never one written in place; Esc and Back never close the
  main window; every control has a tooltip; heavy work runs off the window's thread, so it never freezes. Words the
  learner reads say Current, Soon, Goal and Finished.
- **Fail gracefully.** An optional part, a missing program (Anki closed, Anki Miner not installed) or a file that
  can't be read gives a clear message, never a crash.

## Tests

Every change comes with tests for what it changes.

- **Real data, never `"test1"`.** Use the Japanese and Chinese samples in `tests/Test Resources/`. If what you need
  isn't there, add a small realistic sample there.
- **Think of the edges:** the success path, empty input (no words, an empty file, no results), nested folders, mixed
  scripts and CRLF / LF line ends, and a missing program or optional part.
- **Each test stands alone:** temporary folders and the fixtures in `tests/conftest.py` (they keep every test away
  from your real library and settings). No test may use the network or your own Anki.
- **Name it for what it proves,** e.g. `test_graduation_with_nested_folders_and_empty_files`, with a comment saying
  why it matters.
- A change to an optional part in `modules/<name>/` brings tests in `modules/<name>/tests/`.

Run them:

```
python run_tests.py                        # the core suite
python -m pytest modules/<name>/tests      # an optional part's own suite
python run_tests.py --all                  # everything, each suite in its own process
```

While you work, run the tests of the files you changed; before you send the pull request, run everything once and
make sure it is green.

## Send it

1. Fork the repository and make a branch from `3.0-dev` (the development branch; `main` holds the releases).
2. Commit with messages that say what changed and why.
3. Never include anyone's personal data: a library, known words, word lists, Anki decks, `settings.json`, logs or
   problem reports.
4. Open the pull request against `3.0-dev`. Say what it changes, why, and how you tested it. GitHub runs the tests
   on it.
