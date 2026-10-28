"""The deck, note type and fields Surasura sets in Anki Miner itself (A4M1-2b; Sonic 2026-10-27: "I honestly don't want
to ever have to open anki miner. Ever."), written with Anki Miner's own `settings-import` (Z-3) by *Finish its setup*
(`services.anki_miner_setup.finish_setup`). Lean taken — PROVISIONAL (TRACK *Asks for Sonic* A4M1-2b).

Only what Anki Miner's `check` says is wrong is set; a deck or note type that works is never moved. Each value comes
from Surasura's own settings or from Anki, never guessed from a name alone:

- **the deck** (`deck_for`): the deck Junban keeps in order for this language (`replan_preview.recorded_deck`), else
  Junban's deck when it is one of this language's known-words decks — each only when Anki has it; never a deck only
  because it is the one known-words deck (it may be a premade course: reviews, alpha 5), which is asked, chosen first;
- **the note type** (`note_type_for`): the one most of that deck's newest notes use, when Backfill's note languages
  name none other for this language; else the one Backfill's note languages name for it;
- **the fields** (`fields_for`): Anki Miner's own rule, the word in the note type's first field; every other role keeps
  the field Anki Miner has for it while the note type has that field (one left empty stays empty unless the note type
  changed: Anki Miner reads a mapped field as a switch, word audio for one), else takes the field of its name in the
  note types Anki Miner fills completely (Lapis, Kiku, Anki Miner Note, Senren: `NAMES`, from Anki Miner 3.10.1's
  `note_presets.py`); a note type with no sentence field isn't one Anki Miner can make Surasura's cards with.

What can't be known — several known-words decks and no Junban deck, an empty deck — is asked in Surasura's own window
(`plan` -> "ask", with the choices); never in Anki Miner's.

Standard library only; Anki is read through the `anki` reads handed in (`AnkiReads`: read-only AnkiConnect actions).
"""
from collections import Counter

# Each role's field in the note types Anki Miner fills completely, in its own preset's names (3.10.1
# `services/note_presets.py`: Lapis / Kiku / Anki Miner Note, then Senren). A name is matched ignoring case.
NAMES = {
    "sentence": ("Sentence",),
    "definition": ("MainDefinition", "definition"),
    "glossary": ("Glossary",),
    "picture": ("Picture",),
    "audio": ("SentenceAudio",),
    "expression_audio": ("ExpressionAudio", "wordAudio"),
    "expression_furigana": ("ExpressionFurigana",),
    "expression_reading": ("ExpressionReading", "reading"),
    "sentence_furigana": ("SentenceFurigana",),
    "pitch_position": ("PitchPosition", "pitchPositions"),
    "pitch_category": ("PitchCategories",),
    "frequency": ("Frequency", "frequencies"),
    "frequency_sort": ("FreqSort",),
    "source": ("MiscInfo",),
    "sentence_translation": ("SentenceTranslation",),
    "language": ("Language",),
}
# Those note types read their pitch categories as romaji (Anki Miner's presets set it with them; its default is "jp")
ROMAJI_PITCH = frozenset(("PitchCategories", "pitchCategories"))
RECENT_NOTES = 50               # the deck's newest notes whose note type is counted (`AnkiReads.deck_note_type`)


class AnkiReads:
    """The read-only AnkiConnect reads `plan` needs, at `url`; each raises `anki_connect.AnkiError` when Anki doesn't
    answer."""

    def __init__(self, url):
        self.url = url

    def _invoke(self, action, **params):
        from app import anki_connect
        return anki_connect.invoke(action, self.url, timeout=10, **params)

    def decks(self):
        return [str(d) for d in self._invoke("deckNames") or ()]

    def note_types(self):
        return [str(m) for m in self._invoke("modelNames") or ()]

    def fields(self, note_type):
        return [str(f) for f in self._invoke("modelFieldNames", modelName=note_type) or ()]

    def deck_note_type(self, deck):
        """The note type most of `deck`'s newest notes (RECENT_NOTES) use, or None (an empty deck)."""
        query = '"deck:' + deck.replace("\\", "\\\\").replace('"', '\\"') + '"'
        ids = sorted(self._invoke("findNotes", query=query) or ())[-RECENT_NOTES:]
        if not ids:
            return None
        names = Counter(str(n.get("modelName")) for n in self._invoke("notesInfo", notes=ids) or ()
                        if isinstance(n, dict) and n.get("modelName"))
        return names.most_common(1)[0][0] if names else None


def _known_decks(settings, language):
    return [str(d) for d in ((settings or {}).get("anki_sync_decks") or {}).get(language) or () if str(d).strip()]


def deck_for(settings, language, decks):
    """The deck Surasura's own settings name for `language`'s new cards among Anki's `decks` (module docstring), or
    None when they name none, or several."""
    from app import replan_preview
    known = [d for d in _known_decks(settings, language) if d in decks]
    recorded = replan_preview.recorded_deck(settings, language)
    if recorded and recorded in decks:
        return recorded
    junban = str((settings or {}).get("junban_deck") or "").strip()
    return junban if junban and junban in known else None


def _backfill_types(settings, language, note_types):
    saved = (settings or {}).get("junban_backfill_note_languages")
    saved = saved if isinstance(saved, dict) else {}
    return [str(m) for m, lang in saved.items() if lang == language and str(m) in note_types]


