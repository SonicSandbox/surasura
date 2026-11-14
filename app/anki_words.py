"""What Anki knows of the learner's words (Piyo-AK, 2026-11-14): each studied note of the decks the known-words sync
reads, as young or mature, how often it was forgotten (lapses), whether Anki tagged it a leech, how hard it is, and
whether it was first studied today — read live through AnkiConnect, read-only, in one request of searches.

Piyo's rounds practise from it (`practise`: the sources in SOURCES, `app/cli/mcp_server.py`), and the word hover is
the next reader (`word_states`). Like the young cards' sync (`anki_sync.sync_young`), nothing is rendered: no
cardsInfo, no search per card — each search names the notes with a card of one standing (Anki's `prop:lapses=n`,
`prop:ivl`, `prop:d`, `prop:ease`, `tag:leech`, `introduced:1`), so a note's standing is the searches it is found by,
and a note with two cards (recognition and production) is one note: its worst card for lapses and hardness, mature
only once every studied card is. The word of a note is the known sync's (`anki_sync._note_word`: the chosen word
field, read as Junban reads a card), and two notes of one word count once.

Qt-free and Tk-free; no settings key of its own (the decks and fields are the known sync's, `anki_sync_decks` /
`anki_sync_fields`). Never writes Anki. `tests/test_anki_words.py`.
"""
from dataclasses import dataclass

from app import anki_connect, anki_sync
from app.anki_connect import AnkiError

MATURE_DAYS = anki_sync.MATURE_DAYS     # Anki's own line: a card is mature from a 21-day interval
LAPSES_MOST = 10                        # lapses are read 1 to 9 apiece, then "10 or more"
# How hard a card is, as tie-breaks among equal lapses (each a step that counts once): FSRS's difficulty (Anki's
# `prop:d`, 0 to 1; an Anki before FSRS refuses the search and it counts as none) or SM-2's ease (`prop:ease`).
HARD_D = (0.5, 0.6, 0.7, 0.8, 0.9)
HARD_EASE = (2.2, 1.9, 1.6)

# Where a round's words come from in Anki (Sonic's list, 2026-11-14: the names PROVISIONAL — a rename is one key here;
# every tool text, choice and message is made from this table): name -> `short`, the tools' words for it; `what`, the
# answer's words for those cards; `none`, why a round has none; `rule`, the line a round's brief gives the AI.
SOURCES = {
    "struggling": {"short": "the cards they struggle with in Anki: leeches first, then the most forgotten",
                   "what": "the learner's struggling Anki cards",
                   "none": "No card in the learner's Anki decks is a leech or has been forgotten yet",
                   "rule": "These are words the learner keeps forgetting in Anki: use each one more than once, in "
                           "easy sentences, so it sticks."},
    "today": {"short": "the cards they learned in Anki today",
              "what": "the cards the learner learned in Anki today",
              "none": "The learner hasn't learned a new card in Anki today yet",
              "rule": "These are words the learner met for the first time in Anki today: use each one more than once."},
    "known": {"short": "the cards they know well (mature in Anki)",
              "what": "the learner's well-known Anki cards",
              "none": "No card in the learner's Anki decks is mature yet (a 21-day interval)",
              "rule": "These are words the learner knows well (mature in Anki): use them freely, as the round's frame."},
}


class NoDecks(ValueError):
    """No deck is chosen for the known-words sync in this language: there is nothing to read."""


class NoneStudied(ValueError):
    """The chosen decks hold no studied card at all: Anki open on another profile, or the decks renamed — never "you
    have none" (the young cards' sync reads it the same way, `anki_sync._young_notes`)."""


class NoWords(ValueError):
    """The source has cards, but none of them holds a word in the known sync's word field (the field chosen wrong)."""


