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
card for the word already. A second press for a word whose ask is still open answers that ask (`already`), never a
second card. Not queued on the page (SPEC §3.5: an action that needs the app), so `at` is not read.

Inert until the journey v3 page ships (J-CUT): the door doesn't listen before then (`journey_door.ON`), so nothing
calls these. Runs on the door's thread: opens the ledger and the store there, never a widget. Qt-free.
"""
import logging
import sqlite3

log = logging.getLogger("surasura-cli")

LANGS = ("ja", "zh")
WORD_MAX = 64                   # a word longer than this isn't one the page sends: refused, never written

OFF = "Cards made for you is off: turn it on in Connect, then press again."
NO_LINE = "Surasura can't make a card from that line (it has no time in its file)."
GONE = "Surasura can't find that line in its file now: the journey may be older than your library."
SAME = "That's the line your card already has: pick another one."
HAS_CARD = "This word has a card already: ⇄ gives it another sentence."
KNOWN = "「{}」 is known now: no card is made."
IGNORED = "「{}」 is on your Ignore list: no card is made."
NOT_READ = "Surasura couldn't read that."
NOT_SAVED = "Surasura couldn't keep that ask ({}). Nothing was made."


def swap_route(body, app):
    """`swap/queue` {lang, word, line_id} -> {queued: True, id, already}: ⇄, a new card for a carded word from the
    line pressed (Swap's `make_card`, by `BY_JOURNEY`)."""
    got = _ask(body, journey=True)
    return {"queued": True, "id": got["id"], "already": not got["new"]}


def card_route(body, app):
    """`card/make` {lang, word, line_id} -> {asked: True, id, already}: *Add now*, a card for a word with none from
    the line pressed (Swap's `make_card`, by `BY_ADD_NOW`)."""
    got = _ask(body, journey=False)
    return {"asked": True, "id": got["id"], "already": not got["new"]}


def _ask(body, journey):
    from app import door, settings_manager
    from app.connect import deleted, ledger as ledger_mod, runner, sentences, swap
    lang, word, line_id = body.get("lang"), body.get("word"), body.get("line_id")
    if lang not in LANGS or not isinstance(word, str) or not word.strip() or len(word) > WORD_MAX:
        raise door.RouteError(NOT_READ, "refused")
    word = word.strip()
    if not isinstance(line_id, str) or swap._parse_line_id(line_id) is None:
        raise door.RouteError(NO_LINE, "refused")
    settings = settings_manager.load_settings()
    if not settings_manager.connect_on(settings):
        raise door.RouteError(OFF, "off")
    picked = swap._resolve_line_id(runner.Steps(settings), lang, line_id)
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
