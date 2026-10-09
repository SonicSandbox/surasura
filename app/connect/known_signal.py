"""Known from Anki (P2.4 Part B row 2.4.15; Sonic, 2026-10-07 *known from Anki*: "Default to suspend, and give them the
option to select with dropdown (an 'and' logic so they could pick marked + and or something)"; "you can suspend with
one tap on Ankidroid"; 2026-10-08 P2.4-6 ✅: undo un-suspends).

A card you suspend in Anki says "I know this": at Surasura's next known-words sync its word becomes known.

- **The signal is a setting** (`known_from_anki`, a list; every term must hold — "and"): `suspended` (the default) ·
  `marked` · `flag:1` … `flag:7`; `[]` is off. Read in the decks the known-words sync already reads. A setting with a
  term this doesn't know is off (said once a read), never a wider signal (review B #21).
- **Never counted:** Surasura's own suspensions — Junban's "later" (`Surasura::later`) and Connect's shelf
  (`surasura::shelf`) — and Anki's leeches (`leech`). A Connect-made card **you** suspend counts like any (Anki's tag
  search ignores case).
- **Newly signalled since the last read → known**: appended to KnownWord.json as the sync appends (append-only, under
  its `known-words-<lang>` lock), each entry marked `knownBy: "anki-signal"`; recorded here per language (the word, its
  card, when) for undo.
- **The one-time offer**: the first read finds cards already signalled → none marked; they are kept as an offer
  (*Mark their words known?*), answered once (`accept_offer` / `decline_offer`; accepted, only the cards that still
  carry the signal). A changed signal (other terms, or off and on again) is a first read again: a new offer, never a
  flood of marks (review B #16, #20).
- **Undo per word** (`undo`): its cards un-suspended if still suspended (✅ P2.4-6), then the word taken out of
  KnownWord.json **only if this signal added it** (a word also known another way stays known), after a dated backup
  (`path_utils.backup_to_trash`).
- **The record** is read and written under the known-words lock (one writer across programs and threads); one that
  exists but can't be read stops the read and is never written over (review B #17, #19).
- **2.x:** only while Connect's preview is on (`connect_enabled`); off, no request and nothing written — byte-identical
  to 2.5. In 3.0 the setting alone decides.

The record lives in Connect's local data (`<local data>/connect/known-signal-<lang>.json`), never in User Files.
Standard library only; Anki through `app/anki_connect` (loopback).
"""
import contextlib
import datetime
import json
import os

KNOWN_BY = "anki-signal"
NEVER = ("-tag:Surasura::later", "-tag:surasura::shelf", "-tag:leech")
FLAGS = tuple(f"flag:{n}" for n in range(1, 8))
TERMS = ("suspended", "marked") + FLAGS


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def signal(settings):
    """The terms picked (a clean list in the setting's order), or [] when off — and [] with Connect's preview off
    (2.x: nothing of this runs)."""
    if not (settings or {}).get("connect_enabled"):
        return []
    value = (settings or {}).get("known_from_anki", ["suspended"])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        print("Known from Anki is off: known_from_anki isn't a list of terms.")
        return []
    terms = list(dict.fromkeys(str(v).strip().lower() for v in value))
    wrong = [t for t in terms if t not in TERMS]
    if wrong:           # "and": a term dropped would widen the signal (review B #21)
        print(f"Known from Anki is off: known_from_anki holds {', '.join(wrong)}, which it doesn't know.")
        return []
    return terms


def query(terms, decks):
    """The search for cards that carry the signal in `decks`, or None when there's none to search."""
    if not terms or not decks:
        return None
    from app import anki_connect
    parts = []
    for term in terms:
        if term == "suspended":
            parts.append("is:suspended")
        elif term == "marked":
            parts.append("tag:marked")
        else:
            parts.append(term)
    scope = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in dict.fromkeys(decks))
    return f"({scope}) " + " ".join(parts) + " " + " ".join(NEVER)


def record_path(language):
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", f"known-signal-{language}.json")


class Unreadable(RuntimeError):
    """The record exists but can't be read: nothing is written over it."""


