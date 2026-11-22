"""One deck (Michi-DK, a Send report, 2026-11-18): the cards Connect made outside the deck Surasura shows.

Since Michi-DK a run mines into the deck Surasura shows for new cards, the one 順 keeps in order (`fields.for_run`).
The cards Connect made before went where Anki Miner's own settings said — another deck, which 順 never orders. This
finds them and, on the learner's press, moves them (lean, PROVISIONAL):

- `strays(settings, language)` (read-only, a worker): this language's cards Connect made (the store's `made_words`, so
  never another language's, nor a card the learner mined by hand) that are in another deck than `fields.surasura_deck`
  — never one in a filtered deck (a Custom Study session: Anki puts it back itself), nor one you moved out of its home
  (Kyou-SH4, PROVISIONAL: `_find`; the move moves the same cards it counts). Kept `KEEP_S` a deck, so
  *Needs you*'s refreshes don't ask Anki each time (a move or its Undo asks again at once).
- `move(settings, language, deck, …)`: *Move them to <deck>* — under the Anki-writing lock, never while you review:
  read again, a snapshot of each card's deck written first (Connect's folder, `deck-moves/`), `changeDeck`, read
  back. A card keeps its reviews and its due; only its deck changes. Anki stopping mid-way still offers the Undo.
- `move_back(settings, snapshot_id, …)`: its Undo — each card still in Surasura's deck back to the deck it came from,
  while Anki has that deck (one deleted since is never made again: its cards stay).
- Kyou-SH4: a move is Surasura's, never the learner's — each moved note's home (Connect's ledger, `homes`: the deck
  Surasura last put it in, where Tidy tells your move from its own) is `deck` after it; the snapshot keeps the homes
  before, and the Undo puts them back for the cards it moves back. A record that can't be read or written is logged,
  never a reason to stop: the cards stay in the deck Surasura shows, home by itself. (The homes `_find` reads to
  leave out the cards you filed are another matter: unreadable, no card is shown and nothing moves.)

`getDecks` names each card's deck without rendering it (`cardsInfo` would render every card's two sides).
"""
import json
import logging
import os
import threading
import time

VERB = "Move Surasura's cards"          # the Anki-writing lock's holder, as the waiting line names it
KEEP_S = 60                             # `strays` asks Anki again after this (a move or its Undo: at once)
CHUNK = 500                             # cards (or notes) one request names at a time
FOLDER = "deck-moves"

_KEPT = {}                              # (language, deck) -> (at, answer)
_KEEPING = threading.Lock()
log = logging.getLogger("surasura-cli")


def _term(deck):
    """`deck` as a search term names it: quoted, and Anki's wildcards `_` and `*` read as themselves (`tag_query`'s)."""
    from app import anki_connect
    return 'deck:"' + anki_connect.escape_query(deck).replace("_", "\\_").replace("*", "\\*") + '"'


def _ids_query(ids, deck):
    return f'nid:{",".join(str(int(i)) for i in ids)} -{_term(deck)} -deck:filtered'


def _made(language):
    from app.connect import library
    return sorted(int(n) for n in library.made_notes_of(language))


def _decks_of(url, cards):
    """{deck: [card ids]} for `cards` (`getDecks`)."""
    from app import anki_connect
    out = {}
    for start in range(0, len(cards), CHUNK):
        got = anki_connect.invoke("getDecks", url, cards=cards[start:start + CHUNK])
        for deck, ids in (got if isinstance(got, dict) else {}).items():
            out.setdefault(str(deck), []).extend(int(i) for i in ids or ())
    return out


def _find(url, notes, deck):
    """{deck: [card ids]} of `notes`' cards outside `deck` (and its subdecks), none in a filtered deck — and none you
    moved (Kyou-SH4): a note with a home on record (`homes`) counts only its cards still in that home (Surasura put
    them there); one elsewhere, a subdeck of it included, is yours. No record (made before 2026-11-18, in Anki
    Miner's own deck): counted, as before. `strays` counts and `move` moves the same cards. Homes that can't be read
    raise (Kyou-SH4's lens): no card shown, nothing moved — never a card you filed counted or moved on a guess."""
    from app import anki_connect
    from app.connect.ledger import homes_of
    homes = homes_of(notes)
    groups = {}
    for n in notes:
        home = homes.get(int(n))
        groups.setdefault(str(home).casefold() if home else None, []).append(n)
    out = {}
    for home, ids in groups.items():
        cards = []
        for start in range(0, len(ids), CHUNK):
            cards += anki_connect.find_cards(url, _ids_query(ids[start:start + CHUNK], deck))
        for d, got in (_decks_of(url, sorted(set(cards))) if cards else {}).items():
            if home is None or d.casefold() == home:
                out.setdefault(d, []).extend(got)
    return out


