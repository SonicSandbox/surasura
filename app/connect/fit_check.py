"""The fit-check gate (P2.4 row 2.4.5; K89; P1.5 06-edges E16, E17): Connect mines an episode only when its subtitle is
known to be timed to its video — a card cut from a subtitle a few seconds off holds the wrong line's audio.

- **hato's verdict** (its pairing record; 09-hato-layer v2 *Connect's gate*): `schema` 1, `verdict` `timed`, the
  library copy's sha256 = `subtitle_sha256`, `timing.segments` 1 and `timing.reference` one of tsubasa's three kinds
  (`REFERENCES`) → mine (hato's copy is already timed: no offset).
- **The video's own track** (Michi-ST, `track_timed`): a subtitle Surasura copied out of the video it is mined with
  (its origin record's `verdict` `extracted`, the copy's sha256 as recorded) → mine, no offset: no tsubasa asked.
- **Anything else** (hato's `extracted` / `untimed`, a `timed` record that doesn't hold all five — a `reference`
  absent, `subtitle` (v1's, named no tsubasa reference) or unknown included — or no pairing: your own placement):
  tsubasa's command line when
  it's installed (`tsubasa --pair VIDEO SUB --dry-run --json --no-results`, P0.2: about a second an episode, never a
  write): `CONFIDENT` with one segment → mine; anything else (`REFUSED`, `ERROR`, two segments or none, an answer it
  can't read) → not timed; no answer at all (it timed out, or couldn't start) → asked again at the runner's next look.
  Its offset (`_offset`: the answer's `offset`, else its one [start, offset] segment's) is the shift Anki Miner cuts
  the lines by (`subtitle_offset`, RUNBOOK-P1.3 1.3.4); none readable → not timed (never cut at 0.0): tsubasa
  checks with `--dry-run`, so the copy itself is never re-timed.
- **An audio file's own subtitle, heard** (Michi-AB AB-Q5, Sonic 2026-11-02, PROVISIONAL: `spot`, the runner's
  `lineup.spot_check` through Anki Miner's speech model): a few places of it heard and compared with its lines —
  they match → mine at its own times (no shift); they don't → not timed (never a wrong clip: *Mine anyway* stays
  yours); the model's question passed on as it is; no answer now → the rules below, as before (tsubasa has no
  reference inside an audio file). *Trust my subtitles' timing* is asked first: you said they are synced.
- **Neither** → not timed. 2.x lists it once in *Needs you*, with no button (E16; 3.0: *Mine anyway*, G1.3-6).
- **Trust my subtitles' timing** (`connect_trust_timing`, off by default; laptop try row 9, P-LF-9): with nothing to
  check it — no tsubasa on this PC, or tsubasa's ERROR for a video with no subtitle track inside (a raw; P0.2) — and no
  pairing program's record (`others`), the episode mines at its subtitle's own times (no shift), as *Mine anyway*
  would. Only Surasura's own records are released (`OWN_PRODUCERS`): a Library folder's or + Add's origin (`source`),
  a *Link…* (`surasura`) and its own YouTube download (`youtube`) are no timing anyone was asked to check. Every other record waits — hato's (no producer, or `hato`, as
  `rules.rule_for` reads them) and any program's registered through `connect register` — as do tsubasa's REFUSED and
  any other ERROR.

tsubasa decides by `outcome` and `segments` only (P0.2: on `ERROR` its other fields carry defaults). It is GPL, so it
is run as a program, never imported (K1). Found beside Surasura's own exe when frozen (3.0 ships `tsubasa.exe` in its
bundle, T1), else on PATH (`tsubasa`, or `tsubasa.exe`); a test hands its own.

**A pairing's version** (`version`): a short hash of the record as hato wrote it. The runner keeps it with the pick and
looks again before mining: a pairing changed since (hato re-timed it, a new subtitle) → picked again (E17); after
mining it is left alone.

Standard library only; no Tk.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

from app.connect import stopping

TIMED, NOT_TIMED, RETRY = "timed", "not timed", "retry"
TIMEOUT_S = 120             # a file without a usable index is read whole: 10–30 s over a network share (P0.2)
CREATE_NO_WINDOW = 0x08000000
REFERENCES = ("text-track", "picture-track", "speech-mask")     # what tsubasa timed against (09-hato-layer v2 P13)
SOURCE = "source"               # a source folder's origin record's producer (library_store.SOURCE_PRODUCER)
NO_TRACK = "no subtitle track"   # tsubasa's ERROR for a raw video: nothing inside it to time against (P0.2)
TRUST_LABEL = "Trust my subtitles’ timing"                         # Settings → Anki & mining (settings_strings)
NO_CHECKER = ("Nothing on this PC can check its timing (no tsubasa), so no cards yet. If your subtitles are synced, "
              f"turn on {TRUST_LABEL} in Settings → Anki & mining.")
SPOT_MATCHED, SPOT_NOT_MATCHED = "match", "no-match"      # `lineup.MATCHED` / `NOT_MATCHED`
# tsubasa is sure of the timing, but it shifts part-way (two segments or more: a broadcast cut another way than the
# subtitle's source). One offset can't cut it, so `fit` says not timed; the runner asks tsubasa for a retimed copy
# (`retime`) and, when it holds the same lines (`same_lines`), it becomes Surasura's library copy for good — the episode
# is picked again from it and checked again (Mattias 2026-11-11, rezeroS04)
PART_WAY = "Its timing changes part-way through the {media}, so no cards."
RETIMED = "retimed"             # the folder in a job's run folder that holds tsubasa's retimed copy
SPOT_NO_MATCH = ("Its subtitle doesn't match its audio where Connect listened, so no cards: a card's audio would hold "
                 "another line. Mine anyway only if you know it plays in time.")


def version(pairing):
    """A short, stable hash of a pairing record (None: no pairing)."""
    if not pairing:
        return None
    text = json.dumps(pairing, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def find_tsubasa():
    """tsubasa's program: the one Surasura's bundle ships beside its own exe (frozen: `tsubasa.exe` beside
    `Surasura.exe` and `surasura-cli.exe`, sharing `_internal`; T1), else one on PATH (a developer's pip install), else
    None (nothing here checks timing)."""
    from app.path_utils import is_frozen, program_beside
    if is_frozen():
        bundled = program_beside("tsubasa")
        if os.path.isfile(bundled):
            return bundled
    return shutil.which("tsubasa")


def check(pairing, video, subtitle, tsubasa=None, run=None, timeout=TIMEOUT_S, trust=False):
    """-> (TIMED, NOT_TIMED or RETRY, who decided: `hato` · `track` · `tsubasa` · `you` (`trust`) · None, the reason in plain
    words when not timed). RETRY: tsubasa didn't answer (timed out, couldn't start) — the runner asks again at its next
    look. `tsubasa`: its program (default: found on PATH); `run`: `subprocess.run`'s stand-in (tests); `trust`:
    `connect_trust_timing`. The job's *Stop* ends tsubasa within a second: `stopping.Stopped` (row 56)."""
    return fit(pairing, video, subtitle, tsubasa, run, timeout, trust)[:3]


