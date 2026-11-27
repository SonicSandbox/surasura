# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜 Ukai's routes on the door — optional, self-contained Surasura module (Ukai SPEC §6 U-S2; the subtitle half of
Mattias's #474, by mattias, adapted onto the one door).

Ukai, Surasura's browser extension, sends the Netflix or Disney+ subtitle the learner's browser already shows; it
becomes a library item the way a YouTube transcript does (`subtitles.py`). These are the paired rows of the door's Ukai
class (`app/door.py` `Extension`, built by `app/services/ukai_pairing.Pairing.extension(paired=routes(...))`): the door
has checked the address, the extension's Origin and the paired token before a route runs.

- `GET /v1/hello` (open: any extension) -> {"app", "version", "contract", "door", "languages", "covers"}: the
  languages the learner has a library for (Ukai sends only those, U3) and whether *Download covers* is on (Ukai fetches
  the show's artwork only then, U7). Its CONTRACT.md's v1 shape, plus `door` and `covers`.
- `POST /v1/online-subtitle` (paired) -> {"added", "item"}: `added` false when that video is in already (never a
  second item). A language with no library here: 409 *refused* (Ukai drops it, U3); one whose library isn't the open
  one, or a library busy or read-only: 503 *busy* (Ukai keeps it and sends it again); a body the contract doesn't take:
  400 with why. One subtitle is taken in at a time, so the same episode sent twice at once is still one item.
- `POST /v1/youtube` (paired; U-S3, CONTRACT.md v3) -> {"queued"}: YouTube links for Surasura's own transcript
  downloader, run on the window's thread as if pasted in its window — only while it is here, on and its risk tick
  given (409 with which), never a link already running (`youtube.py`).

Lazy-imported by the window (`ShellWindow.ukai_extension`, only while `door.EXTENSION_ON`): Surasura runs normally
without this folder — Ukai's class is then never built and nothing listens for it. No settings of its own.
"""
import os
import threading

CONTRACT = 1                    # Ukai's CONTRACT.md: v1, the subtitle (2: the clips, U-S4; 3: YouTube links, U-S3 —
                                # v3 is v2 plus the links: 3 once both are here, the later of the two lanes sets it)
NO_LIBRARY = "Surasura has no {name} library: nothing is kept"
NAMES = {"ja": "Japanese", "zh": "Chinese"}
_ONE = threading.Lock()         # one subtitle taken in at a time: two posts of one episode are one item


def libraries():
    """The languages the learner has a library for: those whose library store is on disk (the CLI's own check,
    `cli/contract.py`). Two file looks; a language whose look fails is left out."""
    from app import library_store
    from app.path_utils import get_data_path
    from modules.ukai import subtitles
    found = []
    for language in subtitles.LANGUAGES:
        try:
            if os.path.isfile(library_store.library_db_path(language, get_data_path(language))):
                found.append(language)
        except Exception:                       # (no store here: switched off, or no data folder)
            continue
    return found


def routes(writer, settings, youtube=None):
    """The paired routes (and `hello`) for the door's Ukai class. `writer()` -> the open library's writer
    (`moves.Writer`) or None, asked at each call (a language switch gives another); `settings()` -> the settings as
    the window holds them (`placing_rules`, `covers_download`, the YouTube downloader's switch and tick);
    `youtube(urls, release)` hands Ukai's YouTube links to the window's thread (`youtube.run`), or None: no window to
    run them (the route says the downloader isn't here)."""
    from app import __version__, door
    from modules.ukai import subtitles, youtube as links

    def values():
        try:
            got = settings()
            return got if hasattr(got, "get") else {}
        except Exception:
            return {}

    def hello(_call):
        return {"app": "surasura", "version": __version__, "contract": CONTRACT, "door": door.VERSION,
                "languages": libraries(), "covers": values().get("covers_download") is True}

    def online_subtitle(call):
        try:
            sub = subtitles.subtitle(call.json())
        except subtitles.Bad as e:
            raise door.RouteError(str(e), "body", 400) from None
        if sub["language"] not in libraries():                  # U3: only a language the learner has a library for
            raise door.RouteError(NO_LIBRARY.format(name=NAMES[sub["language"]]), "refused", 409)
        held = values()
        if held.get("covers_download") is not True:             # U7: the show's artwork only behind covers' switch
            sub["cover"] = None
        rules = held.get("placing_rules")
        rules = {str(k): v for k, v in rules.items()} if hasattr(rules, "items") else {}
        with _ONE:
            try:
                added, item = subtitles.take_in(writer(), sub, rules)
            except subtitles.Busy as e:
                raise door.RouteError(str(e) or "Surasura is busy: try again later", "busy", 503) from None
        return {"added": bool(added), "item": item}

    return {"GET /v1/hello": hello, "POST /v1/online-subtitle": online_subtitle,
            "POST /v1/youtube": links.route(writer, values, youtube)}
