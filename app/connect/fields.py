"""The deck, note type and fields Anki Miner fills, from its own settings (P1.3 row 1.3.6; IS:205, IS:276).

A run never writes Anki Miner's settings and never guesses them: `--api settings-export` hands over the profile's
settings for the language, and the run's `config` names the same note type and fields back (`runfile.config`), so a
run can't land anywhere the user didn't set up. **The deck** is Surasura's own while it shows one (Michi-DK: `for_run`,
`surasura_deck`): the deck Settings names for new cards and 順 keeps in order, sent for that run alone — Anki Miner
applies a run file's `config` "for this run only, never saved" (its `resolve_run_config`), so the deck its own window
mines into is never changed (its `settings-import` refuses the window's profile anyway). What's missing is set by
*Finish its setup* (`FINISH`: A4M1-2b, `services.anki_miner_setup`), never in Anki Miner's window. What Junban and
Backfill read of a mined card comes from the same mapping: the word field, the sentence field, and the field Anki Miner
writes the episode's source into (K40: it moved there from MiscInfo), each `None` when unmapped.

Anki Miner's own rule (its `check`): the word field must be the note type's first field (IS:205) — Anki checks a new
note's first field for a duplicate. A mapping that breaks it, a note type missing from Anki, or a mapped field the
note type lacks would fail the whole run (`MINING_FAILED`): each is a *Needs you*, named in plain words.
"""
from collections import namedtuple

# One profile's mapping: `fields` is Anki Miner's own role -> field (unmapped roles left out); `word`, `sentence`,
# `source` and `frequency_sort` are the fields those roles map to, or None. `own_deck` (Michi-DK): Anki Miner's own
# deck when a run mines into Surasura's instead (`for_run`), else None. `quiet_mark` (BOOK-CARD): the profile's card
# type is the audio card — the sentence card's mark a mine with no sound makes instead (`runfile.config`'s `quiet`),
# or "" when the note type has none; None: any other card type, every mine keeps it.
Mapping = namedtuple("Mapping", "deck note_type fields word sentence source frequency_sort own_deck quiet_mark",
                     defaults=(None, None))

# BOOK-CARD (3.0.19; the lead's lean (a), PROVISIONAL until Sonic's § 96 — (b), the plain word card, would be ""): a
# card mined from a book or a text with no audiobook lined up has no sentence audio, so under the learner's audio card
# that mine alone makes the sentence card. Anki Miner's card-type ids (its `config.card_type`); the learner's setting
# is never changed (the run's `config` is for that run only)
AUDIO_CARD, SENTENCE_CARD = "audio", "sentence"


# Where each of these is set right: Surasura's own *Finish its setup* (A4M1-2b), never Anki Miner's window — offered
# only with an Anki Miner whose settings-import (Z-3) sets it (A5F3: `pointer`), else Surasura's update
FINISH = "Surasura sets it: Settings → Anki & mining → Finish its setup…"
UPDATE = "Update Anki Miner from Surasura (Settings → Anki & mining): then Surasura sets it for you."
UNREAD = ("Check again in a moment; if it keeps happening, update Anki Miner from Surasura (Settings → Anki & "
          "mining).")


def pointer(info):
    """A5F3: where a deck, note type or field mapping Anki Miner's `check` flags is set right with this Anki Miner
    (`info`: its `version` answer): *Finish its setup* when it names settings-import (Z-3) — the button is offered
    then (`setup._anki_miner`) —, else Surasura's update; None (not known): *Finish its setup*."""
    if info is None:
        return FINISH
    from app.connect import anki_miner
    return FINISH if "Z-3" in anki_miner.features(info) else UPDATE


