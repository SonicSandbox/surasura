# Surasura v2.0 - Release Notes

## Summary
- Streamlined Content & Library (major GUI overhaul)
- YouTube Integration — transcript downloader + "Preview against your library"
- One-Click Auto-Update
- Browser-side "Completed" tracking + a "Show" priority filter in the report
- Sharper commonness control (new **Uncommon** band)
- Faster analysis + a round of reliability fixes

## 🧭 Streamlined Content & Library (GUI Overhaul)
- **One "Import Content" Button**: The main dashboard's Library Content collapses to a single button — Extract/Splice and the YouTube downloader moved *into* the Content Manager, keeping the main screen focused on Import → Analyze → View.
- **Redesigned Content Manager**: A single home for adding and ordering content — an **Add Content** row (📁 Add files + folder, 📖 Extract EPUB/Anki, ▶ YouTube) plus quick links to paste text or grab subtitles.
- **Tabbed Library (NOW · Soon · 6+ months)**: The three tiers are now connected tabs; added content lands in the tab you're on, and you drag files (▲▼) into your real immersion order, with a per-tier "how much order matters" hint.
- **Friendly First Run**: A brand-new library shows an onboarding card with **Test with samples** — one tap seeds a few files so you can try a full Journey immediately. Fresh installs now ship genuinely empty.
- **Generate Guards Itself**: **Generate Journey** stays disabled (with a short hint) until your library actually has content.
- **On-Brand Polish**: Consistent dark theming across the Content Manager and File Importer — dark scrollbars, clean connected tabs, tidy button padding, and a restored **?** help memo.

## 🎬 YouTube Integration (New, Optional)
- **📥 Transcript Downloader** (in the Content Manager): Paste any video, list, or playlist link and get clean, analysis-ready `.txt` transcripts dropped into **Processed** and your active tab. Pulls JA / ZH / EN captions (manual → auto → auto-translated), with smart channel/playlist grouping and an optional timestamps mode. Powered by a self-updating **yt-dlp** binary. On by default; turn it off in Settings.
- **🔎 Preview Against Library** (▷, next to Generate Journey): Paste a link to instantly see a video's Vocab Journey scored against *your* library — how much you already know and exactly what it would teach you — without a full re-run. Playlists are scored per-video so you can compare head-to-head; one checkbox adds a keeper to the front of NOW.

## 🔄 One-Click Auto-Update
- Minor updates apply in a click and reopen on the new version — a small package (program + templates), not the whole download.
- **Your data is never touched**: known words, ignore/blacklist/graduated lists, content, results, settings, and library order are all left alone. A verified checksum is required before anything applies, and a failed swap rolls back automatically.
- Major/runtime releases stay manual full downloads. Turn auto-update off under **Settings → Data & System → Automatic Updates**.

## 📊 Report Enhancements
- **"Completed" Tracking**: Mark files done directly in the report (✓ button or `w`), auto-advancing to the next unfinished file. Remembered per language, entirely browser-side — no changes to your data.
- **"Show" Filter (⇅)**: Focus the list on **All**, **✦** (high-leverage) only, or **No ✦** — instantly, in place (or press `s`).

## 🎚️ Sharper Commonness Control
- The **By Commonness** slider gains an **Uncommon** band (Core → Common → Occasional → Uncommon → Rare → Very Rare → Native) and a retuned density curve for finer control over how deep you go, with a live word-count and coverage preview.

## ⚡ Faster & Snappier on Big Libraries
- Large libraries analyze noticeably faster with **byte-for-byte identical results** — each file is now parsed once and reused for both scoring and the progressive report (roughly a third faster on ~1M-token libraries), plus further engine tuning. Applies to both Japanese (Fugashi) and Chinese (Jieba).
- The **Content Manager** now opens and switches tabs instantly on large libraries (no more multi-second freeze), the **commonness slider** is smoother, and pressing **Generate Journey** when nothing changed reopens your report immediately instead of re-running the engine.
- The internal results file is much smaller on disk, with **no change to your reports**.

## 🛠️ Reliability & Correctness Fixes
- Chinese single-character words are no longer dropped; Japanese words display in clean dictionary form and match your frequency lists correctly.
- Reports never break on tricky content (`</script>`, `<`, `>`, `&`), and example sentences stay short, clean, and genuinely i+1.
- Non-destructive folder import (merges instead of overwriting), `.md` files supported, cleaner Anki/Migaku/Jiten imports, and Zen Mode renders correctly from Generate Journey.
- File Importer: fixed cramped buttons and trimmed the window.

## Setup Instructions
1. Extract the zip file.
2. Run `Surasura.exe`.

## Usage Tutorial
[Tutorial](https://github.com/SonicSandbox/surasura/blob/main/docs/Tutorial.md)

---

## UPDATE INSTRUCTIONS
> This is a full download (auto-update begins **from v2.0 onward** — future minor updates apply in one click).

- Download and unzip the new release.
- Move your **User Files** (Ignore list, freq lists, blacklist, GraduatedList) into `User Files/<language>/`.
- Move your **content** into `data/<language>/`.

**Note:** Back up your User Files and data before updating.
