"""Listening rounds (Piyo-LR, 3.0.11; Sonic 2026-11-14: "Yeah build both"): the learner's own AI only writes the lines;
Surasura does the rest on this PC — each line checked against the learner's known words (the reading rules of
`surasura_check_text`), voiced by the AI voice, the clips joined into one timed track, saved as a round.

    surasura_listening_round(lines)   (app/cli/mcp_server.py; this module's `check_lines`, then `queue`)
        a line that fails: only which words to swap go back to the AI, and NOTHING is queued
        all pass: the round's folder, `User Files/<lang>/practice/<round_id>/` with `round.json` (state "queued"), and
        while practice rounds are kept its round record beside it (`practice_rounds`: listed by surasura_rounds, done
        again by `again=` — a made round's files again, no voice, no tokens)
    the maker: `surasura-cli _listen` (`start_maker`), its own process, below normal priority (engine.md § Heavy work),
        one at a time on the PC (`LOCK`, an OS lock: two rounds queue, never collide); it outlives the AI's session
        each line's clip -> `lines/NN.wav` (playable as it lands; kept: one line alone, to loop on any player)
        all lines -> `<name>.srt` + `<name>.mp3` (a short gap between lines), `<name> (pauses).srt` + `.mp3` (a pause
        after every line) — joined here as PCM, so every cue is the clip's own length to the sample, then ONE ffmpeg
        encode each (no ffmpeg: `<name>.wav`, and the copy with pauses is skipped and said)
        `state: done` is written LAST: a Stop, a cancel or a crash leaves the round queued / making / cancelled, never
        done (a later maker picks up a queued or making one: the clips made are kept)

The voice comes from ONE table, `VOICES` (language -> the voice's module; lead 2026-11-14: a Chinese voice plugs in
there later with no change to the round, the timing or the saving). A voice module answers `why_not(settings)` (None:
ready; else one plain sentence), `usable(text)` (None, or why the voice can't read it), `seconds_per_line()`, and
`Speaker(settings)` — a context manager holding the voice for this run (`Busy` when another run holds it) with
`speak(text) -> wav bytes`. Japanese today: `modules/irodori/listen.py`. The round itself never names the voice.

Playback is plain files (lead 2026-11-14: no in-app player): any player or phone opens them; `open_file` hands one to
the system's player as the window's ▶ does for an audio item (`app/services/play.py`: audio always opens in the
program Windows picks). Nothing here leaves the PC: the voice runs on 127.0.0.1 (its module), ffmpeg is a local
program. `tests/test_listening.py` (+ `modules/irodori/tests/test_listen.py`).
"""
import array
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import wave

# --- the one language -> voice table (lead 2026-11-14) ------------------------------------------------------------- #
def _ai_voice():
    from modules.irodori import listen          # (a static import: the frozen build's analysis finds it)
    return listen


VOICES = {"ja": _ai_voice}                      # language -> its voice's loader; a Chinese voice is one more row
NOT_YET = {"zh": "Listening rounds are Japanese only for now: a Chinese voice isn't ready yet."}
NO_VOICE = "This Surasura has no AI voice for listening rounds."

# --- PROVISIONAL (each for Sonic; README-style list in the lane's register) ---------------------------------------- #
KIND = "listening"              # the round kind's name, as surasura_rounds lists it
LINES_MOST = 20                 # lines a round may have (a practice round's save takes 20 lines at most)
LINE_GAP_S = 0.6                # the plain track: a short breath between lines
PAUSE_S = 3.0                   # the copy with pauses: a pause after every line
PAUSED = " (pauses)"            # that copy's name: "<name> (pauses).mp3"
NAME = "Listening"              # the files' name when the AI gives no title
MP3_KBPS = 128                  # as the AI voice's own clips (modules/irodori/make.py): speech, mono

