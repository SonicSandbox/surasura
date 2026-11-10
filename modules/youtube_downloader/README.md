<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# YouTube module (optional)

Two opt-in YouTube features (which also take **bilibili.tv** links), in one self-contained,
**lazy-imported** module — Surasura runs normally if this folder is absent:

1. **Transcript Downloader** — pull clean `.txt` transcripts into the active language's **Processed** folder.
2. **Preview Against Library** — paste a link and see its Vocab Journey scored against your existing library, fast, without a full re-run.

> This module is intentionally **not tracked by git** (`modules/*` in `.gitignore`)
> and is **excluded from the build** unless `enable_youtube_transcripts` or
> `enable_youtube_preview` is on.

## Transcript Downloader (red ▶, in Library Content)
- Drives the official **standalone `yt-dlp`** binary via its CLI. The binary is managed in
  `%APPDATA%/SonicSandbox/Surasura/bin/` (downloaded on first use) and kept current with the
  in-GUI **"Update yt-dlp"** button (`yt-dlp -U`). Nothing is frozen into the build, so a
  YouTube breakage is fixed without reshipping.
- Caption resolution: **manual → native auto → auto-translated**, per chosen language (Japanese / Chinese / English).
- **Grouping:** a playlist → `"<Channel> - <PlaylistTitle> (playlist)"`; ≥2 links from one
  channel → a `"<Channel>"` subfolder; single / mixed singles → straight into Processed.
- Options: language (defaults to the app's target language), **Keep timestamps** (off),
  **Channel name first** (on). Output is always `.txt`.
- **The header is a contract with the core** (2026-09-27): `build_text` writes six
  lines — title, `channel | date | duration`, `Captions: <language> (<kind>)`, URL, a blank line, 60 dashes — and
  the cues from the next line on; `analyzer.transcript_body` knows a transcript by that shape and reads only its
  cues (the `[00:01:02]` timestamps and `[音楽]` sound cues go too). Change both together —
  `tests/test_naming.py::TestBuildText::test_the_analyzer_reads_back_only_the_cues` locks it.
- A one-time, persisted **risk acknowledgment** gates the Extract button.

### bilibili.tv (no account)
- **bilibili.tv** links (episodes, seasons, uploads) work in the same box, with no account needed.
  Where a show is licensed for the user's region its subtitle tracks, Chinese included, are plain
  text. Elsewhere yt-dlp's geo error is reported as "not available in your region" — never
  worked around. Members-only episodes are reported as such.
- **bilibili.com** links are refused before anything is fetched, with a pointer to bilibili.tv. That
  site only gives subtitles to signed-in users (0 of 20 popular videos without a login, measured
  2026-09-18).
- Captions are fetched as **SRT** (`--sub-format srt/best`, no `--convert-subs`, which would need
  ffmpeg) and each cue is closed as a sentence with the analyzer's `close_cue`. Chinese subtitles
  carry no end punctuation, so joining them with spaces made one endless sentence.
- Files are named `<Title> [bilibili-<id>]` (a bare bracketed number is too common to trust), with no
  channel prefix (bilibili.tv names no uploader); a season lands in `<Show> (playlist)`. The core
  types them `bilibili`: spoken material, and a ▶ 📺 badge that opens the episode page from the
  sidecar `url`. There is no verified start-time parameter, so the hover names the moment instead.

### Setup's YouTube and a playlist's rest (3.0, alpha 8)

- Setup's page 3 *YouTube…* brings in each line's first video at once (`fetch_first`, `--no-playlist`).
- A line that names a playlist (`playlist_link`: never a Mix, a channel or its "Play all") gets its rest after the
  first video, in the background (`bring_in_rest`): one automatic `youtube` job (a user's own YouTube run goes first),
  reading only the videos whose id isn't in the language's data folder yet (`new_only`, a `--download-archive`),
  "… n of m videos read" in the bottom bar, the files to New arrivals as the window's runs land.
- `youtube_rest_<lang>.json` (persistent folder) keeps what is still to come and what was written but not handed
  over: a quit, an outage or a stall goes on at the next start (`windows.resume_youtube`); Cancel drops it; three
  fruitless runs drop it and say so.
- **A playlist's order** (Mado-Q): `series_order` — the list's own order, unless its entries' rough dates
  (`--extractor-args youtubetab:approximate_date`) run mostly newest → oldest, then turned over (a list YouTube shows
  newest at the top starts at its bottom). Each transcript's sidecar keeps `playlist` {id, index} (`series_places`);
  the library adds each video at its place among its title's videos of that list (`Store._series_spot`), so setup's
  first video, the rest and a video added later all land in the list's order. Setup reads a `watch?v=X&list=Y` link as
  its list (X's place known; X alone when the list can't be read).

## Preview Against Library (red ▷, next to Generate Journey)
- Scores one video (or playlist) against your **last full run** — no library re-scan. Reuses
  the analyzer's tokenizer + your known/ignore/blacklist/graduated sets, then overlays each
  word's **library leverage** from the cached frequency map.
- **Threshold-aware:** keeps a word if `library + in-video` counts meet your min-frequency, so
  below-threshold words the video pushes over still appear.
- **Example sentences:** the video's own sentence first, then the curated i+1 sentences your
  last run already found for that word (from `priority_learning_list.csv`) fill the rest.
- **Low-leverage cue:** words scoring under 10 get the report's example-sentence left line
  recolored red (see `templates/web_app.html`).
- Opens in the **same report UX** (cached ignore / completed / sort), honoring "open in app window".
- Optional **"add to front"** (off by default): copies the transcript to HighPriority position 1
  and prepends the manifest — file only, never marks words known.
- **Guards:** refuses a video already in the library (by `[id]`, filename scan); one self-cleaning
  temp workspace; on-brand playlist prompt (full vs. single); auto-runs a full analysis first if no cache.

## Layout
| File | Purpose |
|---|---|
| `gui.py` | Downloader Toplevel (Surasura-branded, threaded, queue-logged) |
| `downloader.py` | Core: caption parsing, naming, grouping, CLI driving |
| `ytdlp_manager.py` | Locate / download / self-update the yt-dlp binary |
| `preview.py` | Preview engine: scoring, library-context merge, report generation, commit-to-front |
| `preview_gui.py` | Preview Toplevel (link input, branded playlist prompt) |
| `tests/` | Pure-logic unit tests (no network): `pytest modules/youtube_downloader/tests` |

## Settings & build
- `enable_youtube_transcripts` (default **true**) — shows the red **▶ YouTube** button in the
  Content Manager.
- `enable_youtube_preview` (default **false**) — shows the red ▷ preview button, **and** makes a
  full run write `results/library_frequency.json` (the compact, below-threshold-inclusive cache the
  preview scores against). Writing it is gated on this toggle, so normal runs are unaffected.
- `youtube_risk_acknowledged` (default **false**) — remembers the one-time acknowledgment.
- Either feature toggle being on bundles the module at build time (`packaging/Surasura.spec`).
