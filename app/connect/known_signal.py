"""Known from Anki (P2.4 Part B row 2.4.15; Sonic, 2026-10-07 *known from Anki*: "Default to suspend, and give them the
option to select with dropdown (an 'and' logic so they could pick marked + and or something)"; "you can suspend with
one tap on Ankidroid"; 2026-10-08 P2.4-6 ✅: undo un-suspends).

A card you suspend in Anki says "I know this": at Surasura's next known-words sync its word becomes known.

- **The signal is a setting** (`known_from_anki`, a list; every term must hold — "and"): `suspended` (the default) ·
  `marked` · `flag:1` … `flag:7`; `[]` is off. Read in the decks the known-words sync already reads.
- **Never counted:** Surasura's own suspensions — Junban's "later" (`Surasura::later`) and Connect's shelf
  (`surasura::shelf`) — and Anki's leeches (`leech`). A Connect-made card **you** suspend counts like any (Anki's tag
  search ignores case).
- **Newly signalled since the last read → known**: appended to KnownWord.json as the sync appends (append-only, under
  its `known-words-<lang>` lock), each entry marked `knownBy: "anki-signal"`; recorded here per language (the word, its
  card, when) for undo.
- **The one-time offer**: the first read finds cards already signalled → none marked; they are kept as an offer
  (*Mark their words known?*), answered once (`accept_offer` / `decline_offer`).
- **Undo per word** (`undo`): the word taken out of KnownWord.json **only if this signal added it** (a word also
  known another way stays known), after a dated backup (`path_utils.backup_to_trash`); and its card un-suspended if
  it is still suspended (✅ P2.4-6).
- **2.x:** only while Connect's preview is on (`connect_enabled`); off, no request and nothing written — byte-identical
  to 2.5. In 3.0 the setting alone decides.

The record lives in Connect's local data (`<local data>/connect/known-signal-<lang>.json`), never in User Files.
Standard library only; Anki through `app/anki_connect` (loopback).
"""
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
        return []
    return [t for t in dict.fromkeys(str(v).strip().lower() for v in value) if t in TERMS]


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


def load(language):
    try:
        with open(record_path(language), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(language, data):
    path = record_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _words_of(url, card_ids, fields, language):
    """[(word, card id, note id)] for the cards: their notes' words, read as the known-words sync reads them."""
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
    for term, note_id in anki_sync._terms_from_notes(notes, fields, language, result):
        for card_id in by_note.get(note_id, ()):
            out.append((term, card_id, note_id))
    return out


def read(language, url, decks, fields, settings):
    """One read, beside the known-words sync -> {"marked": [words newly known], "offered": n, "skipped": why or
    None}. The first read only records an offer."""
    terms = signal(settings)
    q = query(terms, decks)
    if q is None:
        return {"marked": [], "offered": 0, "skipped": "off"}
    from app import anki_connect
    ids = anki_connect.find_cards(url, q)
    state = load(language)
    seen = set(state.get("seen") or ())
    new = [c for c in ids if c not in seen]
    found = _words_of(url, new, fields, language)
    now = _now()
    out = {"marked": [], "offered": 0, "skipped": None}
    if not state.get("read"):
        state["offer"] = {"state": "pending", "cards": [{"word": w, "card": c, "note": n} for w, c, n in found]}
        out["offered"] = len(found)
    elif found:
        out["marked"] = _mark(language, found, state, now, "signal")
    state.update(read=now, seen=sorted(set(ids)), terms=terms)
    _save(language, state)
    return out


def _mark(language, found, state, now, why):
    """Append the words not yet known to KnownWord.json (append-only, the sync's lock) and record each -> words."""
    from app import anki_sync
    held, refused = anki_sync.hold_known_words(language, "Known from Anki")
    if refused is not None:
        raise RuntimeError(refused[0])
    try:
        data, words = anki_sync._read_known_file(language)
        known = anki_sync._known_keys(words or [])
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
                                                   "added": fresh, "why": why, "shown": False, "undone": None})
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
    finally:
        if held is not None:
            held.release()


def accept_offer(language):
    """The one-time offer, accepted: the words of the cards already signalled at the first read become known."""
    state = load(language)
    offer = state.get("offer") or {}
    if offer.get("state") != "pending":
        return []
    found = [(c["word"], c["card"], c["note"]) for c in offer.get("cards") or ()]
    added = _mark(language, found, state, _now(), "offer") if found else []
    offer["state"] = "accepted"
    state["offer"] = offer
    _save(language, state)
    return added


def decline_offer(language):
    state = load(language)
    offer = state.get("offer") or {}
    if offer.get("state") == "pending":
        offer["state"] = "declined"
        state["offer"] = offer
        _save(language, state)


def unshown(language):
    """The words marked known since the window last showed them (the summary's *You suspended N cards since …*)."""
    return [m for m in load(language).get("marked") or () if not m.get("shown") and not m.get("undone")]


def mark_shown(language):
    state = load(language)
    for m in state.get("marked") or ():
        m["shown"] = True
    _save(language, state)


def undo(language, word, url):
    """Undo one word: out of KnownWord.json only if this signal added it (a dated backup first), its card
    un-suspended if still suspended -> {"removed": bool, "unsuspended": [card ids]}."""
    from app import anki_connect, anki_sync
    from app.path_utils import backup_to_trash
    state = load(language)
    mine = [m for m in state.get("marked") or () if m.get("word") == word and not m.get("undone")]
    if not mine:
        return {"removed": False, "unsuspended": []}
    removed = False
    if any(m.get("added") for m in mine):
        held, refused = anki_sync.hold_known_words(language, "Known from Anki (undo)")
        if refused is not None:
            raise RuntimeError(refused[0])
        try:
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
        finally:
            if held is not None:
                held.release()
    cards = [m["card"] for m in mine if m.get("card") is not None]
    back = []
    if cards:
        info = anki_connect.cards_info(url, cards)
        back = [c.get("cardId") for c in info if c.get("queue") == -1]      # still suspended
        if back:
            with anki_connect.writer("Known from Anki (undo)", wait=10.0):
                anki_connect.invoke("unsuspend", url, cards=back)
    now = _now()
    for m in mine:
        m["undone"] = now
    _save(language, state)
    return {"removed": removed, "unsuspended": back}
