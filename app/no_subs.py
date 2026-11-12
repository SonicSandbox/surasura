"""Videos without subtitles (Michi-NS, 3.0.1; the spec: the 3.0 plan's tracks/tools/work/no-subs/SPEC.md, GATE PASSED
2026-10-31 with Sonic's NS-1…7 — every rule here PROVISIONAL, its P1–P9, checked by tests/test_no_subs.py).

A video in a source folder with no subtitle is a waiting item (SRC K5: *No subtitles yet*, filled in place when its
subtitle comes; `app/tracks.py` first copies out a text track the video carries). Two more ways fill it:

- **Made from the audio by Anki Miner** (`make`; offered, never automatic — *Needs you*'s *Make them from the audio*,
  one press per show): Anki Miner 3.11's `transcribe` (Z-18, its `features` names it), ONE episode per call (P1: a
  cancel loses only the one under way, each lights up as it ends), with the speech model Anki Miner already has, else
  the one Surasura installs through Anki Miner's own `setup --speech-model` (`install_speech`; AB-Q1: `small`). The
  `.srt` it writes is copied into the waiting item's own folder in `Library` (P7: `Library/<show>/<video stem>.<lang>.srt`,
  `library_store.content_target`) and the item filled in place (`Store.fill_track`, verdict `transcribed` — never
  `timed`, K16 — producer `source`, provider `transcribe`): from then it is read, listed and mined like any episode
  (`fit_check.track_timed`: timed to its own audio; Q5 ✅: mined, every card tagged `runfile.FROM_AUDIO_TAG`). Then,
  Q4 ✅ (the S3 exception Sonic approved), a copy beside the video so a player shows it — `<video stem>.<lang>.from-audio.srt`,
  only where no file has that name (never over one, never removed: S3), only while hato's beside-the-video setting
  allows it (`beside_on`: hato has no such setting yet — on, as hato itself writes beside the video), and only after
  the fill (a look that sees it then takes it as another version of the episode: `episode_names.FROM_AUDIO`,
  `Store._track_items`). A folder that takes no file (a read-only share): Surasura's copy only, said once (`beside`).
  `no_speech` → the row says *No speech found*; a video Anki Miner can't open → *Its audio couldn't be read*.
- **Found online by hato** (`find`, NS-2): only once hato's tools entry lists `find` (the contract's amendment, WP1:
  hato 1.1.x — today's hato lists only `pairings`, so nothing is ever sent) and the learner said yes once (SETTING,
  *Find them with hato*). Per source folder, `hato-cli <folder> --only-list <file> --json --progress --wait` with at
  most BATCH due videos (P2), one run at a time; hato writes the subtitle beside the video (and registers it), and the
  folder's next look fills the row in place (K5: `find` names the folders to look at again). A NOT_FOUND's
  `retry_after` is kept here, outside library state (P5: rebuilt for free — hato's own state honours its waits); a
  video is asked again on that date. A run silent for HATO_SILENT_S is stopped (P3); one that fails as a whole (offline,
  a crash) waits OFFLINE_S (P4).

What a row says (`note`): MAKING, NO_SPEECH, UNREADABLE, LOOKING, NOT_FOUND (with hato's date), MADE (a row filled from
the audio) — kept in `state_path(language)` (local data, beside Connect's ledger), read again only when that file
changed (S19); the rows whose words changed are drawn again (`Store.refeed`), only those.

Standard library only; no Qt, no Tk. Every call blocks: run it on a worker. Never Anki: `transcribe` and `setup` write
only Anki Miner's run folder and its own models.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time

log = logging.getLogger("surasura.no_subs")

STATE_VERSION = 1
FEATURE = "transcribe"              # Anki Miner's `version` feature (Z-18)
VERDICT = "transcribed"             # the origin record's verdict (`Store.fill_track`): never `timed` (K16)
PROVIDER = "transcribe"
TRANSCRIBE_TIMEOUT = 3 * 60 * 60.0  # one episode (a 24-minute one is ~6 min on a desktop CPU with large-v3: SPEC Q6)
SETTING = "subs_with_hato"          # settings.json: the learner's one yes to hato (NS-2), off until given
SETTING_ZH = "subs_with_hato_zh"    # Zh-H: the Chinese library's own yes (its card names other sites and keys)
BATCH = 200                         # P2: videos a hato run is handed at most
HATO_SILENT_S = 10 * 60.0           # P3: a hato run that says nothing this long is stopped
OFFLINE_S = 60 * 60.0               # P4: after a hato run that failed as a whole, asked again this much later
HATO_VERB = "find"                  # what hato's tools entry lists once it takes a list of waiting videos (WP1)
# Zh-C (2026-11-12, Chinese end to end): the languages hato finds subtitles in. hato up to 1.2 searches jimaku.cc, a
# site of Japanese anime subtitles, and its ranking never tries a file tagged with another language and no Japanese
# (hato 1.2 `rank.py`, "timing cannot tell a Chinese subtitle from a Japanese one") — so for a Chinese video it would
# put a Japanese subtitle beside it, named as Chinese, and hand it over as Japanese. Such a hato is never handed one.
HATO_LANGUAGES = ("ja",)
# Zh-H (2026-11-12): hato 1.3.0 (Layer 20) finds Chinese subtitles — assrt.net, then OpenSubtitles, on the learner's
# own keys, for a `--lang zh` run only — and hands them to the Chinese library. Its tools entry says so by its
# `version` alone (09-hato-layer.md §7.9): from this one, Chinese videos go to it too — and since hato's *Go back* to
# 1.2 leaves the entry naming 1.3 until the kept hato starts again (§7.1), the program itself is asked first
# (`<cli> --version`, §3's quick verb, trusted over the file) before every Chinese run
HATO_ZH_SINCE = (1, 3, 0)
_VERSION = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")       # hato's own one shape (`update.parse_version`): X.Y.Z
JOB_KIND = "transcribe"             # the job registry's kind (`services.jobs.RESOURCES`)

MAKING, NO_SPEECH, UNREADABLE, LOOKING, NOT_FOUND, MADE = ("making", "no-speech", "unreadable", "looking",
                                                           "not-found", "made")
WAITING_NOTES = (MAKING, NO_SPEECH, UNREADABLE, LOOKING, NOT_FOUND)     # said on a waiting row
DONE_NOTES = (NO_SPEECH, UNREADABLE)  # a video made no subtitle from: not offered again until it changes

_make_lock = threading.Lock()       # one `make` at a time in a process
_find_lock = threading.Lock()       # one hato run at a time in a process (hato holds its own lock too: `--wait`)
_state_lock = threading.Lock()      # the state file read, changed and written by one thread at a time
_NOTES = {}                         # `note`'s last read per language: {"stamp": the file's (mtime_ns, size), "notes"}
_MINERS = {}                        # Anki Miner's program -> {"stamp": `anki_miner.stamp`, "miner": (path, profile)}


# --- the state file ------------------------------------------------------------------------------------------------ #
def state_path(language):
    """The rows' notes and hato's retry dates (beside Connect's ledger and the tracks' cache: local data)."""
    from app.connect import ledger
    return os.path.join(ledger.folder(), f"no-subs-{language}.json")


def _load(language, store_id):
    try:
        with open(state_path(language), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == STATE_VERSION and data.get("store") == store_id and \
                isinstance(data.get("notes"), dict) and isinstance(data.get("hato"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": STATE_VERSION, "store": store_id, "notes": {}, "hato": {}, "offline_until": 0}


def _save(language, data):
    """Written whole (a temp file, then replaced); one that can't be written is only lost words: logged."""
    path = state_path(language)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("What the videos without subtitles say couldn't be kept (%s): %r", path, e)


