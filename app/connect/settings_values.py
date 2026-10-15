"""The values Connect's settings write (pure; P3.1 rows 3.1.2–3.1.3): moved from `app/connect/settings_panel.py` (W3.3
P1, a pure move) so the 3.0 window's Settings computes them without Tk. The Tk panel imports them from here under its
own names; their tests read them through it.

- `connect_backlog_cap` and `connect_video_folders` are one value per language (D31): a plain value is every
  language's, a dict each its own. Setting one language keeps each other language's value as it was.
- `anki_sync_delay_min`: Settings' three choices, and a held value outside them (順's "5 minutes after") kept as itself.
- `known_from_anki`: the picked card states in the setting's order ("and": every one must hold); none is off.

No Tk, no Qt.
"""
LANGUAGES = ("ja", "zh")

# connect_mine_words: (value, label, the line under it)
WORDS = (("list", "Your list", "Words on your list that you don't know and have no card yet."),
         ("unknown", "Every unknown word", "Every word of the episode you don't know yet."),
         ("i1", "Only i+1", "Only words with a line whose other words you know."))
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
