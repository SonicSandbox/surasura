"""A book lined up with its audiobook, and an audiobook's own subtitles spot-checked (Michi-AB Stage B: Anki Miner
3.11's Z-17 `sync`, Z-22 `setup --speech-model`, Z-18 `transcribe`; Sonic's AB-Q1…Q5, 2026-11-02 — PROVISIONAL rules
held by `tests/connect/test_lineup.py`; plan: `tracks/pipeline/work/AB/plan.md`).

- **What is lined up**: a book of the library Hon paired with its audiobook (`library.audiobook_of_book`: the
  audiobook's record names the book's EPUB, sure or answered). Anki Miner's `sync` reads the EPUB and listens to the
  audio files in order, and writes one timed subtitle per audio file, each cue one of the book's sentences. Once, per
  pair (`key`: Hon's answer key — the audio files' sizes and the EPUB's sha256: a new edition of either is lined up
  again), into Connect's own folder (`lineup/<key>/`: never the learner's folders nor the library's, so no look ever
  takes the subtitles in).
- **While it runs** (`start_sync`, `look`): a child of Connect's (`anki_miner.start`: never a look's wait, ended with
  Connect — Anki Miner keeps each audio file it finished, so the next start goes on from there); each look reads its
  `progress.json` (two stages an audio file: `file k of n`). *Stop* (`stop`) is its `cancel` file, the stop's time kept
  (`stopped_at`) so the book waits for your next *Mine now*.
- **What its cards are cut from** (`cues`, `place`): a word's sentence found among the cues (the sync's own
  normalisation — NFKC, letters and digits — the cue holding the word's spelling) is mined as an audio episode of that
  file; the rest as the book (no sentence audio). AB-Q4: a grade of C or D is no line-up for cards (`usable`: never a
  wrong clip); the narrator's skipped passages (`unheard`) are said in one plain line (`partial_line`).
- **Nothing lined up** (`NONE`: no grade, no file synced): the one question per pair (`library_store`'s mark,
  `Store.audiobook_mismatches`).
- **Its own timed subtitle instead** (Kura-AB3, Mattias's 3.0.2 report; PROVISIONAL): an audiobook of one audio file
  whose transcript Hon found this book's (`audiobooks.TIMING`: an `.srt` beside the audio, its lines in the book in
  order) is the line-up as it is (`own`: no sync, no speech model) — its cues cut the cards as a sync's do. Its timing
  is spot-checked first when Anki Miner has its speech model (a subtitle not timed to that audio: lined up as above).
- **The speech model** (AB-Q1/Q2): one Anki Miner already has is used (`anki_miner.speech_ready`); else the one question,
  its answer kept here (`answer`, `set_answer`); yes → Anki Miner's own `setup --speech-model --model small`
  (`start_speech`), a child as the sync is (`look(SPEECH)`), its progress file in *Finish its setup*'s folder so a Connect
  told BUSY meanwhile says Anki Miner is finishing its setup (`anki_miner.setting_up`).
- **The spot-check** (AB-Q5, `spot_check`): an audiobook's own subtitle (Stage A's audio episode) heard in SAMPLES places
  (~SAMPLE_S each, through the file: `media` cuts them, `transcribe` listens) and each compared with the subtitle's
  lines there (`overlap`); MATCHES of them at MATCH or more → timed. Kept per subtitle and audio file (`spot.json`).

Light: the standard library; Anki Miner is called through `anki_miner`.
"""
import difflib
import hashlib
import json
import os
import re
import time
import unicodedata
from collections import namedtuple

ROOT = "lineup"                 # under Connect's folder
STATE = "state.json"            # a pair's line-up
VERDICT = "verdict.json"        # the running child's stdout (its verdict line)
RUN_ID = "sync"                 # its one run in `run/` (Anki Miner's run folder)
SPEECH = "speech-model"         # the speech model's setup, a line-up of its own (`look(SPEECH)`)
ANSWER = "speech.json"          # AB-Q2's answer: {"answer": "yes" | "no", "at"}
# AB-Q2: the speech model's one question (Connect's standing *Needs you* line: `runner._line_up`, `actions.speech_model`)
# and, its download failed or stopped, the same question with why (kept while unanswered: review B-6)
SPEECH_ASK = ("Lining up books with their audiobooks, and checking an audiobook's own subtitles, needs Anki Miner's "
              "speech model: a 0.5 GB download, then about 20–30 minutes for each hour of audio. Download it? Not now: "
              "their cards are made without sentence audio.")