class NeedsYou(Exception):
    """Something only the user can set right in Anki Miner or Anki: `message` says what, in plain words."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def from_export(export, language="ja", do=FINISH):
    """The Mapping in an Anki Miner settings export (the JSON `--api settings-export` writes). `do`: where what's
    missing is set right (`pointer`); an export that can't be read is no item of Anki Miner's `check`: read again."""
    name = {"ja": "Japanese", "zh": "Chinese"}.get(language, language)
    if not isinstance(export, dict) or not isinstance(export.get("settings"), dict):
        raise NeedsYou("Anki Miner's settings couldn't be read. " + UNREAD)
    if export.get("configured") is False:
        raise NeedsYou(f"Anki Miner isn't set up for {name} yet. " + do)
    settings = export["settings"]
    deck, note_type = settings.get("anki_deck_name"), settings.get("anki_note_type")
    roles = settings.get("anki_fields")
    if not isinstance(deck, str) or not deck.strip():
        raise NeedsYou("Anki Miner has no deck to put cards in. " + do)
    if not isinstance(note_type, str) or not note_type.strip():
        raise NeedsYou("Anki Miner has no note type. " + do)
    if not isinstance(roles, dict):
        raise NeedsYou("Anki Miner's field mapping couldn't be read. " + do)
    fields = {str(role): str(field) for role, field in roles.items() if isinstance(field, str) and field.strip()}
    if not fields.get("word"):
        raise NeedsYou("Anki Miner doesn't say which field holds the word. " + do)
    return Mapping(deck, note_type, fields, fields["word"], fields.get("sentence"), fields.get("source"),
                   fields.get("frequency_sort"), quiet_mark=_quiet_mark(settings, fields))


def _quiet_mark(settings, mapped):
    """BOOK-CARD: `Mapping.quiet_mark` from the export's `settings` — the sentence card's mark field, as Anki Miner
    names it (compared exactly, as its preflight does), while the card type is the audio card; "" when the mark map
    names none, there's no map, or the mark is a field `mapped` fills (Anki Miner refuses a field written twice);
    else None."""
    if settings.get("card_type") != AUDIO_CARD:
        return None
    marks = settings.get("card_type_marker_fields")
    mark = marks.get(SENTENCE_CARD) if isinstance(marks, dict) else None
    return mark if isinstance(mark, str) and mark.strip() and mark not in mapped.values() else ""


def with_note_fields(mapping, model_fields):
    """BOOK-CARD: `mapping` with its sentence card's mark none ("") when Anki's note type (`model_fields`) has no field
    for it — Anki Miner refuses a run whose card type's mark the note type lacks (its preflight asks for the field);
    `model_fields` None (not read): `mapping` as it is."""
    if mapping.quiet_mark and model_fields is not None and mapping.quiet_mark not in model_fields:
        return mapping._replace(quiet_mark="")
    return mapping


def surasura_deck(settings, language):
    """Michi-DK: the deck Surasura shows for `language`'s new cards and 順 keeps in order — Settings' *New cards a
    day* deck (`anki_deck_options.deck_for`: 順's deck while its scope is one deck), only while it is this language's
    (`setup_wizard.junban_deck`: one recorded for the other language is none here) — or None (Anki Miner's own)."""
    from app import anki_deck_options
    from app.services import setup_wizard
    settings = settings or {}
    if not anki_deck_options.deck_for(settings):
        return None
    return setup_wizard.junban_deck(settings, language)


def for_run(mapping, settings, language, decks=None):
    """The mapping a Connect run mines with: `mapping` (Anki Miner's own, from its settings export) with Surasura's
    deck (`surasura_deck`) in place of its own, kept as `own_deck` (the words carded there still count). `decks`:
    Anki's decks (None: not read) — a deck Anki answers without is none to mine into (Anki Miner refuses the whole
    run): Anki Miner's own then, as before. Deck names compare as Anki does, ignoring case."""
    deck = surasura_deck(settings, language)
    if not deck or deck.casefold() == str(mapping.deck).casefold() or (
            decks is not None and deck.casefold() not in {str(d).casefold() for d in decks}):
        return mapping
    return mapping._replace(deck=deck, own_deck=mapping.deck)


def check_note_type(mapping, model_fields, do=FINISH):
    """Raise NeedsYou unless Anki's note type (`model_fields`: its fields in order, None when the note type isn't in
    Anki) takes this mapping: the word field first, every mapped field present — each an item Anki Miner's own `check`
    flags too (its note type, its fields), set right where `do` says (`pointer`)."""
    if model_fields is None:
        raise NeedsYou(f'Anki has no note type "{mapping.note_type}", which Anki Miner is set to fill. '
                       + do)
    if not model_fields or model_fields[0] != mapping.word:
        raise NeedsYou(f'The word field ("{mapping.word}") must be the first field of "{mapping.note_type}" '
                       "for Anki Miner to make cards. " + do)
    missing = sorted(set(mapping.fields.values()) - set(model_fields))
    if missing:
        raise NeedsYou(f'"{mapping.note_type}" has no field ' + ", ".join(f'"{m}"' for m in missing)
                       + ". " + do)