def _sha256(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


# Surasura's own verdicts on a source folder's video (`library_store.fill_track`): its own track copied out (Michi-ST),
# a subtitle made from its own audio (Michi-NS)
OWN_VERDICTS = ("extracted", "transcribed")


def track_timed(pairing, subtitle):
    """Michi-ST (`app/tracks.py`): the subtitle is the video's own track, copied out by Surasura — its own record (a
    source folder's origin, `producer` "source"), `verdict` "extracted", and the library copy is that very file (its
    sha256): timed to that video, nothing to check. A copy changed since is checked as any other. Michi-NS
    (`app/no_subs.py`, Q5 ✅ Sonic 2026-10-31: mined like any timed subtitle): a subtitle Anki Miner made from the
    video's own audio (`verdict` "transcribed") is timed to that audio the same way."""
    pairing = pairing if isinstance(pairing, dict) else {}
    want = pairing.get("subtitle_sha256")
    if pairing.get("producer") != SOURCE or pairing.get("verdict") not in OWN_VERDICTS or             not isinstance(want, str) or not want or not subtitle:
        return False
    return _sha256(subtitle) == want.lower()


def hato_timed(pairing, subtitle):
    """hato's own verdict holds (09-hato-layer v2 *Connect's gate*): schema 1, `timed`, one segment, a reference
    Surasura knows (`REFERENCES`), and the library copy is the file hato timed (its sha256)."""
    pairing = pairing if isinstance(pairing, dict) else {}     # a row of another shape is no verdict of hato's
    timing = pairing.get("timing") if isinstance(pairing.get("timing"), dict) else {}
    if pairing.get("schema") != 1 or pairing.get("verdict") != "timed" or timing.get("segments") != 1:
        return False
    if timing.get("reference") not in REFERENCES:   # an unknown one means "check it yourself"
        return False
    want = pairing.get("subtitle_sha256")
    if not isinstance(want, str) or not want or not subtitle:
        return False
    return _sha256(subtitle) == want.lower()


# Released by the switch: Surasura's own records — a folder's or + Add's origin (library_store.SOURCE_PRODUCER) and a
# *Link…* (link.PRODUCER), which `connect register` refuses from any other program (connect_verbs.RESERVED) — and a
# YouTube / bilibili download's (`youtube`: Surasura's own, app/qt/windows.youtube_record, or a downloader the placing
# rules name): its transcript is that very video's, so no timing is in doubt whoever registered it.
OWN_PRODUCERS = ("source", "surasura", "youtube")


def others(pairing):
    """Did a pairing program write this record — hato (no producer named, or `hato`: `rules.rule_for` reads them so) or
    any other registering through `connect register`? Then its verdict stands and the switch never releases it. Only
    Surasura's own records (`OWN_PRODUCERS`) and no record at all (None) are released. A row that is there but empty, or
    of a shape Surasura doesn't know, waits."""
    if pairing is None:
        return False
    if not isinstance(pairing, dict):
        return True
    return str(pairing.get("producer") or "hato").strip() not in OWN_PRODUCERS


def fit(pairing, video, subtitle, tsubasa=None, run=None, timeout=TIMEOUT_S, trust=False, spot=None):
    """`check`, with the shift to cut by -> (verdict, who, why, offset in seconds: tsubasa's one segment's, else
    0.0). `spot()`: an audio file's spot-check (AB-Q5) -> SPOT_MATCHED / SPOT_NOT_MATCHED / None (no answer now), or a
    whole answer of its own (the speech model's question), passed on."""
    if hato_timed(pairing, subtitle):
        return TIMED, "hato", None, 0.0
    if track_timed(pairing, subtitle):
        return TIMED, "audio" if pairing.get("verdict") == "transcribed" else "track", None, 0.0
    if spot is not None and _media(video) == "audio":
        heard = spot()
        if heard == SPOT_MATCHED:
            return TIMED, "spot-check", None, 0.0
        if heard == SPOT_NOT_MATCHED:
            return NOT_TIMED, "spot-check", SPOT_NO_MATCH, 0.0
        if isinstance(heard, tuple):
            return heard
    exe = tsubasa if tsubasa is not None else find_tsubasa()
    if not exe:
        if others(pairing):         # a pairing program paired it but didn't time it: the switch never releases that
            return NOT_TIMED, None, f"Not timed to its {_media(video)}, so no cards.", 0.0
        if trust:                   # you said your subtitles are synced: cut where the subtitle puts the lines
            return TIMED, "you", None, 0.0
        return NOT_TIMED, None, NO_CHECKER, 0.0
    command = [exe, "--pair", video, subtitle, "--dry-run", "--json", "--no-results"]
    try:
        stdout = _run(command, timeout) if run is None else run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        # no answer in time (a file read whole over a slow share or a slow disk): asked again — the hourglass says so
        # (LF56-1: Sonic's laptop sat at *Checking the timing* with no word why)
        return RETRY, "tsubasa", (f"Checking its timing took longer than {_span(timeout)}; Connect tries again at its "
                                  "next look."), 0.0
    except (OSError, subprocess.SubprocessError) as e:
        # no answer this time (a program that wouldn't start): asked again
        return RETRY, "tsubasa", (f"tsubasa couldn't check its timing this time ({type(e).__name__}); Connect tries "
                                  "again at its next look."), 0.0
    answer = _answer(stdout)
    outcome = (answer or {}).get("outcome")
    segments = (answer or {}).get("segments")
    if outcome == "CONFIDENT" and isinstance(segments, list) and len(segments) == 1:
        offset = _offset(answer)
        if offset is None:          # nothing to cut by: 0.0 could be seconds off, so not timed
            return NOT_TIMED, "tsubasa", "tsubasa gave no shift to cut its lines by, so no cards.", 0.0
        return TIMED, "tsubasa", None, offset
    if outcome == "CONFIDENT" and isinstance(segments, list) and len(segments) > 1:
        return NOT_TIMED, "tsubasa", PART_WAY.format(media=_media(video)), 0.0
    if outcome == "CONFIDENT":
        return NOT_TIMED, "tsubasa", "tsubasa found no timing to cut its lines by, so no cards.", 0.0
    reason = (answer or {}).get("reason")
    raw = outcome == "ERROR" and isinstance(reason, str) and NO_TRACK in reason and not others(pairing)
    if raw and trust:               # nothing inside the video to time against, and you trust your subtitles
        return TIMED, "you", None, 0.0
    if outcome in ("REFUSED", "ERROR"):
        return NOT_TIMED, "tsubasa", f"Not timed to its {_media(video)} ({outcome.lower()}), so no cards." + (
            f" tsubasa: {reason}" if isinstance(reason, str) and reason else "") + (
            f" If your subtitles are synced, turn on {TRUST_LABEL} in Settings → Anki & mining." if raw else ""), 0.0
    return NOT_TIMED, "tsubasa", "tsubasa gave no answer, so no cards.", 0.0


def part_way(why):
    """Is `why` the reason `fit` gives a subtitle whose timing shifts part-way (`PART_WAY`)? Only that one is retimed:
    a refusal or an error has no timing tsubasa could write."""
    return isinstance(why, str) and why in (PART_WAY.format(media="video"), PART_WAY.format(media="audio"))


def retime(video, subtitle, out_dir, tsubasa=None, run=None, timeout=TIMEOUT_S):
    """tsubasa's retimed copy of `subtitle` for `video`, written in `out_dir` (emptied first) -> its path, or None.

    `tsubasa --pair VIDEO SUB --out DIR --json --no-results`: it times the subtitle piece by piece (every segment its
    own shift) and writes the copy under DIR only — the library's copy, the original and the video's folder are never
    written by tsubasa, and no record of tsubasa's is updated (the runner puts the copy in the library's place). Only
    an SRT is retimed (`lineup.srt_cues` reads both for `same_lines`); anything else, no tsubasa, a refusal, an error,
    no answer in time, or no file where it says it wrote one -> None, and the episode stays not timed. The job's
    *Stop* ends it as the check does."""
    if not subtitle or os.path.splitext(subtitle)[1].lower() != ".srt":
        return None
    exe = tsubasa if tsubasa is not None else find_tsubasa()
    if not exe:
        return None
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    command = [exe, "--pair", video, subtitle, "--out", out_dir, "--json", "--no-results"]
    try:
        stdout = _run(command, timeout) if run is None else run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
        return None
    answer = _answer(stdout) or {}
    path = answer.get("output_path")
    if answer.get("outcome") != "CONFIDENT" or answer.get("write_failed") or not isinstance(path, str) or not path:
        return None
    inside = os.path.normcase(os.path.abspath(out_dir)) + os.sep
    if not os.path.normcase(os.path.abspath(path)).startswith(inside) or not os.path.isfile(path):
        return None                 # never a file outside the job's own folder
    return path


def same_lines(before, after):
    """Does tsubasa's retimed copy hold the library copy's lines — the same cues (`lineup.srt_cues`), the same texts,
    in the same order, only their times moved? Only then may it take the library copy's place: anything else is not
    the copy it should be, and the library copy is left as it is."""
    return bool(before) and len(before) == len(after) and all(a[2] == b[2] for a, b in zip(before, after))


def _media(path):
    """What the lines are cut from, in the reasons' words: "audio" for an audio file (Z-16: tsubasa 0.1.11 has no
    reference inside one — its ERROR names no subtitle track, a raw's — so it waits for *Trust my subtitles' timing*
    or *Mine anyway*, as a raw video does), else "video"."""
    from app.connect.anki_miner import is_audio
    return "audio" if is_audio(path) else "video"


def _span(seconds):
    """`timeout` in plain words: "2 minutes", "90 seconds"."""
    seconds = int(seconds)
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60} minute{'' if seconds == 60 else 's'}"
    return f"{seconds} second{'' if seconds == 1 else 's'}"


