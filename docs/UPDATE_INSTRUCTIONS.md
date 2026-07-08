# How to Update Surasura - Readability Analyzer

Surasura can update itself for most releases, and you can always update manually if you
prefer. Either way, **your personal data is never touched by an update.**

## What an automatic update changes (and what it doesn't)
An in-app update refreshes **only the program itself and the report templates** — a small
download (a few megabytes), versus the ~400 MB full package. It **never** reads or changes:

- your known words (`KnownWord.json`), ignore/blacklist/graduated lists,
- your content in `data/`, your generated `results/`,
- your `settings.json`, or your library order (`master_manifest.json`).

New settings that ship with a version appear automatically from the updated code; your own
settings are left exactly as you had them.

## Automatic updates (recommended)
1. When an update is available you'll see a small **"⬆ Update available"** link in the
   bottom-left of the dashboard. It never interrupts you — click it when you're ready.
2. Choose **Update now**. Surasura downloads the small update, verifies it, then briefly
   closes and reopens itself on the new version. That's it.
3. If you'd rather not, choose **Skip this version** (it won't ask again) or **Later**.

You can turn automatic updates off anytime in **Settings → Data & System → Automatic
Updates**. Bigger "major" updates (the rare ones that change the app's internals) always use
the manual path below, even with automatic updates on.

If an automatic update ever can't finish (e.g. no internet), Surasura simply keeps running
the version you have and lets you try again or update manually — it will never get stuck
retrying.

## Manual update (always available)
1. **(Optional) Back up your data.** Auto-updates don't need this, but for a manual full
   replacement it's good practice: copy your `User Files` folder somewhere safe.
2. Download the latest **`Surasura_vX.Y.zip`** from the
   [Releases page](https://github.com/SonicSandbox/surasura/releases).
3. Extract it to a new folder and run `Surasura.exe`.
4. If you're moving from an old version, copy your `User Files/<language>/` files
   (`KnownWord.json`, `IgnoreList.txt`, `Blacklist.txt`, `GraduatedList.txt`, any frequency
   lists) and your `data/<language>/` content into the new folder.

## Release Notes
See the `RELEASE_*.md` files or the GitHub Releases page for what's new in each version.

## Issues & Contributions
Found a bug or have a suggestion? Please open an issue on the
[GitHub repository](https://github.com/SonicSandbox/surasura).
