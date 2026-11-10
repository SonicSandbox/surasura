# SPDX-License-Identifier: GPL-3.0-or-later
"""The optional card touch-ups — a tag and a frequency entry. (The extra example sentence moved to
Anki Backfill's 例文, 2026-09-24: Patterns_Spec.md §17.6.)

Until WP-L this module wrote **`due` and nothing else**, and that is a mild risk: a wrong queue
position is annoying, syncs, and comes straight back out of the snapshot. A note field is a
different class of damage. The `Glossary` a user hand-edited, the `Hint` they wrote themselves —
those exist nowhere else, and once overwritten the snapshot is the *only* copy. So three rules
shape every function below, and none of them is defensive style:

**Nothing is written to a field the user did not nominate.** The frequency entry goes only into the
field the user names (`junban_frequency_field`) and only once they switch it on; a field a note does
not actually have is skipped rather than created.

**Frequency is a list, so it is appended to, never replaced.** 96 of the user's 115 mined notes hold
`<ul><li>JPDBv2㋕: 54614</li></ul>`; a second `<li>` beside it is exactly how multi-dictionary
frequency renders and it destroys nothing. Re-running removes junban's own `<li>` first, so a
hundred runs still leave one — and a run that would produce the value already there emits no edit
at all.

**`FreqSort` is a single sort key the user's browser ordering depends on**, so overwriting it lives
behind its own setting and can never ride along with the frequency append.

Everything here is pure: plain dicts in, plain dicts out, no network, no clock, no file I/O. The
decision of what to overwrite has to be testable exhaustively with no collection in the room, for
the same reason the planner is (`plan.py`) — only more so, because this one cannot be fixed by
writing a number back.
"""

import re

from modules.junban.match import MARKERS

# WP-N. `Surasura::☆`, `Surasura::⚖`, `Surasura::文` — hierarchical under whatever `junban_tag`
# names, so everything junban did collapses into one branch of Anki's browser sidebar and each
# marker can be browsed on its own. The spec first chose ASCII names (`Surasura::star`, typable in a
# search box); the user asked for the mark itself, so the leaves are glyphs — see MARKER_TAG_LEAF.
TAG_SEPARATOR = "::"

# The label junban writes into the frequency list, and the prefix it recognises as its own on a
# re-run. Deliberately a constant rather than `junban_tag`: renaming the tag must not orphan every
# `<li>` a previous run left behind, which would then accumulate one per rename.
FREQUENCY_LABEL = "Surasura"

# The one field `junban_write_freqsort` targets. It has no setting of its own because the key exists
# precisely to name this field: it is the sort number Anki's browser orders by, measured at 96/115
# on the live collection, and turning the key on IS the nomination.
FREQSORT_FIELD = "FreqSort"

