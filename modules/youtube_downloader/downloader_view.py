# SPDX-License-Identifier: GPL-3.0-or-later
"""The transcript downloader's rules, Qt-free (W3.4 row 4): what the Tk window (`gui.py`, `YoutubeDownloaderGui`)
kept inside its class, moved here so the Qt window (`qt_window.py`) only paints their answers. No Qt, no Tk.

- `links(text)`: one link per non-blank line (the Tk `on_extract`).
- `processed_folder(language)`: `data/<lang>/Processed`, set up first (the Tk `_output_dir`).
- `run_extract(...)`: yt-dlp made ready, the download, and **the created-files diff**: the new content files anywhere
  under Processed (a channel's or a playlist's folder made by an earlier download included; W3.2 L1 B2), which the
  opener's `on_complete` routes (W3.2's arrivals seam). Its inputs are taken
  on the window's thread before the worker starts (the Tk window read its Tk variables on the worker: defect 2), and
  `should_stop` (the window closed) ends the run between videos.
- `backfill_minutes(n)`: the time the *Fill missing timestamps* question names (the Tk `on_backfill`'s formula).
- `pending_backfill(language)`, `run_backfill(...)`, `run_update(...)`: the other two actions, on a worker.

Known, for W3.2's seam (the intent keeper's IK-15): a re-download over a same-named file is not "created"; and a close
mid-run leaves the files finished before it in Processed, un-routed.
"""
import json
import os
import threading

from app.path_utils import ensure_data_setup, get_data_path
from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import ytdlp_manager


def links(text):
    """The links in the box: one per non-blank line, stripped."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def default_caption_language(language):
    """The caption language the picker starts on for the window's language (`core.LANG_BY_CODE`)."""
    return core.LANG_BY_CODE.get(language, core.DEFAULT_LANG)


def processed_folder(language):
    """(A worker: it sets the language's folders up.) `data/<lang>/Processed`."""
    ensure_data_setup(language)
    path = os.path.join(get_data_path(language), "Processed")
    os.makedirs(path, exist_ok=True)
    return path


def _content_files(folder):
    """Every content file under `folder` (sidecars and logs aren't): a new video written into a channel's or a
    playlist's folder an earlier download made is new, though its folder isn't (W3.2 L1 B2)."""
    from app.library_store import is_content_name
    return {os.path.join(d, n) for d, _s, names in os.walk(folder) for n in names if is_content_name(n)}


def run_extract(urls, language, caption_language, keep_timestamps, channel_first, log, should_stop=None,
                ensure=None, extract=None, first_only=False, new_only=False, written=None):
    """(A worker.) Download `urls`' transcripts into the language's Processed folder. -> the new content files'
    paths, at any depth, sorted (the routing contract: only what did not exist before). [] when yt-dlp couldn't be
    had. `first_only` (alpha 8, setup): each link's one video; `new_only` (alpha 8, a playlist's rest): the videos
    not in the library's folder yet; `written(path)`: each transcript as it is written (`core.extract`'s)."""
    ensure = ensure or ytdlp_manager.ensure_available
    extract = extract or core.extract
    if not ensure(log):
        log("Cannot proceed without yt-dlp.")
        return []
    out = processed_folder(language)
    before = _content_files(out)
    asked = {k: True for k, on in (("first_only", first_only), ("new_only", new_only)) if on}
    if written is not None:
        asked["written"] = written
    with core.stopping(should_stop):                     # a stop ends the yt-dlp child running then, too
        extract(urls, out, lang=caption_language, keep_timestamps=keep_timestamps, channel_first=channel_first,
                log=log, should_stop=should_stop, **asked)
    return sorted(_content_files(out) - before)


# --- alpha 8 (Sonic: "it should still get the whole playlist"): the playlists whose rest is still to come ---------- #
# One small file per language in the persistent data folder: {"playlists": [their links], "unrouted": [the transcripts
# a run wrote, each as it was written, until the library took them — a quit or a crash before the hand-over leaves
# them here], "tries": {link: runs in a row that brought nothing for a passing problem}}. A playlist leaves it once a
# run of it ends without a quit or a passing problem (no connection, YouTube turning requests away, a stall), when the
# learner cancels it, or after REST_TRIES fruitless runs.
_REST_LOCK = threading.Lock()
REST_TRIES = 3


def rest_path(language):
    from app.path_utils import get_persistent_user_data_path
    return os.path.join(get_persistent_user_data_path(), f"youtube_rest_{language}.json")