SPEECH_FAILED = "Anki Miner's speech model didn't download ({why}). Download it again?"
SPOT = "spot.json"              # the spot-check's verdicts: {key: {"verdict", "at", "shares"}}
SPOT_RULE = "v2"                # the spot-check's rule (one line a place, SAMPLES / MATCHES): its verdicts' key
RUNNING, DONE, NONE, STOPPED, FAILED, INTERRUPTED, NO_MODEL = (
    "running", "done", "none", "stopped", "failed", "interrupted", "no-model")
GOOD = ("A", "B")               # AB-Q4: grades whose cues cut cards (C / D: another edition, the wrong book)
OWN = "transcript"              # Kura-AB3: a line-up that is the audiobook's own timed subtitle (`own`), never graded
TRIES = 3                       # a line-up that failed this many times running is given up (the book mined as it is)
MIN_CHARS = 8                   # a sentence this long (clean characters) or longer is found inside a longer one
# AB-Q5 (PROVISIONAL): SAMPLES places through the subtitle, ONE line each (review B-13: a 30 s window passed a subtitle
# 10 s off — one line's clip holds another line's words once it is off by more than about a line), each a line of
# SAMPLE_CHARS clean characters or more (a short line is too little to hear); MATCHES of them heard at MATCH or more
# (Stage A's drill: a card's own line min 0.57, another line's median 0.12) is timed
SAMPLES = 5
SAMPLE_CHARS = 8
MATCH = 0.5
MATCHES = 3
SPOT_TIMEOUT = 20 * 60.0        # the spot-check's two calls, each (the model loads, three clips heard)
MATCHED, NOT_MATCHED = "match", "no-match"

Cue = namedtuple("Cue", "audio subtitle start end text unit", defaults=(None,))


# --------------------------------------------------------------------------- #
# Where
# --------------------------------------------------------------------------- #
def root():
    from app.cli.verbs import _connect_folder
    return os.path.join(_connect_folder(), ROOT)


def folder(key):
    return os.path.join(root(), str(key))


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def read(key):
    """A pair's line-up as last written ({} none yet)."""
    return _read_json(os.path.join(folder(key), STATE)) or {}


def write(key, state):
    """A pair's line-up written whole, atomically — only when it changed (S19). -> `state`."""
    if read(key) != state:
        _write_json(os.path.join(folder(key), STATE), state)
    return state


def asks_speech(reason):
    """Is a job's reason the speech model's question (either wording)? `actions.speech_model` frees those jobs."""
    return isinstance(reason, str) and (reason == SPEECH_ASK or reason.startswith(SPEECH_FAILED.split("(")[0]))


def answer():
    """AB-Q2's answer: "yes" (download it, then line up by itself), "no" (cards without sentence audio) or None."""
    said = (_read_json(os.path.join(root(), ANSWER)) or {}).get("answer")
    return said if said in ("yes", "no") else None


def set_answer(yes):
    """The window's answer to the speech model's question (`actions.speech_model`), kept for every book after."""
    _write_json(os.path.join(root(), ANSWER), {"answer": "yes" if yes else "no", "at": time.time()})


def clear_answer():
    """A download that failed: the question is asked again (never a second download nobody asked for)."""
    try:
        os.remove(os.path.join(root(), ANSWER))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# The children: a sync, the speech model's setup
# --------------------------------------------------------------------------- #
_RUNNING = {}           # key -> (Popen, its verdict file): the children this Connect started, while it runs


def running(key):
    held = _RUNNING.get(key)
    return held is not None and held[0].poll() is None


def other_running(key):
    """Another pair's line-up this Connect runs now (review B-2: one at a time — each loads the speech model and
    listens for hours), or None."""
    return next((k for k in list(_RUNNING) if k not in (key, SPEECH) and running(k)), None)