TITLE_CHARS = 40
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(10)}
PROBLEM_CHARS = 200             # a failed round's why, as the AI reads it
LOCK = "listening-maker.lock"   # in the install's locks folder: one maker at a time
TRIES = 3                       # a round a maker starts this often and never finishes is failed, said
LOCK_LOOKS = 10                 # a new maker tries it this often, 0.2 s apart, before it leaves it to the holder
BUSY_WAIT_S = 1800              # the voice held by another run (card audio): waited for this long, then said
BUSY_LOOK_S = 10
STATES = ("new", "queued", "making", "done", "cancelled", "failed")     # new: written, its record not yet
CANCEL = "cancel"               # a file in the round's folder: the maker stops between two lines
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class Problem(ValueError):
    """A round that can't be made, in words the learner's AI can say."""


# --- the voice ----------------------------------------------------------------------------------------------------- #
def voice(language):
    """The voice module for `language` (VOICES), or None: no row, or its module absent (a build without it)."""
    load = VOICES.get(language)
    if load is None:
        return None
    try:
        return load()
    except Exception:                           # the module left out of this build, or broken: no voice
        return None


def why_not(language, settings):
    """Why a listening round can't be made in `language` now -> one plain sentence, or None (it can)."""
    if language not in VOICES:
        return NOT_YET.get(language) or NO_VOICE
    module = voice(language)
    if module is None:
        return NO_VOICE
    try:
        return module.why_not(settings or {})
    except Exception as e:
        return f"The AI voice can't be asked just now ({e})."


# --- the check: each line against the known words (the reading rules), before anything is made ------------------- #
def check_lines(checker, lines, usable=None):
    """Each line read as `surasura_check_text` reads a reading -> (fixes, counts). `fixes`: one entry per line that
    fails, {"line": n (1 = the first), "swap": [the words to replace]} or {"line": n, "why": ...} for a line the voice
    can't read; [] when every line passes. The new-word share (under 3 %) is the round's, across all lines: past it,
    the new words of the last lines with any are named until the rest fits."""
    fixes, per_line, uses, words, new_uses = [], [], [], 0, 0
    for n, line in enumerate(lines, 1):
        why = usable(line) if usable else None
        if why:
            fixes.append({"line": n, "why": why})
            per_line.append([])
            uses.append(0)
            continue
        got = checker.check(line, "reading")
        swap = []
        for sentence in got["sentences"]:
            new = sentence["new"]
            for i, word in enumerate(new):
                if not word["allowed"] or i > 0:            # a second new word in a sentence goes (keep the first)
                    swap.append(word["word"])
        if not any(s["text"] for s in got["sentences"]):
            fixes.append({"line": n, "why": "no Japanese in it"})
            per_line.append([])
            uses.append(0)
            continue
        if swap:
            fixes.append({"line": n, "swap": list(dict.fromkeys(swap))})
        per_line.append([w["word"] for w in got["new_words"]])
        words += got["words"]
        uses.append(int(round(got["new_share"] * got["words"])))        # every use, as the checker counts them
        new_uses += uses[-1]
    allowed, total = _share_allowed(words), new_uses
    if new_uses > allowed:
        named = {f["line"]: f for f in fixes}
        for n in range(len(lines), 0, -1):
            if new_uses <= allowed:
                break
            if per_line[n - 1]:
                entry = named.setdefault(n, {"line": n, "swap": []})
                if "swap" in entry:
                    entry["swap"] = list(dict.fromkeys(entry["swap"] + per_line[n - 1]))
                new_uses -= uses[n - 1]
        fixes = sorted(named.values(), key=lambda f: f["line"])
    return fixes, {"words": words, "new": total}


def _share_allowed(words):
    """New-word uses a round of `words` counted words may hold: under READING_SHARE (3 %)."""
    from app import practice
    most = 0
    while words and (most + 1) / words < practice.READING_SHARE:     # the checker's own test: share >= 3 % fails
        most += 1
    return most


# --- where a round lives -------------------------------------------------------------------------------------------- #
def folder(language, round_id):
    from app import practice_rounds
    practice_rounds._path(language, round_id)           # the id's shape checked (never a path of the caller's)
    return os.path.join(practice_rounds.folder(language), round_id)


def _round_file(language, round_id):
    return os.path.join(folder(language, round_id), "round.json")


