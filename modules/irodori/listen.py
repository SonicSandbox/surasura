# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI voice for listening rounds (`app/listening.py`'s VOICES["ja"]).

A listening round's lines are the learner's AI's, checked by Surasura; this file only voices them, as a card's
sentence is voiced (`make.make_clips`), on the same loopback server — but with ONE voice for the whole round (a
listening pack, `voices/*.json` with `"for": "listening"`: one caption and one seed on every line, the pack's speed),
the wav back as it is (the round joins PCM itself, so its subtitles are the clips' own times) and
nothing to Anki. The beta switch and the install are the card audio's: no switch of its own.

* `why_not(settings)` — None when the voice can read a round now; else one plain sentence with how to turn it on.
* `usable(text)` — `voice.usable` in words: None, or why the voice can't read a line (no Japanese, too long).
* `voices()` — the listening voices' ids, DEFAULT_VOICE first; `unknown(name)` — None, or the sentence naming them.
* `seconds_per_line()` — about how long a line takes here (README § Running: CPU 15–34 s, a GPU a few).
* `Speaker(settings, voice=None)` — the voice named (else DEFAULT_VOICE; with no listening pack at all, the card
  audio's own pack) — holds the voice's one-run lock (`runtime.running`: card audio and rounds take turns, across
  every Surasura process; `Busy` while another holds it) and its server; `speak(text)` -> the wav's bytes;
  `rest_before()` -> the seconds to rest before the next line (the round takes them a second at a time).

GPU pace: card audio's (make.py's BURST lines, then PAUSE_S off), counted across every round one maker process makes.
"""
import re

from modules.irodori import enabled, installed

OFF = ("The AI voice is off. Turn it on in Surasura: Settings › App › Beta › AI audio for cards without audio, then "
       "press Install.")
NOT_INSTALLED = ("The AI voice isn't installed yet. In Surasura: Settings › App › Beta › AI audio for cards without "
                 "audio › Install.")
BUSY = "The AI voice is making card audio just now; this round starts once it has finished."
WHY = {"no Japanese": "no Japanese in it", "too long": "too long for the voice: 200 characters at most"}
CPU_S, GPU_S = 20, 3
DEFAULT_VOICE = "woman-20s"             # PROVISIONAL: a round's voice when the AI names none
_IDEOGRAPH = re.compile(r"[\u3400-\u9fff\uf900-\ufaff々〆]")


_MADE = [0]                             # lines this process has voiced (the GPU's pace runs across rounds)
_RESTED = [0]                           # the count it last rested at


class Busy(Exception):
    pass


def why_not(settings):
    if not enabled(settings):
        return OFF
    if not installed():
        return NOT_INSTALLED
    return None


def usable(text):
    """`voice.usable` in words — but a round's line is Japanese already (the round checked it as Japanese), so one in
    kanji alone (冒険！) is read too: the kana rule is there to keep a Chinese card's sentence from the voice."""
    from modules.irodori import voice
    why = voice.usable(text)
    if why == "no Japanese" and _IDEOGRAPH.search(text or ""):
        why = "too long" if len(text) > voice.MAX_CHARS else None      # the length rule still holds
    return WHY.get(why, why) if why else None


def _listening_packs():
    from modules.irodori import runtime, voice
    return {k: p for k, p in voice.packs(runtime.home()).items() if p.get("for") == "listening"}


def voices():
    """The listening voices' ids, the default first (none: the round speaks in the card audio's pack)."""
    found = sorted(_listening_packs())
    return sorted(found, key=lambda k: k != DEFAULT_VOICE)


def unknown(name):
    """None when `name` is a listening voice (or empty: the default); else one sentence naming the voices."""
    if not name or name in _listening_packs():
        return None
    return f"There is no voice {name[:40]!r}: choose one of {', '.join(voices())} (or leave it out)."


def seconds_per_line():
    from modules.irodori import runtime
    try:
        backend = runtime.status().get("backend") or "cpu"
    except Exception:
        backend = "cpu"
    return CPU_S if backend == "cpu" else GPU_S


class Speaker:
    """`with Speaker(settings) as s: s.speak(line)`. The server starts at the first line and stops at the end."""

    def __init__(self, settings, srv=None, voice=None):
        from modules.irodori import runtime
        from modules.irodori import voice as packs
        rounds = _listening_packs()             # one voice for the whole round: the one named, else the first listed
        first = (voices() or [None])[0]         # (the default, while it is there: the description's "the first")
        self.pack = rounds.get(voice or first) or rounds.get(first) or \
            packs.pack((settings or {}).get("irodori_voice"), runtime.home())
        self._srv = srv
        self._held = None

    def __enter__(self):
        from modules.irodori import runtime, server
        if self.pack is None:
            raise RuntimeError("no voice pack was found")
        self._held = runtime.running()
        if self._held is None:
            raise Busy(BUSY)
        self._own = self._srv is None
        try:
            self._srv = self._srv or server.Server()
        except BaseException:
            from app import path_utils
            path_utils.release_lock(self._held)
            self._held = None
            raise
        return self

    def rest_before(self):
        """Seconds to rest before the next line: make.PAUSE_S after each make.BURST on a GPU (the card's heat, README
        § Running), else 0. The round rests them a second at a time, so a cancel or an update is still heard."""
        from modules.irodori import make
        due = _MADE[0] and _MADE[0] % make.BURST == 0 and seconds_per_line() != CPU_S and _MADE[0] != _RESTED[0]
        if due:
            _RESTED[0] = _MADE[0]
        return make.PAUSE_S if due else 0

    def speak(self, text):
        from modules.irodori import voice
        _MADE[0] += 1
        self._srv.start()
        return self._srv.speak(text, voice.caption(text, self.pack), speed=self.pack.get("speed") or 1.0,
                               seed=voice.seed(text, self.pack), num_steps=self.pack.get("steps"), lora=self.pack.get("lora"),
                               voice=self.pack.get("voice") or "none")

    def __exit__(self, *exc):
        from app import path_utils
        try:
            if self._own and self._srv is not None:
                self._srv.stop()
        finally:
            path_utils.release_lock(self._held)
            self._held = None