def _change(store, language, notes=None, drop_if=None, hato=None, offline_until=None, unless=(), live=None):
    """One change to the state file under its lock: `notes` {rel: note} (a kind, or (kind, extra), or (kind, extra,
    mark)); `drop_if` {rel: kind} — that note goes only while it is still that kind (another writer's newer note stays);
    `unless`: kinds a note of `notes` never writes over (hato's answer never over a MAKING); `hato` {video key:
    record}; `offline_until`; `live` {rel: video stats} (`tidy`: the rows waiting now) — a waiting row's note goes
    once its row waits no more, a NO_SPEECH / UNREADABLE once its video changed (MADE notes stay, and LOOKING: its hato
    run, beside `tidy` on another worker, drops it at its end). MAKING and LOOKING carry this process's id: one a
    Surasura that quit or crashed left is no note at all (`_live`). The rows whose words changed are drawn again (S19:
    only those)."""
    store_id = store.meta().get("store_id")
    with _state_lock:
        data = _load(language, store_id)
        before = json.dumps(data, sort_keys=True)
        data["notes"] = {rel: v for rel, v in data["notes"].items() if _live(v)}
        said = dict(data["notes"])
        for rel, kind in (drop_if or {}).items():
            if (data["notes"].get(rel) or [None])[0] == kind:
                del data["notes"][rel]
        for rel, value in (notes or {}).items():
            if (data["notes"].get(rel) or [None])[0] in unless:
                continue
            data["notes"][rel] = _entry(value)
        if live is not None:
            data["notes"] = {rel: v for rel, v in data["notes"].items() if v[0] in (MADE, LOOKING) or (
                rel in live and (v[0] not in DONE_NOTES or len(v) < 3 or v[2] == live[rel]))}
        if hato:
            data["hato"].update(hato)
        if offline_until is not None:
            data["offline_until"] = offline_until
        if json.dumps(data, sort_keys=True) != before:
            _save(language, data)
        _keep_notes(language, data["notes"])
    moved = {rel for rel in set(said) | set(data["notes"]) if said.get(rel) != data["notes"].get(rel)}
    if moved:
        _redraw(store, moved)
    return data


def _entry(value):
    """A note as the file keeps it: [kind, extra, mark] — MAKING / LOOKING marked with this process's id."""
    kind, extra, mark = (list(value) + [None, None])[:3] if isinstance(value, (list, tuple)) else (value, None, None)
    if kind in TRANSIENT:
        mark = os.getpid()
    return [kind, extra, mark]


