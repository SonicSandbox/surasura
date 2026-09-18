# Surasura v2.2 - Release Notes

## Summary
- **✂ Cleaner anime sentences** — two subtitle-parsing fixes to how anime lines become sentences
- Immersion Architect's daily time budget now actually saves
- A round of packaging and reliability fixes

> **One thing will look different after you update.** The two subtitle fixes change how anime lines
> are split into sentences, so your first **Generate Journey** is a one-time full re-analysis. Your
> library, known words, order and settings are untouched — your example sentences just get better.

## ✂ Cleaner Anime Sentences
Two parsing fixes to how subtitle lines become sentences, which is why the first Generate Journey after updating is a full re-analysis.

- **Speaker Labels No Longer Leave a Bracket Behind**: a name carrying furigana — `（風太郎(ふうたろう)）` — used to be stripped only as far as its inner bracket, leaving a stray `）` glued to the front of the line. It reached example sentences and exports alike. Now the whole label goes.
- **Netflix's Dash Now Joins the Line**: `―` at the end of a cue means "this sentence continues", the same as the `➡` fansubs use, but it was treated as ordinary text and a full stop was added after it — cementing a fragment. Measured on a real episode, 3.4% of cues were affected.

Together these mean fewer half-sentences and no more stray punctuation in the sentences you mine.

## 🛠️ Fixes
- **The Immersion Architect's Time Budget Saves Again**: in a packaged build the daily immersion slider was writing to a location that does not exist there, so every change was silently discarded and the engine kept using 30 minutes. It now reads and writes the same file in both packaged and source runs.
- **A Rare Start-up Race in the Word Index**: two Surasura processes starting at the same moment could both try to create the index and one would fail. Harmless, but it could fail a run for no reason.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** This is a one-click in-app update. You'll see **⬆ Update available** at the bottom-left of the dashboard — click **Update now** and Surasura reopens on v2.2. Your known words, ignore/blacklist/graduated lists, content, results, settings and library order are never touched.

If you're on **v1.9 or earlier**, or you'd rather update by hand:

- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating manually.