def read(language, round_id):
    """A round's record -> its dict, or None (no such round, or unreadable)."""
    try:
        with open(_round_file(language, round_id), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("lines"), list) else None


def _write(language, round_id, data):
    from app.anki_sync import _atomic_write_json
    _atomic_write_json(_round_file(language, round_id), data)


def base_name(title):
    """The files' name from the AI's title: path and control characters out, TITLE_CHARS at most; else NAME."""
    text = "".join(" " if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in str(title or ""))
    text = " ".join(text.split())[:TITLE_CHARS].strip(" .")
    if text.split(".")[0].strip().upper() in _RESERVED:
        text = f"{NAME} {text}"                         # CON, NUL, COM1 … are devices on Windows, never files
    return text or NAME


def queue(language, lines, title="", round_id=None, state="queued"):
    """A checked round written as queued -> its round_id. (The caller checked every line and starts the maker.)"""
    from app import practice_rounds
    round_id = round_id or practice_rounds.new_id()
    os.makedirs(os.path.join(folder(language, round_id), "lines"), exist_ok=True)
    _write(language, round_id, {"round_id": round_id, "language": language, "kind": KIND,
                                "title": str(title or "")[:TITLE_CHARS * 5],
                                "name": base_name(title), "lines": list(lines), "state": state,
                                "queued": time.strftime("%Y-%m-%dT%H:%M:%S"), "order": time.time_ns()})
    return round_id


def ready(language, round_id):
    """A round written "new" (`queue(state="new")`: no maker takes it while its record is written) made queued."""
    data = read(language, round_id)
    if data is None:
        raise Problem(f"No listening round {round_id}.")
    _write(language, round_id, dict(data, state="queued", order=time.time_ns()))


def keep_record(language, round_id, lines, title=""):
    """The round's practice record (`practice_rounds.save`): listed by surasura_rounds, done again by again=, and its
    lines read back to later rounds as any kept lines are."""
    from app import practice_rounds
    practice_rounds.save(language, round_id, start={"round": {"kind": KIND, "title": str(title or "")[:TITLE_CHARS]},
                                                    "words": []}, lines=list(lines))


def cancel(language, round_id):
    """Ask the maker to stop this round between two lines -> its state now ("done" stays done: nothing is deleted)."""
    data = read(language, round_id)
    if data is None:
        raise Problem(f"No listening round {round_id}.")
    if data.get("state") in ("done", "cancelled", "failed"):
        return data["state"]
    with open(os.path.join(folder(language, round_id), CANCEL), "w", encoding="utf-8") as f:
        f.write("cancelled by the learner\n")
    from app import path_utils
    held = path_utils.try_lock(_lock_path())
    if held is None:
        return "cancelling"                             # a maker is at work: it stops between two lines
    try:                                                # no maker can write it now: said cancelled at once
        data = read(language, round_id)
        if data is not None and data.get("state") in ("queued", "making"):
            return _finish(language, round_id, data, "cancelled")
        return (data or {}).get("state") or "cancelled"
    finally:
        path_utils.release_lock(held)


def again(language, round_id):
    """A round done once more: a made round is its files (nothing voiced); a cancelled, failed or unfinished one is
    queued again (its clips kept: only the missing lines are voiced) -> whether the maker is needed."""
    data = read(language, round_id)
    if data is None:
        raise Problem(f"The listening round {round_id}'s files are gone: make it again from its lines.")
    if data.get("state") == "done" and all(os.path.isfile(p) for p in _files(language, round_id, data).values()):
        return False
    try:
        os.remove(os.path.join(folder(language, round_id), CANCEL))     # asked again: it is wanted after all
    except OSError:
        pass
    if data.get("state") in ("queued", "making"):
        from app import path_utils
        held = path_utils.try_lock(_lock_path())
        if held is None:
            return True                                 # a maker is at work: never rewritten under it
        try:                                            # none: its tries start over (asked for again)
            data = read(language, round_id) or data
            if data.get("state") in ("queued", "making"):
                _write(language, round_id, dict(data, tries=0))
        finally:
            path_utils.release_lock(held)
        return True
    data = dict(data, state="queued", order=time.time_ns(), tries=0)   # after the rounds already waiting
    data.pop("problem", None)
    _write(language, round_id, data)
    return True


