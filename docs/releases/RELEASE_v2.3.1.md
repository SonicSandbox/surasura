# Surasura v2.3.1 - Release Notes

## Summary
- **🔄 "In Anki" knows more of your cards** - words mined with their と (バシッと) and kana cards you matched in Junban (あおぐ → 仰ぐ) now mark their word In Anki
- **順 A word with its する is that word** - Junban places 努力する as 努力: at its place on your list, or last when you already know it
- **⬆ "Skip this version" really skips** - and Settings can offer a skipped update again

Your list doesn't change: the same words, in the same order.

## 🔄 Anki and Your List Agree on More Cards
- **"In Anki" Knows More of Your Cards**: a word mined with its と (バシッと, ひょいと) now marks バシッ and ひょい
  **In Anki** — and so does a kana card you told Junban is a word on your list (あおぐ → 仰ぐ). **Show → Not in
  Anki** now lists only what you really still have to mine.
- **A Word With Its する Is That Word**: Junban places 努力する, 仲良くする and バシッと as 努力, 仲良く and バシッ —
  at the word's place on your list, or last when you already know it — instead of as new two-word phrases, and
  without asking. 楽しみにする and クビにする, whose meaning moves, stay phrases.

## ⬆ Updates
- **Skip This Version Means Skip**: pressing **Skip this version** used to leave the ⬆ Update available link
  in the footer on your next start — and clicking it only offered a manual download, calling it "a larger
  update". Now a version you skip isn't offered again, and the next one is, in one click as usual.
- **Skipped It by Mistake?** While the version you skipped is still newer than yours, **Settings → 🧮 Data &
  System** shows it under Automatic Updates with an **Offer again** button. Press it and the one-click update
  is back.
- **A Failed Update Says So**: if an in-app update ever can't finish, that version is offered as a download
  from then on, so it can never loop — and the dialog says the last update didn't finish, instead of calling
  it a larger update.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> **On v2.0 or later?** This is a one-click in-app update. You'll see **⬆ Update available** at the
> bottom-left of the dashboard — click **Update now** and Surasura reopens on v2.3.1. Your known words,
> ignore/blacklist/graduated lists, content, results, settings and library order are never touched.

> **Pressed "Skip this version" on 2.3.1 by accident?** The version you're on still has the old behaviour:
> open `settings.json` next to `Surasura.exe`, change `"skipped_version": "2.3.1"` to `"skipped_version": ""`,
> and restart Surasura.

If you're on **v1.9 or earlier**, or you'd rather update by hand:

- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating manually.