def strays(settings, language):
    """-> {"deck": Surasura's deck, "from": {deck: card count}, "cards": n} while some of this language's Connect cards
    are outside it, else None (no deck shown, nothing made, Anki not answering, all in place; never Anki under
    `SURASURA_NO_ANKI_SYNC`: the test suites, a developer's run). Kept `KEEP_S`, whatever it was. Never raises."""
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return None
    try:
        from app import anki_connect
        from app.connect import fields
        deck = fields.surasura_deck(settings, language)
        if not deck:
            return None
        with _KEEPING:
            kept = _KEPT.get((language, deck))
        if kept is not None and time.monotonic() - kept[0] < KEEP_S:
            return kept[1]
        notes = _made(language)
        url = anki_connect.address(settings)
        found = _find(url, notes, deck) if notes and anki_connect.probe(url, timeout=2).get("ok") else {}
        answer = ({"deck": deck, "from": {d: len(c) for d, c in found.items()},
                   "cards": sum(len(c) for c in found.values())} if found else None)
        with _KEEPING:
            _KEPT[(language, deck)] = (time.monotonic(), answer)
        return answer
    except Exception:
        return None


def forget():
    """What `strays` kept is asked again (a move, its Undo)."""
    with _KEEPING:
        _KEPT.clear()


def _folder():
    from app.connect import ledger
    return os.path.join(ledger.folder(), FOLDER)


def _write(path, data):
    temp = f"{path}.{os.getpid()}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def _held(settings, wait, cancel, on_wait):
    """-> (url, the held lock, None) or (url, None, why not)."""
    from app import anki_connect
    url = anki_connect.address(settings)
    held, problem = anki_connect.take_writer(VERB, url, wait, cancel, on_wait)
    if held is not None and anki_connect.reviewing(url, cancel):
        held.release()
        return url, None, anki_connect.REVIEWING
    return url, held, problem


def _change(url, cards, deck):
    from app import anki_connect
    for start in range(0, len(cards), CHUNK):
        anki_connect.invoke("changeDeck", url, cards=cards[start:start + CHUNK], deck=deck)


def _notes(url, cards):
    """The notes of `cards` (`cardsToNotes`), sorted."""
    from app import anki_connect
    out = set()
    for start in range(0, len(cards), CHUNK):
        out |= {int(n) for n in anki_connect.invoke("cardsToNotes", url, cards=cards[start:start + CHUNK]) or ()}
    return sorted(out)


def _homes_before(url, cards):
    """{note id (str): its home before the move, or None} for the snapshot; {} when it can't be read (the Undo then
    leaves each record as the move wrote it: Tidy keeps those cards, never takes one)."""
    try:
        from app.connect.ledger import Ledger, path
        notes = _notes(url, cards)
        if not os.path.exists(path()):
            return {str(n): None for n in notes}
        with Ledger() as book:
            had = book.homes(notes)
        return {str(n): had.get(n) for n in notes}
    except Exception:
        log.warning("Couldn't read the moved cards' homes", exc_info=True)
        return {}


def _set_homes(url, cards, home):
    """`cards`' notes recorded at `home` — a deck, or {note id (str): deck or None} (the Undo's). Never raises."""
    try:
        from app.connect.ledger import Ledger, path
        if not cards or not os.path.exists(path()):
            return
        notes = _notes(url, cards)
        by_deck = {}
        for n in notes:
            if isinstance(home, dict):
                if str(n) in home:
                    by_deck.setdefault(home[str(n)], []).append(n)
            else:
                by_deck.setdefault(home, []).append(n)
        with Ledger() as book:
            for deck, ids in by_deck.items():
                book.set_homes(ids, deck)
    except Exception:
        log.warning("Couldn't record the moved cards' homes", exc_info=True)


def move(settings, language, deck=None, wait=0.0, cancel=None, on_wait=None):
    """*Move them to <deck>* -> {"ok", "say", "moved", "deck", "id"} (`id`: the snapshot its Undo names, whenever
    anything may have moved: a move Anki stopped answering in the middle of is undone the same way). `deck`: the deck
    the learner's button named — Surasura's deck changed since, nothing is moved. Never raises."""
    try:
        from app.connect import fields
        ours = fields.surasura_deck(settings, language)
        if not ours:
            return {"ok": False, "say": NO_DECK}
        if deck is not None and deck != ours:
            return {"ok": False, "say": DECK_CHANGED.format(deck=ours)}
        url, held, problem = _held(settings, wait, cancel, on_wait)
    except Exception as e:
        return {"ok": False, "say": f"{NOT_MOVED} {e}"}
    if held is None:
        return {"ok": False, "say": problem}
    snapshot = None
    try:
        with held:
            found = _find(url, _made(language), ours)
            cards = sorted(c for ids in found.values() for c in ids)
            if not cards:
                return {"ok": True, "say": NONE_LEFT.format(deck=ours), "moved": 0, "deck": ours, "id": None}
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.time_ns() % 10 ** 9}"
            _write(os.path.join(_folder(), f"{name}.json"),
                   {"language": language, "deck": ours, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": found,
                    "homes": _homes_before(url, cards)})
            snapshot = name                 # from here on, whatever happens, its Undo is offered
            _change(url, cards, ours)
            there = sorted(_decks_of(url, cards).get(ours) or ())
            moved = len(there)
            _set_homes(url, there, ours)    # Surasura's move: their home is its deck now (Tidy's, never yours)
        if moved != len(cards):
            say = SOME_MOVED.format(n=moved, k=len(cards), deck=ours)
        else:
            say = MOVED_ONE.format(deck=ours) if moved == 1 else MOVED.format(n=moved, deck=ours)
        return {"ok": moved > 0, "say": say, "moved": moved, "deck": ours, "id": snapshot}
    except Exception as e:
        if snapshot is None:            # nothing sent to Anki yet (the read, the snapshot's write)
            return {"ok": False, "say": f"{NOT_MOVED} {e}"}
        return {"ok": False, "say": MAYBE_MOVED.format(deck=ours, why=e), "moved": None, "deck": ours,
                "id": snapshot}
    finally:
        forget()