def where(language, round_id):
    """Where a round's files are, in words with no account name in them."""
    return f"Surasura's User Files › {language} › practice › {round_id}"


def made(language, round_id):
    """Whether the round is made and every one of its files is there."""
    data = read(language, round_id)
    return bool(data and data.get("state") == "done"
                and all(os.path.isfile(p) for p in _files(language, round_id, data).values()))


def to_open(language, round_id, what="play"):
    """The path `play` hands the player (the copy with pauses, else the plain one) or `folder` shows."""
    data = read(language, round_id) or {}
    if what == "folder":
        return folder(language, round_id)
    files = _files(language, round_id, data)
    return files.get("with_pauses") or files.get("audio")


def _files(language, round_id, data):
    here = folder(language, round_id)
    return {key: os.path.join(here, name) for key, name in (data.get("files") or {}).items()}


# --- what the AI is told (short: it reads every answer) ------------------------------------------------------------ #
def status(language, round_id, start=True):
    """A round's state for the AI -> a short dict. A queued or making round with no maker running is started again
    (`start`; not when the caller has just started one)."""
    data = read(language, round_id)
    if data is None:
        raise Problem(f"No listening round {round_id}.")
    state = data.get("state")
    out = {"round_id": round_id, "state": state}
    if state in ("queued", "making") and _cancelled(language, round_id):
        out["state"] = cancel(language, round_id) if not maker_running() else "cancelling"   # its maker gone: now
        return out
    if state == "done":
        files = _files(language, round_id, data)
        out["files"] = dict(data.get("files") or {})      # names only: a path would carry the learner's account name
        out["where"] = where(language, round_id)
        if data.get("note"):
            out["note"] = data["note"]
        if not all(os.path.isfile(p) for p in files.values()):
            out["next"] = (f"Some of its files were moved or deleted: surasura_practice_start(again=\"{round_id}\") "
                           "makes them again.")
            return out
        out["next"] = ("Tell the learner it's ready: any player or phone plays the mp3 with its .srt. "
                       "surasura_listening_status(round_id, play=true) opens it in their player; open_folder=true "
                       "shows its folder.")
        return out
    if state in ("cancelled", "failed"):
        if data.get("problem"):
            out["why"] = data["problem"]
        from app import practice_rounds
        kept = os.path.isfile(practice_rounds._path(language, round_id))      # its record: again= finds it
        out["next"] = (f"surasura_practice_start(again=\"{round_id}\") makes the rest of it." if kept else
                       "Send its lines again with surasura_listening_round to make it.")
        return out
    ready = len(_clips(language, round_id, data))
    out.update(ready=ready, of=len(data["lines"]))
    if data.get("waiting"):
        out["waiting"] = data["waiting"]
    if start and not maker_running():
        start_maker(language)
    module = voice(language)
    per_line = getattr(module, "seconds_per_line", lambda: 20)() if module else 20
    left = max(1, round((len(data["lines"]) - ready) * per_line / 60))
    out["next"] = (f"About {left} min left; each finished line is in its lines folder already (open_folder=true). "
                   "Ask again later with surasura_listening_status(round_id); don't wait in this turn.")
    return out


def _clips(language, round_id, data):
    here = os.path.join(folder(language, round_id), "lines")
    out = []
    for n in range(1, len(data["lines"]) + 1):
        path = os.path.join(here, f"{n:02d}.wav")
        if not (os.path.isfile(path) and os.path.getsize(path) > 0):
            break
        out.append(path)
    return out


def open_file(path, startfile=None):
    """`path` in the system's player — as the window's ▶ opens an audio item (`play.program_for` names no program for
    audio: Windows picks), with COM set up around the shell call as `screens.open_with_system` does. Raises OSError."""
    if sys.platform != "win32":
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return
    import ctypes
    ole32 = ctypes.windll.ole32
    mine = ole32.CoInitializeEx(None, 0x2 | 0x4) >= 0         # (windows.com_apartment's rule, Qt-free here)
    try:
        (startfile or os.startfile)(path)
    finally:
        if mine:
            ole32.CoUninitialize()


