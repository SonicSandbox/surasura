"""Connect's and Swap's routes on the journey's door (journey v3 SPEC §3.3; the registry is `journey_door.ROUTES`, the
transport `app/door.py`). Two presses on the page, one maker: both ask Swap's `swap.make_card` with the line the
learner pressed (SPEC row 11: no second card maker), and Connect's next look makes the card as it makes every one.

- `swap/queue` {lang, word, line_id, item, line} — ⇄ on a word that has a card: a new card for it from this line (the simple
  Swap: a new card; one out, one in — once the new one is made, Swap suspends and tags the old one, and its Undo puts
  it back as it was: `swap.JOURNEY_TAKES_OLD`, the one place that turns, PROVISIONAL).
  The old card is the newest one Connect made for the word that may still be in Anki (`deleted._newer_cards`); a card
  of your own Connect didn't make is none (its line isn't known to Swap, so it isn't avoided or tagged).
- `card/make` {lang, word, line_id, item, line} — *Add now* on a word with no card: its card from this line. Pinned as every
  swap's card is (`tidy.asked_for` reads Swap's record), and it counts in the cap as any Connect card (D3).

A subtitle line the page gave no time (its video not found at the render, or *Play a line's own audio* off: the
page's own key, `p<hash>`) is found at the press in its one subtitle from the line's item and text (`_line_id`,
SWAP-TIME): Swap is never refused for want of a time the subtitle holds, whatever the audio switch says (it governs ▶
only). Each answer says whether the line's episode has its video on this computer (`video`): without it the ask is
kept all the same, Connect's job for it waits on *No video*, and Needs you's *Find video* asks where it is.

Both refuse in plain words, nothing recorded, when: Connect is off (no one would make it), the line has no time in
any file (a book's or a text's line, or the page's key with no item), the line isn't in its file now, it is the old card's own line, the word is Known or Ignored now (Swap's own rule), or (*Add now*) Connect has a
card for the word already. The library store busy with another save just now is told apart from a line gone (`busy`:
press again; `_line`). A second press for a word whose ask is still open answers that ask (`already`), never a
second card. Not queued on the page (SPEC §3.5: an action that needs the app), so `at` is not read.

And `clip/cut` {lang, line_id} — ▶ on a line the browser can't play: its clip, cut on the press and kept
(`app/connect/clips.py`, J-CLIP); {lang, line_ids, ahead: true} — the shown lines cut before they are pressed.

Inert until the journey v3 page ships (J-CUT): the door doesn't listen before then (`journey_door.ON`), so nothing
calls these. Runs on the door's thread: opens the ledger and the store there, never a widget. Qt-free.
"""
import logging
import os
import sqlite3

log = logging.getLogger("surasura-cli")

LANGS = ("ja", "zh")
WORD_MAX = 64                   # a word longer than this isn't one the page sends: refused, never written
LINE_MAX = 40                   # `<item>:<ms>` is far shorter: a longer id is no line (and never a 4300-digit int())
TEXT_MAX = 2000                 # a line's text the page sends with its own key: a longer one is no line it shows

OFF = "Cards made for you is off: turn it on in Connect, then press again."
NO_LINE = "Surasura can't make a card from that line (it has no time in its file)."
GONE = "Surasura can't find that line in its file now: the journey may be older than your library."
BUSY = "Surasura's library is busy just now: press again in a moment."
SAME = "That's the line your card already has: pick another one."
HAS_CARD = "This word has a card already: ⇄ gives it another sentence."
KNOWN = "「{}」 is known now: no card is made."
IGNORED = "「{}」 is on your Ignore list: no card is made."
NOT_READ = "Surasura couldn't read that."
NOT_SAVED = "Surasura couldn't keep that ask ({}). Nothing was made."


def swap_route(body, app):
    """`swap/queue` {lang, word, line_id, item, line} -> {queued: True, id, already, same, video}: ⇄, a carded word's
    card from the line pressed (Swap's `make_card`, by `BY_JOURNEY`); `video`: `_video_here`. `same` (FS-2): the learner's *Swap gives* asks for the same card
    with this sentence (`swap.in_place_on`, read at the press: the page's words; the kind itself is decided when the
    job is made, decision 10)."""
    from app import settings_manager
    from app.connect import swap
    got = _ask(body, journey=True)
    try:                                    # the ask is kept: words read after it never turn it into a failure
        same = swap.in_place_on(settings_manager.load_settings())
    except Exception:
        same = False
    return {"queued": True, "id": got["id"], "already": not got["new"], "same": same, "video": got.get("video")}