# One `<li>` written by us, in any casing and with any spacing Anki's editor may have reflowed into
# it. Matched rather than remembered: the note is the only record of what a previous run wrote.
_OUR_ENTRY_RE = re.compile(r'<li[^>]*>\s*' + FREQUENCY_LABEL + r'\s*:\s*[^<]*</li>', re.IGNORECASE)
_LIST_END_RE = re.compile(r'</ul>', re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def options(settings):
    """The touch-up settings, read defensively and normalised into one dict.

    `tag` is the only one that arrives switched on — a tag is purely additive, is the answer to
    "which of these did Surasura touch?", and is removed again by the same snapshot that restores
    the positions. The one that writes into the user's own content (`frequency`) is off until asked
    for, and `freqsort` twice over.
    """
    settings = settings or {}

    tag = settings.get("junban_tag", "")
    tag = tag.strip() if isinstance(tag, str) else ""

    frequency_field = settings.get("junban_frequency_field", "")
    frequency_field = frequency_field.strip() if isinstance(frequency_field, str) else ""

    return {
        "tag": tag,
        # `and tag`: the marker tags hang UNDER the plain tag, so with no parent named there is
        # nowhere for them to go. Tagging `::star` at the root would scatter three loose tags
        # through the user's sidebar with nothing tying them to Surasura.
        "tag_markers": bool(settings.get("junban_tag_markers")) and bool(tag),
        # `and frequency_field`: the switch alone is not a nomination — the field named is.
        "frequency": bool(settings.get("junban_write_frequency")) and bool(frequency_field),
        "frequency_field": frequency_field,
        "freqsort": bool(settings.get("junban_write_freqsort")),
    }


#: The leaf each marker gets in Anki. The user asked for the mark itself rather than the word, so
#: the tag tree reads `Surasura ▸ ☆ / ⚖ / 文` and is recognisable at a glance in the sidebar.
#:
#: **Bare glyphs — no variation selector.** Verified against the live collection: `Surasura::⚖` and
#: `Surasura::⚖︎` round-trip as TWO SEPARATE TAGS, because the selector is a real character
#: that is simply invisible. A near-duplicate tag nobody can see the difference between is the worst
#: possible outcome here, so the panel keeps U+FE0E for rendering and the tag never carries it.
#:
#: All three were round-trip tested through addTags/notesInfo on a real note before being adopted.
MARKER_TAG_LEAF = {"star": "☆", "lopsided": "⚖", "reading": "文"}


def marker_tag(tag, marker):
    """`Surasura::☆` — the hierarchical tag for one marker, or `""` with no parent tag."""
    tag = str(tag or "").strip()
    marker = str(marker or "").strip().lower()
    if not tag or marker not in MARKERS:
        return ""
    return f"{tag}{TAG_SEPARATOR}{MARKER_TAG_LEAF[marker]}"


def carries_tag(existing, tag):
    """Does a note already carry `tag`, as ANKI sees it? Anki compares tags case-insensitively, and
    removing a tag also removes its children (`tag::…`). A note with either — `surasura`, or the
    user's own `Surasura::keep` — counts as already tagged, so junban never records it and a Restore
    can never take away a tag the user put there themselves."""
    wanted = str(tag or "").lower()
    if not wanted:
        return False
    return any(name.lower() == wanted or name.lower().startswith(wanted + TAG_SEPARATOR)
               for name in existing)


def is_active(opts):
    """Does anything here write? Used to keep an all-off run exactly as cheap as it was before."""
    opts = opts or {}
    return bool(opts.get("tag") or opts.get("frequency") or opts.get("freqsort"))


# --------------------------------------------------------------------------- #
# The two values
# --------------------------------------------------------------------------- #
def frequency_value(existing, rank):
    """The frequency field with junban's `<li>` in it exactly once. `rank` is 1-based.

    Append, never replace — that is the whole point. `<ul><li>JPDBv2㋕: 54614</li></ul>` gains a
    sibling and keeps every dictionary already in it. Our own entry is stripped out first so a
    second, third and hundredth run leave exactly one, and a field that has no list at all gains a
    fresh one after whatever it already held rather than losing it.
    """
    entry = f"<li>{FREQUENCY_LABEL}: {int(rank)}</li>"
    text = existing if isinstance(existing, str) else ""

    # Every previous entry of ours goes, not just the first: a field that somehow collected two
    # must come out of this with one, not with two identical ones.
    text = _OUR_ENTRY_RE.sub("", text)

    end = _LIST_END_RE.search(text)
    if end:
        return text[:end.start()] + entry + text[end.start():]
    if text.strip():
        # Content but no list — a hand-typed number, say. Keep it and start a list beside it;
        # dropping it would be the exact damage this module exists not to do.
        return text + f"<ul>{entry}</ul>"
    return f"<ul>{entry}</ul>"


def freqsort_value(rank):
    """The browser's sort key: the rank, 1-based, as the bare number Anki sorts on."""
    return str(int(rank))


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #
def plan(moved, notes, opts, marks_of=None):
    """Work out every note edit and every tag this run would make. Writes nothing, anywhere.

    `moved` is `[(card_id, note_id, word, rank)]` for the cards that are **matched and actually
    moving** — spec WP-L: an unmatched card has no rank, so it gets no touch-up of any kind, and a
    card already in the right place was not touched by this run either.

    `notes` is `{note_id: {"fields": {name: value}, "tags": [...]}}` straight off `notesInfo`;
    `opts` comes from `options()`.

    `marks_of` maps a normalised word to the ✦ / ⚖ / 📖 it carries (WP-N); it is only consulted when
    `junban_tag_markers` is on, and a word it says nothing about simply gets no marker tag.

    Returns `{"fields": {note_id: {field: {"before": str, "after": str}}}, "tags": [note_id],
    "tag": str, "marker_tags": {tag: [note_id]}, "counts": {...}}`.

    `before` **and** `after` are both recorded, and that is what makes the undo honest: restoring
    has to tell "junban put this here" apart from "the user has edited it since", and it can only do
    that by knowing what junban wrote. Without the `after` the only safe restore would be no restore.

    A note is visited once even when several of its cards moved (anki_miner dedups to one note per
    word, but Yomitan and Migaku do not), and the best — lowest — rank wins.
    """
    opts = opts or {}
    notes = notes or {}
    tag = opts.get("tag") or ""

    fields_out = {}
    tag_notes = []
    marker_notes = {}           # marker tag -> [note_id], WP-N
    counts = {"notes": 0, "tag": 0, "frequency": 0, "freqsort": 0, "markers": 0}

    if not is_active(opts):
        return {"fields": {}, "tags": [], "tag": "", "marker_tags": {}, "counts": counts}

    best = {}
    for entry in moved or []:
        try:
            _card_id, note_id, word, rank = entry
        except (TypeError, ValueError):
            continue
        if not isinstance(note_id, int) or not isinstance(rank, int) or isinstance(rank, bool):
            continue                    # no rank means unmatched, and `True` is an int in Python
        if note_id not in best or rank < best[note_id][1]:
            best[note_id] = (word, rank)

    for note_id in sorted(best):
        word, rank = best[note_id]
        note = notes.get(note_id)
        if not isinstance(note, dict):
            continue
        fields = note.get("fields")
        if not isinstance(fields, dict):
            continue
        counts["notes"] += 1

        edits = {}
        # 1-based, so it reads as "the 42nd word you should learn" rather than the 41st. The
        # preview's `rank` column is the 0-based row index; this is that plus one, by spec.
        display_rank = rank + 1

        if opts.get("frequency"):
            field = opts.get("frequency_field") or ""
            if field in fields:
                before = fields.get(field) or ""
                after = frequency_value(before, display_rank)
                if after != before:     # a re-run that changes nothing must not write
                    edits[field] = {"before": before, "after": after}
                    counts["frequency"] += 1

        if opts.get("freqsort") and FREQSORT_FIELD in fields:
            before = fields.get(FREQSORT_FIELD) or ""
            after = freqsort_value(display_rank)
            if after != before:
                edits[FREQSORT_FIELD] = {"before": before, "after": after}
                counts["freqsort"] += 1

        if edits:
            fields_out[note_id] = edits

        existing = note.get("tags")
        existing = [str(name) for name in existing] if isinstance(existing, list) else []

        if tag:
            # Only notes that do not already carry it. Anki ignores a duplicate `addTags`, but the
            # snapshot would then promise to remove a tag the user put there themselves.
            if not carries_tag(existing, tag):
                tag_notes.append(note_id)
                counts["tag"] += 1

        if opts.get("tag_markers"):
            # A word with no markers gets no marker tag — 38% of the live library carries none, and
            # a `Surasura::` branch that tagged them anyway would say nothing.
            marks = (marks_of or {}).get(word) or ()
            marked = False
            for marker in MARKERS:              # a stable order, so the snapshot reads the same way
                if marker not in marks:
                    continue
                name = marker_tag(tag, marker)
                if not name or carries_tag(existing, name):
                    continue
                marker_notes.setdefault(name, []).append(note_id)
                marked = True
            if marked:
                counts["markers"] += 1

    return {"fields": fields_out, "tags": tag_notes, "tag": tag if tag_notes else "",
            "marker_tags": marker_notes, "counts": counts}


def edits_for_wire(fields):
    """`{note_id: {field: new_value}}` — what `updateNoteFields` is actually handed.

    Derived from the same before/after map the snapshot holds, so the value that reaches Anki and
    the value the undo promises to recognise cannot drift apart.
    """
    out = {}
    for note_id, edits in (fields or {}).items():
        values = {field: change.get("after", "") for field, change in (edits or {}).items()}
        if values:
            out[note_id] = values
    return out


def restrict(touchups, note_ids, opts=None):
    """The same plan, narrowed to the notes whose cards genuinely moved.

    The snapshot is taken before the first write, from the cards the planner *intended* to move.
    If Anki goes away halfway through, some of those never moved — and a tag saying "Surasura
    ordered this" on a card that stayed put is a small lie the user cannot see. Narrowing afterwards
    costs nothing: the snapshot still covers the superset, so the undo is complete either way.

    **The counts are recomputed, not carried over.** They used to come through untouched, which made
    the report say "tagged 47 notes" after a run that tagged 46 — and the panel say it before one,
    once a row could be deselected. Every number here is derived from the narrowed structures
    themselves, so what is promised and what is done cannot drift. It is one pass over data already
    in hand.

    `opts` names which field is which (frequency / freqsort); without it those two counts cannot be
    told apart and are left as they were.
    """
    keep = {int(note_id) for note_id in (note_ids or [])}
    fields = {note_id: edits for note_id, edits in (touchups.get("fields") or {}).items()
              if note_id in keep}
    tags = [note_id for note_id in (touchups.get("tags") or []) if note_id in keep]
    markers = {}
    for name, ids in (touchups.get("marker_tags") or {}).items():
        kept = [note_id for note_id in ids if note_id in keep]
        if kept:
            markers[name] = kept

    previous = dict(touchups.get("counts") or {})
    counts = dict(previous)
    counts["notes"] = len(set(fields) | set(tags))
    counts["tag"] = len(tags)
    counts["markers"] = len({note_id for ids in markers.values() for note_id in ids})
    if opts:
        by_field = {(opts.get("frequency_field") or ""): "frequency", FREQSORT_FIELD: "freqsort"}
        by_field.pop("", None)
        for kind in ("frequency", "freqsort"):
            counts[kind] = 0
        for edits in fields.values():
            for field_name in edits:
                kind = by_field.get(field_name)
                if kind:
                    counts[kind] += 1

    return {"fields": fields, "tags": tags, "tag": touchups.get("tag") if tags else "",
            "marker_tags": markers, "counts": counts}