# --- the maker ------------------------------------------------------------------------------------------------------ #
def _lock_path():
    """The maker's lock in the install's locks folder (`locks.folder`: path_utils.PARTS' `locks`, kept by a Start
    over) — an OS lock on the file itself, never `locks.take`'s holder record (a maker killed lets it go at once)."""
    from app import locks
    return os.path.join(locks.folder("listening"), LOCK)


def maker_running():
    """Whether a maker holds the lock (a look: taken and let go at once)."""
    from app import path_utils
    held = path_utils.try_lock(_lock_path())
    if held is None:
        return True
    path_utils.release_lock(held)
    return False


def maker_command(language):
    """(argv, env) of the maker: `surasura-cli _listen --lang <language>`, the same program the MCP server is."""
    from app.cli import mcp_server
    exe, args, env = mcp_server.server_command()            # [... "mcp"]: this install's surasura-cli
    return [exe] + list(args[:-1]) + ["_listen", "--lang", language], env


def start_maker(language, popen=None):
    """The maker started in its own process, below normal, no window, out of the AI app's job where Windows lets it
    (the AI's session may end long before the round does). A start that fails is logged: the round stays queued and
    the next status starts one. -> the Popen, or None."""
    from app.connect import power
    argv, extra = maker_command(language)
    env = dict(os.environ, **extra)
    flags = 0
    if sys.platform == "win32":
        flags = NO_WINDOW | 0x00000200 | 0x01000000        # CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
              close_fds=True)
    for creation in ((flags, flags & ~0x01000000) if flags else (0,)):
        try:
            return power.popen_below_normal(argv, popen=popen, creationflags=creation, **kw)
        except OSError:
            continue                                        # a job that forbids breakaway: started inside it
    _log().exception("listening: the maker didn't start")
    return None


def said(e):
    """An error in words for the AI: an OSError's own reason (its filename would carry the account's name), else its
    text, short."""
    if isinstance(e, OSError):
        return e.strerror or type(e).__name__
    text = str(e) or type(e).__name__
    return text if len(text) <= PROBLEM_CHARS else text[:PROBLEM_CHARS - 1] + "…"


def _log():
    import logging
    return logging.getLogger("surasura-cli")


def waiting_rounds(language):
    """The rounds a maker should make, oldest first: queued or making (one with a cancel asked is taken and finished
    cancelled at once)."""
    from app import practice_rounds
    try:
        names = sorted(os.listdir(practice_rounds.folder(language)))
    except OSError:
        return []
    out = []
    for name in names:
        if not practice_rounds._ID.match(name) or not os.path.isdir(os.path.join(practice_rounds.folder(language), name)):
            continue
        data = read(language, name)
        if data is not None and data.get("state") in ("queued", "making"):
            out.append((data.get("order") or 0, name))
    return [name for _order, name in sorted(out)]       # the order they were queued in (two in one second too)


def make_waiting(language, settings=None, should_stop=None, sleep=time.sleep, tool="look"):
    """(The maker's body: `surasura-cli _listen`.) Every waiting round, oldest first, while this process holds LOCK;
    another maker holding it: nothing (it makes these too). Looked at again after the lock is let go, so a round
    queued in that moment is never left. -> {"made": [round ids], "left": n, "busy": bool}."""
    from app import path_utils
    made, tried = [], set()

    def key(round_id):                          # again= gives a round a new order: queued again, it is new to this run
        return round_id, (read(language, round_id) or {}).get("order")

    def left():
        return [r for r in waiting_rounds(language) if key(r) not in tried]
    while True:
        held = None
        for _look in range(LOCK_LOOKS):                 # a status's look or a cancel holds it for a moment only
            held = path_utils.try_lock(_lock_path())
            if held is not None:
                break
            sleep(0.2)
        if held is None:
            return {"made": made, "left": len(waiting_rounds(language)), "busy": True}
        try:
            while True:
                if should_stop is not None and should_stop():
                    return {"made": made, "left": len(waiting_rounds(language)), "busy": False}
                waiting = left()
                if not waiting:
                    break
                tried.add(key(waiting[0]))              # once a run: a round its disk refused waits for the next
                if make_round(language, waiting[0], settings, should_stop, sleep, tool) == "done":
                    made.append(waiting[0])
        finally:
            path_utils.release_lock(held)
        if not left():
            return {"made": made, "left": len(waiting_rounds(language)), "busy": False}


