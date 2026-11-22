# SPDX-License-Identifier: GPL-3.0-or-later
"""One run of the AI voice: the notes' sentences → clips → the shared writer (README § Running).

    count (read-only)  ->  make the clips (the server on, paced, Stop between two)  ->  ONE write, ONE Undo

* Only notes whose audio field is empty are made: a field holding anything is never asked for a clip, and the shared
  writer reads every note again before it writes (`writer.fill` → the shared writer, `app/connect/sentence_audio.py`).
* A clip is kept on disk by what made it (the pack, its version, the sentence, the caption) under `<runtime>/clips/`:
  a run stopped or failed half-way loses nothing — the next run reuses what was made.
* Stop (`cancel`, an Event; `should_stop`, a callable) ends it between two sentences: what was made by then is written,
  one Undo for all of it.
* GPU pace: BURST sentences, then PAUSE_S off (PROVISIONAL; in testing: about 15, then let the card cool). CPU: no pause.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time

from app import anki_connect
from modules.irodori import runtime, server, voice, writer

BURST, PAUSE_S = 15, 180
SENTENCE_FIELDS = ("Sentence", "SentenceFurigana", "Example", "例文")      # the first the note has, not empty
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _url(settings):
    return anki_connect.address(settings or {})


def _sentence(note, fields=SENTENCE_FIELDS):
    got = note.get("fields") or {}
    for name in fields:
        entry = got.get(name)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if value and str(value).strip():
            return voice.sentence_text(str(value))
    return ""


def plan(url, note_ids, field=writer.FIELD):
    """(Read-only.) -> {"ok", "todo": [(note id, sentence)], "kept", "no_field", "gone", "skipped": {reason: n},
    "problems"} — `todo` the notes with an empty audio field and a sentence the voice can read."""
    look = writer.look(url, note_ids, field)
    out = {"ok": look["ok"], "todo": [], "kept": look["kept"], "no_field": look["no_field"], "gone": look["gone"],
           "skipped": {}, "problems": list(look["problems"])}
    if not look["ok"] or not look["empty"]:
        return out
    try:
        notes = anki_connect.notes_info(url, look["empty"])
    except anki_connect.AnkiError as e:
        out.update(ok=False, problems=[str(e)])
        return out
    for note in notes:
        text = _sentence(note)
        why = voice.usable(text)
        if why:
            out["skipped"][why] = out["skipped"].get(why, 0) + 1
        else:
            out["todo"].append((note["noteId"], text))
    return out


def find_empty(url, deck=None, field=writer.FIELD):
    """(Read-only.) The notes in `deck` (None: every deck) whose `field` is empty and whose Sentence isn't — Anki's own
    search, so a note type without the field never matches."""
    query = f'"{field}:" "Sentence:_*"'
    if deck:
        query = f'"deck:{anki_connect.escape_query(deck)}" {query}'
    return anki_connect.find_notes(url, query)


def clip_path(base, pack, text, cap, fmt):
    key = hashlib.sha256(f"{pack.get('id')}|{pack.get('version')}|{pack.get('speed')}|{pack.get('steps')}|"
                         f"{pack.get('lora')}|{cap}|{text}".encode("utf-8")).hexdigest()[:32]
    return os.path.join(base, "clips", f"{pack.get('id')}-v{pack.get('version')}", f"{key}.{fmt}")


def _ffmpeg():
    return shutil.which("ffmpeg")


def _to_mp3(ffmpeg, wav_path, mp3_path):
    """128 kbps mono mp3 (PROVISIONAL); False when ffmpeg can't."""
    try:
        done = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", wav_path, "-ac", "1", "-b:a", "128k",
                    "-f", "mp3", mp3_path], capture_output=True, timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0


def _stopping(cancel, should_stop):
    return (cancel is not None and cancel.is_set()) or (should_stop is not None and bool(should_stop()))