def _run(command, timeout):
    """tsubasa's stdout, waited for in slices (row 56, `stopping.wait`): the job's *Stop* ends it within a second and
    raises `stopping.Stopped` (the job stops before its fit check); past `timeout` it is ended and TimeoutExpired
    raised (asked again)."""
    options = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **options)
    try:
        return stopping.wait(proc, timeout, look_up=True)[0]
    except subprocess.TimeoutExpired:
        stopping.end(proc)
        raise


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _offset(answer):
    """The shift, in seconds, tsubasa's answer says to cut its lines by, or None. Its real `--json` (0.1.10,
    `cli.as_json`): a top-level `offset` (the first segment's), read first, and `segments` as [start, offset] pairs.
    Anki Miner adds it to every subtitle time (`subtitle_offset`): a subtitle 2.4 s late reads -2.4."""
    offset = _number(answer.get("offset"))
    if offset is None:
        segments = answer.get("segments")
        first = segments[0] if isinstance(segments, list) and segments else None
        offset = _number(first[1]) if isinstance(first, list) and len(first) == 2 else None
    return offset


def _answer(stdout):
    """tsubasa's JSON line: the last line of its output that starts with `{`, or None."""
    text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else (stdout or "")
    for line in reversed(text.splitlines()):
        if line.lstrip().startswith("{"):
            try:
                value = json.loads(line)
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None
