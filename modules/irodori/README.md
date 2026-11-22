<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 彩 Irodori — AI sentence audio for cards with none (optional, beta)

Fills a card's **SentenceAudio** with an AI voice made **on the learner's own PC**, only when that field is empty.
Off by default (`enable_irodori`, Settings › App › *Beta*). The app runs the same with this folder absent.

## What the learner sees

1. **Opt in.** Settings › App › *Beta* · **AI audio for cards without audio** (off). Ticking it shows two lines — what
   it is (an AI voice, made on this PC, nothing sent anywhere) and the download (its size, CPU or GPU; how long a
   sentence takes is in the line's hover) — and *Install*. Nothing downloads until *Install* is pressed; *Stop* cancels
   it. Installed: its size and *Remove* (frees it all). Unticking keeps the download; *Remove* deletes it.
2. **At the book.** With the beta on and installed, Connect's question about a book (*Do you have 「…」's audiobook?*)
   offers **Pick its audiobook… · Make AI audio (beta) · Mine without audio**. Real audio stays first. *Make AI audio*
   mines the book as *Mine without audio* does, then the AI voice fills the new cards' SentenceAudio.
3. **Existing cards (Anki Backfill).** Backfill's window gets **AI sentence audio (beta)…**: first a count — *N cards
   have no sentence audio.* — then *Make it*, then *Undo AI audio*. Any card in Backfill's deck, not only Surasura's.
4. **Existing cards (Connect).** Connect's *Add audio to these cards* can offer *AI audio (beta)* when no audiobook is
   lined up: its press calls `modules.irodori.make_for_notes` (`on(settings)` says whether to offer it).