def _live(v):
    """Is a kept note still true? A MAKING or LOOKING only while the process that wrote it is this one."""
    return isinstance(v, list) and bool(v) and (v[0] not in TRANSIENT or (len(v) > 2 and v[2] == os.getpid()))


TRANSIENT = (MAKING, LOOKING)
NOTES_FRESH_S = 1.0     # `note`: the file looked at again at most this often (this process's writes are seen at once)


def _redraw(store, rels):
    try:
        from app import library_store as ls
        keys = [ls.path_key(r) for r in rels]
        ids = []
        for chunk in range(0, len(keys), 400):
            part = keys[chunk:chunk + 400]
            ids += [i for (i,) in store.conn.execute(f"SELECT id FROM items WHERE rel_key IN "
                                                     f"({','.join('?' * len(part))})", part)]
        if ids:
            store.refeed(ids)
    except Exception as e:
        log.info("The rows of the videos without subtitles are drawn again at their next change: %r", e)


def note(rel_path, language=None):
    """What a row says of its video's subtitle (MAKING, NO_SPEECH, UNREADABLE, LOOKING, MADE, or (NOT_FOUND, date)),
    else None. `rel_path`: the item's as the store holds it; `language` None: either library's (two libraries' items
    never share a place). A dict look: the file is looked at again at most every NOTES_FRESH_S and read only once it
    changed (S19; this process's own writes are kept as they are written, `_change`); never raises."""
    if not rel_path:
        return None
    for lang in ([language] if language else ("ja", "zh")):
        got = _notes(lang).get(rel_path)
        if got and _live(got):
            if got[0] != NOT_FOUND:
                return got[0]
            # Zh-H: a Chinese NOT_FOUND says so (its row names hato's Chinese sites, never jimaku): (NOT_FOUND, date, "zh")
            return (got[0], got[1]) + (("zh",) if lang == "zh" else ())
    return None


def _where(language):
    """(the cache's key, the state file's path): the path worked out once per place (a test moves the data root)."""
    key = (language, os.environ.get("SURASURA_TEST_ROOT"), os.environ.get("LOCALAPPDATA"))
    path = _PATHS.get(key)
    if path is None:
        path = _PATHS[key] = state_path(language)
    return key, path


_PATHS = {}


def _keep_notes(language, notes):
    key, path = _where(language)
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
    except (OSError, ValueError):
        stamp = None
    _NOTES[key] = {"stamp": stamp, "notes": dict(notes), "at": time.monotonic()}


def _notes(language):
    try:
        key, path = _where(language)
    except Exception:
        return {}
    held = _NOTES.get(key)
    if held is not None and time.monotonic() - held["at"] < NOTES_FRESH_S:
        return held["notes"]
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
    except (OSError, ValueError):
        stamp = None
    if held is None or held["stamp"] != stamp:
        notes = {}
        if stamp is not None:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                notes = data.get("notes") if isinstance(data, dict) and isinstance(data.get("notes"), dict) else {}
            except (OSError, ValueError):
                notes = {}
        held = {"stamp": stamp, "notes": notes}
    held["at"] = time.monotonic()
    _NOTES[key] = held
    return held["notes"]


def tidy(store, language, away=()):
    """(The looks' worker, after each look.) The notes kept true: a row that waits no more says nothing (MADE notes
    stay, and a hato run's LOOKING: the run drops it), a NO_SPEECH / UNREADABLE whose video changed since is offered
    again. Writes only when something moved."""
    held = _notes(language)
    if not held:
        return
    live = {}
    for _item_id, rel, record in store.waiting_tracks():
        kept = held.get(rel)
        stats = kept[2] if kept and len(kept) > 2 else None     # a video not read now (away, gone): as it was
        if kept and kept[0] in DONE_NOTES and record.get("root") not in away:
            try:
                st = os.stat(record.get("video_path"))
                stats = [st.st_size, st.st_mtime_ns]
            except (OSError, TypeError, ValueError):
                pass
        live[rel] = stats
    if any(v and v[0] not in (MADE, LOOKING) and (rel not in live or (v[0] in DONE_NOTES and len(v) > 2 and
                                                                   v[2] != live[rel])) for rel, v in held.items()):
        _change(store, language, live=live)


# --- which videos ------------------------------------------------------------------------------------------------- #
class Video:
    """A waiting video: its item, the item's place, its record, the video, its key and its stats."""
    __slots__ = ("item_id", "rel", "record", "video", "key", "stats")

    def __init__(self, item_id, rel, record, video, key, stats):
        self.item_id, self.rel, self.record, self.video, self.key, self.stats = item_id, rel, record, video, key, stats


def waiting(store, item_ids=None, away=()):
    """The waiting videos there now (`Store.waiting_tracks`: never an audiobook's) -> [Video]; `item_ids` only those;
    `away`: source ids the last look couldn't reach (their videos aren't read). A cloud placeholder is never read (B3)."""
    from app import library_store as ls
    want = None if item_ids is None else {int(i) for i in item_ids}
    out = []
    for item_id, rel, record in store.waiting_tracks():
        if want is not None and item_id not in want:
            continue
        if record.get("root") in away:
            continue
        video = record.get("video_path")
        try:
            st = os.stat(video)
        except (OSError, TypeError, ValueError):
            continue
        if ls.is_placeholder(st):
            continue
        key = record.get("video_key") or ls.path_key(os.path.abspath(video))
        out.append(Video(item_id, rel, record, video, key, [st.st_size, st.st_mtime_ns]))
    return out


