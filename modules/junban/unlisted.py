# SPDX-License-Identifier: GPL-3.0-or-later
"""What happens to the new cards NOT on your list — the panel's "Cards not on your list:" row.

Junban_Backlog_Spec §13, as the user answered it (2026-09-23). After the reorder, every card placed
behind the list's group — the rarer words, cards from content the library lacks, and the words the
learner already knows — can be tagged, flagged purple and/or suspended, in any combination. Nothing
ticked is "No action", the default. **Delete is deliberately absent**: Junban cannot undo it, it
syncs to AnkiWeb and the phone, and this module "creates nothing and deletes nothing". The route to
deleting them is Anki's own browser (`tag:Surasura::later`), where Anki's undo exists.

Every action goes through the same snapshot as the reorder and comes back out with Restore: the tag
off exactly the notes Junban put it on, each card's previous flag back (unless the user has flagged
it since), and only the cards Junban suspended unsuspended. **Suspend always tags as well**, so a card
suspended by a run whose snapshot a later run has replaced can still be found in Anki:
`tag:Surasura::later is:suspended`.

Which cards: a row the planner placed behind the list (`tier` not one of PLACED_WITH_LIST) whose word
is on the list in NO form — `marks_of` covers every row of the list, filtered or not, so a marker
filter (WP-N) can never make a listed word look unlisted and get it suspended. A card the user
deselected in the preview is their choice, and is never acted on.

Pure, like `touchup.py`: plain data in, plain data out, no Anki, no tkinter.
"""

from modules.junban import match, touchup

# The leaf under the Junban tag, and the flag: Anki's flags are 1 red … 7 purple (the user's choice).
LATER_LEAF = "later"
FLAG_PURPLE = 7
DEFAULT_PARENT = "Surasura"

# Tiers placed WITH the list: its own words, the phrases held to its bar, and — with "List first"
# off — the words it cut off that the journey interleaves among them.
PLACED_WITH_LIST = ("list", "phrase", "library")


def options(settings):
    """`{"tag", "flag", "suspend"}` from `junban_later_tag` / `_flag` / `_suspend` — each on only when
    explicitly True, so a missing or garbled key is "No action"."""
    settings = settings or {}
    return {"tag": settings.get("junban_later_tag") is True,
            "flag": settings.get("junban_later_flag") is True,
            "suspend": settings.get("junban_later_suspend") is True}


def is_active(opts):
    return any((opts or {}).values())


def required_actions(opts):
    """The AnkiConnect actions a run needs beyond reordering — asked in preflight, and only when on."""
    return ("suspend", "unsuspend") if (opts or {}).get("suspend") else ()


def later_tag(parent):
    """`Surasura::later` — under the Junban tag the user named, or under Surasura when they switched
    that tag off (the later tag is its own choice)."""
    return f"{str(parent or '').strip() or DEFAULT_PARENT}{touchup.TAG_SEPARATOR}{LATER_LEAF}"


# --- P4.1 L2: *Take its new cards out* (05 §5.7, D14; W1.2 01-scope fc) ---------------------------------------- #
# A taken-out item's unstudied new cards whose words left the list: suspended and tagged `<Junban's tag>::out` (never
# deleted), whatever the `junban_later_*` settings say — by the runs that record what they change in the store's
# `anki_changes` (`spaced.Job.cards_out`); *Put back* restores exactly those. A card whose word is still on the list
# stays in, placed by the list (TF fix 3, P4.1-7 ⭐ (b): the shelf's rule, P2.4-5); one you mined yourself is never
# taken out (TF fix 2, P4.1-6 ⭐ (b), ruling P1.4-1).
OUT_LEAF = "out"


def out_tag(parent):
    """`Surasura::out` — `later_tag`'s scheme: under the Junban tag the user named, or under Surasura."""
    return f"{str(parent or '').strip() or DEFAULT_PARENT}{touchup.TAG_SEPARATOR}{OUT_LEAF}"


