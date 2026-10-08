"""The fit-check gate (P2.4 row 2.4.5; K89; P1.5 06-edges E16, E17): Connect mines an episode only when its subtitle is
known to be timed to its video — a card cut from a subtitle a few seconds off holds the wrong line's audio.

- **hato's verdict** (its pairing record, `verdict`): `timed` → mine.
- **Anything else** (hato's `extracted` / `untimed`, or no pairing: your own placement): tsubasa's command line when
  it's installed (`tsubasa --pair VIDEO SUB --dry-run --json --no-results`, P0.2: about a second an episode, never a
  write): `CONFIDENT` with one segment → mine; anything else (`REFUSED`, `ERROR`, two segments, no answer) → not timed.
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

TIMED, NOT_TIMED = "timed", "not timed"
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
    """-> (TIMED or NOT_TIMED, who decided: `hato` · `tsubasa` · None, the reason in plain words when not timed).
    `tsubasa`: its program (default: found on PATH); `run`: `subprocess.run`'s stand-in (tests)."""
    if (pairing or {}).get("verdict") == "timed":
        return TIMED, "hato", None
    exe = tsubasa if tsubasa is not None else find_tsubasa()
    if not exe:
        return NOT_TIMED, None, "Not timed to its video, so no cards."
    command = [exe, "--pair", video, subtitle, "--dry-run", "--json", "--no-results"]
    options = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" and run is None else {}
    try:
        done = (run or subprocess.run)(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, timeout=timeout, **options)
    except (OSError, subprocess.SubprocessError) as e:
        return NOT_TIMED, "tsubasa", f"tsubasa couldn't check it ({type(e).__name__}), so no cards."
    answer = _answer(done.stdout)
    outcome = (answer or {}).get("outcome")
    segments = (answer or {}).get("segments")
    if outcome == "CONFIDENT" and isinstance(segments, list) and len(segments) == 1:
        return TIMED, "tsubasa", None
    if outcome == "CONFIDENT":
        return NOT_TIMED, "tsubasa", "Its timing changes part-way through the video, so no cards."
    reason = (answer or {}).get("reason")
    if outcome in ("REFUSED", "ERROR"):
        return NOT_TIMED, "tsubasa", f"Not timed to its video ({outcome.lower()}), so no cards." + (
            f" tsubasa: {reason}" if isinstance(reason, str) and reason else "")
    return NOT_TIMED, "tsubasa", "tsubasa gave no answer, so no cards."


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