def move_back(settings, snapshot, wait=0.0, cancel=None, on_wait=None):
    """The move's Undo: each card the snapshot names, while it is still in the deck it was moved to, back to the deck
    it came from — while Anki still has that deck (one deleted or renamed since is never made again) -> {"ok", "say",
    "back"}. Never raises."""
    path = os.path.join(_folder(), f"{snapshot}.json")
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        deck, came = str(record["deck"]), {str(d): [int(c) for c in ids] for d, ids in record["from"].items()}
    except Exception:
        return {"ok": False, "say": UNDO_GONE}
    try:
        url, held, problem = _held(settings, wait, cancel, on_wait)
    except Exception as e:
        return {"ok": False, "say": f"{NOT_UNDONE} {e}"}
    if held is None:
        return {"ok": False, "say": problem}
    back, gone, went = 0, 0, []
    try:
        from app import anki_connect
        with held:
            here = set(_decks_of(url, sorted(c for ids in came.values() for c in ids)).get(deck) or ())
            have = set(anki_connect.deck_names(url))
            try:
                for home, ids in came.items():
                    still = [c for c in ids if c in here]
                    if home not in have:
                        gone += len(still)
                        continue
                    for start in range(0, len(still), CHUNK):     # counted a chunk at a time (PART_UNDONE)
                        part = still[start:start + CHUNK]
                        _change(url, part, home)
                        back += len(part)
                        went += part
            finally:                    # the cards that went back: their homes as they were before the move
                if went:                # (a snapshot without them: no record, as before homes — Tidy keeps them)
                    _set_homes(url, went, record.get("homes") or None)
    except Exception as e:
        return {"ok": False, "say": PART_UNDONE.format(n=back, why=e) if back else f"{NOT_UNDONE} {e}", "back": back}
    finally:
        forget()
    try:
        _write(path, dict(record, undone=time.strftime("%Y-%m-%dT%H:%M:%S")))
    except OSError:                     # the cards are back: only the record's note of it is missing
        pass
    if not back:
        return {"ok": False, "say": HOME_GONE.format(deck=deck) if gone else NOTHING_BACK, "back": 0}
    say = UNDONE_ONE if back == 1 else UNDONE.format(n=back)
    return {"ok": True, "say": f"{say} · {KEPT_HERE.format(n=gone, deck=deck)}" if gone else say, "back": back}


# The words (PROVISIONAL, Michi-DK)
NO_DECK = "Surasura shows no deck for new cards: choose one in Settings › Card order. Nothing was moved."
NOT_MOVED = "Nothing was moved:"
NONE_LEFT = "Every card Surasura made is in “{deck}” already."
MOVED = "Moved {n:,} cards to “{deck}”"
MOVED_ONE = "Moved 1 card to “{deck}”"
SOME_MOVED = "Moved {n:,} of {k:,} cards to “{deck}”: look at the rest in Anki"
UNDO_GONE = "This move can't be undone any more: its record is gone."
NOT_UNDONE = "Nothing was put back:"
UNDONE = "Put {n:,} cards back where they were"
UNDONE_ONE = "Put 1 card back where it was"
DECK_CHANGED = "Surasura's deck for new cards is “{deck}” now: look at Needs you again. Nothing was moved."
MAYBE_MOVED = ("Anki stopped answering while the cards went to “{deck}” ({why}): look in Anki. Undo puts back what "
               "moved.")
PART_UNDONE = "Put {n:,} cards back, then Anki stopped answering ({why}): the rest are still in their new deck."
NOTHING_BACK = "Nothing to put back: those cards were moved again since."
HOME_GONE = "Nothing was put back: the decks they came from are gone from Anki, so they stay in “{deck}”."
KEPT_HERE = "{n:,} stay in “{deck}”: the deck they came from is gone"
