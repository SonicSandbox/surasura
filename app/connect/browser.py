"""Netflix and Disney+ mined after the fact (鵜 Ukai's contract v2; Ukai SPEC §6 U-S4, by mattias in #474, adapted onto
the one door): Connect never downloads these videos (DRM), so the lines a job picked are recorded in the learner's own
browser by Ukai, one short clip each, and each clip is given to Anki Miner as any video is.

Two processes share one folder, and nothing else: Connect (its own process) and the window's door, through Ukai's
routes (`modules/ukai`: `GET /v1/jobs`, the clip, `done` — only from the paired Ukai). The job's folder is
`<connect>/browser/b<job>/` — never the library, never swept with the fetched YouTube videos (`online.sweep`: a
recording outlives a Connect restart):

- `subtitle.srt` — the episode's cues from the library's transcript sidecar (`srt_of`), the file the words are picked
  from (Connect, at the pick: `Steps.download`).
- `lines.json` — the hand-off (Connect, once the words are picked: `hand_off`): the job's site, page and title and each
  line to record, {"n", "start", "end", "text"} in video seconds (a word's line with the lines its card expands to).
- `clip-<n>.webm` and `clip-<n>.json` {"start", "end"} — each recorded clip and the video time of its first and last
  frame (the door: `keep_clip`, streamed whole by `door.Call.save`, never held in memory, and only then put in place).
- `done.json` {"failed": [{"n", "why"}]} — Ukai recorded what it could (the door: `finish`).

Connect looks at the folder at each look (`state`): no `done.json` yet → its job waits (`WAIT`); done
→ each clip gets a one-cue-per-line `.srt` of its own (`clip_subtitle`: the lines it holds in clip time) and its words
go to Anki Miner with their line's start in clip time (`runner.Steps.mine`); the folder goes once the cards are made
(`drop`). The cues are in time order (Ukai's subtitle is sorted as it comes in, `modules/ukai/subtitles.tidy_cues`):
a word's line and a clip's lines are found by halving (`bisect`), never a walk of every cue. Standard library only; no
Qt.
"""
import bisect
import json
import os
import re
import shutil

FOLDER = "browser"
PAD_BEFORE, PAD_AFTER = 1.0, 1.0        # seconds Ukai records before and after a line (the contract's pads)
LINES, DONE, SUBTITLE = "lines.json", "done.json", "subtitle.srt"
# A Netflix / Disney+ job's line while Ukai hasn't recorded its lines (its row's tip; PROVISIONAL words)
WAIT = "Waits for Ukai: Record now in its menu."
_N = re.compile(r"\d{1,5}")


def folder():
    """<local data>/connect/browser — every job waiting for (or holding) the browser's clips."""
    from app.cli.verbs import _connect_folder
    return os.path.join(_connect_folder(), FOLDER)


def place(job_id, root=None):
    return os.path.join(root or folder(), f"b{int(job_id)}")


def _write_json(path, data):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


# --- the subtitle --------------------------------------------------------------------------------------------------- #
def _stamp(seconds):
    ms = max(0, int(round(seconds * 1000)))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt_of(cues):
    """[(start, end, text), …] -> an .srt's text."""
    return "".join(f"{n}\n{_stamp(s)} --> {_stamp(e)}\n{t}\n\n" for n, (s, e, t) in enumerate(cues, 1))


def sidecar_cues(transcript):
    """The cues Ukai sent, from the transcript's sidecar ([text, start, end] each) -> [(start, end,
    text)]; [] when it has none (a transcript from before v1 kept no ends)."""
    from app.path_utils import SIDECAR_SUFFIX
    side = _read_json(os.path.splitext(transcript)[0] + SIDECAR_SUFFIX) or {}
    out = []
    for cue in side.get("cues") or ():
        if isinstance(cue, list) and len(cue) == 3 and isinstance(cue[0], str):
            try:
                out.append((float(cue[1]), float(cue[2]), cue[0]))
            except (TypeError, ValueError):
                continue
    return out


