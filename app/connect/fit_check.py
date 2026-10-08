"""The fit-check gate (P2.4 row 2.4.5; K89; P1.5 06-edges E16, E17): Connect mines an episode only when its subtitle is
known to be timed to its video — a card cut from a subtitle a few seconds off holds the wrong line's audio.

- **hato's verdict** (its pairing record; 09-hato-layer *Connect's gate*): `schema` 1, `verdict` `timed`, the library
  copy's sha256 = `subtitle_sha256` and `timing.segments` 1 → mine (hato's copy is already timed: no offset).
- **Anything else** (hato's `extracted` / `untimed`, a `timed` record that doesn't hold all four, or no pairing: your
  own placement): tsubasa's command line when
  it's installed (`tsubasa --pair VIDEO SUB --dry-run --json --no-results`, P0.2: about a second an episode, never a
  write): `CONFIDENT` with one segment → mine; anything else (`REFUSED`, `ERROR`, two segments or none, an answer it
  can't read) → not timed; no answer at all (it timed out, or couldn't start) → asked again at the runner's next look.
  Its one segment's `offset` is the shift Anki Miner cuts the lines by (`subtitle_offset`, RUNBOOK-P1.3 1.3.4): tsubasa
  checks with `--dry-run`, so the copy itself is never re-timed.
- **Neither** → not timed. 2.x lists it once in *Needs you*, with no button (E16; 3.0: *Mine anyway*, G1.3-6).

tsubasa decides by `outcome` and `segments` only (P0.2: on `ERROR` its other fields carry defaults). It is GPL, so it
is run as a program, never imported (K1). Found on PATH (`tsubasa`, or `tsubasa.exe`); a test hands its own.

**A pairing's version** (`version`): a short hash of the record as hato wrote it. The runner keeps it with the pick and
looks again before mining: a pairing changed since (hato re-timed it, a new subtitle) → picked again (E17); after
mining it is left alone.

Standard library only; no Tk.
"""
import hashlib
import json
import shutil
import subprocess
import sys

TIMED, NOT_TIMED, RETRY = "timed", "not timed", "retry"
TIMEOUT_S = 120             # a file without a usable index is read whole: 10–30 s over a network share (P0.2)
CREATE_NO_WINDOW = 0x08000000


def version(pairing):
    """A short, stable hash of a pairing record (None: no pairing)."""
    if not pairing:
        return None
    text = json.dumps(pairing, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def find_tsubasa():
    return shutil.which("tsubasa")


def check(pairing, video, subtitle, tsubasa=None, run=None, timeout=TIMEOUT_S):
    """-> (TIMED, NOT_TIMED or RETRY, who decided: `hato` · `tsubasa` · None, the reason in plain words when not
    timed). RETRY: tsubasa didn't answer (timed out, couldn't start) — the runner asks again at its next look.
    `tsubasa`: its program (default: found on PATH); `run`: `subprocess.run`'s stand-in (tests)."""
    return fit(pairing, video, subtitle, tsubasa, run, timeout)[:3]


def hato_timed(pairing, subtitle):
    """hato's own verdict holds (09-hato-layer *Connect's gate*): schema 1, `timed`, one segment, and the library copy
    is the file hato timed (its sha256)."""
    pairing = pairing or {}
    timing = pairing.get("timing") if isinstance(pairing.get("timing"), dict) else {}
    if pairing.get("schema") != 1 or pairing.get("verdict") != "timed" or timing.get("segments") != 1:
        return False
    want = pairing.get("subtitle_sha256")
    if not isinstance(want, str) or not want or not subtitle:
        return False
    digest = hashlib.sha256()
    try:
        with open(subtitle, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == want.lower()


def fit(pairing, video, subtitle, tsubasa=None, run=None, timeout=TIMEOUT_S):
    """`check`, with the shift to cut by -> (verdict, who, why, offset in seconds: tsubasa's one segment's, else
    0.0)."""
    if hato_timed(pairing, subtitle):
        return TIMED, "hato", None, 0.0
    exe = tsubasa if tsubasa is not None else find_tsubasa()
    if not exe:
        return NOT_TIMED, None, "Not timed to its video, so no cards.", 0.0
    command = [exe, "--pair", video, subtitle, "--dry-run", "--json", "--no-results"]
    options = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" and run is None else {}
    try:
        done = (run or subprocess.run)(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, timeout=timeout, **options)
    except (OSError, subprocess.SubprocessError) as e:
        # no answer this time (a file read whole over a slow share, a program that wouldn't start): asked again
        return RETRY, "tsubasa", f"tsubasa couldn't check it this time ({type(e).__name__}); Connect asks again.", 0.0
    answer = _answer(done.stdout)
    outcome = (answer or {}).get("outcome")
    segments = (answer or {}).get("segments")
    if outcome == "CONFIDENT" and isinstance(segments, list) and len(segments) == 1:
        offset = segments[0].get("offset") if isinstance(segments[0], dict) else None
        return TIMED, "tsubasa", None, float(offset) if isinstance(offset, (int, float)) else 0.0
    if outcome == "CONFIDENT" and isinstance(segments, list) and len(segments) > 1:
        return NOT_TIMED, "tsubasa", "Its timing changes part-way through the video, so no cards.", 0.0
    if outcome == "CONFIDENT":
        return NOT_TIMED, "tsubasa", "tsubasa found no timing to cut its lines by, so no cards.", 0.0
    reason = (answer or {}).get("reason")
    if outcome in ("REFUSED", "ERROR"):
        return NOT_TIMED, "tsubasa", f"Not timed to its video ({outcome.lower()}), so no cards." + (
            f" tsubasa: {reason}" if isinstance(reason, str) and reason else ""), 0.0
    return NOT_TIMED, "tsubasa", "tsubasa gave no answer, so no cards.", 0.0


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