def _cancelled(language, round_id):
    return os.path.exists(os.path.join(folder(language, round_id), CANCEL))


def _finish(language, round_id, data, state, problem=None):
    data = dict(data, state=state)
    data.pop("waiting", None)
    if problem:
        data["problem"] = problem if len(problem) <= PROBLEM_CHARS else problem[:PROBLEM_CHARS - 1] + "…"
    _write(language, round_id, data)
    here = folder(language, round_id)
    for sub in (here, os.path.join(here, "lines")):
        try:
            names = os.listdir(sub)
        except OSError:
            continue
        for name in names:
            if name.endswith(".part"):
                try:
                    os.remove(os.path.join(sub, name))
                except OSError:
                    pass
    return state


def make_round(language, round_id, settings=None, should_stop=None, sleep=time.sleep, tool="look"):
    """One round: the clips (each kept as it lands), then the files, then `done` -> the state it ends in ("done",
    "cancelled", "failed", or "stopped": left as it was, for the next maker). Never raises for the round's own trouble."""
    data = read(language, round_id)
    if data is None:
        return "failed"
    if data.get("state") not in ("queued", "making"):
        return data.get("state")                            # made, cancelled, failed or new: nothing to make
    if _cancelled(language, round_id):
        return _finish(language, round_id, data, "cancelled")
    if settings is None:
        from app import settings_manager
        settings = settings_manager.load_settings()
    why = why_not(language, settings)
    if why:
        return _finish(language, round_id, data, "failed", why)
    module = voice(language)
    tries = int(data.get("tries") or 0) + 1
    if tries > TRIES:                                       # killed each time it ran (antivirus, memory): said
        return _finish(language, round_id, data, "failed", f"Making it stopped {TRIES} times before it was done.")
    data = dict(data, state="making", tries=tries)
    try:
        _write(language, round_id, data)
        got = _voice_lines(language, round_id, data, module, settings, should_stop, sleep)
        if got == "stopped":                                # asked to stop (an update): not one of its tries
            _write(language, round_id, dict(data, tries=tries - 1))
        if got != "voiced":
            return got
        if _cancelled(language, round_id):
            return _finish(language, round_id, data, "cancelled")
        files, note = build(folder(language, round_id), data["name"], data["lines"],
                            _clips(language, round_id, data), tool)
    except (Problem, OSError) as e:                         # a disk full, a file held open: said, the clips kept
        why = str(e) if isinstance(e, Problem) else f"Surasura couldn't write the round ({e.strerror or e})."
        try:
            return _finish(language, round_id, data, "failed", why)
        except OSError:
            return "stopped"
    except Exception as e:                                  # the voice's own trouble starting: said, never raised
        _log().exception("listening: round %s stopped", round_id)
        try:
            return _finish(language, round_id, data, "failed", f"The AI voice stopped ({said(e)}).")
        except OSError:
            return "stopped"
    data = dict(data, files=files, made=time.strftime("%Y-%m-%dT%H:%M:%S"))
    if note:
        data["note"] = note
    try:
        return _finish(language, round_id, data, "done")    # LAST: the files are all in place by now
    except OSError:                                         # its record refused: left making, made again next time
        _log().exception("listening: round %s's record wasn't written", round_id)
        return "stopped"