def subtitle(job_id, transcript, root=None):
    """The episode's `subtitle.srt` in the job's folder (written again each time: the library's transcript is the
    truth) -> its path, or None when its sidecar holds no timed cues."""
    cues = sidecar_cues(transcript)
    if not cues:
        return None
    here = place(job_id, root)
    os.makedirs(here, exist_ok=True)
    path = os.path.join(here, SUBTITLE)
    with open(path + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.write(srt_of(cues))
    os.replace(path + ".part", path)
    return path


def read_srt(path):
    """An .srt this module wrote -> [(start, end, text)]."""
    try:
        with open(path, encoding="utf-8") as f:
            blocks = f.read().strip().split("\n\n")
    except OSError:
        return []

    def sec(stamp):
        h, m, rest = stamp.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    out = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) >= 3 and " --> " in lines[1]:
            a, b = lines[1].split(" --> ")
            out.append((sec(a), sec(b), "\n".join(lines[2:])))
    return out


# --- Connect's side: the hand-off ----------------------------------------------------------------------------------- #
def index(cues):
    """(the cues' starts, the longest cue's length) — made once a look, for `lines_for` and `clip_subtitle`."""
    return [c[0] for c in cues], max((e - s for s, e, _t in cues), default=0.0)


def _nearest(starts, start):
    """The cue whose start is nearest `start` (the earlier one on a tie, as a walk of every cue chose), by halving."""
    at = bisect.bisect_left(starts, start)
    if at == len(starts) or (at > 0 and start - starts[at - 1] <= starts[at] - start):
        return at - 1
    return at


def lines_for(words, cues, starts=None):
    """Each picked word's line (its `line_start`, widened by its `line_expansion` [before, after] to the lines its card
    holds) -> ([{"n", "start", "end", "text"}], {(line_start, before, after): n}); one line for words that share one.
    A word cut from another episode's line (`from`, Kantan-SD 6) has no line here: that episode's video holds it."""
    starts = [c[0] for c in cues] if starts is None else starts
    out, index = [], {}
    for w in words:
        key = line_key(w)
        if key in index or not cues or w.get("from") is not None:
            continue
        at = _nearest(starts, key[0])
        first, last = max(0, at - key[1]), min(len(cues) - 1, at + key[2])
        index[key] = len(out)
        out.append({"n": len(out), "start": cues[first][0], "end": cues[last][1],
                    "text": " ".join(c[2] for c in cues[first:last + 1])})
    return out, index


def line_key(word):
    return (float(word["line_start"]), *(int(x) for x in (word.get("line_expansion") or (0, 0))))


def hand_off(job_id, web, title, lines, root=None):
    """`lines.json` for Ukai (written once; the same job asks again with what it has)."""
    here = place(job_id, root)
    os.makedirs(here, exist_ok=True)
    path = os.path.join(here, LINES)
    if not os.path.isfile(path):
        _write_json(path, {"job": int(job_id), "rev": 0, "site": web["site"], "video_id": web.get("video_id") or "",
                           "url": web.get("url") or "", "title": title, "pad_before": PAD_BEFORE,
                           "pad_after": PAD_AFTER, "lines": lines})
    return path


def span(line):
    """A line's place in the video, the key that never changes: (start, end) to the millisecond."""
    return round(float(line["start"]), 3), round(float(line["end"]), 3)


def handed(job_id, root=None):
    """{span: n} of the lines `lines.json` hands Ukai — each line's `n` is its clip's name for the job's whole
    life (never renumbered: a later pick that wants other lines adds them, `add_lines`)."""
    job = _read_json(os.path.join(place(job_id, root), LINES)) or {}
    return {span(ln): ln["n"] for ln in job.get("lines") or () if isinstance(ln.get("n"), int)}


def add_lines(job_id, lines, root=None):
    """Lines the job wants that `lines.json` doesn't hold yet (a pick again after the hand-off) appended, each with a
    new `n` after the last; `done.json` taken back so Ukai records them -> {span: n} of the added."""
    here = place(job_id, root)
    path = os.path.join(here, LINES)
    job = _read_json(path) or {}
    have = list(job.get("lines") or ())
    nxt = max([ln["n"] for ln in have if isinstance(ln.get("n"), int)] + [-1]) + 1
    added = {}
    for ln in lines:
        added[span(ln)] = nxt
        have.append(dict(ln, n=nxt))
        nxt += 1
    _write_json(path, dict(job, lines=have, rev=int(job.get("rev") or 0) + 1))   # a `done` for the older set is stale
    try:
        os.remove(os.path.join(here, DONE))
    except OSError:
        pass
    return added