# --- made from the audio (Anki Miner) ------------------------------------------------------------------------------ #
def can_make(settings, path=None):
    """(Anki Miner's program, the profile its calls name) when this computer's Anki Miner makes subtitles from audio
    (`transcribe` among its features, Z-18: 3.11), else None. Read again only when its program or settings change
    (`anki_miner.stamp`, S19); a failed read is no answer (asked again next time). Never raises."""
    from app.connect import anki_miner
    try:
        exe = path if path is not None else anki_miner.find(settings)
    except Exception:
        return None
    if not exe:
        return None
    stamp = anki_miner.stamp(exe)
    held = _MINERS.get(exe)
    if held is not None and stamp is not None and held["stamp"] == stamp:
        return held["miner"]
    try:
        info = anki_miner.version(exe)
        if FEATURE not in (info.get("features") or ()):
            miner = None
        else:
            name = str((settings or {}).get("connect_anki_miner_profile") or anki_miner.DEFAULT_PROFILE)
            try:
                profile = anki_miner.choose_profile(info, anki_miner.profiles(exe), name)
            except anki_miner.AnkiMinerError:
                profile = None              # a profile it lacks: its active one (listening needs no deck)
            miner = (exe, profile)
    except Exception as e:
        log.warning("Anki Miner can't be asked about making subtitles now (asked again later): %r", e)
        return None
    _MINERS[exe] = {"stamp": stamp, "miner": miner}
    return miner


def speech_ready(miner, language):
    """Does this Anki Miner have a speech model for `language` now (`anki_miner.speech_ready`: one it has is used as it
    is, never a second download)? -> True / False; None when it can't be asked now (busy, its setup running)."""
    from app.connect import anki_miner, lineup
    exe, profile = miner
    try:
        return anki_miner.speech_ready(exe, language, profile, lineup.folder(lineup.SPEECH))
    except anki_miner.AnkiMinerError as e:
        log.info("Anki Miner's speech model can't be checked now: %s", e.message)
        return None


def install_speech(miner, language, cancel=None, on_poll=None):
    """Anki Miner's own `setup --speech-model` (AB-Q2 (b): installed only through it; its download can't show bytes or
    stop part way — API.md), its progress file in *Finish its setup*'s folder so a Connect told BUSY meanwhile says Anki
    Miner is finishing its setup (`anki_miner.setting_up`; Surasura's heartbeat beside it). Blocking. -> None when
    installed (or there); STOPPED when `cancel()` ended the wait (Anki Miner's setup goes on by itself: never bound, so
    the next press finds it there or still running); else the reason in plain words."""
    from app.connect import anki_miner
    exe, profile = miner
    staging = anki_miner.setup_folder()
    started = time.monotonic()
    try:
        os.makedirs(staging, exist_ok=True)
        out = os.path.join(staging, f"speech-{os.getpid()}-{time.time_ns()}.json")    # each setup its own
        proc = anki_miner.start(exe, anki_miner.speech_setup_args(
            language, profile, os.path.join(staging, anki_miner.PROGRESS)), out, bind=False)
        while True:
            try:
                verdict = anki_miner.ended(proc, out)
            except anki_miner.AnkiMinerError:
                _gone(out)
                raise
            if verdict is not None:
                _gone(out)
                break
            _heartbeat()
            if on_poll is not None:
                on_poll()
            if cancel is not None and cancel():
                return STOPPED
            if time.monotonic() - started > anki_miner.SPEECH_TIMEOUT:
                return "it took longer than three hours"
            time.sleep(anki_miner.POLL_S)
    except anki_miner.AnkiMinerError as e:
        return e.message
    except OSError as e:
        return str(e)
    why = anki_miner.speech_setup_done(verdict)
    if why is None:
        anki_miner._SPEECH.clear()          # installed: asked again at once
    return why


STOPPED = "stopped"


