"""The values Connect's settings write (pure; P3.1 rows 3.1.2–3.1.3): moved from `app/connect/settings_panel.py` (W3.3
P1, a pure move) so the 3.0 window's Settings computes them without Tk. The Tk panel imports them from here under its
own names; their tests read them through it.

- `connect_backlog_cap` and `connect_video_folders` are one value per language (D31): a plain value is every
  language's, a dict each its own. Setting one language keeps each other language's value as it was.
- `anki_sync_delay_min`: Settings' three choices, and a held value outside them (順's "5 minutes after") kept as itself.
- `known_from_anki`: the picked card states in the setting's order ("and": every one must hold); none is off.
- The Anki Miner card's state (`card_state`, from `setup.checks`) and the star's answer (U6: `star_answered`,
  `answer_star`, kept in local data `star.json`, never settings.json) — moved here too (W3.3 P8, a pure move), so the
  3.0 window's card reads them without Tk.

No Tk, no Qt.
"""
import datetime
import json
import os

LANGUAGES = ("ja", "zh")
STAR_URL = "https://github.com/0xzerolight/anki_miner"
STAR_FILE = "star.json"

# connect_mine_words: (value, label, the line under it) — both Settings read these (`app/qt/settings_strings.py`). a7
# (Sonic, DIAGNOSIS 4: "it is i+1 AND the other stuff"): *Your list* takes every listed word, in the list's order, each
# on its i+1 line when it has one (A7S-2: i+1 picks the line, never the order);
# *Only i+1* is another set (`pick.py`: any word with an i+1 line, on the list or not), never a stricter *Your list*
# (one line each: a choice card is one line high, never wider than `settings-card-w`)
WORDS = (("list", "Your list", "i+1 and more: every unknown word on your list, on an i+1 line if it has one."),
         ("unknown", "Every unknown word", "Every word of the episode you don't know yet."),
         ("i1", "Only i+1", "Only words with an i+1 line, on your list or not. The rest get no card."))
# anki_sync_delay_min (E1.1 04 §3)
SYNC = (("About a minute after", 1), ("Right away", 0), ("Only at session start and Anki close", "off"))
# known_from_anki's terms, in the setting's order (known_signal.TERMS) with Anki's flag colours
FLAG_COLOURS = ("Red", "Orange", "Green", "Blue", "Pink", "Turquoise", "Purple")
KNOWN = (("suspended", "Suspended"), ("marked", "Marked")) + tuple(
    (f"flag:{n}", f"Flag {n} ({colour})") for n, colour in enumerate(FLAG_COLOURS, 1))


def cap_value(current, language, n):
    """`connect_backlog_cap` with `language`'s cap set to `n`: a number is every language's cap, so it becomes
    `{lang: …}` keeping each other language's; a dict keeps its other languages as they are."""
    if isinstance(current, dict):
        return dict(current, **{language: n})
    try:
        every = max(0, int(current))
    except (TypeError, ValueError):
        every = 300
    return {lang: (n if lang == language else every) for lang in LANGUAGES}


def cap_of(current, language):
    value = current.get(language, 300) if isinstance(current, dict) else current
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 300


def folders_value(current, language, folders):
    """`connect_video_folders` with `language`'s folders set: a plain list (or one folder) is every language's, so it
    becomes `{lang: […]}` keeping it for each other language; a dict keeps its other languages as they are."""
    if isinstance(current, dict):
        return dict(current, **{language: list(folders)})
    from app.connect import videos
    every = videos.configured({"connect_video_folders": current}, language)
    return {lang: (list(folders) if lang == language else list(every)) for lang in LANGUAGES}


def sync_choices(held):
    """The sync combo's (label, value)s: Settings' three, and the file's own value as itself when it is none of them
    (順's "5 minutes after": 5), kept until the user picks another."""
    if any(str(v) == str(held) for _label, v in SYNC):
        return SYNC
    try:
        minutes = int(held)
        label = f"{minutes} minute{'s' if minutes != 1 else ''} after"
    except (TypeError, ValueError):
        label = str(held)
    return SYNC + ((label, held),)


def sync_label(choices, held):
    return next((label for label, v in choices if str(v) == str(held)), choices[0][0])


def known_value(picked):
    """`known_from_anki`: the picked terms in the setting's order ("and": every one must hold); none → [] (off)."""
    return [term for term, _label in KNOWN if term in picked]


# --------------------------------------------------------------------------- #
# The Anki Miner card (U5) and the star's answer (U6): local data, never settings.json
# --------------------------------------------------------------------------- #
def star_path():
    from app.connect import ledger
    return os.path.join(ledger.folder(), STAR_FILE)


def star_answered():
    try:
        with open(star_path(), "r", encoding="utf-8") as f:
            return bool((json.load(f) or {}).get("answer"))
    except (OSError, ValueError, AttributeError):
        return False


def answer_star(answer):
    """`starred` or `not-now`, kept so the suggestion doesn't come back. Never raises."""
    try:
        path = star_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = f"{path}.{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({"answer": answer, "at": datetime.datetime.now().isoformat(timespec="seconds")}, f)
        os.replace(temp, path)
        return True
    except Exception as e:
        print(f"The star's answer wasn't kept: {e}")
        return False


def card_state(result):
    """What the Anki Miner card shows, from `setup.checks` -> {"state": "missing" | "setup" | "ready", "say",
    "missing": [plain sentences], "steps": bool (the two guided steps), "path", "version", "can_set_up": bool (A4M1-2:
    what is missing is what Anki Miner's own setup installs — Surasura runs it, `check["setup"]`), "update": bool
    (A5F2: what is missing comes with Anki Miner's installer: Surasura's update)}."""
    checks = {c["id"]: c for c in (result or {}).get("checks") or ()}
    found = (result or {}).get("anki_miner") or {}
    first = checks.get("anki_miner") or {}
    if first.get("state") != "ok":
        return {"state": "missing", "say": "Not installed", "missing": [first.get("say")] if first.get("say") else [],
                "steps": False, "path": None, "version": None}
    version = found.get("app")
    pieces = [checks.get(i) for i in ("anki_miner_version", "anki_miner_profile", "anki_miner_setup")]
    missing = [c for c in pieces if c and c.get("state") != "ok"]
    if not missing:
        return {"state": "ready", "say": f"Ready — Anki Miner {version}" if version else "Ready", "missing": [],
                "steps": False, "path": found.get("path"), "version": version}
    profile = checks.get("anki_miner_profile") or {}
    # A5F2: the steps by hand only for an Anki Miner older than 3.7 lacking its "Surasura" profile (the check marks
    # its update first); a profile Surasura makes, its address, its setup are *Finish its setup*'s; what only an update
    # brings is `update` (the card's Install, as *Update Anki Miner…*)
    return {"state": "setup", "say": f"Installed {version or ''} — needs setup".replace("  ", " "),
            "missing": [c["say"] for c in missing if c.get("say")],
            "steps": profile.get("state") == "needs-you" and bool(profile.get("update")),
            "path": found.get("path"), "version": version,
            "can_set_up": any(bool(c.get("setup")) for c in missing),
            "update": any(bool(c.get("update")) for c in missing)}