COVER_SLACK = 0.25          # seconds a clip may start after, or end before, its line and still hold it


def covers(times, line):
    """Does a clip recorded from `times["start"]` to `times["end"]` hold the whole line?"""
    start, end = times.get("start"), times.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return False
    return start <= float(line["start"]) + COVER_SLACK and end >= float(line["end"]) - COVER_SLACK


def take_over(job_id, earlier, root=None):
    """The clips earlier jobs of the same episode recorded (`earlier`: their job ids, the newest first — a job dropped
    when you reordered the list, or one that failed) copied into this job's folder for the lines it hands off and they
    hold (`covers`): those lines never need recording again. Each earlier folder is then removed: its job is gone
    (`runner._earlier_jobs`: older, no longer open). A line this job has a clip for already is never
    touched; once every line has one, the job is done -> how many lines were taken over."""
    here = place(job_id, root)
    want = handed(job_id, root)
    lines = {span(ln): ln for ln in (_read_json(os.path.join(here, LINES)) or {}).get("lines") or ()}
    have = {n for n in want.values() if clip(job_id, n, root) is not None}
    taken = set()
    for old in earlier:
        there = place(old, root)
        if not os.path.isdir(there):
            continue
        for key, n in handed(old, root).items():
            mine = want.get(key)
            kept = clip(old, n, root)
            if mine is None or mine in have or mine in taken or kept is None or not covers(kept[1], lines[key]):
                continue
            _write_json(os.path.join(here, f"clip-{mine}.json"), kept[1])
            shutil.copyfile(kept[0], os.path.join(here, f"clip-{mine}.webm.part"))
            os.replace(os.path.join(here, f"clip-{mine}.webm.part"), os.path.join(here, f"clip-{mine}.webm"))
            taken.add(mine)
        drop(old, root)                         # its job is gone: what a later job needs is copied
    if taken and len(have | taken) == len(want) and not os.path.exists(os.path.join(here, DONE)):
        _write_json(os.path.join(here, DONE), {"failed": []})      # every line held: nothing to record
    return len(taken)


def folders(root=None):
    """The job ids that have a folder here."""
    try:
        return sorted(int(n[1:]) for n in os.listdir(root or folder()) if n.startswith("b") and _N.fullmatch(n[1:]))
    except OSError:
        return []


def close(job_id, keep, root=None):
    """A job's folder whose job left: `keep` (its job is known, no longer open) closed (`done.json`: never listed for
    recording again) while it holds a clip to take over, else gone; `keep` None (its job is open) untouched."""
    here = place(job_id, root)
    if keep is None or not os.path.isdir(here):
        return
    if keep and any(n.startswith("clip-") and n.endswith(".webm") for n in os.listdir(here)):
        if not os.path.exists(os.path.join(here, DONE)):
            _write_json(os.path.join(here, DONE), {"failed": []})
    else:
        drop(job_id, root)


def state(job_id, root=None):
    """None (nothing handed off), "waiting" (no `done.json` yet), or the done dict {"failed": [...]}."""
    here = place(job_id, root)
    if not os.path.isfile(os.path.join(here, LINES)):
        return None
    done = _read_json(os.path.join(here, DONE))
    return done if done is not None else "waiting"


def clip(job_id, n, root=None):
    """(clip path, its {"start", "end"}) for line `n`, or None when none arrived."""
    here = place(job_id, root)
    video, times = os.path.join(here, f"clip-{n}.webm"), _read_json(os.path.join(here, f"clip-{n}.json"))
    if not os.path.isfile(video) or not times or not isinstance(times.get("start"), (int, float)):
        return None
    return video, times