def _gone(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _heartbeat():
    """Surasura's heartbeat beside the setup's progress file (`anki_miner.setting_up`)."""
    from app.connect import anki_miner
    beat = os.path.join(anki_miner.setup_folder(), anki_miner.HEARTBEAT)
    try:
        with open(beat, "a"):
            pass
        os.utime(beat)
    except OSError:
        pass


def make(store, language, item_ids, settings=None, stop=None, on_progress=None, path=None):
    """Each of `item_ids`' waiting videos (one show's, *Make them from the audio*) made a subtitle from its audio, one
    `transcribe` call each (P1), the item filled in place as each ends. `stop()`: the window closes or the job is
    cancelled — the episode under way is cancelled (Anki Miner keeps nothing of it), nothing more asked; `on_progress(
    done, total, percent)`: each poll. -> {"made", "no_speech", "unreadable", "failed", "gone", "beside_refused"} counts;
    {"no_miner": True} (no Anki Miner here that makes them), {"no_model": True} (its speech model isn't there: the
    caller asks, `install_speech`, then asks again), {"busy": True} (one runs already)."""
    if not _make_lock.acquire(blocking=False):
        return {"busy": True}
    try:
        return _make(store, language, item_ids, settings if settings is not None else _settings(),
                     stop or (lambda: False), on_progress or (lambda *_a: None), path)
    finally:
        _make_lock.release()


def _make(store, language, item_ids, settings, stop, on_progress, path):
    from app.connect import anki_miner
    miner = can_make(settings, path)
    if miner is None:
        return {"no_miner": True}
    ready = speech_ready(miner, language)
    if not ready:
        return {"no_model": True} if ready is False else {"busy": True}
    todo = waiting(store, item_ids)
    out = {"made": 0, "no_speech": 0, "unreadable": 0, "failed": 0, "gone": len(set(item_ids)) - len(todo),
           "beside_refused": 0}
    run_dir = os.path.join(os.path.dirname(state_path(language)), f"no-subs-run-{language}")
    beside = beside_on(settings)
    # every episode of the press says *Making…* at once (one write): hato never takes one meanwhile (`due`), nor its
    # answer writes over it (`unless`); each goes back to nothing once its turn ends without a subtitle
    _change(store, language, notes={v.rel: MAKING for v in todo})
    try:
        for n, v in enumerate(todo):
            if stop():
                break
            try:
                said = _one(store, language, miner, run_dir, v, stop, lambda pct, n=n: on_progress(n, len(todo), pct),
                            beside, out)
            except Exception as e:                          # never the window's fault: asked again on the next press
                log.warning("A video's subtitle couldn't be made from its audio: %r", e)
                said = "failed"
            if said != "made":                              # its turn ended with no fill: *Making…* goes now
                _change(store, language, drop_if={v.rel: MAKING})
            if said == "no_model":
                out["no_model"] = True
                break
            if said == "cancelled":
                break
        on_progress(len(todo), len(todo), 100)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
        # a row still MAKING (cancelled, failed, the window closed) says nothing again: offered as before
        _change(store, language, drop_if={v.rel: MAKING for v in todo})
    log.info("Subtitles made from the audio (%s): %s", language, out)
    return out


def _one(store, language, miner, run_dir, v, stop, on_pct, beside, out):
    """One episode -> "made" · "no_speech" · "unreadable" · "failed" · "gone" · "cancelled" · "no_model"."""
    from app.connect import anki_miner
    exe, profile = miner
    run_id = f"s{v.item_id}"
    os.makedirs(run_dir, exist_ok=True)
    job = {"schema": 1, "run_dir": run_dir, "language": language,
           "episodes": [{"run_id": run_id, "video_file": os.path.abspath(v.video)}]}
    if profile:
        job["profile"] = profile
    job_path = os.path.join(run_dir, f"transcribe-{run_id}.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)

    def poll():
        if stop():
            anki_miner.cancel(run_dir, run_id)
        progress = anki_miner.read_progress(run_dir, run_id)
        if progress and progress.get("stages"):
            on_pct(percent(progress))
    try:
        verdict = anki_miner.api(exe, ["transcribe", job_path], timeout=TRANSCRIBE_TIMEOUT, on_poll=poll)
    except anki_miner.AnkiMinerError as e:
        log.warning("Anki Miner couldn't make a subtitle from %s's audio (asked again on the next press): %s",
                    v.video, e.message)
        out["failed"] += 1
        return "failed"
    run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == run_id), None)
    if run is None:
        if verdict.get("error") == "SETUP_ERROR":           # the speech model (or ffmpeg) went: asked again
            anki_miner._SPEECH.clear()
            return "no_model"
        out["failed"] += 1
        log.warning("Anki Miner refused to make a subtitle (asked again on the next press): %s", verdict.get("message"))
        return "failed"
    if not run.get("ok"):
        code = run.get("error")
        if code == "CANCELLED":
            return "cancelled"
        if code in ("VIDEO_UNREADABLE", "AUDIO_UNREADABLE"):
            _change(store, language, notes={v.rel: (UNREADABLE, None, v.stats)})
            out["unreadable"] += 1
            return "unreadable"
        if code == "SETUP_ERROR":
            anki_miner._SPEECH.clear()
            return "no_model"
        out["failed"] += 1
        return "failed"
    made = _made_file(run_dir, run)
    if made is None:
        out["failed"] += 1
        return "failed"
    status, srt = made
    if status == "no_speech" or srt is None:
        _change(store, language, notes={v.rel: (NO_SPEECH, None, v.stats)})
        out["no_speech"] += 1
        return "no_speech"
    said = take(store, language, v, srt, beside, out)
    if said == "made":
        out["made"] += 1
    elif said == "no_speech":
        out["no_speech"] += 1
    else:
        out["failed" if said != "gone" else "gone"] += 1
    return said