def plan_out(order, out, notes, parent="", exclude=()):
    """What *Take its new cards out* does this run, in `plan`'s shape (so `_still_new` and `_apply_later` take it as
    they take §13's): every row of `order` whose card is out (`out`: `{card_id: item_id}`, `pins.out_cards`) — the
    planner's rows are the new, unsuspended cards alone, so a reviewed, learning or suspended card is never one —
    tagged (a note already carrying the tag is left alone, so a Put back never takes off one you put there) and
    suspended; `item_of` keeps each card's item for the store's record. A card you clicked to leave alone in the
    preview is left alone, as a pin leaves it (`plan`). `{}` when nothing is out."""
    excluded = set(exclude or ())
    rows = [row for row in order or [] if row.card_id in (out or {}) and row.card_id not in excluded]
    if not rows:
        return {}
    note_of = {row.card_id: row.note_id for row in rows}
    tag = out_tag(parent)
    tag_notes = [note_id for note_id in sorted({note for note in note_of.values() if isinstance(note, int)})
                 if not touchup.carries_tag(((notes or {}).get(note_id) or {}).get("tags") or [], tag)]
    return _with_counts({"cards": sorted(note_of), "note_of": note_of, "tag": tag, "tag_notes": tag_notes,
                         "flags": {}, "flag_kept": 0, "suspend": sorted(note_of),
                         "item_of": {row.card_id: out[row.card_id] for row in rows}})
# --- end P4.1 L2 ---


def plan(order, marks_of, language, flags_of, notes, opts, parent="", exclude=(), taken_off=(), out=()):
    """What the chosen actions will do, for the preview (I5) and the run. `{}` when nothing is on.

    `order` is the planner's Placement rows, `marks_of` the list's every key (`build_index`),
    `flags_of` `{card_id: flag}` from `cardsInfo`, `notes` `{note_id: {"tags": [...]}}`, `exclude` the
    cards the user clicked off to leave alone, `taken_off` the listed ones they clicked off the list —
    those are acted on like any card not on it (the user, 2026-09-23). Returns `{"cards", "note_of", "tag", "tag_notes", "flags", "flag_kept",
    "suspend", "counts"}`:

      * `tag_notes` — the notes to tag, never one already carrying the tag (so a restore cannot take
        away one the user put there);
      * `flags` — `{card_id: flag_before}` for the cards to flag purple: unflagged ones only. A card
        the user flagged another colour keeps it (`flag_kept` counts them); one already purple needs
        nothing;
      * `suspend` — every target card (the scope holds unsuspended cards only).
    """
    if not is_active(opts):
        return {}
    excluded, taken = set(exclude or ()), set(taken_off or ())
    gone = set(out or ())               # P4.1 L2: a taken-out item's card is `plan_out`'s, never also "later"'s
    # A card of a *Study its cards first* item is never "not on your list" (E1.1 03 §8): a finished
    # show's words leave the list, and without this its cards would be the first a run tags or suspends.
    cards = [row for row in order or []
             if getattr(row, "pinned", None) is None and row.card_id not in gone
             and (row.card_id in taken
                  or (row.card_id not in excluded and row.tier not in PLACED_WITH_LIST
                      and not match.lookup(row.word or "", marks_of or {}, language)))]
    note_of = {row.card_id: row.note_id for row in cards}
    tagging = opts.get("tag") or opts.get("suspend")
    tag = later_tag(parent) if tagging else ""
    tag_notes = []
    if tagging:
        for note_id in sorted({note for note in note_of.values() if isinstance(note, int)}):
            existing = ((notes or {}).get(note_id) or {}).get("tags") or []
            if not touchup.carries_tag(existing, tag):
                tag_notes.append(note_id)
    flags, kept = {}, 0
    if opts.get("flag"):
        for row in cards:
            before = (flags_of or {}).get(row.card_id) or 0
            if before == 0:
                flags[row.card_id] = 0
            elif before != FLAG_PURPLE:
                kept += 1
    suspend = sorted(row.card_id for row in cards) if opts.get("suspend") else []
    return _with_counts({"cards": sorted(note_of), "note_of": note_of, "tag": tag,
                         "tag_notes": tag_notes, "flags": flags, "flag_kept": kept,
                         "suspend": suspend})


def has_work(later):
    """Will the run write anything for the cards not on the list?"""
    counts = (later or {}).get("counts") or {}
    return bool(counts.get("tag") or counts.get("flag") or counts.get("suspend"))


def _with_counts(later):
    later["counts"] = {"cards": len(later["cards"]), "tag": len(later["tag_notes"]),
                       "flag": len(later["flags"]), "flag_kept": later["flag_kept"],
                       "suspend": len(later["suspend"])}
    return later