def card_route(body, app):
    """`card/make` {lang, word, line_id, item, line} -> {asked: True, id, already, video}: *Add now*, a card for a word
    with none from the line pressed (Swap's `make_card`, by `BY_ADD_NOW`)."""
    got = _ask(body, journey=False)
    return {"asked": True, "id": got["id"], "already": not got["new"], "video": got.get("video")}


def _ask(body, journey):
    from app import door, settings_manager
    from app.connect import runner, swap
    lang, word, line_id = body.get("lang"), body.get("word"), body.get("line_id")
    word = word.strip() if isinstance(word, str) else ""
    if lang not in LANGS or not word or len(word) > WORD_MAX:
        raise door.RouteError(NOT_READ, "refused")
    if not isinstance(line_id, str) or len(line_id) > LINE_MAX:
        raise door.RouteError(NO_LINE, "refused")
    timed = swap._parse_line_id(line_id) is not None
    item, text = body.get("item"), body.get("line")
    if not timed and (type(item) is not int or item < 0 or not isinstance(text, str) or not text.strip()
                      or len(text) > TEXT_MAX):
        raise door.RouteError(NO_LINE, "refused")     # the page's own key with no item: a line no file times
    settings = settings_manager.load_settings()
    if not settings_manager.connect_on(settings):
        raise door.RouteError(OFF, "off")
    steps = runner.Steps(settings)
    if not timed:
        line_id = _line_id(steps, lang, item, text, settings)
    picked = _line(steps, lang, line_id, word)
    if picked is None:
        raise door.RouteError(GONE, "gone")
    got = _asked(lang, word, line_id, picked, journey)
    if got["state"] == swap.DROPPED:
        raise door.RouteError((IGNORED if got["why"] == "ignored" else KNOWN).format(word), got["why"] or "refused")
    got["video"] = _video_here(steps, lang, picked[0])     # (the ledger closed: the video look may list folders)
    return got


def _asked(lang, word, line_id, picked, journey):
    """The ask recorded through Swap's one maker -> `make_card`'s answer, or the word's ask still open (`new` False)."""
    from app import door
    from app.connect import deleted, ledger as ledger_mod, sentences, swap
    try:
        with ledger_mod.Ledger() as ledger:
            swap.ensure(ledger)
            open_ = swap._rows(ledger, "language = ? AND word = ? AND state IN (?, ?, ?)",
                               (lang, word, swap.ASKED, swap.QUEUED, swap.WAITS))
            if open_:
                return {"id": open_[-1]["id"], "state": open_[-1]["state"], "new": False}
            notes = deleted._newer_cards(ledger.conn, lang, {word}).get(word) or set()
            old_note = max(notes) if notes else None
            if not journey and old_note is not None:
                raise door.RouteError(HAS_CARD, "refused")
            if old_note is not None:
                lines = swap._old_lines(ledger, {"old_note": old_note})
                if lines and sentences.same_line(picked[1], lines):
                    raise door.RouteError(SAME, "refused")
            return swap.make_card(lang, word, old_note=old_note, line_id=line_id, ledger=ledger,
                                  by=swap.BY_JOURNEY if journey else swap.BY_ADD_NOW)
    except door.RouteError:
        raise
    except (ledger_mod.TooNew, OSError, sqlite3.Error) as e:
        raise door.RouteError(NOT_SAVED.format(e), "refused")


def _line_id(steps, lang, item, text, settings):
    """A line the page keyed itself (no time on the page) -> its `<item>:<start ms>` (`swap.line_id`), found at the
    press in that item's one subtitle (SWAP-TIME, option A): its time by the render's own reader,
    `cues.timeline(...).line` — the one `AnchorFinder.line` asks for the page's ▶, the same sentence in the same
    script — so it names the line a timed page would have. One file read, nothing added to the render. Refused: an
    item whose file is no subtitle (a book's, a text's line: NO_LINE, it has no time anywhere); the item or its file
    gone, or the line no longer in it (GONE); the store busy just now (BUSY, `_watch`)."""
    from app import cues, door
    from app.connect import swap
    from app.zh_script import effective
    read, busy = steps.subtitle, _watch(steps)
    try:
        subtitle = steps.subtitle(lang, {"id": 0, "item_id": item})
    except Exception:
        subtitle = None
    finally:
        steps.subtitle = read
    if any(busy):
        raise door.RouteError(BUSY, "busy")
    if subtitle and not str(subtitle).lower().endswith(cues.SUBTITLES):
        raise door.RouteError(NO_LINE, "refused")
    found = None
    if subtitle and os.path.isfile(subtitle):
        try:
            found = cues.timeline(subtitle, lang, effective(lang, settings.get("zh_script"))).line(text)
        except Exception:
            log.info("Door: a line pressed couldn't be read in its subtitle", exc_info=True)
    if found is None:
        raise door.RouteError(GONE, "gone")
    return swap.line_id(item, cues.seconds(found[0]))