def _voice_lines(language, round_id, data, module, settings, should_stop, sleep):
    """Each line not voiced yet -> lines/NN.wav. -> "voiced", or the state the round was left in."""
    here = os.path.join(folder(language, round_id), "lines")
    os.makedirs(here, exist_ok=True)
    if len(_clips(language, round_id, data)) == len(data["lines"]):
        return "voiced"
    waited = 0.0
    while True:
        try:
            speaker = module.Speaker(settings)
            speaker.__enter__()
            break
        except getattr(module, "Busy", ()) as e:            # card audio holds the voice: this round waits its turn
            if waited >= BUSY_WAIT_S:
                return _finish(language, round_id, data, "failed",
                               f"The AI voice stayed busy making card audio for {BUSY_WAIT_S // 60} minutes.")
            if waited == 0:
                _write(language, round_id, dict(data, waiting=str(e)))
            if _cancelled(language, round_id):
                return _finish(language, round_id, data, "cancelled")
            if should_stop is not None and should_stop():
                return "stopped"
            sleep(BUSY_LOOK_S)
            waited += BUSY_LOOK_S
    try:
        if waited:
            _write(language, round_id, data)
        for n, line in enumerate(data["lines"], 1):
            path = os.path.join(here, f"{n:02d}.wav")
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                continue
            for _second in range(int(getattr(speaker, "rest_before", lambda: 0)())):   # the voice's rest (GPU)
                if _cancelled(language, round_id) or (should_stop is not None and should_stop()):
                    break
                sleep(1)
            if _cancelled(language, round_id):
                return _finish(language, round_id, data, "cancelled")
            if should_stop is not None and should_stop():
                return "stopped"                            # left making: the next maker goes on from this line
            try:
                wav = speaker.speak(line)
                if not read_wav(wav)[2]:                    # audio we can join, or the line is said
                    raise ValueError("no audio came back")
            except Exception as e:
                raise Problem(f"The AI voice couldn't read line {n} ({said(e)}).") from None
            with open(f"{path}.part", "wb") as f:
                f.write(wav)
            os.replace(f"{path}.part", path)
    finally:
        speaker.__exit__(None, None, None)
    return "voiced"


# --- the files: PCM joined here (exact times), one ffmpeg encode each ------------------------------------------------ #
def read_wav(data):
    """A wav's bytes -> (rate, channels, 16-bit PCM bytes). PCM 16 as it is, 32-bit float made 16-bit (WAVE_FORMAT_
    EXTENSIBLE read through). ValueError for anything else."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a wav")
    at, fmt, pcm = 12, None, None
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack("<I", data[at + 4:at + 8])[0]
        body = data[at + 8:at + 8 + size]
        if cid == b"fmt ":
            if len(body) < 16:
                raise ValueError("a wav with a short format")
            tag, channels, rate, _bps, _align, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            pcm = body
        at += 8 + size + (size & 1)
    if fmt is None or pcm is None or not fmt[1] or not fmt[2]:
        raise ValueError("a wav without its format or audio")
    tag, channels, rate, bits = fmt
    if tag == 1 and bits == 16:
        return rate, channels, pcm[:len(pcm) - len(pcm) % (2 * channels)]
    if tag == 3 and bits == 32:
        floats = array.array("f")
        floats.frombytes(pcm[:len(pcm) - len(pcm) % 4])
        if sys.byteorder != "little":
            floats.byteswap()
        ints = array.array("h", (int(max(-1.0, min(1.0, x)) * 32767) for x in floats))
        if sys.byteorder != "little":
            ints.byteswap()
        out = ints.tobytes()
        return rate, channels, out[:len(out) - len(out) % (2 * channels)]
    raise ValueError(f"a wav this can't join (format {tag}, {bits} bits)")


def timeline(lengths, gap):
    """Each line's (start, end) in samples, a `gap` (samples) after every line."""
    out, at = [], 0
    for n in lengths:
        out.append((at, at + n))
        at += n + gap
    return out


def srt(lines, spans, rate):
    """The subtitles: one cue per line, its times the clip's own (to the millisecond)."""
    def stamp(samples):
        ms = int(round(samples * 1000 / rate))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    cues = [f"{n}\n{stamp(a)} --> {stamp(b)}\n{one_line(line)}\n"
            for n, (line, (a, b)) in enumerate(zip(lines, spans), 1)]
    return "\n".join(cues)