@dataclass
class Standing:
    """One studied note's standing in Anki (its cards together)."""
    note_id: int
    leech: bool = False
    lapses: int = 0         # its most forgotten card's lapses (LAPSES_MOST for 10 or more)
    hard: int = 0           # how many of HARD_D / HARD_EASE's steps its hardest card is past
    young: bool = False     # a studied card under MATURE_DAYS
    mature: bool = False    # every studied card mature
    today: bool = False     # first studied today (Anki's `introduced:1`)


def _terms(decks):
    terms = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in anki_sync._clean_decks(decks))
    return f"({terms})"


def _searches(decks):
    """[(slot, query, needed)]: every search one read asks, in one `multi`. `needed`: a refused search fails the read
    (a missing one would rank wrongly); the others (FSRS's difficulty, `introduced:`) an older Anki may not know."""
    studied = f"{_terms(decks)} -is:new -is:suspended"
    # a leech Anki suspended (its default leech action in older versions) is still a struggling card
    worked = f"{_terms(decks)} -is:new (-is:suspended OR tag:leech)"
    out = [("leech", f"{_terms(decks)} -is:new tag:leech", True)]
    out += [(("lapses", n), f"{worked} prop:lapses={n}", True) for n in range(1, LAPSES_MOST)]
    out.append((("lapses", LAPSES_MOST), f"{worked} prop:lapses>={LAPSES_MOST}", True))
    out += [(("hard", "d", d), f"{worked} prop:d>={d}", False) for d in HARD_D]
    out += [(("hard", "ease", e), f"{worked} prop:ease<{e}", True) for e in HARD_EASE]
    out.append(("young", f"{studied} prop:ivl<{MATURE_DAYS}", True))
    out.append(("mature", f"{studied} prop:ivl>={MATURE_DAYS}", True))
    out.append(("today", f"{studied} introduced:1", False))
    return out


@dataclass
class Reading:
    """One read of the decks: each studied note's Standing, and whether Anki could say what was learned today."""
    notes: dict
    today_known: bool = True


def read(url, decks):
    """Every studied note of `decks` (their subdecks too; never a deck outside them) with its Standing, in ONE request
    to Anki. Raises NoDecks without a deck, AnkiError when Anki is closed or a needed search fails."""
    if not anki_sync._clean_decks(decks):
        raise NoDecks("no Anki deck chosen")
    searches = _searches(decks)
    replies = list(anki_connect.multi([{"action": "findNotes", "params": {"query": q}} for _s, q, _n in searches],
                                      url or anki_connect.DEFAULT_URL)) + [None] * len(searches)
    notes, today_known = {}, True
    found = {}
    for (slot, _query, needed), reply in zip(searches, replies):
        ok = isinstance(reply, dict) and reply.get("error") is None and isinstance(reply.get("result"), list)
        if not ok:
            if needed:          # through `refusal`: a slot refused only while Anki is busy is marked busy
                raise anki_connect.refusal("findNotes", (reply.get("error") if isinstance(reply, dict) else None)
                                           or "no answer")
            if slot == "today":
                today_known = False
            continue
        found[slot] = set(anki_connect._int_ids(reply["result"]))

    def note(note_id):
        return notes.setdefault(note_id, Standing(note_id))
    for note_id in found.get("leech", ()):
        note(note_id).leech = True
    for n in range(1, LAPSES_MOST + 1):
        for note_id in found.get(("lapses", n), ()):
            note(note_id).lapses = max(note(note_id).lapses, n)
    for slot, ids in found.items():
        if isinstance(slot, tuple) and slot[0] == "hard":
            for note_id in ids:
                note(note_id).hard += 1
    for note_id in found.get("young", ()):
        note(note_id).young = True
    for note_id in found.get("mature", set()) - found.get("young", set()):
        note(note_id).mature = True
    for note_id in found.get("today", ()):
        note(note_id).today = True
    return Reading(notes, today_known)