def start_sync(miner, language, profile, key, book, audio):
    """Anki Miner's `sync` for one pair, started and left running (`anki_miner.start`): the book's EPUB and the audio
    files in order. -> its state (RUNNING). Raises AnkiMinerError (absent, quarantined, crashed)."""
    from app.connect import anki_miner
    if running(key):            # review B-1: never a second run on one run folder (a stopped one not ended yet)
        raise anki_miner.AnkiMinerError("busy", "This audiobook's line-up hasn't stopped yet.")
    where = folder(key)
    run_dir = os.path.join(where, "run")
    os.makedirs(os.path.join(run_dir, RUN_ID), exist_ok=True)
    for name in ("cancel", "progress.json"):            # a stop's file an earlier call left is never this one's
        try:
            os.remove(os.path.join(run_dir, RUN_ID, name))
        except OSError:
            pass
    data = {"schema": 1, "run_dir": run_dir, "language": language,
            "episodes": [{"run_id": RUN_ID, "book": os.path.abspath(book), "audio": [os.path.abspath(a) for a in audio]}]}
    if profile:
        data["profile"] = profile
    job = os.path.join(where, "sync.json")
    _write_json(job, data)
    out = os.path.join(where, VERDICT)
    proc = anki_miner.start(miner, ["sync", job], out)
    _RUNNING[key] = (proc, out)
    old = read(key)
    return write(key, {"status": RUNNING, "book": os.path.abspath(book), "audio": [os.path.abspath(a) for a in audio],
                       "file": 1, "of": len(audio), "started": time.time(), "tries": old.get("tries") or 0})


def start_speech(miner, language, profile):
    """Anki Miner's own `setup --speech-model --model small` (AB-Q2 (b)), started and left running. Its progress file
    sits in *Finish its setup*'s folder (`anki_miner.SETUP_STAGING`): a mine told BUSY meanwhile says Anki Miner is
    finishing its setup. -> its state (RUNNING)."""
    from app.connect import anki_miner
    staging = anki_miner.setup_folder()
    os.makedirs(staging, exist_ok=True)
    try:
        os.remove(os.path.join(staging, "cancel"))
    except OSError:
        pass
    os.makedirs(folder(SPEECH), exist_ok=True)
    out = os.path.join(folder(SPEECH), VERDICT)
    # never bound to Connect (review B-17, as *Finish its setup*'s: Anki Miner's own setup, under its own lock, writing
    # its shared models folder, finishes whenever Connect quits)
    proc = anki_miner.start(miner, anki_miner.speech_setup_args(language, profile, os.path.join(
        staging, anki_miner.PROGRESS)), out, bind=False)
    _RUNNING[SPEECH] = (proc, out)
    return write(SPEECH, {"status": RUNNING, "started": time.time(), "tries": read(SPEECH).get("tries") or 0})