def make_clips(todo, pack, say=None, cancel=None, should_stop=None, srv=None, sleep=time.sleep, ffmpeg="look"):
    """Make (or reuse) a clip for each (note id, sentence) -> ({note id: clip path}, {reason: n}). Stops between two
    sentences when asked (the clips made so far kept and returned)."""
    say = say or (lambda done, of, text: None)
    base = runtime.home()
    ffmpeg = _ffmpeg() if ffmpeg == "look" else ffmpeg
    fmt = "mp3" if ffmpeg else "wav"
    files, failed, made_now, failures_in_a_row = {}, {}, 0, 0
    gpu = (runtime.status().get("backend") or "cpu") != "cpu"
    own = srv is None
    srv = srv or server.Server()
    try:
        for i, (note_id, text) in enumerate(todo):
            if _stopping(cancel, should_stop):
                break
            cap = voice.caption(text, pack)
            path = clip_path(base, pack, text, cap, fmt)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                files[note_id] = path
                say(i + 1, len(todo), text)
                continue
            if gpu and made_now and made_now % BURST == 0:
                for k in range(PAUSE_S):                # a pause for the card's heat; Stop still answers
                    if (cancel is not None and cancel.is_set()) or (k % 15 == 0 and _stopping(None, should_stop)):
                        break
                    sleep(1)
                if _stopping(cancel, should_stop):
                    break
            say(i, len(todo), text)
            try:
                srv.start()
                wav = srv.speak(text, cap, speed=pack.get("speed") or 1.0, seed=voice.seed(text, pack),
                                num_steps=pack.get("steps"), lora=pack.get("lora"), voice=pack.get("voice") or "none")
            except server.ServerError as e:
                failed[str(e)] = failed.get(str(e), 0) + 1
                failures_in_a_row += 1
                if failures_in_a_row >= 3:
                    break                               # three in a row: the voice is broken this run
                continue
            failures_in_a_row = 0
            os.makedirs(os.path.dirname(path), exist_ok=True)
            wav_path = path if fmt == "wav" else f"{path}.wav"
            with open(f"{wav_path}.part", "wb") as f:
                f.write(wav)
            os.replace(f"{wav_path}.part", wav_path)
            if fmt == "mp3":
                if _to_mp3(ffmpeg, wav_path, f"{path}.part"):
                    os.replace(f"{path}.part", path)
                    os.remove(wav_path)
                else:                                   # ffmpeg failed this once: the wav is the clip
                    path = wav_path
            files[note_id] = path
            made_now += 1
            say(i + 1, len(todo), text)
    finally:
        if own:
            srv.stop()
    return files, failed


BUSY = "The AI voice is already making audio for other cards. Try again once it has finished."


def make_for_notes(settings, language, note_ids, say=None, cancel=None, should_stop=None, dry_run=False,
                   field=writer.FIELD, verb="AI sentence audio", wait=0.0, srv=None, source=None):
    """The whole run for `note_ids` -> a report: {"ok", "message", "problems", "todo" (how many need audio), "made",
    "written", "kept", "no_field", "skipped", "run" (for Undo), "stopped", "busy"}. `dry_run`: the count only (no
    server, no write). One run at a time, across every Surasura process (`runtime.running`). A run that wrote is
    remembered for its Undo (`remembered`; `source` says which door). Never raises."""
    report = {"ok": False, "message": "", "problems": [], "todo": 0, "made": 0, "written": [], "kept": 0,
              "no_field": 0, "skipped": {}, "run": None, "stopped": False, "busy": False}
    if language not in ("ja",):
        report["problems"] = ["The AI voice reads Japanese only."]
        return report
    try:
        return _make_for_notes(report, settings, language, note_ids, say, cancel, should_stop, dry_run, field, verb,
                               wait, srv, source)
    except Exception as e:                  # a disk that fills, a broken pack: said, never raised
        report.update(ok=False, problems=report["problems"] + [f"The AI voice stopped: {e}"])
        return report


