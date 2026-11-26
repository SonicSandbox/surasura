"""Connect's and Swap's routes on the journey's door (journey v3 SPEC §3.3; the registry is `journey_door.ROUTES`, the
transport `app/door.py`). Two presses on the page, one maker: both ask Swap's `swap.make_card` with the line the
learner pressed (SPEC row 11: no second card maker), and Connect's next look makes the card as it makes every one.

- `swap/queue` {lang, word, line_id} — ⇄ on a word that has a card: a new card for it from this line (the simple
  Swap: a new card; one out, one in — once the new one is made, Swap suspends and tags the old one, and its Undo puts
  it back as it was: `swap.JOURNEY_TAKES_OLD`, the one place that turns, PROVISIONAL).
  The old card is the newest one Connect made for the word that may still be in Anki (`deleted._newer_cards`); a card
  of your own Connect didn't make is none (its line isn't known to Swap, so it isn't avoided or tagged).
- `card/make` {lang, word, line_id} — *Add now* on a word with no card: its card from this line. Pinned as every
  swap's card is (`tidy.asked_for` reads Swap's record), and it counts in the cap as any Connect card (D3).

Both refuse in plain words, nothing recorded, when: Connect is off (no one would make it), the line isn't one a card
can be cut from (no item or start time: a book's line, a line the page names by a hash), the line isn't in its file
now, it is the old card's own line, the word is Known or Ignored now (Swap's own rule), or (*Add now*) Connect has a
card for the word already. The library store busy with another save just now is told apart from a line gone (`busy`:
press again; `_line`). A second press for a word whose ask is still open answers that ask (`already`), never a
second card. Not queued on the page (SPEC §3.5: an action that needs the app), so `at` is not read.

And `clip/cut` {lang, line_id} — ▶ on a line the browser can't play: its clip, cut on the press and kept
(`app/connect/clips.py`, J-CLIP); {lang, line_ids, ahead: true} — the shown lines cut before they are pressed.

Inert until the journey v3 page ships (J-CUT): the door doesn't listen before then (`journey_door.ON`), so nothing
calls these. Runs on the door's thread: opens the ledger and the store there, never a widget. Qt-free.
"""
import logging
import sqlite3

log = logging.getLogger("surasura-cli")

LANGS = ("ja", "zh")
WORD_MAX = 64                   # a word longer than this isn't one the page sends: refused, never written
LINE_MAX = 40                   # `<item>:<ms>` is far shorter: a longer id is no line (and never a 4300-digit int())

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
    """`swap/queue` {lang, word, line_id} -> {queued: True, id, already, same}: ⇄, a carded word's card from the line
    pressed (Swap's `make_card`, by `BY_JOURNEY`). `same` (FS-2): the learner's *Swap gives* asks for the same card
    with this sentence (`swap.in_place_on`, read at the press: the page's words; the kind itself is decided when the
    job is made, decision 10)."""
    from app import settings_manager
    from app.connect import swap
    got = _ask(body, journey=True)
    try:                                    # the ask is kept: words read after it never turn it into a failure
        same = swap.in_place_on(settings_manager.load_settings())
    except Exception:
        same = False
    return {"queued": True, "id": got["id"], "already": not got["new"], "same": same}


def card_route(body, app):
    """`card/make` {lang, word, line_id} -> {asked: True, id, already}: *Add now*, a card for a word with none from
    the line pressed (Swap's `make_card`, by `BY_ADD_NOW`)."""
    got = _ask(body, journey=False)
    return {"asked": True, "id": got["id"], "already": not got["new"]}


def _ask(body, journey):
    from app import door, settings_manager
    from app.connect import deleted, ledger as ledger_mod, runner, sentences, swap
    lang, word, line_id = body.get("lang"), body.get("word"), body.get("line_id")
    word = word.strip() if isinstance(word, str) else ""
    if lang not in LANGS or not word or len(word) > WORD_MAX:
        raise door.RouteError(NOT_READ, "refused")
    if not isinstance(line_id, str) or len(line_id) > LINE_MAX or swap._parse_line_id(line_id) is None:
        raise door.RouteError(NO_LINE, "refused")
    settings = settings_manager.load_settings()
    if not settings_manager.connect_on(settings):
        raise door.RouteError(OFF, "off")
    picked = _line(runner.Steps(settings), lang, line_id, word)
    if picked is None:
        raise door.RouteError(GONE, "gone")
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
            got = swap.make_card(lang, word, old_note=old_note, line_id=line_id, ledger=ledger,
                                 by=swap.BY_JOURNEY if journey else swap.BY_ADD_NOW)
    except door.RouteError:
        raise
    except (ledger_mod.TooNew, OSError, sqlite3.Error) as e:
        raise door.RouteError(NOT_SAVED.format(e), "refused")
    if got["state"] == swap.DROPPED:
        raise door.RouteError((IGNORED if got["why"] == "ignored" else KNOWN).format(word), got["why"] or "refused")
    return got


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