def load(language):
    """The record, {} when there's none yet; raises `Unreadable` when it exists and can't be read (review B #17)."""
    try:
        with open(record_path(language), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise Unreadable(f"Known from Anki's record can't be read ({e}); it was left as it is.") from None
    if not isinstance(data, dict):
        raise Unreadable("Known from Anki's record isn't what it should be; it was left as it is.")
    return data


def _save(language, data):
    """Written whole through a unique temporary file, tried again while Windows holds the file (review B #19)."""
    from app import anki_sync
    path = record_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    anki_sync._atomic_write_json(path, data, indent=1)


@contextlib.contextmanager
def _held(language, verb, wait=None):
    """The known-words lock around a read-modify-write of the record (and KnownWord.json); raises when another
    program keeps it. Already held by this thread: nothing more to take."""
    from app import anki_sync
    held, refused = anki_sync.hold_known_words(language, verb, wait=wait)
    if refused is not None:
        raise RuntimeError(refused[0])
    try:
        yield
    finally:
        if held is not None:
            held.release()


def _words_of(url, card_ids, fields, language):
    """[(word, card id, note id)] for the cards: their notes' words, read as the known-words sync reads them — note by
    note, so a word on two notes keeps both its cards (review B #12)."""
    from app import anki_connect, anki_sync
    if not card_ids:
        return []
    info = anki_connect.cards_info(url, card_ids)
    by_note = {}
    for card in info:
        by_note.setdefault(card.get("note"), []).append(card.get("cardId"))
    notes = anki_connect.notes_info(url, [n for n in by_note if n is not None])
    result = anki_sync.SyncResult()
    out = []
    for note in notes:
        for term, note_id in anki_sync._terms_from_notes([note], fields, language, result):
            for card_id in by_note.get(note_id, ()):
                out.append((term, card_id, note_id))
    return out


def read(language, url, decks, fields, settings):
    """One read, beside the known-words sync -> {"marked": [words newly known], "offered": n, "skipped": why or
    None}. The first read, and the first after the signal changed, only records an offer."""
    terms = signal(settings)
    q = query(terms, decks)
    if q is None:
        with _held(language, "Known from Anki"):
            state = load(language)
            if state.get("terms"):          # off now: on again later is a first read (review B #20)
                state["terms"] = []
                _save(language, state)
        return {"marked": [], "offered": 0, "skipped": "off"}
    from app import anki_connect
    with _held(language, "Known from Anki"):
        state = load(language)
        ids = anki_connect.find_cards(url, q)
        seen = set(state.get("seen") or ())
        new = [c for c in ids if c not in seen]
        found = _words_of(url, new, fields, language)
        now = _now()
        out = {"marked": [], "offered": 0, "skipped": None}
        if not state.get("read") or state.get("terms") != terms:     # first, or a changed signal (#16)
            if found:
                state["offer"] = {"state": "pending", "query": q,
                                  "cards": [{"word": w, "card": c, "note": n} for w, c, n in found]}
            out["offered"] = len(found)
        elif found:
            out["marked"] = _mark(language, found, state, now, "signal")
        seen_now = sorted(set(ids))
        if found or not state.get("read") or state.get("terms") != terms or state.get("seen") != seen_now:
            state.update(read=now, seen=seen_now, terms=terms)
            _save(language, state)      # nothing new, nothing written (charter S19)
        return out


def _mark(language, found, state, now, why):
    """Append the words not yet known to KnownWord.json (append-only, the sync's lock) and record each -> words. A
    word already there by this signal's own entry (a record save that failed after it) is recorded as added, so undo
    still takes it out (review B #18)."""
    from app import anki_sync
    with _held(language, "Known from Anki"):
        data, words = anki_sync._read_known_file(language)
        known = anki_sync._known_keys(words or [])
        ours = {anki_sync._norm(w.get("dictForm", "")) for w in words or ()
                if isinstance(w, dict) and w.get("knownBy") == KNOWN_BY}
        added, entries = [], []
        for word, card, note in found:
            key = anki_sync._norm(word)
            fresh = key not in known
            if fresh:
                entry = anki_sync._entry(word, note, language, now)
                entry["knownBy"] = KNOWN_BY
                entries.append(entry)
                known.add(key)
            state.setdefault("marked", []).append({"word": word, "card": card, "note": note, "at": now,
                                                   "added": fresh or key in ours, "why": why, "shown": False,
                                                   "undone": None})
            if fresh:
                added.append(word)
        if entries:
            if data is None:
                data = anki_sync._fresh_file(entries)
            elif isinstance(data, list):
                data = data + entries
            else:
                data = dict(data)
                data["words"] = list(words) + entries
            anki_sync._atomic_write_json(anki_sync._known_path(language), data)
        return added


def accept_offer(language, url=None):
    """The one-time offer, accepted: the words of the cards signalled at the first read become known — only the cards
    that still carry the signal when you answer (asked of Anki with `url`; review B #14)."""
    from app import anki_connect
    with _held(language, "Known from Anki"):
        state = load(language)
        offer = state.get("offer") or {}
        if offer.get("state") != "pending":
            return []
        cards = offer.get("cards") or ()
        if url and offer.get("query") and cards:
            still = set(anki_connect.find_cards(url, offer["query"]))
            cards = [c for c in cards if c["card"] in still]
        found = [(c["word"], c["card"], c["note"]) for c in cards]
        added = _mark(language, found, state, _now(), "offer") if found else []
        offer["state"] = "accepted"
        state["offer"] = offer
        _save(language, state)
        return added


def decline_offer(language):
    with _held(language, "Known from Anki"):
        state = load(language)
        offer = state.get("offer") or {}
        if offer.get("state") == "pending":
            offer["state"] = "declined"
            state["offer"] = offer
            _save(language, state)


def unshown(language):
    """The words your suspensions marked known since the window last showed them (the summary's *You suspended N
    cards since …*) — never the offer's, which you answered yourself (review B #15)."""
    return [m for m in load(language).get("marked") or ()
            if not m.get("shown") and not m.get("undone") and m.get("why") != "offer"]


def mark_shown(language):
    """On the window's own thread: never waits for the lock (another program writing: shown again next time)."""
    try:
        with _held(language, "Known from Anki", wait=0):
            state = load(language)
            fresh = [m for m in state.get("marked") or () if not m.get("shown")]
            for m in fresh:
                m["shown"] = True
            if fresh:
                _save(language, state)
    except Exception as e:
        print(f"Known from Anki: not marked shown ({e})")


def undo(language, word, url):
    """Undo one word: its cards un-suspended first if still suspended (read under Anki's writer), then out of
    KnownWord.json only if this signal added it (a dated backup first) -> {"removed": bool, "unsuspended": [card ids]}.
    Anki closed or busy: raises with nothing changed; tried again after a later failure, the cards are back already
    (review B #13, #25)."""
    from app import anki_connect, anki_sync
    from app.path_utils import backup_to_trash
    with _held(language, "Known from Anki (undo)"):
        state = load(language)
        mine = [m for m in state.get("marked") or () if m.get("word") == word and not m.get("undone")]
        if not mine:
            return {"removed": False, "unsuspended": []}
        cards = [m["card"] for m in mine if m.get("card") is not None]
        back = []
        if cards:
            with anki_connect.writer("Known from Anki (undo)", wait=10.0):
                info = anki_connect.cards_info(url, cards)
                back = [c.get("cardId") for c in info if c.get("queue") == -1]      # still suspended
                if back:
                    anki_connect.invoke("unsuspend", url, cards=back)
        removed = False
        if any(m.get("added") for m in mine):
            data, words = anki_sync._read_known_file(language)
            key = anki_sync._norm(word)

            def ours(w):
                return isinstance(w, dict) and w.get("knownBy") == KNOWN_BY and anki_sync._norm(
                    w.get("dictForm", "")) == key
            keep = [w for w in (words or []) if not ours(w)]
            if words is not None and len(keep) != len(words):
                backup_to_trash(anki_sync._known_path(language))
                if isinstance(data, list):
                    data = keep
                else:
                    data = dict(data)
                    data["words"] = keep
                anki_sync._atomic_write_json(anki_sync._known_path(language), data)
                removed = True
        now = _now()
        for m in mine:
            m["undone"] = now
        _save(language, state)
        return {"removed": removed, "unsuspended": back}