def _video_here(steps, lang, item):
    """Is the line's episode's video on this computer, as Connect's pick looks for it (`Steps.video`; an online title's
    is fetched when its card is made, `runner._online`) -> True / False; None when it couldn't be looked at now (the
    page then says nothing of it). Without it the ask waits on *No video*, and Needs you asks where it is."""
    from app.connect import ledger as ledger_mod, runner
    job = {"id": 0, "item_id": item, "kind": ledger_mod.SWAP}
    try:
        return bool(steps.video(lang, job) or runner._online(steps, lang, job))
    except Exception:
        log.info("Door: the line's video couldn't be looked for", exc_info=True)
        return None


def _line(steps, lang, line_id, word=None):
    """The line pressed -> (item id, its text), None when it is gone — or the door's *busy* (as the other routes say
    it: `kind` "busy") when the library store couldn't be read just now. `word`: the word pressed (two lines that
    start together are told apart by it: `swap.line_cue`). Swap's `_resolve_line_id` reads every failure
    as a line gone, so its one store read (`steps.subtitle`) is watched here: a store busy past its own wait (Connect's
    `Wait(LIBRARY_BUSY)` at the open, SQLite's "locked" in the read) is no line gone (J-FIX)."""
    from app import door
    from app.connect import swap
    busy = _watch(steps)
    picked = swap._resolve_line_id(steps, lang, line_id, word)
    if any(busy):
        raise door.RouteError(BUSY, "busy")
    return picked


def _watch(steps):
    """`steps.subtitle` watched for a store busy just now (`_line`'s rule) -> the list it appends to (True: busy) —
    the line's one store read, Swap's and the clip's alike."""
    from app.connect import runner
    read, busy = steps.subtitle, []

    def subtitle(language, job):
        try:
            return read(language, job)
        except runner.Wait as e:
            busy.append(e.reason == runner.LIBRARY_BUSY)
            raise
        except sqlite3.OperationalError as e:
            busy.append("locked" in str(e).lower() or "busy" in str(e).lower())
            raise
    steps.subtitle = subtitle
    return busy


def clip_route(body, app):
    """`clip/cut` {lang, line_id} -> {url}: ▶ on a line the browser can't play (an .mkv) — its clip cut now, or the one
    kept (`clips.cut`), served by the door's one GET (`door.serve_file`: the URL's path, as SPEC §3.3 names it).
    {lang, line_ids, ahead: true} -> {ahead: n}: the page idle on a word asks its shown lines of the open episode cut
    before they are pressed (`clips.ahead`; answered at once — the one ask that doesn't stop a cut ahead,
    `journey_door._route`). Refused in the clip's own words (Connect off, Anki Miner absent or too old, no time in its
    file, gone, the video not on this PC, Anki Miner couldn't); the store busy is `busy`, as above."""
    from app import door, settings_manager
    from app.connect import clips, runner
    lang = body.get("lang")
    if lang not in LANGS:
        raise door.RouteError(NOT_READ, "refused")
    if body.get("ahead"):
        ids = body.get("line_ids")
        ids = [i for i in ids if isinstance(i, str) and len(i) <= LINE_MAX] if isinstance(ids, list) else []
        return {"ahead": clips.ahead(lang, ids)}
    line_id = body.get("line_id")
    if not isinstance(line_id, str) or len(line_id) > LINE_MAX:
        raise door.RouteError(clips.NO_LINE, "refused")
    settings = settings_manager.load_settings()
    steps = runner.Steps(settings)
    busy = _watch(steps)
    try:
        path = clips.cut(lang, line_id, settings=settings, steps=steps)
    except clips.Refused as e:
        if any(busy):
            raise door.RouteError(BUSY, "busy") from None
        raise door.RouteError(e.message, e.kind) from None
    url = door.serve_file(path, clips.kind(path))
    if url is None:
        raise door.RouteError("Surasura is closing.", "closed")
    return {"url": url[url.index(door.CLIP_PATH):]}
