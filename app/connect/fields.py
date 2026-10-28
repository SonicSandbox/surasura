"""The deck, note type and fields Anki Miner fills, from its own settings (P1.3 row 1.3.6; IS:205, IS:276).

A run never writes Anki Miner's settings and never guesses them: `--api settings-export` hands over the profile's
settings for the language, and the run's `config` names the same deck, note type and fields back (`runfile.config`),
so a run can't land anywhere the user didn't set up. What's missing is set by *Finish its setup* (`FINISH`: A4M1-2b,
`services.anki_miner_setup`), never in Anki Miner's window. What Junban and Backfill read of a mined card comes from the
same mapping: the word field, the sentence field, and the field Anki Miner writes the episode's source into (K40: it
moved there from MiscInfo), each `None` when unmapped.

Anki Miner's own rule (its `check`): the word field must be the note type's first field (IS:205) — Anki checks a new
note's first field for a duplicate. A mapping that breaks it, a note type missing from Anki, or a mapped field the
note type lacks would fail the whole run (`MINING_FAILED`): each is a *Needs you*, named in plain words.
"""
from collections import namedtuple

# One profile's mapping: `fields` is Anki Miner's own role -> field (unmapped roles left out); `word`, `sentence`,
# `source` and `frequency_sort` are the fields those roles map to, or None.
Mapping = namedtuple("Mapping", "deck note_type fields word sentence source frequency_sort")


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
                   fields.get("frequency_sort"))


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