def _make_for_notes(report, settings, language, note_ids, say, cancel, should_stop, dry_run, field, verb, wait, srv,
                    source):
    url = _url(settings)
    planned = plan(url, note_ids, field)
    report.update(ok=planned["ok"], problems=planned["problems"], todo=len(planned["todo"]), kept=planned["kept"],
                  no_field=planned["no_field"], skipped=planned["skipped"])
    if not planned["ok"] or dry_run or not planned["todo"]:
        report["message"] = count_line(report)
        return report
    if not writer.available():
        report.update(ok=False, problems=[writer.WAITS])
        return report
    if not runtime.ready():
        report.update(ok=False, problems=["The AI voice isn't installed (Settings › App › Beta)."])
        return report
    pack = voice.pack((settings or {}).get("irodori_voice"), runtime.home())
    if pack is None:
        report.update(ok=False, problems=["No voice pack was found."])
        return report
    held = runtime.running()
    if held is None:
        report.update(ok=False, busy=True, problems=[BUSY])
        return report
    try:
        return _run(report, url, language, planned, pack, say, cancel, should_stop, field, verb, wait, srv, source)
    finally:
        from app import path_utils
        path_utils.release_lock(held)


def _run(report, url, language, planned, pack, say, cancel, should_stop, field, verb, wait, srv, source):
    files, failed = make_clips(planned["todo"], pack, say=say, cancel=cancel, should_stop=should_stop, srv=srv)
    report["made"] = len(files)
    report["stopped"] = _stopping(cancel, should_stop)
    if failed:
        report["problems"] += [f"{why} ({n})" for why, n in failed.items()]
    if not files:
        report["ok"] = not failed
        report["message"] = "Stopped before any audio was made." if report["stopped"] else "No audio was made."
        return report
    # What was made is written even after a Stop (the write takes seconds; the clips stay cached either way): the
    # shared writer waits a little for another writer, then says busy — written by the next run
    wrote = writer.fill(url, language, files, tag=writer.AI_TAG, field=field)
    report.update(ok=bool(wrote.get("ok")) and not failed, written=list(wrote.get("written") or ()),
                  run=wrote.get("run"), message=wrote.get("message") or "", busy=bool(wrote.get("busy")))
    report["problems"] += list(wrote.get("problems") or ())
    if report["run"]:                       # a write cut part-way too: its Undo stays reachable
        remember(language, report["run"], len(report["written"]), source)
    return report


# --- the runs' Undo, kept: every run that wrote, newest last, so a window opened later (or Connect's
# runs, made with no window) still offers its Undo. In the local data folder, never the runtime (Remove keeps it).
KEEP = 50


def _runs_path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"irodori-runs-{language}.json")


def remembered(language):
    """The runs that wrote, newest last: [{"run", "cards", "source", "at", "undone"?}]."""
    import json
    try:
        with open(_runs_path(language), "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return []
    return [r for r in got if isinstance(r, dict) and r.get("run")] if isinstance(got, list) else []


def _write_runs(language, runs):
    import json
    path = _runs_path(language)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(runs[-KEEP:], f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def remember(language, run_id, cards, source=None):
    try:
        _write_runs(language, remembered(language) + [{"run": run_id, "cards": int(cards), "source": source,
                                                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")}])
    except OSError:
        pass                            # the shared writer keeps its own record: this list is the doors' way to it


def last_undoable(language, source=None):
    """The newest run not undone yet (of `source`, when given), or None."""
    for r in reversed(remembered(language)):
        if not r.get("undone") and (source is None or r.get("source") == source):
            return r
    return None


def mark_undone(language, run_id):
    try:
        _write_runs(language, [dict(r, undone=True) if r.get("run") == run_id else r for r in remembered(language)])
    except OSError:
        pass


def count_line(report):
    """The count before the press: "12 cards have no sentence audio." (+ the ones the voice can't read)."""
    n = report.get("todo", 0)
    line = (f"{n} card{'' if n == 1 else 's'} {'has' if n == 1 else 'have'} no sentence audio." if n else
            "Every card here already has sentence audio.")
    skipped = sum((report.get("skipped") or {}).values())
    if skipped:
        line += f" {skipped} more can't be read aloud (too long, or no Japanese)."
    return line