def rest_read(language):
    """(A worker.) The language's playlists still to come and its transcripts not handed over: a file missing or
    unreadable is none."""
    try:
        with open(rest_path(language), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    state = {key: [str(v) for v in data.get(key) or () if isinstance(v, str)] for key in ("playlists", "unrouted")}
    tries = data.get("tries") if isinstance(data.get("tries"), dict) else {}
    state["tries"] = {str(k): v for k, v in tries.items() if isinstance(v, int) and k in state["playlists"]}
    return state


def rest_update(language, add=(), done=(), unrouted=(), routed=(), prune=False, tried=(), fruitful=()):
    """(A worker.) The record changed — `add` / `done` playlists, `unrouted` / `routed` transcripts, `prune`: the
    transcripts no longer on disk dropped (a file the learner deleted never keeps the record alive), `tried`: a run of
    these brought nothing for a passing problem, `fruitful`: one brought something — and written whole (temp file +
    replace: old or new, never half); nothing left, the file goes. -> the record now."""
    with _REST_LOCK:
        state = rest_read(language)
        gone, handed = set(done), {os.path.normcase(p) for p in routed}
        state["playlists"] = [p for p in dict.fromkeys(state["playlists"] + list(add)) if p not in gone]
        state["unrouted"] = [p for p in dict.fromkeys(state["unrouted"] + list(unrouted))
                             if os.path.normcase(p) not in handed and (not prune or os.path.exists(p))]
        tries = {k: v for k, v in state["tries"].items() if k in state["playlists"] and k not in fruitful}
        for link in tried:
            if link in state["playlists"]:
                tries[link] = tries.get(link, 0) + 1
        state["tries"] = tries
        path = rest_path(language)
        if not state["playlists"] and not state["unrouted"]:
            state["tries"] = {}
            try:
                os.remove(path)
            except OSError:
                pass
            return state
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(temp, path)
        return state


def rest_kept(problems, stopped):
    """Does a playlist's rest wait for the next try — a stop, or a passing problem (`core.transient`, yt-dlp not had)?"""
    return stopped or any(core.transient(p) or p == NO_READER for p in problems)


# Alpha 8: what a run's log says went wrong, as setup's screen says it (the window keeps the whole log)
_PROBLEM = ("  ! ", "  – ")
NO_READER = "Couldn't get yt-dlp, the program that reads YouTube: check your internet connection"


def problems(lines):
    """The plain-words lines of what went wrong in a run's log `lines` (a link not read, a video without captions, a
    stalled download, no yt-dlp), each once, in order."""
    out = []
    for line in lines:
        text = str(line)
        if text.startswith(_PROBLEM):
            text = text[len(_PROBLEM[0]):].strip()
        elif text.startswith("Could not download yt-dlp"):
            text = NO_READER
        else:
            continue
        if text and text not in out:
            out.append(text)
    return out


def backfill_minutes(n):
    """The rough wall-clock of filling `n` transcripts' cue times: a request plus its pause each, and a longer rest
    between batches (the Tk window's formula, gui.py:369-372). At least 1."""
    return max(1, round((n * (core.REQUEST_PAUSE + 2.0) + (n // core.BATCH_SIZE) * core.BATCH_PAUSE) / 60))


def pending_backfill(language):
    """(A worker: it walks the language's folders.) The transcripts with no cue times yet, tiers included."""
    return core.find_transcripts_missing_cues(get_data_path(language))


def run_backfill(language, caption_language, log, should_stop, ensure=None, backfill=None):
    """(A worker.) Fetch the missing cue times: transcripts are never rewritten, only their sidecars written; paced,
    resumable, and stopped by `should_stop` (the window closed)."""
    ensure = ensure or ytdlp_manager.ensure_available
    backfill = backfill or core.backfill_cues
    if not ensure(log):
        log("Cannot proceed without yt-dlp.")
        return None
    with core.stopping(should_stop):
        return backfill(get_data_path(language), lang=caption_language, log=log, should_stop=should_stop)


def run_update(log, should_stop=None, update=None):
    """(A worker.) Update yt-dlp (`ytdlp_manager.update`); `should_stop()` true ends its child."""
    return (update or ytdlp_manager.update)(log, should_stop=should_stop)


LOG_KINDS = {"download": "youtube-download", "fill": "youtube-fill", "update": "youtube-update"}


def log_path(kind="download"):
    """An action's log (the RUNBOOK's *Open the log*, for the Tk window's scrolling Activity box): its last run's
    lines, in the command line's log folder (`tools.log_path`) — one per action, so an update never overwrites the
    last download's (AD4-14)."""
    from app.services import tools
    return tools.log_path(LOG_KINDS.get(kind, LOG_KINDS["download"]))


def newest_log():
    """(A worker.) The newest of the actions' logs, or None when no action has run yet."""
    found = [p for p in (log_path(k) for k in LOG_KINDS) if os.path.isfile(p)]
    return max(found, key=os.path.getmtime) if found else None


class RunLog:
    """(A worker.) One run's lines: each written to the log (fresh for the run, flushed per line) and handed to
    `on_line`. The file is opened by the first line, on the run's thread — never where the log is made (the window's
    thread: AD4-5). A log that can't be opened never stops the run."""

    def __init__(self, on_line, kind="download"):
        self.on_line = on_line
        self.kind = kind
        self.path = None
        self._file = None
        self._opened = False

    def _open(self):
        self._opened = True
        try:
            self.path = log_path(self.kind)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._file = open(self.path, "w", encoding="utf-8", errors="replace")
        except OSError:
            self._file = None

    def __call__(self, line):
        line = str(line)
        if not self._opened:
            self._open()
        if self._file is not None:
            try:
                self._file.write(line + "\n")
                self._file.flush()
            except (OSError, ValueError):
                pass
        self.on_line(line)

    def close(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