def percent(progress):
    """`transcribe`'s progress (two stages, extracting then transcribing, each `done` of `total` in percent) -> the
    episode's percent: extracting its first EXTRACT_SHARE, listening the rest; never 100 before it ends."""
    total = progress.get("total") or 100
    part = min(1.0, max(0.0, (progress.get("done") or 0) / total))
    if (progress.get("stage") or 1) <= 1:
        return int(EXTRACT_SHARE * part)
    return min(99, int(EXTRACT_SHARE + (100 - EXTRACT_SHARE) * part))


EXTRACT_SHARE = 10                  # percent of an episode's making its audio's extraction takes (PROVISIONAL)


def _made_file(run_dir, run):
    """(status, its .srt or None) from a run's `transcribe-<n>.json` (inside its run folder), or None (unreadable)."""
    name = os.path.basename(str(run.get("file") or ""))
    try:
        with open(os.path.join(run_dir, run["run_id"], name), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    srt = data.get("subtitle_file")
    return data.get("status"), srt if isinstance(srt, str) and os.path.isfile(srt) else None


def take(store, language, v, srt, beside=True, out=None):
    """The made `.srt` copied into the waiting item's folder in `Library` and the item filled in place
    (`Store.fill_track`, verdict `transcribed`); then (Q4) its copy beside the video. -> "made"; "no_speech" (its text
    isn't the library's language: the look's one rule, `sources._refusal`); "gone" (the item no longer waits on that
    video: filled or removed meanwhile, or its video changed — nothing kept); "failed" (the copy couldn't be written, or
    the store refused it: asked again on the next press)."""
    from app import library_store as ls, sources
    try:
        with open(srt, "rb") as f:
            data = f.read()
    except OSError:
        return "failed"
    if not data or sources._refusal(data, language) is not None:
        _change(store, language, notes={v.rel: (NO_SPEECH, None, v.stats)})
        return "no_speech"
    stem = os.path.splitext(os.path.basename(v.video))[0]
    folder = v.rel.rpartition("/")[0] or ls.CONTENT_FOLDER
    sha = hashlib.sha256(data).hexdigest()
    want = f"{folder}/{stem}.{language}.srt"
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
        log.warning("A made subtitle couldn't be copied into the library (%s): %r", full, e)
        return "failed"
    # the row's words first, so its first read after the fill says *Made from the audio*
    _change(store, language, notes={target: MADE}, drop_if={v.rel: MAKING})
    info = {"model": None, "made_from": "audio"}
    try:
        filled = store.fill_track(v.item_id, target, sha, info, v.record.get("video_key"), verdict=VERDICT,
                                  provider=PROVIDER)
    except Exception as e:
        log.warning("A made subtitle couldn't be taken in (asked again on the next press): %r", e)
        filled = None
    if not filled:
        _change(store, language, drop_if={target: MADE})
        if not reuse and not store.conn.execute("SELECT 1 FROM items WHERE rel_key = ?",
                                                (ls.path_key(target),)).fetchone():
            try:
                os.remove(full)                     # ours, made a moment ago, held by no item
            except OSError:
                pass
        return "gone" if filled is False else "failed"
    if beside and not _beside(v.video, stem, language, data) and out is not None:
        out["beside_refused"] += 1
    return "made"


def beside_path(video, language):
    """Where a made subtitle's copy goes beside its video (Q4): `<video stem>.<lang>.from-audio.srt`."""
    from app.episode_names import FROM_AUDIO
    stem = os.path.splitext(os.path.basename(video))[0]
    return os.path.join(os.path.dirname(os.path.abspath(video)), f"{stem}.{language}.{FROM_AUDIO}.srt")


def _beside(video, stem, language, data):
    """The copy beside the video, only where no file has its name (never over one, S3), and never half a file: written
    whole to a temp name in that folder, then given its name by a step that refuses a name already taken (`os.link`;
    Windows' rename refuses too, where a folder has no links). -> True when it is there now (written, or a file there
    already); False when the folder took none (read-only, a share offline, a full disk: the temp file goes)."""
    path = beside_path(video, language)
    if os.path.lexists(path):
        return True                                 # whatever is there stays (S3)
    tmp = f"{path}.{os.getpid()}.part"
    try:
        with open(tmp, "xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return True
        except OSError:
            if sys.platform != "win32":
                raise
            try:
                os.rename(tmp, path)                # Windows: refused when the name is taken
            except FileExistsError:
                return True
        return True
    except OSError as e:
        log.info("A made subtitle's copy couldn't go beside its video (%s): %r", path, e)
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def beside_on(settings=None):
    """Q4: may a made subtitle's copy go beside its video? hato's beside-the-video setting decides (SRC-7) once hato
    has one and says so (`hato_config`'s BESIDE_KEY); until then on — as hato itself writes beside the video."""
    config = hato_config(settings)
    value = (config or {}).get(BESIDE_KEY)
    return value is not False


BESIDE_KEY = "write_beside_video"   # hato's SRC-7 setting as `config --show --json` will name it (WP1, hato's to-do)


# --- found online (hato) ------------------------------------------------------------------------------------------- #
def hato_entry():
    """hato's tools entry (`tools_entry.read`), or None (no hato, or one Surasura can't speak to). Never raises."""
    try:
        from app import tools_entry
        return tools_entry.read("hato")
    except Exception:
        return None


def setting(language):
    """The settings.json key of the learner's yes to hato for `language`'s videos (NS-2): Japanese `SETTING` (as
    since 3.0.1), Chinese `SETTING_ZH` (Zh-H: the Chinese card's own yes — another site, the learner's own keys)."""
    return SETTING_ZH if language == "zh" else SETTING


def hato_languages(entry):
    """The languages this hato finds subtitles in -> a tuple: Japanese (`HATO_LANGUAGES`), and Chinese once its
    entry's `version` is HATO_ZH_SINCE or later (§7.9). A version that doesn't read as numbers: Japanese only."""
    version = entry.get("version") if isinstance(entry, dict) else None
    return HATO_LANGUAGES + ("zh",) if _finds_zh(version) else HATO_LANGUAGES


def _finds_zh(version):
    """Does `version` (exactly X.Y.Z, hato's one shape: a `1.3.0rc1` or `v1.3.0` is not one) name a hato that finds
    Chinese subtitles (HATO_ZH_SINCE or later)?"""
    got = _VERSION.fullmatch(version) if isinstance(version, str) else None
    return bool(got) and tuple(int(n) for n in got.groups()) >= HATO_ZH_SINCE


def hato_says_zh(cli, run=None):
    """Zh-H: does the hato program at `cli` itself say it finds Chinese subtitles (`<cli> --version` -> `hato X.Y.Z`,
    HATO_ZH_SINCE or later)? Asked before each Chinese run: its entry can still name a 1.3 that *Go back* replaced
    (§7.1). No answer, another shape or an older version: False — no Chinese video is handed to it. Never raises."""
    try:
        done = (run or subprocess.run)([cli, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, timeout=30, creationflags=_NO_WINDOW)
        words = (done.stdout or b"").decode("utf-8", "replace").strip().split()
        return done.returncode == 0 and len(words) == 2 and words[0] == "hato" and _finds_zh(words[1])
    except Exception:
        return False


def hato_finds(entry=None, language="ja"):
    """hato's command line when its entry lists HATO_VERB (it takes a list of waiting videos: WP1, hato 1.1.x) and it
    finds subtitles in `language` (`hato_languages`), else None — a hato that lists only `pairings` is sent nothing."""
    entry = hato_entry() if entry is None else entry
    if not isinstance(entry, dict) or HATO_VERB not in (entry.get("verbs") or ()):
        return None
    if language not in hato_languages(entry):
        return None
    cli = entry.get("cli")
    return cli if isinstance(cli, str) and os.path.exists(cli) else None


def hato_on(settings, language="ja"):
    """Does Surasura hand hato `language`'s waiting videos: hato takes them in that language (`hato_finds`) and the
    learner said yes once for that library (NS-2, `setting`)?"""
    return bool((settings or {}).get(setting(language))) and hato_finds(language=language) is not None


def hato_config(settings=None, run=None):
    """hato's own settings as `hato-cli config --show --json` gives them (NS-4: hato's config is their one home), or
    None (no hato, or it didn't answer). Never raises."""
    entry = hato_entry()
    cli = entry.get("cli") if isinstance(entry, dict) else None
    if not cli:
        return None
    try:
        done = (run or subprocess.run)([cli, "config", "--show", "--json"], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
                                       creationflags=_NO_WINDOW)
        data = json.loads((done.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def due(store, language, now=None, away=()):
    """The waiting videos hato is asked about now: not asked yet, changed since, or past hato's `retry_after` ->
    [Video]. Nothing while a failed run's wait (P4) lasts."""
    now = time.time() if now is None else now
    data = _load(language, store.meta().get("store_id"))
    if (data.get("offline_until") or 0) > now:
        return []
    out = []
    for v in waiting(store, away=away):
        held = data["hato"].get(v.key)
        if isinstance(held, dict) and held.get("stats") == v.stats and (held.get("retry_at") or 0) > now:
            continue
        kept = data["notes"].get(v.rel)
        if kept and _live(kept) and kept[0] in DONE_NOTES + (MAKING,):
            continue
        out.append(v)
    return out


def find(store, language, settings=None, stop=None, now=None, away=(), popen=None):
    """The due waiting videos handed to hato, per source folder, at most BATCH a run (P2), one run at a time. ->
    {"asked", "found", "not_found", "failed", "roots": {root id: its folder}} — the folders whose next look takes what
    hato wrote beside their videos (K5); {"off": True} when hato isn't asked (no yes for this library, a hato that
    takes no list, or one that finds no subtitles in this language: `hato_languages`);
    {"busy": True} when one runs already. `popen`: the process starter (a test's)."""
    settings = settings if settings is not None else _settings()
    cli = hato_finds(language=language) if settings.get(setting(language)) else None
    if not cli:
        return {"off": True}
    if not _find_lock.acquire(blocking=False):
        return {"busy": True}
    try:
        return _find(store, language, cli, stop or (lambda: False), now, away, popen or subprocess.Popen)
    finally:
        _find_lock.release()


def _find(store, language, cli, stop, now, away, popen):
    out = {"asked": 0, "found": 0, "not_found": 0, "failed": 0, "roots": {}}
    todo = due(store, language, now, away)
    if not todo:
        return out
    if language == "zh" and not hato_says_zh(cli):      # Zh-H: the program, not only its entry (§7.9)
        return {"off": True}
    roots = {r["id"]: r["path"] for r in store.sources(counts=False)}
    by_root = {}
    for v in todo:
        root = v.record.get("root")
        if root in roots:
            by_root.setdefault(root, []).append(v)
    run_dir = os.path.join(os.path.dirname(state_path(language)), f"no-subs-hato-{language}")
    os.makedirs(run_dir, exist_ok=True)
    try:
        for root, videos in by_root.items():
            for n in range(0, len(videos), BATCH):
                if stop():
                    return out
                batch = videos[n:n + BATCH]
                _change(store, language, notes={v.rel: LOOKING for v in batch}, unless=(MAKING,))
                found = out["found"]
                try:
                    ok = _hato_run(store, language, cli, roots[root], batch, run_dir, stop, now, out, popen)
                finally:
                    _change(store, language, drop_if={v.rel: LOOKING for v in batch})
                if out["found"] > found:
                    out["roots"][root] = roots[root]
                if stop():
                    return out                  # the window closing says nothing of hato: no wait
                if not ok:
                    _change(store, language, offline_until=(time.time() if now is None else now) + OFFLINE_S)
                    return out
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    return out


def _hato_run(store, language, cli, folder, batch, run_dir, stop, now, out, popen):
    """One hato run over `batch` (its list file: Windows' command-line limit, hato's A33) -> True when it answered
    (whatever it found); False when it failed as a whole (no video line: offline, a crash, a hang past HATO_SILENT_S)."""
    listed = os.path.join(run_dir, "only.txt")
    with open(listed, "w", encoding="utf-8") as f:
        f.write("\n".join(os.path.abspath(v.video) for v in batch) + "\n")
    by_video = {os.path.normcase(os.path.abspath(v.video)): v for v in batch}
    command = [cli, folder, "--only-list", listed, "--json", "--progress", "--wait", "--lang", language]
    try:
        proc = popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     creationflags=_NO_WINDOW)
    except OSError as e:
        log.warning("hato couldn't be started (asked again later): %r", e)
        out["failed"] += len(batch)
        return False
    lines, heard = [], [time.monotonic()]
    reader = threading.Thread(target=_read_lines, args=(proc.stdout, lines, heard), daemon=True)
    reader.start()
    while reader.is_alive():
        reader.join(0.5)
        if stop() or time.monotonic() - heard[0] > HATO_SILENT_S:
            _end(proc)
            break
    _end(proc)
    answered, records, said = False, {}, {}
    stamp = time.time() if now is None else now
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "video":
            continue
        answered = True
        v = by_video.get(os.path.normcase(os.path.abspath(str(obj.get("video") or ""))))
        if v is None:
            continue
        out["asked"] += 1
        outcome = obj.get("outcome")
        if outcome == "CONFIDENT":
            out["found"] += 1           # the folder's next look fills it (K5); still waiting an hour on: asked again
            records[v.key] = {"stats": v.stats, "outcome": outcome, "asked_at": stamp, "retry_at": stamp + OFFLINE_S}
        elif outcome == "NOT_FOUND":
            out["not_found"] += 1
            retry = _when(obj.get("retry_after"))
            # never sooner than OFFLINE_S (a date already past, a time read in another zone: never asked each look)
            retry = max(retry if retry is not None else 0, stamp + OFFLINE_S)
            records[v.key] = {"stats": v.stats, "outcome": outcome, "asked_at": stamp, "retry_at": retry}
            said[v.rel] = (NOT_FOUND, time.strftime("%Y-%m-%d", time.localtime(retry)))
        else:                       # skipped (present, embedded, refused …): asked again OFFLINE_S on
            records[v.key] = {"stats": v.stats, "outcome": str(outcome or ""), "asked_at": stamp,
                              "retry_at": stamp + OFFLINE_S}
    if answered:                    # a video hato said nothing of (a path written another way, a cut run): an hour on
        for v in batch:
            records.setdefault(v.key, {"stats": v.stats, "outcome": "", "asked_at": stamp,
                                       "retry_at": stamp + OFFLINE_S})
    if records or said:
        _change(store, language, notes=said, hato=records, unless=(MAKING,))
    if not answered:
        out["failed"] += len(batch)
    return answered


def _read_lines(stream, lines, heard):
    try:
        for raw in iter(stream.readline, b""):
            heard[0] = time.monotonic()
            text = raw.decode("utf-8", "replace").strip()
            if text:
                lines.append(text)
    except (OSError, ValueError):
        pass


def _end(proc):
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def _when(value):
    """hato's `retry_after` (an ISO date or date-time) -> seconds since the epoch, or None."""
    import datetime
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return time.mktime(d.timetuple())
    return d.timestamp()


def _settings():
    from app import settings_manager
    try:
        return settings_manager.load_settings()
    except Exception:
        return {}