def clip_subtitle(job_id, n, cues, start, end, root=None, at=None):
    """The clip's own .srt (beside it): the cues inside [start, end] in clip time (each cut to the clip) -> its path.
    `at`: `index(cues)`, made once for every clip of a look — the clip's cues found by halving (log cues, then the
    cues from one longest cue's length before it), never a walk of every cue per clip."""
    starts, longest = at or index(cues)
    first, last = bisect.bisect_left(starts, start - longest), bisect.bisect_left(starts, end)
    inside = [(max(s, start) - start, min(e, end) - start, t) for s, e, t in cues[first:last] if e > start]
    path = os.path.join(place(job_id, root), f"clip-{n}.srt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(srt_of(inside))
    return path


def drop(job_id, root=None):
    """The job's folder gone (its cards made, or the job ended) -> True; none there counts."""
    shutil.rmtree(place(job_id, root), ignore_errors=True)
    return not os.path.exists(place(job_id, root))


# --- the door's side (Ukai's routes, `modules/ukai`) ---------------------------------------------------------------- #
def waiting(root=None):
    """`GET /v1/jobs`: every handed-off job not done, oldest first, each with only its lines still missing a clip — one
    listing of the folders, then one listing and one `lines.json` read a job's folder."""
    root = root or folder()
    try:
        names = [n for n in os.listdir(root) if n.startswith("b") and _N.fullmatch(n[1:])]
    except OSError:
        return []
    out = []
    for name in sorted(names, key=lambda n: int(n[1:])):
        here = os.path.join(root, name)
        try:
            have = set(os.listdir(here))
        except OSError:
            continue
        if DONE in have:
            continue
        job = _read_json(os.path.join(here, LINES))
        if not job:
            continue
        missing = [{"n": ln["n"], "start": ln["start"], "end": ln["end"]} for ln in job.get("lines") or ()
                   if f"clip-{ln['n']}.webm" not in have]
        out.append({k: job.get(k) for k in ("job", "site", "video_id", "url", "title", "pad_before", "pad_after")}
                   | {"rev": int(job.get("rev") or 0), "lines": missing})
    return out


def _open_job(job_id, root):
    here = place(job_id, root)
    job = _read_json(os.path.join(here, LINES))
    if job is None or os.path.exists(os.path.join(here, DONE)):
        return None, None
    return here, job


def waiting_lines(root=None):
    """How many lines wait for Ukai to record them (Settings' Ukai row)."""
    return sum(len(job["lines"]) for job in waiting(root))


def keep_clip(job_id, n, save, start, end, root=None):
    """A clip for line `n` of a waiting job -> True; False when the job or its line doesn't wait (a 404: nothing read,
    nothing written). `save(path)` streams the body whole to `path` or raises (the door's `Call.save`: a body cut short
    leaves nothing); its times are written beside it, then the clip is put in place — a clip that didn't arrive whole
    leaves neither, and its line still waits."""
    here, job = _open_job(job_id, root)
    if job is None or not any(ln.get("n") == n for ln in job.get("lines") or ()):
        return False
    video = os.path.join(here, f"clip-{n}.webm")
    got = video + ".got"
    try:
        save(got)
        _write_json(os.path.join(here, f"clip-{n}.json"), {"start": float(start), "end": float(end)})
        os.replace(got, video)
    except BaseException:
        try:
            os.remove(got)
        except OSError:
            pass
        raise
    return True


def finish(job_id, failed, root=None, rev=None):
    """`done`: Ukai recorded what it could -> True; False when the job doesn't wait (a 404). `rev`: the lines' version
    its `GET /v1/jobs` listed. A stale one (lines were added since, `add_lines`) closes nothing: the job stays listed
    with the lines still missing a clip. None (Ukai before its #2, which knows no rev): it closes the job only when
    every line has a clip or is among `failed` — so it still ends a job it was asked for again."""
    here, job = _open_job(job_id, root)
    if job is None:
        return False
    named = {f.get("n") for f in failed if isinstance(f, dict)}
    if rev is None:
        if any(not os.path.isfile(os.path.join(here, f"clip-{ln.get('n')}.webm")) and ln.get("n") not in named
               for ln in job.get("lines") or ()):
            return True
    elif int(rev) != int(job.get("rev") or 0):
        return True
    known = {ln.get("n") for ln in job.get("lines") or ()}
    kept = [{"n": f["n"], "why": str(f.get("why") or "")[:200]} for f in failed
            if isinstance(f, dict) and f.get("n") in known]
    _write_json(os.path.join(here, DONE), {"failed": kept})
    return True