5. **Undo.** Every run has its own Undo (the shared writer's record): a field still holding what the run wrote goes
   back to empty and its tag comes off; a field the learner changed since stays as they left it.

## The rules

- **Add only, never overwrite.** A SentenceAudio holding anything — a clip, a `[sound:…]`, text, `<br>`, a space — is
  left exactly as it is. Only an exactly empty one is filled, read again under the Anki-write lock right before the
  write (the shared writer's rule).
- **One field.** SentenceAudio only: never another field, never the sentence, never a card's schedule.
- **One writer.** Every write goes through Connect's sentence-audio writer, `app/connect/sentence_audio.py`
  (`fill(anki, ledger, clips, field, tag, by)` / `undo(anki, ledger, id)`, its Undo records in Connect's ledger),
  reached through one seam, `writer.py` — the same writer as the narrator's clips. The seam checks that writer's
  signatures: without it, or with a changed contract, `on()` is False and no door offers AI audio.
- **Tagged** `surasura::ai-audio` (the narrator's: `surasura::audio-added`) so the learner can find, review or remove
  them.
- **Everything on the learner's PC.** The voice is made by a server on `127.0.0.1` only, with a key made for each
  start, started when there is work and stopped when it is done. No sentence leaves the PC and nothing is sent
  anywhere. The only network is the install, on the learner's press.

## Why Surasura makes the sentence audio

Anki Miner makes the cards and its own word audio. Its sentence text-to-speech (off by default) covers reading sources
only and is **online** (the sentence is sent to a web service), and it has no hook for a local engine. So Surasura
makes and writes the sentence audio itself, after the cards exist.

## The engine (called K2 in the code: the voice packs' `k2-natural`, the caption rules)

- **Irodori-TTS v4.1 Small** (Aratako; MIT; ≈ 766 M parameters, 48 kHz) + the codec **Semantic-DACVAE-Japanese-32dim**
  (MIT), served by **Irodori-TTS-Server** (Aratako, MIT) at commit `61012c7`, its Irodori-TTS at `89f9d8f`. Every clip
  carries the model's inaudible **SilentCipher** watermark (Sony, code MIT; its 44.1 kHz files are part of the
  install): the model card's rule. The model card also forbids cloning a real person's voice without consent — the
  packs carry no clip of anyone.
- **No reference clip.** Short AI-made reference clips added a hiss in testing, so none is shipped. The voice is
  described in words instead (a caption), one per sentence.
- **A voice per sentence**: who would say the line, to whom, a modest emotion, natural everyday speech at a normal
  pace. There is no AI to ask on the learner's PC, so `voice.py` writes the caption by **rules**: a man's own words
  (俺 / 僕 / ぜ / ぞ …) → a man, a woman's (わよ / かしら / のよ / あたし …) → a woman, else a woman; age 20s; a
  question, a request or an exclamation changes the delivery phrase. Words that pull the model toward a slow
  read-aloud voice never appear (落ち着いた · ナレーター · ナレーション · 語り口 · 語る · 朗読 · 読んでいる · 読み上げ ·
  ゆっくり · ゆったり · 静か · 穏やか, hoarse / breathy / whisper). ≤ 50 characters.
- **Speed 1.1** (it shortens the pauses at commas), 40 steps, a seed from the sentence's hash (made again, it sounds
  the same).
- Output: wav from the server → mp3 128 kbps mono through an ffmpeg on PATH, else the wav as it is.

## Voice packs

A voice pack is one JSON file: `voices/<id>.json` here (shipped) or `<runtime>/voices/<id>.json` (added later, no code
change). It names its `version`, `speed`, `steps`, an optional `lora` (the server's per-request LoRA adapter:
`irodori.lora_adapter`), a reference `voice` (or `"none"`), and the caption parts (or none). The setting
`irodori_voice` picks one (default `k2-natural`). A fine-tuned voice = a new pack file + its LoRA, `version` bumped; a
pack under the runtime replaces a shipped one of the same id only with a higher version. Clips are cached by pack id
and version, so a new version makes new clips.

**Listening voices.** A listening round keeps ONE voice for all its lines, so its packs carry `"for": "listening"`,
one `caption` and one `seed` (7) for every line instead of the caption parts, at the card voice's speed (1.1) and
steps. Five ship: `woman-20s` (the default), `woman-30s`, `man-20s`, `man-30s`, and `storyteller` — a calm adult
woman, whose calm words are the ones the card voice leaves out on purpose (they slow a card's line; a story may want
them). `listen.voices()` lists them and `listen.unknown()` names them back for a voice that isn't there; the round keeps
its voice in its record (a voice gone since: the default; lines already made stay as they are). Cards still use
`irodori_voice` (`k2-natural`); the listening packs change nothing there.

## Install and remove (the module's own environment)

Nothing is added to `requirements.txt`. On *Install* the module builds its own runtime under
`%LOCALAPPDATA%\Houseki\Surasura\irodori\` (per user, every install shares it; local, never roaming), as Anki Miner
puts its speech model in its own folder:

1. `uv` 0.13.4 (Astral; MIT / Apache-2.0) from its GitHub release, sha256 checked.
2. Python 3.10.22 by uv (python-build-standalone, from GitHub) into the runtime.
3. PyTorch 2.10 from download.pytorch.org — `cpu`, or `cu126` for an NVIDIA GPU with ≥ 6 GB and a driver ≥ 525 (`cu128`
   for compute capability ≥ 12) — then the server's own pins from PyPI (`requirements-server.txt`, the server's
   `uv.lock` exported with its hashes), then the server and its three git dependencies as GitHub archives at their
   pinned commits (no git needed). Every `uv pip install` is `--no-deps`: the lists are the whole lock.
4. The model, the codec and the watermark from Hugging Face at pinned revisions.

**What is checked by hash:** uv, the model, codec and watermark files (sha256 / git blob hash), the server's PyPI
packages and the CPU PyTorch (`--require-hashes`). **By pinned commit only:** the four GitHub archives (GitHub doesn't
promise an archive's bytes). **Not pinned:** the build tools (setuptools …) uv fetches from PyPI to build those four.
**By pinned version only:** a CUDA PyTorch (the server's lock has none).

≈ 5 GB on the CPU (measured: 4.9 GB), ≈ 8.5 GB with a GPU, shown before the press. A failed or stopped install is
never read as installed (`installed.json` is written last) and picks up where it stopped. *Remove* deletes the
runtime folder — only one carrying the installer's mark (`.surasura-irodori`). The cards' audio stays.

## Running it

- The server runs in its own process: `<runtime>/env/python.exe -I host.py <port>`, below-normal priority, no window,
  on a free loopback port with `IRODORI_API_KEY` set per start and `HF_HUB_OFFLINE=1`; `host.py` ends by itself when its
  parent ends or after 5 idle minutes. `Server.stop` ends the process tree (the venv's python.exe is a launcher).
- Measured on a 12-core desktop processor: model load 17–22 s; **CPU 15.5–34 s a sentence** (2.4–7.3 s of audio). A
  3 GB graphics card can't hold the model (slower than the CPU) — hence ≥ 6 GB.
- **GPU pace:** bursts of 15 sentences, then 3 minutes off, to let the card cool. CPU: no pause.
- **Stop** between two sentences (Backfill's window closing, Connect's stop, an update staged, the battery, a review or
  Anki closing).
- **One run at a time**, across every Surasura process (`<runtime>/run.lock`); *Remove* waits for none and refuses
  while a run holds it. A Remove that fails part-way keeps the installer's mark (deleted last), so Remove can run again.
- **In Connect:** the book's new cards are queued (`<local data>/irodori-queue-<lang>.json`, outside the runtime) when
  the part fills, and made once the run's mining jobs are through. A part that comes in meanwhile (*Mine now*, a new
  placement) stops the voice between two sentences and goes first — AI audio never holds a part back.
- **Undo:** every run that wrote is kept (`<local data>/irodori-runs-<lang>.json`, the last 50): Backfill's window
  offers its last run's *Undo AI audio* when it opens again; Connect's runs (made with no window) are kept the same way
  for *Add audio to these cards* to offer.
- **Japanese only:** a line with no kana (Chinese) is never read; another language is refused.

## Files

| File | What |
| --- | --- |
| `__init__.py` | `SETTINGS_DEFAULTS`, `on()`, `make_for_notes()`, `find_empty()`, `undo()`, `queue_notes()`, `run_queue()` |
| `writer.py` | the one seam to the shared writer (`fill` / `undo`), and the read-only count (`look`) |
| `runtime.py` | install / remove / status; the pins |
| `requirements-server.txt`, `requirements-torch-cpu.txt` | the server's pins with hashes; the CPU PyTorch's |
| `host.py` | runs the server inside the runtime's Python, with the parent and idle watch |
| `server.py` | start / stop / speak, loopback only |
| `voice.py` | voice packs, the caption rules, a card's sentence as the voice reads it |
| `make.py` | a run: count → clips (cached, paced, stoppable) → one write |
| `queue.py` | Connect's waiting list |
| `listen.py` | the practice chat's listening rounds (`app/listening.py`'s voice for `ja`): a round's lines in ONE listening voice (`voices()`, `unknown()`, `DEFAULT_VOICE`), the wav back as it is; the run lock shared with card audio; nothing to Anki |
| `voices/k2-natural.json` | the default pack (cards) |
| `voices/woman-20s.json` … `storyteller.json` | the five listening voices (`"for": "listening"`) |
| `qt_settings.py`, `qt_backfill.py`, `qt_strings.py` | the Settings beta row, Backfill's button, the words |
| `tests/` | the module's suite (below); `tests/live_drill.py` is a by-hand check against a real Anki, never collected |

Core touchpoints (each guarded): `app/settings_manager.py` (the registry), `app/settings_placement.py`,
`app/analyzer.py` (`enable_irodori`, `irodori_` out of the run signature), `app/qt/settings_catalog.py` +
`settings_strings.py` + `shell.mount_settings` (the Beta row), `app/connect/runner.py` + `actions.py` (the book's
answer, the queue, the end-of-run pass), `app/qt/needs.py` + `app/services/needs.py` + `app/qt/strings.py` (the book's
third button), `modules/junban/qt_backfill.py` (the button), `packaging/Surasura.spec`, `package_app.py`,
`packaging/build_config.json`.

## Tests

```
python -m pytest modules/irodori/tests
```

No network, no model and no GPU: the downloads, uv, the voice's server and AnkiConnect are faked; the shared writer is
the real one, its Undo records in a Connect ledger under the test's own folder. Sentences come from
`tests/Test Resources/ja`.