def one_line(text):
    """A line as one line: its breaks and tabs made spaces, its own spaces (an ideographic one too) kept."""
    return re.sub(r"[\r\n\t\v\f\x1c-\x1e\x85\u2028\u2029]+", " ", str(text or "")).strip()


def ffmpeg():
    return shutil.which("ffmpeg")


def _encode(tool, wav_path, mp3_path):
    try:
        done = subprocess.run([tool, "-hide_banner", "-loglevel", "error", "-y", "-i", wav_path, "-ac", "1", "-b:a",
                               f"{MP3_KBPS}k", "-f", "mp3", mp3_path], capture_output=True, timeout=600,
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        raise Problem("ffmpeg couldn't make the mp3 (it didn't start or didn't finish).") from None
    if done.returncode != 0 or not os.path.isfile(mp3_path) or not os.path.getsize(mp3_path):
        raise Problem("ffmpeg couldn't make the mp3.")


def build(here, name, lines, clips, tool="look"):
    """The round's files in `here` from its clips -> ({key: file name}, a note or None). Each is written as `.part` and
    renamed into place; nothing is marked here (the caller marks the round done after)."""
    tool = ffmpeg() if tool == "look" else tool
    parts = []
    for path in clips:
        with open(path, "rb") as f:
            parts.append(read_wav(f.read()))
    if not parts or len(parts) != len(lines):
        raise Problem("Some lines have no audio yet.")
    rate, channels = parts[0][0], parts[0][1]
    if any((r, c) != (rate, channels) for r, c, _pcm in parts):
        raise Problem("The AI voice gave lines in different formats.")
    frame = 2 * channels
    lengths = [len(pcm) // frame for _r, _c, pcm in parts]
    files, note = {}, None
    for key, gap_s, suffix in (("audio", LINE_GAP_S, ""), ("with_pauses", PAUSE_S, PAUSED)):
        if key == "with_pauses" and not tool:
            note = ("ffmpeg isn't on this PC, so the round is a .wav and the copy with a pause after each line wasn't "
                    "made.")
            break
        gap = int(round(gap_s * rate))
        spans = timeline(lengths, gap)
        stem = f"{name}{suffix}"
        wav_path = os.path.join(here, f"{stem}.wav")
        with wave.open(f"{wav_path}.part", "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            silence = b"\0" * (gap * frame)
            for _r, _c, pcm in parts:
                w.writeframes(pcm)
                w.writeframes(silence)
        with open(os.path.join(here, f"{stem}.srt.part"), "w", encoding="utf-8", newline="\n") as f:
            f.write(srt(lines, spans, rate))
        if tool:
            _encode(tool, f"{wav_path}.part", os.path.join(here, f"{stem}.mp3.part"))
            os.replace(os.path.join(here, f"{stem}.mp3.part"), os.path.join(here, f"{stem}.mp3"))
            os.remove(f"{wav_path}.part")
            files[key] = f"{stem}.mp3"
        else:
            os.replace(f"{wav_path}.part", wav_path)
            files[key] = f"{stem}.wav"
        os.replace(os.path.join(here, f"{stem}.srt.part"), os.path.join(here, f"{stem}.srt"))
        files[f"{key}_subtitles"] = f"{stem}.srt"
    return files, note


# --- the maker's verb: `surasura-cli _listen --lang ja` (hidden; started by `start_maker`) -------------------------- #
def verb_args(parser):
    parser.add_argument("--lang", choices=tuple(VOICES) + tuple(NOT_YET), default="ja")


def verb(args):
    """Make every waiting round of the language, then end. An update (staged, another build here, Setup run by hand:
    the MCP server's own looks, `why_step_aside`) stops it between two lines — this program file is let go; the round
    is left making, and the next maker goes on."""
    from app.cli import mcp_server
    seen = [None]

    def stop():                                 # the same reason at two looks in a row (a stamp read mid-scan isn't one)
        reason, seen[0] = mcp_server.why_step_aside(), seen[0]
        twice = reason is not None and reason == seen[0]
        seen[0] = reason
        return twice
    got = make_waiting(args.lang, should_stop=stop)
    return {"verb": "_listen", "made": got["made"], "left": got["left"], "busy": got["busy"]}