def look(key):
    """The line-up (or, `SPEECH`, the speech model's setup) as it stands now: a child of this Connect's still running →
    RUNNING (a sync: `file` of `of`, from its progress); one that ended → its outcome, written (`_ended`); a RUNNING one
    no child of this Connect holds (Connect ended mid-run, so its child too) → INTERRUPTED (the caller starts it again).
    -> its state."""
    state = read(key)
    held = _RUNNING.get(key)
    if held is None:
        if state.get("status") == RUNNING:
            return dict(state, status=INTERRUPTED)
        return state
    proc, out = held
    from app.connect import anki_miner
    try:
        verdict = anki_miner.ended(proc, out)
    except anki_miner.AnkiMinerError as e:
        _RUNNING.pop(key, None)
        return write(key, dict(state, status=FAILED, message=e.message, tries=(state.get("tries") or 0) + 1,
                               failed_at=utc()))
    if verdict is None:
        if key == SPEECH:
            _heartbeat()
            return state
        progress = anki_miner.read_progress(os.path.join(folder(key), "run"), RUN_ID)
        if progress and progress.get("stages"):
            files = max(1, progress["stages"] // 2)
            return write(key, dict(state, file=min(files, max(1, (progress["stage"] + 1) // 2)), of=files))
        return state
    _RUNNING.pop(key, None)
    return write(key, _ended(key, state, verdict))


def utc():
    """Now as Connect's ledger writes times (`ledger._now`): a stop compared with a job's `asked_at`."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _heartbeat():
    """`anki_miner.run_setup`'s heartbeat, beside the speech model's progress file: a download that writes no progress
    for minutes still reads as *finishing its setup* (`anki_miner.setting_up`)."""
    from app.connect import anki_miner
    beat = os.path.join(anki_miner.setup_folder(), anki_miner.HEARTBEAT)
    try:
        with open(beat, "a"):
            pass
        os.utime(beat)
    except OSError:
        pass


def _ended(key, state, verdict):
    """A child's verdict -> the state it leaves."""
    from app.connect import anki_miner
    tries = (state.get("tries") or 0) + 1
    if key == SPEECH:
        why = anki_miner.speech_setup_done(verdict)
        if why is None:
            anki_miner._SPEECH.clear()      # installed: asked again at once, never the no kept
            return {"status": DONE, "at": time.time()}
        if verdict.get("error") == "BUSY":  # review B-5: its window open — no failure, started again once it closes
            return dict(state, status=INTERRUPTED, busy=True)
        if verdict.get("error") == "CANCELLED" or (
                ((verdict.get("result") or {}).get(anki_miner.SPEECH_ITEM) or {}).get("status") == "not_attempted"):
            return dict(state, status=STOPPED, stopped_at=utc())
        return dict(state, status=FAILED, message=why, tries=tries)
    run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == RUN_ID), None)
    code = (run or {}).get("error") or verdict.get("error")
    if code == "CANCELLED":
        return dict(state, status=STOPPED, stopped_at=state.get("stopped_at") or utc())
    if code == "SETUP_ERROR":
        # its speech model went (or never was), or ffmpeg: asked again — a try counted, so it never loops (review B-12)
        anki_miner._SPEECH.clear()
        return dict(state, status=NO_MODEL, message=(run or verdict).get("message"), tries=tries, failed_at=utc())
    if run is None or not run.get("ok"):
        return dict(state, status=FAILED, message=(run or verdict).get("message") or code or "no answer",
                    code=code, tries=tries, failed_at=utc())
    report = _read_json(os.path.join(folder(key), "run", RUN_ID, os.path.basename(str(run.get("file") or "")))) or {}
    files = [{"audio_file": f.get("audio_file"), "subtitle_file": f.get("subtitle_file"), "status": f.get("status"),
              "units": {str(c["n"]): c["index"] for c in f.get("cues") or () if isinstance(c, dict)
                        and isinstance(c.get("n"), int) and isinstance(c.get("index"), int)}}
             for f in report.get("files") or () if isinstance(f, dict)]
    synced = [f for f in files if f["status"] == "synced" and isinstance(f["subtitle_file"], str)
              and os.path.isfile(f["subtitle_file"])]
    out = {"status": DONE if synced and report.get("grade") else NONE, "book": state.get("book"),
           "audio": state.get("audio"), "files": files, "grade": report.get("grade"),
           "sentence_pct": report.get("sentence_pct"), "audio_pct": report.get("audio_pct"),
           "unheard": [u for u in report.get("unheard") or () if isinstance(u, dict)], "at": time.time()}
    return out


def stop(key):
    """*Stop* while it lines up: its run's `cancel` file (Anki Miner stops at its next step; each audio file it
    finished stays kept for the next start), the stop's time kept so the book waits for your next *Mine now*. -> True
    when a line-up of this pair was running."""
    held = running(key)
    if held:
        from app.connect import anki_miner
        anki_miner.cancel(os.path.join(folder(key), "run"), RUN_ID)
    state = read(key)
    if state.get("status") in (RUNNING, INTERRUPTED) or held:
        write(key, dict(state, status=STOPPED, stopped_at=utc()))
        return True
    return False


def file_line(state):
    """`file k of n` while it runs (AB-Q3)."""
    return int(state.get("file") or 1), int(state.get("of") or len(state.get("audio") or ()) or 1)


# --------------------------------------------------------------------------- #
# What the cards are cut from
# --------------------------------------------------------------------------- #
def own(key, audio, subtitle):
    """Kura-AB3: the line-up an audiobook's own timed subtitle is (one audio file, its `.srt`): DONE, no grade — its
    cues the transcript's, read as a sync's are (`cues`)."""
    return {"status": DONE, "key": key, "source": OWN, "grade": None,
            "files": [{"audio_file": os.path.abspath(audio), "subtitle_file": os.path.abspath(subtitle),
                       "status": "synced", "units": {}}]}


def usable(state):
    """Are this line-up's cues fit to cut cards from (AB-Q4: grade A or B; never C / D — another edition, the wrong
    book: never a wrong clip)? The audiobook's own subtitle (`own`) is: Hon found it the book's."""
    return state.get("status") == DONE and (state.get("grade") in GOOD or state.get("source") == OWN)


def partial_line(state, title):
    """AB-Q4's one plain line for a pair, or None: a grade of C or D (its cards are made without sentence audio), or
    passages the narrator skipped (their cards have no sentence audio)."""
    if state.get("status") != DONE:
        return None
    if state.get("grade") not in GOOD:
        return (f"「{title}」: its audiobook doesn't follow this book closely (grade {state.get('grade')}), so its cards "
                f"are made without sentence audio. Is it another edition?")
    skipped = len(state.get("unheard") or ())
    if skipped:
        return (f"「{title}」: its audiobook skips {skipped} passage{'s' if skipped != 1 else ''} of the book; cards from "
                f"{'them' if skipped != 1 else 'it'} have no sentence audio.")
    return None


_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def _seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def srt_cues(path):
    """[(start, end, text)] of an SRT (Anki Miner's: UTF-8), in order; [] when it can't be read."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                out.append((_seconds(*m.groups()[:4]), _seconds(*m.groups()[4:]), "".join(lines[i + 1:]).strip()))
                break
    return out


def clean(text):
    """The sync's normalisation: NFKC, letters and digits only (ruby, punctuation, spaces out)."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LN").casefold()


def cues(state):
    """Every cue of a usable line-up, in the book's order: [Cue(audio, subtitle, start, end, clean text, the book's unit
    it is)] — only a file whose audio and subtitle are on this computer now (review B-3: an audiobook moved or away
    since is never sent: those words go as the book)."""
    out = []
    for f in state.get("files") or ():
        if f.get("status") != "synced" or not f.get("subtitle_file") or not f.get("audio_file") or \
                not os.path.isfile(f["audio_file"]) or not os.path.isfile(f["subtitle_file"]):
            continue
        units = f.get("units") or {}
        for n, (start, end, text) in enumerate(srt_cues(f["subtitle_file"]), 1):
            out.append(Cue(f["audio_file"], f["subtitle_file"], start, end, clean(text), units.get(str(n))))
    return out


def place(line_text, spelling, found, unit=None):
    """The cue a word's card is cut from -> a Cue, or None (its sentence wasn't heard: the book's card, no clip). The
    book's unit the pick knows (`unit`, Anki Miner's own index: the sync's `cues[].index`) names it when its cue holds
    the word. Else its sentence (`line_text`) is a cue, or holds one / sits inside one (MIN_CHARS or longer: a short
    line is only ever its own cue), and that cue holds the word as written (`spelling`) — the one cue of the sentence
    that does (review B-14: two of its cues holding it, 人 in 人間 and in 人, is no answer): never a neighbour's clip."""
    hold = clean(spelling)
    if isinstance(unit, int) and not isinstance(unit, bool):
        cue = next((c for c in found if c.unit == unit), None)
        if cue is not None and (not hold or hold in cue.text):
            return cue
    want = clean(line_text)
    if not want:
        return None
    for k, cue in enumerate(found):
        if not cue.text:
            continue
        if cue.text == want or (len(want) >= MIN_CHARS and want in cue.text):
            return cue if not hold or hold in cue.text else None
        if len(cue.text) >= MIN_CHARS and cue.text in want:
            run = [cue]                     # the sentence's cues, in a row
            for nxt in found[k + 1:]:
                if not nxt.text or nxt.text not in want or len(nxt.text) < MIN_CHARS:
                    break
                run.append(nxt)
            holding = [c for c in run if not hold or hold in c.text]
            return holding[0] if len(holding) == 1 else None
    return None


def split(words, state):
    """A book's picked words cut from its line-up -> ({(audio, subtitle): [word, …]}, [the rest]): each word placed
    (`place`, its spelling as the line writes it) goes as its file's audio episode, its `line_start` the cue's start;
    a word not placed, or every word of a line-up not `usable`, goes as the book."""
    groups, rest = {}, []
    found = cues(state) if usable(state) else []
    for word in words:
        cue = place(word.get("line_text"), word.get("surface") or word.get("orth") or word.get("word"), found,
                    word.get("unit_index")) if found else None
        if cue is None:
            rest.append(word)
            continue
        groups.setdefault((cue.audio, cue.subtitle), []).append(
            dict(word, line_start=cue.start, line_end=cue.end, line_expansion=[0, 0]))
    return groups, rest


# --------------------------------------------------------------------------- #
# The spot-check (AB-Q5)
# --------------------------------------------------------------------------- #
def overlap(said, heard):
    """How much of the subtitle's lines (`said`) the speech model heard (`heard`), in order: the share of `said`'s clean
    characters in matching runs (`difflib`, no junk heuristic)."""
    a, b = clean(said), clean(heard)
    if not a:
        return 0.0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(a)


def samples(lines, n=SAMPLES):
    """Where a subtitle is heard: n places at 1/(n+1)… of its lines, each the first line from there of SAMPLE_CHARS
    clean characters or more, one line alone -> [(its start, 0 lines after it, its text)]."""
    long_enough = [k for k, line in enumerate(lines) if len(clean(line[2])) >= SAMPLE_CHARS]
    if not long_enough:
        return []
    picks = []
    for k in range(1, n + 1):
        at = (len(lines) * k) // (n + 1)
        found = next((i for i in long_enough if i >= at), long_enough[-1])
        if found not in picks:
            picks.append(found)
    return [(lines[at][0], 0, lines[at][2]) for at in sorted(picks)]


def spot_key(audio, subtitle):
    """The spot-check's key: the subtitle's bytes and the audio file's size and time (either changed: checked again)."""
    digest = hashlib.sha256()
    try:
        with open(subtitle, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        st = os.stat(audio)
    except OSError:
        return None
    return f"{SPOT_RULE}-{digest.hexdigest()[:24]}-{st.st_size}-{st.st_mtime_ns}"


def spot_kept(key):
    return ((_read_json(os.path.join(root(), SPOT)) or {}).get(key) or {}).get("verdict") if key else None


def _keep_spot(key, verdict, shares):
    path = os.path.join(root(), SPOT)
    kept = _read_json(path) or {}
    kept[key] = {"verdict": verdict, "shares": [round(s, 3) for s in shares], "at": time.time()}
    _write_json(path, kept)


def spot_check(miner, language, profile, audio, subtitle, timeout=SPOT_TIMEOUT):
    """(`_spot_check`, its run folder removed after: the clips and transcripts are Anki Miner's for the caller to
    delete — review B-22.)"""
    import shutil
    try:
        return _spot_check(miner, language, profile, audio, subtitle, timeout)
    finally:
        shutil.rmtree(folder("spot-" + ((spot_key(audio, subtitle) or "x").split("-", 1)[-1])[:24]),
                      ignore_errors=True)


def _spot_check(miner, language, profile, audio, subtitle, timeout=SPOT_TIMEOUT):
    """AB-Q5: is `subtitle` timed to `audio`? SAMPLES places of it cut from the audio (`media`, one call) and heard
    (`transcribe`, one call), each compared with its lines (`overlap`): MATCHES of them at MATCH or more → MATCHED,
    else NOT_MATCHED; kept per `spot_key`. -> MATCHED / NOT_MATCHED, or None (it couldn't be checked now: a call
    refused or failed — asked again at the next look). Raises AnkiMinerError `setup` when Anki Miner has no speech
    model (the caller asks for it)."""
    from app.connect import anki_miner
    key = spot_key(audio, subtitle)
    kept = spot_kept(key)
    if kept in (MATCHED, NOT_MATCHED):
        return kept
    places = samples(srt_cues(subtitle))
    if not places:
        return None
    where = folder("spot-" + ((key or "x").split("-", 1)[-1])[:24])
    os.makedirs(where, exist_ok=True)
    run_dir = os.path.join(where, "run")
    os.makedirs(run_dir, exist_ok=True)
    base = {"schema": 1, "run_dir": run_dir, "language": language}
    if profile:
        base["profile"] = profile
    media = dict(base, episodes=[{"run_id": "spot", "audio_file": os.path.abspath(audio),
                                  "subtitle_file": os.path.abspath(subtitle),
                                  "lines": [{"line_start": start, "line_expansion": [0, after]}
                                            for start, after, _t in places]}])
    path = os.path.join(where, "media.json")
    _write_json(path, media)
    # a look-up for the job's *Stop* (review B-16): nothing here writes anything but its run folder, so a press ends it
    verdict = anki_miner.api(miner, ["media", path], timeout=timeout, look_up=True)
    run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == "spot"), None)
    if run is None or not run.get("ok"):
        if not verdict.get("runs"):
            anki_miner._result(verdict)     # a refusal of the whole call (BUSY never: `media` takes no lock): raised
        return None
    cut = _read_json(os.path.join(run_dir, "spot", os.path.basename(str(run.get("file") or "")))) or {}
    lines = [line for line in cut.get("lines") or () if isinstance(line, dict)]
    # each clip a path inside the run's folder (`media-<n>/<k>.mp3`), its lines as Anki Miner merged them (its 30 s
    # budget may hold fewer than asked: what was cut is what is compared)
    clips = [os.path.join(run_dir, "spot", line["audio"]) if isinstance(line.get("audio"), str) else None
             for line in lines]
    if len(clips) != len(places):
        return None
    # a line Anki Miner cut no clip for (the drill of record: another file's subtitle, its lines past this audio's end)
    # is a place where nothing of it is heard — never a wrong clip, so it counts against it
    clips = [c if c and os.path.isfile(c) else None for c in clips]
    places = [(s, a, line.get("text") if isinstance(line.get("text"), str) and line.get("text") else t)
              for (s, a, t), line in zip(places, lines)]
    shares = []
    if any(clips):
        heard_job = dict(base, episodes=[{"run_id": f"heard-{k}", "audio_file": os.path.abspath(c)}
                                         for k, c in enumerate(clips, 1) if c])
        path = os.path.join(where, "transcribe.json")
        _write_json(path, heard_job)
        verdict = anki_miner.api(miner, ["transcribe", path], timeout=timeout, look_up=True)
        if not verdict.get("runs") and not verdict.get("ok"):
            anki_miner._result(verdict)             # SETUP_ERROR (no speech model) and the like: raised
    for k, (_s, _a, said) in enumerate(places, 1):
        if clips[k - 1] is None:
            shares.append(0.0)
            continue
        run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == f"heard-{k}"),
                   None)
        if run is None or not run.get("ok"):
            # a clip it couldn't listen to (the drill of record: a clip of silence past this audio's end, refused as
            # unreadable) is heard as nothing; every clip refused is no answer (looked at again)
            shares.append(None)
            continue
        made = _read_json(os.path.join(run_dir, f"heard-{k}", os.path.basename(str(run.get("file") or "")))) or {}
        heard = "".join(t for _s2, _e2, t in srt_cues(made["subtitle_file"])) \
            if isinstance(made.get("subtitle_file"), str) else ""
        shares.append(overlap(said, heard))
    if any(clips) and all(s is None for s, c in zip(shares, clips) if c):
        return None
    shares = [0.0 if s is None else s for s in shares]
    need = min(MATCHES, len(shares))
    out = MATCHED if sum(1 for s in shares if s >= MATCH) >= need else NOT_MATCHED
    if key:
        _keep_spot(key, out, shares)
    return out