def note_type_for(settings, language, note_types, deck_type):
    """The note type for `language`'s new cards among Anki's `note_types`: the one `deck_type` (most of the deck's newest
    notes) names — unless Backfill's note languages name others for this language and not it —, else the one Backfill
    names; None when neither knows."""
    named = _backfill_types(settings, language, note_types)
    if deck_type and deck_type in note_types and (not named or deck_type in named):
        return deck_type
    return named[0] if len(named) == 1 else None


def fields_for(note_fields, current, fill=True):
    """Anki Miner's role -> field map for a note type whose fields are `note_fields` (in order), from `current` (the
    profile's map for this language: its roles are the ones this Anki Miner knows) — or None when Anki Miner can't make
    Surasura's cards with it (no fields, no sentence field). Every role of `current` is in the map ("" unmapped), the
    word in the first field (Anki's duplicate check reads it), and no field twice. `fill` False (the same note type): a
    role `current` leaves empty stays empty — but the sentence, which Surasura's cards need (review round 2: it is
    filled, and a map with no sentence role at all still looks for one)."""
    note_fields = [str(f) for f in note_fields or ()]
    if not note_fields:
        return None
    by_fold = {f.casefold(): f for f in note_fields}
    out, taken = {}, {note_fields[0]}
    for role in list(current or {}) + ([] if "sentence" in (current or {}) else ["sentence"]):
        if role == "word":
            continue
        have = str((current or {}).get(role) or "")
        if not have and not fill and role != "sentence":
            out[role] = ""
            continue
        named = [by_fold[n.casefold()] for n in NAMES.get(role, ()) if n.casefold() in by_fold]
        field = next((f for f in ([have] if have in note_fields else []) + named if f not in taken), "")
        out[role] = field
        if field:
            taken.add(field)
    if not out.get("sentence"):
        return None
    return dict({"word": note_fields[0]}, **out)


def plan(settings, language, current, failed, anki, chosen=None):
    """What to write into Anki Miner's profile for `language` -> ("write", values) | ("ask", asked).

    `current`: the profile's settings for the language (its `settings-export`'s `settings`); `failed`: the `check` items
    that aren't ok (only those are set: `SETTINGS_ITEMS`); `anki`: `AnkiReads`; `chosen`: {"deck", "note_type"} the
    learner picked in Surasura's window. `values`: Anki Miner's settings keys to write ({} when none is wrong).
    `asked`: {"deck": [choices] | None, "note_type": [choices] | None, "why": None | "fields", "values": {...}} —
    each list with Surasura's own first (this language's known-words decks; the note types Backfill names), None when
    it isn't asked; one at a time, the deck first (its notes most often name the note type); the note types offered are
    only those Anki Miner can fill (`fields_for`: [] when Anki has none); "fields": `asked["note"]` has no sentence
    field; `values`: what is already decided (the deck chosen), written meanwhile so it is never asked again (the
    DevTest drill, run 1). Raises `anki_connect.AnkiError` when Anki doesn't answer."""
    chosen = chosen or {}
    failed = set(failed or ())
    current = current or {}
    values = {}
    deck = str(current.get("anki_deck_name") or "")
    if "deck" in failed:
        decks = anki.decks()
        deck = chosen.get("deck") if chosen.get("deck") in decks else deck_for(settings, language, decks)
        if deck is None:            # the note type waits for it: most often the deck's own notes name it
            known = [d for d in _known_decks(settings, language) if d in decks]
            return "ask", {"deck": known + [d for d in decks if d not in known], "note_type": None, "why": None,
                           "values": values}
        values["anki_deck_name"] = deck
    if not failed & {"note_type", "fields"}:
        return "write", values
    note_types = anki.note_types()
    note = str(current.get("anki_note_type") or "")
    if chosen.get("note_type") in note_types:      # the learner's pick, also after "no Sentence field" (review round 2)
        note = chosen["note_type"]
    elif "note_type" in failed or note not in note_types:
        note = note_type_for(settings, language, note_types, anki.deck_note_type(deck) if deck else None)
        if note is None:
            return "ask", {"deck": None, "note_type": _note_choices(settings, language, note_types, anki, current),
                           "why": None, "values": values}
    note_fields = anki.fields(note)
    changed = note != str(current.get("anki_note_type") or "")
    fields = fields_for(note_fields, current.get("anki_fields") or {}, fill=changed)
    if fields is None:
        return "ask", {"deck": None, "note_type": _note_choices(settings, language, note_types, anki, current),
                       "why": "fields", "note": note, "values": values}
    values.update(anki_note_type=note, anki_fields=fields)
    card_type = str(current.get("card_type") or "")
    marker = str((current.get("card_type_marker_fields") or {}).get(card_type) or "")
    if card_type and marker and marker not in note_fields:      # a card-type mark this note type has no field for
        values["card_type"] = ""
    if fields.get("pitch_category") in ROMAJI_PITCH and fields.get("pitch_category") != \
            (current.get("anki_fields") or {}).get("pitch_category"):
        values["pitch_category_format"] = "romaji"
    return "write", values


def _note_choices(settings, language, note_types, anki, current):
    """The note types Anki Miner can fill (`fields_for`), those Backfill names for this language first."""
    named = _backfill_types(settings, language, note_types)
    roles = (current or {}).get("anki_fields") or {}
    return [m for m in named + [m for m in note_types if m not in named]
            if fields_for(anki.fields(m), roles) is not None]