def ranked(reading, source):
    """The note ids `source` (SOURCES) practises, in its order: struggling — Anki's leeches first, then the most
    lapses, then the hardest, then the newest note; today — the notes first studied today, the newest first; known —
    the mature notes (no leech), the newest first."""
    notes = reading.notes.values()
    if source == "struggling":
        picked = [s for s in notes if s.leech or s.lapses]
        return [s.note_id for s in sorted(picked, key=lambda s: (not s.leech, -s.lapses, -s.hard, -s.note_id))]
    if source == "today":
        return sorted((s.note_id for s in notes if s.today), reverse=True)
    if source == "known":
        return sorted((s.note_id for s in notes if s.mature and not s.leech), reverse=True)
    raise ValueError(f"no source {source!r}")


def words(url, note_ids, fields, language, limit, chunk=50):
    """[(word, note id)] of `note_ids` in their order, each word once (its first note), at most `limit`: notesInfo a
    chunk at a time, only as far as `limit` words need. A note with no usable word is passed over."""
    out, seen = [], set()
    note_ids = list(note_ids)
    for start in range(0, len(note_ids), max(1, chunk)):
        part = note_ids[start:start + chunk]
        by_id = {n.get("noteId"): n for n in anki_connect.notes_info(url, part)}
        for note_id in part:
            info = by_id.get(note_id)
            word = anki_sync._note_word(info, fields, language) if info else None
            if word and word not in seen:
                seen.add(word)
                out.append((word, note_id))
                if len(out) >= limit:
                    return out
    return out


def _scope(settings, language):
    decks = list(((settings or {}).get("anki_sync_decks") or {}).get(language) or [])
    fields = [str(f) for f in ((settings or {}).get("anki_sync_fields") or {}).get(language) or []]
    return anki_connect.address(settings or {}), decks, fields


def practise(language, source, limit, settings):
    """`source`'s words for a practice round, at most `limit`: [{"word", "note", "lapses", "leech"}], in its order
    (`ranked`); [] when the source has no card; None when the source is `today` and this Anki can't say (too old for
    `introduced:`). Raises NoDecks, NoneStudied (no studied card in the decks at all), NoWords (cards, but no word in
    any) or AnkiError (Anki closed, busy, a search refused)."""
    if source not in SOURCES:
        raise ValueError(f"no source {source!r}")
    url, decks, fields = _scope(settings, language)
    reading = read(url, decks)
    if not reading.notes:
        raise NoneStudied("no studied card in the chosen decks")
    if source == "today" and not reading.today_known:
        return None
    note_ids = ranked(reading, source)
    found = words(url, note_ids, fields, language, limit)
    if note_ids and not found:
        raise NoWords("no word in the cards' word field")
    out = []
    for word, note_id in found:
        standing = reading.notes[note_id]
        out.append({"word": word, "note": note_id, "lapses": standing.lapses, "leech": standing.leech})
    return out


def word_states(language, settings, url=None):
    """{word: Standing} of every studied note in the known sync's decks (a word's first note, its leech / lapses /
    hardness the worst of its notes, young if any is, mature only if every one is) — for the word hover. Reads every
    note's word (notesInfo in chunks), so it is a worker's call. Raises NoDecks or AnkiError."""
    scope_url, decks, fields = _scope(settings, language)
    url = url or scope_url
    reading = read(url, decks)
    out = {}
    ids = sorted(reading.notes, reverse=True)
    by_id = {n.get("noteId"): n for n in anki_connect.notes_info(url, ids)}
    for note_id in ids:
        info = by_id.get(note_id)
        word = anki_sync._note_word(info, fields, language) if info else None
        if not word:
            continue
        s = reading.notes[note_id]
        have = out.get(word)
        if have is None:
            out[word] = Standing(note_id, s.leech, s.lapses, s.hard, s.young, s.mature, s.today)
        else:
            have.leech, have.lapses, have.hard = have.leech or s.leech, max(have.lapses, s.lapses), max(have.hard, s.hard)
            have.young, have.mature, have.today = have.young or s.young, have.mature and s.mature, have.today or s.today
    return out
