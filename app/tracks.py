"""Subtitle tracks inside a video (Michi-ST, 2026-11-02; Anki Miner 3.11's `inspect`, Z-19, and `extract`, Z-24; the
plan, PROVISIONAL: tracks/pipeline/work/ST/plan.md).

A video in a source folder with no subtitle file is a waiting item (SRC K5: *No subtitles yet*, filled in place when
its subtitle comes). When the video carries a text subtitle track in the library's language, Anki Miner copies that
track out and the waiting item takes it in place (`Store.fill_track`): from then it is read, listed and mined like any
other episode, its timing the video's own (`fit_check.track_timed`: no tsubasa asked).

- **Which videos** (`Store.waiting_tracks`): the waiting items with a video — never an audiobook's. Each video is asked
  once per its size and time (`cache_path`: kept beside Connect's video index, S19); a cloud placeholder never (B3), nor
  a video that isn't there now.
- **One rule for the track** (`choose`, PROVISIONAL): text subtitle tracks only; tagged in the library's language
  (TAGS) first, untagged ones only when none is; signs, songs and forced tracks (`_extra`) only when nothing else is;
  at most TRIES of them, the default first. Each one extracted is kept only when its text is the library's language
  (`sources._refusal`, the look's one rule); of several, the most dialogue lines (`sources.dialogue_lines`) wins.
- **Where it goes:** `Library/<show>/<video stem>.<lang>.<ext>`, the waiting item's own folder in the data folder
  (`library_store.content_target`) — never the user's media folder. A WebVTT track is written as SubRip (`_srt`): the
  library reads `.srt` / `.ass`. Anki Miner's run folder goes once read.
- **Picture subtitles only** (PGS, VobSub): not read yet (video OCR comes later). The item stays waiting and its row
  says so (`note`: PICTURES); never a silent miss.
- **No Anki Miner on this computer** (or one before 3.11, whose `version` names no `inspect` and `tracks`: `_miner`,
  read again only when its program or settings change): nothing is asked and nothing remembered (asked again once it
  is there); the waiting rows' tip says a subtitle inside the video is read once it is (`note`: NO_MINER). Its calls
  name the profile Connect mines with (`connect_anki_miner_profile`).
- **Failures** never end anything: a call that gave no verdict, a store that is busy, a copy that couldn't be written —
  logged, and that video asked again at a later look; a video's own failure FAILS times at the same stats is
  remembered (`_failed`), so it never costs a whole-video read every look. What Anki Miner said of the video itself
  (no text in the library's language, picture subtitles only, no video in it) is remembered with its stats.
- **A source away** (the last look couldn't reach it): its videos aren't looked at (`fill`'s `away`).

Run on the window's source-looks worker of its own (`services/source_looks.SourceLooks`), never on the window's thread
and never inside a look. Standard library only; no Qt, no Tk.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import threading

log = logging.getLogger("surasura.tracks")

CACHE_VERSION = 1
CHUNK = 8                       # videos (then tracks) per Anki Miner call
TRIES = 3                       # tracks of one video extracted at most, to find its full dialogue
INSPECT_TIMEOUT = 300.0         # one `inspect` of CHUNK videos (ffprobe each; a share is slow)
EXTRACT_TIMEOUT = 60 * 60.0     # one `extract` of CHUNK tracks (ffmpeg reads each whole video)
# A track's language tag in the library's language (ffprobe gives ISO 639-2, lowercased; some muxers write 639-1)
TAGS = {"ja": frozenset(("jpn", "ja", "jp", "jap")),
        "zh": frozenset(("chi", "zho", "zh", "cmn", "yue", "chs", "cht"))}
# A track that is no full dialogue: by its title (or the forced flag)
_EXTRA = re.compile(r"sign|song|forced|karaoke|lyric|看板|歌", re.I)

PICTURES, NO_MINER = "pictures", "no-miner"     # `note`'s answers
EXTRACTED, NONE, UNREADABLE = "extracted", "none", "unreadable"

_lock = threading.Lock()        # one fill at a time in a process
_NOTES = {}                     # `note`'s last read per language: {"stamp": the cache's (mtime_ns, size), "notes": …}


def cache_path(language):
    """Where the videos asked are remembered (beside Connect's video index, `videos.index_path`)."""
    from app.connect import ledger
    return os.path.join(ledger.folder(), f"tracks-{language}.json")


def _load(path, store_id):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION and data.get("store") == store_id and \
                isinstance(data.get("videos"), dict) and isinstance(data.get("notes"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "store": store_id, "videos": {}, "notes": {}}


def _save(path, data):
    """Written whole (a temp file, then replaced); one that can't be written is only a cache: asked again next time."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("The videos' tracks couldn't be remembered (%s): %r", path, e)


def note(rel_path, language=None):
    """What a waiting item's row says of its video's tracks: PICTURES (only picture subtitles: not read yet), NO_MINER
    (no Anki Miner on this computer: a subtitle inside a video isn't read), else None. `rel_path`: the item's as the
    store holds it (a waiting item's is its video's name in `Library`); `language` None: either library's (a row knows
    its item, not its language — two libraries' waiting items never share a place). Each file is read again only once
    it changed (S19); never raises."""
    if not rel_path:
        return None
    said = None
    for lang in ([language] if language else sorted(TAGS)):
        notes = _notes(lang)
        if notes.get(rel_path) == PICTURES:
            return PICTURES
        if notes.get("*") == NO_MINER:
            said = NO_MINER
    return said


def _notes(language):
    try:
        st = os.stat(cache_path(language))
        stamp = (st.st_mtime_ns, st.st_size)
    except (OSError, ValueError):
        stamp = None
    held = _NOTES.get(language)
    if held is None or held["stamp"] != stamp:
        notes = {}
        if stamp is not None:
            try:
                with open(cache_path(language), encoding="utf-8") as f:
                    data = json.load(f)
                notes = data.get("notes") if isinstance(data, dict) and isinstance(data.get("notes"), dict) else {}
            except (OSError, ValueError):
                notes = {}
        held = _NOTES[language] = {"stamp": stamp, "notes": notes}
    return held["notes"]


# --- the rule ------------------------------------------------------------------------------------------------------ #
def _tag(track):
    return str(track.get("language") or "").strip().lower()


def _extra(track):
    """A signs / songs / forced track: no full dialogue."""
    return bool(track.get("forced")) or bool(_EXTRA.search(str(track.get("title") or "")))


def choose(tracks, language):
    """`inspect`'s tracks of one video -> (the text tracks to extract, best first, at most TRIES; True when it has
    picture subtitles in the library's language, or untagged — what its row says when no text track is read)."""
    subs = [t for t in tracks or () if isinstance(t, dict) and t.get("kind") == "subtitle"
            and isinstance(t.get("index"), int) and not isinstance(t.get("index"), bool)]
    tags = TAGS.get(language, TAGS["ja"])
    ours = [t for t in subs if _tag(t) in tags]
    untagged = [t for t in subs if _tag(t) in ("", "und")]
    text = [t for t in ours if t.get("text") is True] or [t for t in untagged if t.get("text") is True]
    full = [t for t in text if not _extra(t)] or text
    full.sort(key=lambda t: (not t.get("default"), t["index"]))
    pictures = any(t.get("text") is False for t in ours + untagged)
    return full[:TRIES], pictures


def _decoded(data, language):
    from app.path_utils import decode_text
    return decode_text(data, language)


def pick(extracted, language):
    """[(track, its extracted file)] of one video -> (track, file, its bytes) of the one to read, or None: each kept
    only when its text is the library's language (the look's one rule), the most dialogue lines first, then the
    default track, then the lowest index."""
    from app import sources
    best = None
    for track, path in extracted:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if path.lower().endswith(".vtt"):
            data = _srt(_decoded(data, language)).encode("utf-8")
        if not data or sources._refusal(data, language) is not None:
            continue
        rank = (sources.dialogue_lines(_decoded(data, language)), bool(track.get("default")), -track["index"])
        if best is None or rank > best[0]:
            best = (rank, track, path, data)
    return None if best is None else best[1:]


_VTT_TIME = re.compile(r"^((?:\d+:)?\d{1,2}:\d{2})[.,](\d{3})\s+-->\s+((?:\d+:)?\d{1,2}:\d{2})[.,](\d{3})")


def _srt(text):
    """A WebVTT track as SubRip: its cues numbered, `hh:mm:ss,mmm`, the header, notes and cue settings left out."""
    def full(t):
        parts = t.split(":")
        return ":".join(["00"] * (3 - len(parts)) + [p.zfill(2) for p in parts])
    out, n = [], 0
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        at = next((i for i, x in enumerate(lines) if _VTT_TIME.match(x.strip())), None)
        if at is None:
            continue                                # WEBVTT, NOTE, STYLE, REGION: no cue
        m = _VTT_TIME.match(lines[at].strip())
        n += 1
        out.append(f"{n}\n{full(m.group(1))},{m.group(2)} --> {full(m.group(3))},{m.group(4)}\n"
                   + "\n".join(lines[at + 1:]))
    return "\n\n".join(out) + ("\n" if out else "")


# --- one fill ------------------------------------------------------------------------------------------------------ #
def fill(store, language, settings=None, stop=None, path=None, away=()):
    """Every waiting video not asked yet (or changed since) asked, and those with a track filled in place. `store`: an
    open store (its worker's handle); `settings`: settings.json as read (Anki Miner's path and profile); `stop()`: the
    window closes — the call under way is cancelled, nothing more asked; `path`: Anki Miner's program (a test's);
    `away`: the ids of the sources the last look couldn't reach (their videos aren't looked at: a share offline can
    hold a stat for seconds). -> {"filled", "pictures", "none", "failed", "asked"} counts, or {"no_miner": True} (none
    on this computer, or one too old to look inside a video), or {"busy": True} (one runs already)."""
    if not _lock.acquire(blocking=False):
        return {"busy": True}
    try:
        return _fill(store, language, settings if settings is not None else _settings(), stop or (lambda: False),
                     path, set(away or ()))
    finally:
        _lock.release()


def _fill(store, language, settings, stop, path, away):
    from app import library_store as ls
    out = {"filled": 0, "pictures": 0, "none": 0, "failed": 0, "asked": 0}
    where = cache_path(language)
    cache = _load(where, store.meta().get("store_id"))
    before = json.dumps(cache, sort_keys=True)
    said = dict(cache["notes"])
    waiting = store.waiting_tracks()
    live = {rel for _i, rel, _r in waiting}
    cache["notes"] = {k: v for k, v in cache["notes"].items() if k in live}    # a filled or removed item says nothing
    cache["notes"].pop("*", None)
    miner = _miner(path, settings) if waiting else None
    try:
        if waiting and miner is None:
            cache["notes"]["*"] = NO_MINER          # nothing asked, nothing remembered: asked once it is there
            return {"no_miner": True}
        todo = []
        for item_id, rel, record in waiting:
            if record.get("root") in away:
                continue                            # its source away: its videos wait for it (G5)
            video = record.get("video_path")
            try:
                st = os.stat(video)
            except (OSError, TypeError, ValueError):
                continue                            # not there now: asked once it is
            if ls.is_placeholder(st):
                continue                            # a cloud placeholder is never read (B3)
            key = record.get("video_key") or ls.path_key(os.path.abspath(video))
            stats = [st.st_size, st.st_mtime_ns]
            held = cache["videos"].get(key)
            if isinstance(held, dict) and held.get("stats") == stats and held.get("outcome"):
                continue
            todo.append(_Video(item_id, rel, record, video, key, stats))
        run_dir = os.path.join(os.path.dirname(where), f"tracks-run-{language}")
        try:
            for n in range(0, len(todo), CHUNK):
                if stop():
                    break
                _chunk(store, language, miner, run_dir, todo[n:n + CHUNK], cache, out, stop)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        return out
    finally:
        _keep(where, cache, before)
        _redraw(store, waiting, said, cache["notes"])


class _Video:
    """A waiting video asked about: its item, the item's place, its record, the video, its key and stats."""
    __slots__ = ("item_id", "rel", "record", "video", "key", "stats", "pictures")

    def __init__(self, item_id, rel, record, video, key, stats):
        self.item_id, self.rel, self.record, self.video, self.key, self.stats = item_id, rel, record, video, key, stats
        self.pictures = False


def _redraw(store, waiting, said, notes):
    """The rows whose words changed drawn again now, not at their next change (S19: only these): a video's own note,
    or every waiting row when the no-Anki-Miner line came or went."""
    if said.get("*") != notes.get("*"):
        redraw = [item_id for item_id, _rel, _r in waiting]
    else:
        moved = {rel for rel in set(said) | set(notes) if said.get(rel) != notes.get(rel)}
        redraw = [item_id for item_id, rel, _r in waiting if rel in moved]
    if redraw:
        try:
            store.refeed(redraw)
        except Exception as e:
            log.info("The waiting videos' rows are drawn again at their next change: %r", e)


_MINERS = {}        # Anki Miner's program -> {"stamp": `anki_miner.stamp`, "miner": its (path, profile) or None}


def _miner(path, settings):
    """(Anki Miner's program, the profile id its calls name) — None when there is none here, or it can't look inside a
    video (no `inspect` and `tracks` among its features: before 3.11, Z-19 / Z-24). Its `version` and `profiles` are
    read again only when its program or settings change (`anki_miner.stamp`, S19); a failed read is no answer, asked
    again next time."""
    from app.connect import anki_miner
    exe = path if path is not None else anki_miner.find(settings)
    if not exe:
        return None
    stamp = anki_miner.stamp(exe)
    held = _MINERS.get(exe)
    if held is not None and stamp is not None and held["stamp"] == stamp:
        return held["miner"]
    try:
        info = anki_miner.version(exe)
        if not set(FEATURES) <= set(info.get("features") or ()):
            miner = None
        else:
            name = str(settings.get("connect_anki_miner_profile") or anki_miner.DEFAULT_PROFILE)
            listed = anki_miner.profiles(exe)
            try:
                profile = anki_miner.choose_profile(info, listed, name)
            except anki_miner.AnkiMinerError:
                profile = None              # a profile it lacks: its active one (a copy needs only its ffmpeg)
            miner = (exe, profile)
    except anki_miner.AnkiMinerError as e:
        log.warning("Anki Miner can't be asked about subtitle tracks now (asked again later): %s", e.message)
        return None
    _MINERS[exe] = {"stamp": stamp, "miner": miner}
    return miner


FEATURES = ("inspect", "tracks")    # Anki Miner's `version` features `inspect` (Z-19) and `extract` (Z-24) answer to


def _keep(where, cache, before):
    if json.dumps(cache, sort_keys=True) != before:
        _save(where, cache)


def _settings():
    from app import settings_manager
    try:
        return settings_manager.load_settings()
    except Exception:
        return {}


def _remember(cache, v, outcome):
    """What Anki Miner said of a video, kept with its stats: never asked again until it changes."""
    cache["videos"][v.key] = {"stats": v.stats, "outcome": outcome}
    if outcome == PICTURES:
        cache["notes"][v.rel] = PICTURES
    else:
        cache["notes"].pop(v.rel, None)


def _failed(cache, v, out, own=True):
    """A failure this time: the video asked again. `own` (the video's own: Anki Miner couldn't copy its track, its
    copy outlasted EXTRACT_TIMEOUT, the store refused its copy): after FAILS of them at the same stats it is remembered
    as failed, so a failure that holds never costs a whole-video read every look (S19). Anything else — ffprobe or
    ffmpeg missing, the window closing, a call with no answer, a busy library, a disk that took no copy — says nothing
    of the video and is never counted."""
    out["failed"] += 1
    if not own:
        return
    held = cache["videos"].get(v.key)
    fails = held.get("fails", 0) + 1 if isinstance(held, dict) and held.get("stats") == v.stats else 1
    cache["videos"][v.key] = {"stats": v.stats, "fails": fails}
    if fails >= FAILS:
        cache["videos"][v.key]["outcome"] = FAILED


FAILS = 3
FAILED = "failed"


def _job(run_dir, language, profile, kind, entries):
    os.makedirs(run_dir, exist_ok=True)
    data = {"schema": 1, "run_dir": run_dir, "profile": profile, "language": language, kind: entries}
    name = os.path.join(run_dir, f"{'inspect' if kind == 'sources' else 'extract'}.json")
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return name


def _poll(run_dir, run_ids, stop):
    """While a call runs: the window closing cancels it (API.md's `cancel` file in each run's folder)."""
    def poll():
        if stop():
            from app.connect import anki_miner
            for run_id in run_ids:
                anki_miner.cancel(run_dir, run_id)
    return poll


def _chunk(store, language, miner, run_dir, todo, cache, out, stop):
    """One `inspect` of up to CHUNK videos, then one `extract` a video (its tracks: at most TRIES), each one's track
    taken in as it comes."""
    from app.connect import anki_miner
    exe, profile = miner
    try:
        verdict = anki_miner.api(exe, ["inspect", _job(run_dir, language, profile, "sources",
                                                       [{"path": v.video} for v in todo])], timeout=INSPECT_TIMEOUT)
        sources = anki_miner._result(verdict).get("sources")
    except (anki_miner.AnkiMinerError, OSError) as e:
        log.warning("Anki Miner couldn't look inside %d videos (asked again later): %s", len(todo), e)
        out["failed"] += len(todo)
        return
    if not isinstance(sources, list) or len(sources) != len(todo):
        log.warning("Anki Miner's look inside the videos couldn't be read (asked again later)")
        out["failed"] += len(todo)
        return
    for v, source in zip(todo, sources):
        out["asked"] += 1
        if not isinstance(source, dict) or source.get("error"):
            if isinstance(source, dict) and source.get("error") == "VIDEO_UNREADABLE":
                _remember(cache, v, UNREADABLE)     # no video in it (API.md § inspect)
            else:                                   # ffprobe missing, a file it couldn't read now: asked again
                _failed(cache, v, out, own=False)
            continue
        tracks, v.pictures = choose(source.get("tracks"), language)
        if not tracks:
            _remember(cache, v, PICTURES if v.pictures else NONE)
            out["pictures" if v.pictures else "none"] += 1
            continue
        if stop():
            return
        _extract(store, language, exe, profile, run_dir, v, tracks, cache, out, stop)


def _extract(store, language, exe, profile, run_dir, v, tracks, cache, out, stop):
    """One video's chosen tracks copied out (one `extract` call), the best taken in."""
    from app.connect import anki_miner
    runs = {f"t{v.item_id}-{t['index']}": t for t in tracks}
    episodes = [{"run_id": r, "video_file": os.path.abspath(v.video), "track": t["index"]} for r, t in runs.items()]
    try:
        verdict = anki_miner.api(exe, ["extract", _job(run_dir, language, profile, "episodes", episodes)],
                                 timeout=EXTRACT_TIMEOUT, on_poll=_poll(run_dir, list(runs), stop))
    except (anki_miner.AnkiMinerError, OSError) as e:
        log.warning("Anki Miner couldn't copy a video's subtitle tracks (asked again later): %s", e)
        _failed(cache, v, out, own=getattr(e, "kind", None) == "timeout")
        return
    if not verdict.get("runs") and not verdict.get("ok"):    # refused as a whole (SETUP_ERROR: no ffmpeg)
        log.warning("Anki Miner refused to copy the tracks (asked again later): %s", verdict.get("message"))
        out["failed"] += 1
        return
    extracted, failed, own = [], False, False
    for run in verdict.get("runs") or ():
        track = runs.get(run.get("run_id")) if isinstance(run, dict) else None
        if track is None:
            continue
        path = _extracted(run_dir, run) if run.get("ok") else None
        if path is not None:
            extracted.append((track, path))
        elif run.get("error") not in ("TRACK_NOT_FOUND", "TRACK_NOT_TEXT"):
            failed = True                           # CANCELLED, VIDEO_UNREADABLE (the copy failed too): asked again
            own = own or run.get("error") != "CANCELLED"    # (a window closing says nothing of the video)
    chosen = pick(extracted, language)
    if chosen is None and failed:
        _failed(cache, v, out, own=own)
    elif chosen is None:                            # none of its text in the library's language
        _remember(cache, v, PICTURES if v.pictures else NONE)
        out["pictures" if v.pictures else "none"] += 1
    else:
        took = _take(store, language, v, chosen, extracted)
        if took is True:
            _remember(cache, v, EXTRACTED)
            out["filled"] += 1
        elif took is not None:                      # None: the item no longer waits on it (filled, removed): done
            _failed(cache, v, out, own=took == "own")


def _extracted(run_dir, run):
    """The subtitle file a run's `extract-<n>.json` names (inside its run folder), or None."""
    run_id = run.get("run_id")
    name = os.path.basename(str(run.get("file") or ""))
    try:
        with open(os.path.join(run_dir, run_id, name), encoding="utf-8") as f:
            data = json.load(f)
        path = data.get("subtitle_file")
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not isinstance(path, str) or not os.path.isfile(path):
        return None
    if data.get("warning"):
        log.info("A subtitle track was copied from a damaged video and may be cut short (%s): %s", path,
                 data["warning"])
    return path


def _take(store, language, v, chosen, extracted):
    """The chosen track's text copied into the waiting item's folder in `Library` and the item filled in place. ->
    True; None when the item no longer waits on that video (nothing to do); "own" when the store refused the copy,
    "later" when the disk or a busy library held it (the copy is removed again: no item holds it)."""
    from app import library_store as ls
    track, path, data = chosen
    ext = ".srt" if path.lower().endswith(".vtt") else os.path.splitext(path)[1].lower()
    stem = os.path.splitext(os.path.basename(v.video))[0]
    folder = v.rel.rpartition("/")[0] or ls.CONTENT_FOLDER
    sha = hashlib.sha256(data).hexdigest()
    want = f"{folder}/{stem}.{language}{ext}"
    target, reuse = ls.content_target(store.data_dir, want, len(data), sha)
    if reuse and store.conn.execute("SELECT 1 FROM items WHERE rel_key = ?", (ls.path_key(target),)).fetchone():
        target, reuse = ls.content_target(store.data_dir, want)    # another item's file: a name of its own
    full = os.path.join(store.data_dir, *target.split("/"))
    try:
        if not reuse:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            part = full + ".part"
            with open(part, "wb") as f:
                f.write(data)
            os.replace(part, full)
    except OSError as e:
        log.warning("A subtitle track couldn't be copied into the library (%s): %r", full, e)
        return "later"
    info = {"index": track["index"], "codec": track.get("codec"), "language": track.get("language"),
            "title": track.get("title"), "tried": len(extracted)}
    try:
        filled = True if store.fill_track(v.item_id, target, sha, info, v.record.get("video_key")) else None
    except ls.StoreError as e:                      # busy: asked again at a later look
        log.info("A video's subtitle track waits for the library (asked again later): %r", e)
        filled = "later"
    except Exception as e:                          # anything else: asked again, remembered after FAILS
        log.warning("A video's subtitle track couldn't be taken in (asked again later): %r", e)
        filled = "own"
    if filled is not True and not reuse:
        try:
            os.remove(full)                         # ours, made a moment ago, held by no item
        except OSError:
            pass
    return filled
