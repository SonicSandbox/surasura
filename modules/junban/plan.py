# SPDX-License-Identifier: GPL-3.0-or-later
"""Decide where every card lands — the one place the whole feature can go wrong.

Everything else in this module moves data around; this function is the feature. It takes plain
dicts, returns plain data, and touches nothing: no network, no tkinter, no file I/O, no clock. That
is deliberate rather than tidy — a reposition cannot be undone by Anki
(`setSpecificValueOfCard` hardcodes `skip_undo_entry=True`) and it syncs to AnkiWeb and mobile, so
the decision of *which* cards move has to be testable exhaustively against data, with no collection
in the room.

Three properties the algorithm buys, in order of how much they matter:

**Nothing but a new card ever moves.** `type == 0 and queue == 0` is re-checked here, per card, even
though the caller's query already said `is:new -is:suspended`. That query is a *string* interpreted
by Anki's search parser; this is not. Writing `due` on a review card does not fail — it silently
reschedules it to a garbage date, because on a review card `due` is a day number, not a queue
position. The user's existing schedule is sacred (invariants I1/I2), and this check is the only
thing standing in front of it: `setSpecificValueOfCard` is a raw `setattr`, with no check of its own
that the card is new.

**The block stays where it was.** Positions run from `min(due)` over the cards being moved, not from
1. The reordered cards therefore occupy exactly the span of positions they already occupied, so
reordering one deck cannot shove it in front of another deck the user deliberately left behind.

**A second run writes nothing.** Only pairs whose value actually changed are emitted, so pressing
the button twice is free, and "how many cards will change?" is a real number the panel can show
before the first write (invariant I5) rather than a count of cards it happens to be looping over.

Ordering itself is `(rank, due)` for matched cards — rank is Surasura's learn order, and `due`
breaks ties *deterministically* while also clustering several cards of the same word consecutively,
which is the behaviour the feature is for. Unmatched cards keep their existing relative order and
follow the whole matched block, so a card the current list says nothing about is never promoted past
one it ranks. A card the user deselects in the preview joins them (`exclude`, WP-O): it is the same
outcome — no rank, existing order kept, still positioned — rather than a fourth kind of card.
"""

from collections import namedtuple

# One card's place in the finished order. The panel previews these rows — `# | new pos | word |
# rank | deck` — and the preview is the single confirmation the user gets, so it is built from the
# same pass that builds the writes rather than recomputed next to it: a preview derived
# independently is a second implementation of this algorithm, free to disagree with the one that
# writes. `rank` is None for an unmatched card; `changed` is False for a card already in place.
#: `note_id` is carried so the panel can say how many NOTES a run touches without re-deriving
#: touchup's accounting. Appended last: the namedtuple is built by keyword in one place, so a
#: new trailing field costs nothing anywhere else.
#: `tier` says how Surasura placed the card (TIERS, below; None is unplaced, at the back), `sort` is
#: the key it was placed by — kept so `replan` can place it again without re-reading anything —
#: and `why` is the reason in a few words, for the preview ("list #412", "i+1", "known").
#: `fallback` is `(tier, sort, why)` — where a card placed WITH the list would go by its own
#: sentence if the user took it off the list (Junban_Backlog_Spec §13, the user 2026-09-23).
#: `suggestion` is `(key, rank, sort, why)` — the list word the card's word may be, spelled another
#: way, and the place it takes once the user ticks "Same word as one on your list?" (§16).
#: `pinned` is the index of the *Study its cards first* group the card belongs to (`plan`'s `pins`;
#: lifted to the front unless the user clicked it off), None for every other card — and for every
#: card while nothing is pinned, so an unpinned row is the row it always was.
#: `out` (P4.1 L2) is True for a card of an item whose new cards were taken out of the learning order (`plan`'s
#: `out`: placed after every other card), None for every other card — and for every card while nothing is out.
Placement = namedtuple("Placement",
                       "position card_id due word rank deck changed note_id tier sort why fallback "
                       "suggestion pinned out",
                       defaults=(None, None, "", None, None, None, None))

# Junban_Backlog_Spec §5.4, as the user's answers shaped it (§11, §12 item 8): the list's own words
# first, in the journey's order — "anything that IS in our list should come first" (2026-09-23) —
# and among them the phrases the library meets as often as the list's own words ("phrase": the list
# cannot hold a phrase, so it is held to the list's bar), each with its episode's words. A word the
# list cut off joins them ("library") only when the user switches "List first" off. Then the cards
# whose sentence holds no other unknown word (i+1), then those with more, then the rest; the words
# the learner already knows last (D3). A tier's cards go by their `sort`, then `due`.
TIERS = {"list": 0, "library": 0, "phrase": 0, "i+1": 2, "multi": 3, "rest": 4, "known": 5}
# Connect's preview (P1.4, HC-N54): the cards you mined yourself go ahead of every other, in the order you mined them.
TIERS["yours"] = -1


def _exact_int(value):
    """True only for a genuine `int`.

    Two things this rules out, both of which would otherwise sail through a bare `== 0`:
    `True == 1` and `False == 0` in Python, so a JSON payload carrying booleans would read as a card
    type; and a mocked collaborator compares equal to nothing, so a test that hands this function a
    `MagicMock` gets the card *discarded* rather than quietly repositioned (`testing.md` §5.3 — the
    decision has to be made against plain data). Anki sends ints for all four of these fields.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def plan(cards, rank_of, exclude=None, number=None, pins=None, out=None):
    """Work out the new queue positions.

    `cards` is `[{"card_id", "due", "type", "queue", "word", "deck"}]` — one dict per card in scope,
    already joined to its note's word (an empty or unresolvable word is fine, it simply cannot
    match), plus an optional `key`: the list key that word reached, when it is not the word itself
    (`anki_match.lookup`). `rank_of` maps a normalised word to its 0-based rank in
    `results/priority_learning_list.csv`, where the row index *is* the rank.

    **One order for the list and the library (Junban_Backlog_Spec §11.1).** A card may also carry
    `sort`, the journey's own key for its word, and `tier="library"` when that word is in the
    library but below the list's cut-off. Matched and library cards are then sorted together by
    `sort`, so a word the list cut off lands exactly where the journey would meet it. Without
    `sort` a matched card is placed by its rank alone — the order before §11.1.

    `exclude` is the card ids the user clicked off in the preview (WP-O), and what that means
    depends on the card (the user, 2026-09-23: a word clicked off the list is "treated as
    'not-on-your-list'"):

      * a card placed WITH the list that carries a `fallback` — `(tier, sort, why)`, where its own
        sentence would put it — is **taken off the list**: placed by that fallback among the cards
        not on the list, with no rank, so the list's touch-ups pass it by and the not-on-your-list
        actions (`unlisted.py`) reach it. Listed in `stats["taken_off_ids"]`;
      * any other card is **left alone**: it keeps its existing relative order at the back, exactly
        like a card nothing placed. The contiguous block still runs from `min(due)` and nothing is
        left unpositioned.

    `number` is the fast re-plan's preview (E1.1 03): given, it numbers the planned order instead of
    `min(due) + index` — `number(dues)` takes the cards' current positions in the new order and returns
    `(positions, info)` (`spaced.number`), and `stats["numbering"]` carries the `info`. The ORDER is
    decided by the same pass, with one difference: among cards nothing else tells apart, a card made
    since the last spaced run (`number.after`, `spaced.Numbering`) goes after the others — on a spaced
    ladder its position is Anki's counter, below every card on it. None is 2.5's dense block.

    `pins` is *Study its cards first* (G1.6-10; E1.1 03 §8): `[[card_id, …], …]`, one group per pin,
    the oldest pin first (`plan_rules.pin_groups`' order). Every still-new card of a group goes ahead
    of the whole planned order, group by group, and inside a group in the order planned here — the
    same ranking, i+1 first — whatever its tier; then every other card, exactly as planned. A card
    two groups claim goes with the older pin. A card the user clicked off stays off: the click is
    their word for that card. It moves cards, never words or scores, and nothing but the user's own
    pin ever feeds it (no move, finish, Connect or Junban run pins anything). None or empty: today's
    plan, row for row.

    `out` (P4.1 L2, *Take its new cards out*, D14): the card ids of items taken out of the learning order
    (`pins.out_cards`; TF fix 3, P4.1-7: only cards whose words left the list) — a stable partition of the planned
    order with them after every other card, keeping the order just planned among them. A pinned card is never out (a
    pin is the later click), and one the user clicked off stays where the click left it. None or empty: the plan
    as before, row for row.

    Returns `(writes, stats)`:

      * `writes` — `[(card_id, new_due)]`, in new-position order, **only** where `new_due` differs
        from the card's current `due`. Empty is the correct, common answer.
      * `stats` — the counts the panel must state before any write, plus `order`: the full list of
        `Placement` rows for the preview table.
    """
    cards = list(cards or [])
    rank_of = rank_of or {}
    excluded = set(exclude or ())

    movable = []
    skipped_review = 0          # already in the schedule: learning, review or relearning (I1)
    skipped_suspended = 0       # a deliberate user act (I2)
    skipped_other = 0           # buried, in a filtered deck, or missing the fields to decide at all

    for card in cards:
        card_type = card.get("type")
        queue = card.get("queue")

        # Order matters: a *suspended review* card is reported as suspended, because that is the
        # reason the user would recognise. Everything below -1 is buried — temporary, but equally
        # not ours to reposition.
        if _exact_int(queue) and queue == -1:
            skipped_suspended += 1
            continue
        if not (_exact_int(card_type) and card_type == 0):
            skipped_review += 1
            continue
        if not (_exact_int(queue) and queue == 0):
            skipped_other += 1
            continue
        # `due` is the value we sort on and the value we overwrite, and `card_id` is the write
        # target. A card that cannot supply both as real integers is not repositionable, and letting
        # one through would poison `min()`, the sort, or the write itself.
        if not (_exact_int(card.get("due")) and _exact_int(card.get("card_id"))):
            skipped_other += 1
            continue
        movable.append(card)

    matched = []                # (tier order, sort, rank, tier, card) — every card Surasura placed
    unmatched = []
    deselected = []             # WP-O: left alone by the user, in the panel only
    taken_off = []              # ...or taken off the list by the user, to go with the cards not on it
    for card in movable:
        # Checked before the word is even looked up: a clicked-off card is not a card whose rank
        # happens to be unusable, it is one the user made a choice about.
        if card["card_id"] in excluded:
            fallback = card.get("fallback")
            if (isinstance(fallback, (tuple, list)) and len(fallback) == 3
                    and fallback[0] in TIERS and fallback[1] is not None):
                taken_off.append(card["card_id"])
                matched.append((TIERS[fallback[0]], fallback[1], None, fallback[0],
                                dict(card, why=fallback[2])))
            else:
                deselected.append(card)
            continue
        # `key` is the list key the card's word reached (`anki_match.lookup`: a spelling the content
        # used, or the kana fold), when the caller resolved one; otherwise the word itself.
        word = card.get("key") or card.get("word")
        # `rank_of.get` rather than `in` plus an index, and `is None` rather than a truth test:
        # rank 0 is the single most important card in the entire list and is falsy.
        rank = rank_of.get(word) if isinstance(word, str) and word else None
        sort = card.get("sort")
        tier = card.get("tier")
        # Placed by its tier, not its rank: a list word whose sentence waits ("i+1 first", §17), and
        # a word the learner already knows, which goes last whatever else matched it (D3).
        if card.get("held") or tier in ("known", "yours"):
            rank = None
        if rank is not None:
            matched.append((0, sort if sort is not None else (rank,), rank, "list", card))
        elif tier in TIERS and tier != "list" and sort is not None:
            matched.append((TIERS[tier], sort, None, tier, card))
        else:
            unmatched.append(card)

    # The two unranked groups are sorted as ONE block rather than appended one after the other:
    # both mean "keep the order you already had", and splitting them would reshuffle a deselected
    # card past an unmatched one it currently sits behind — a move the user did not ask for by
    # asking for no move at all.
    unranked = unmatched + deselected

    # `card_id` is the final tiebreak on both sorts. It changes nothing when dues differ, but two
    # new cards *can* share a position in Anki, and without it the output would depend on the order
    # `findCards` happened to return — which is `SortOrder.NoOrder`, i.e. arbitrary.
    # With the fast re-plan's numbers, a card made since the last spaced run (`number.after`) goes after
    # the cards nothing else tells it apart from: Anki numbered it at its next-position counter, which a
    # spaced ladder leaves BELOW every card on it — "by current position" alone would put it ahead of
    # every older one, the reverse of 2.5. Every other card keeps its existing order (E2.1 reviews #4, 2 #3).
    after = getattr(number, "after", None)
    if after is None:
        matched.sort(key=lambda entry: (entry[0], entry[1], entry[4]["due"], entry[4]["card_id"]))
        unranked.sort(key=lambda card: (card["due"], card["card_id"]))
    else:
        matched.sort(key=lambda entry: (entry[0], entry[1], entry[4]["card_id"] > after, entry[4]["due"],
                                        entry[4]["card_id"]))
        unranked.sort(key=lambda card: (card["card_id"] > after, card["due"], card["card_id"]))

    ordered = ([(rank, tier, sort, card) for _order, sort, rank, tier, card in matched]
               + [(None, None, None, card) for card in unranked])

    # *Study its cards first*: a stable partition of the planned order — the pinned cards lifted to
    # the front, group by group, each group keeping the order just planned; nothing else moves
    # relative to anything else. Numbered below like any order, so on the spaced ladder the pinned
    # run lands at its front by the same delta a move makes.
    group_of = _groups(pins)
    lift = {card_id: group for card_id, group in group_of.items() if card_id not in excluded}
    if lift:
        first = [entry for entry in ordered if entry[3]["card_id"] in lift]
        first.sort(key=lambda entry: lift[entry[3]["card_id"]])     # stable: the planned order inside
        ordered = first + [entry for entry in ordered if entry[3]["card_id"] not in lift]
    # --- P4.1 L2: *Take its new cards out* — after every other card, the planned order kept among them ---
    gone = {card_id for card_id in (out or ()) if _exact_int(card_id)} - set(lift) - excluded
    if gone:
        ordered = ([entry for entry in ordered if entry[3]["card_id"] not in gone]
                   + [entry for entry in ordered if entry[3]["card_id"] in gone])
    # --- end P4.1 L2 ---

    # The existing minimum, not 1 — see the module docstring. Taken over the cards actually being
    # moved: a review card's `due` is a day number and would drag the base into nonsense.
    base = min(card["due"] for card in movable) if movable else None

    # The fast re-plan's preview numbers the same order on its spaced ladder (`spaced.number`); off,
    # `base + index` exactly as before.
    numbering = None
    if number is not None and ordered:
        positions, numbering = number([card["due"] for _rank, _tier, _sort, card in ordered])
    else:
        positions = [base + index for index in range(len(ordered))]

    writes = []
    order = []
    for index, (rank, tier, sort, card) in enumerate(ordered):
        new_due = positions[index]
        changed = new_due != card["due"]
        if changed:
            writes.append((card["card_id"], new_due))
        # Only a placed card has a reason; a deselected one is "your choice", not its old tier's.
        why = (card.get("why") or (f"list #{rank + 1:,}" if tier == "list" else tier)) if tier else ""
        order.append(Placement(position=new_due,
                               card_id=card["card_id"],
                               due=card["due"],
                               word=card.get("word"),
                               rank=rank,
                               deck=card.get("deck"),
                               changed=changed,
                               note_id=card.get("note"),
                               tier=tier,
                               sort=sort,
                               why=why,
                               fallback=card.get("fallback"),
                               suggestion=card.get("suggestion"),
                               pinned=group_of.get(card["card_id"]),
                               out=True if card["card_id"] in gone else None))

    tiers = {name: 0 for name in TIERS if name != "yours"}     # "yours" only when a card is (Connect's preview)
    for _order, _sort, _rank, tier, _card in matched:
        tiers[tier] = tiers.get(tier, 0) + 1
    stats = {
        "total": len(cards),                    # everything handed in, before any filtering
        "considered": len(movable),             # new + unsuspended: the cards this run may touch
        "matched": tiers["list"],               # ...of which the current list can order
        "library": tiers["library"],            # ...and the library places, below its cut-off
        "tiers": tiers,                         # every tier's count, for the panel's stats line
        "unmatched": len(unmatched),            # ...and which keep their order at the back
        # Counted apart from `unmatched` even though they are placed identically: one number is the
        # list's answer, the other is the user's, and adding them together would report their own
        # choice back to them as a shortfall (WP-O).
        "deselected": len(deselected) + len(taken_off),
        "taken_off": len(taken_off),            # ...of which taken off the list, to go with the rest
        "taken_off_ids": taken_off,
        "skipped": skipped_review + skipped_suspended + skipped_other,
        "skipped_review": skipped_review,
        "skipped_suspended": skipped_suspended,
        "skipped_other": skipped_other,
        "to_write": len(writes),                # the number the confirmation must state (I5)
        "unchanged": len(movable) - len(writes),
        "base": base,                           # None when there is nothing to move
        "order": order,                         # Placement rows, for the preview table
    }
    if numbering is not None:
        stats["numbering"] = numbering          # the preview's spaced numbers: kind, base, windows
    if group_of:
        # Only when something is pinned, so a plan with no pin returns what it always returned.
        stats["pinned"] = sum(1 for row in order if row.card_id in lift)
    if gone:
        stats["out"] = sum(1 for row in order if row.out)     # P4.1 L2: only when something is out
    return writes, stats


def _groups(pins):
    """`{card_id: group index}` for `plan`'s `pins` — the first (oldest) group claiming a card keeps
    it. A clicked-off card stays a member (never "not on your list") but isn't lifted (`plan`).
    Anything that isn't a list of groups of real ids is no pin."""
    group_of = {}
    for index, group in enumerate(pins or ()):
        if isinstance(group, (str, bytes)):
            continue
        for card_id in group or ():
            if _exact_int(card_id) and card_id not in group_of:
                group_of[card_id] = index
    return group_of


def replan(order, exclude=None, number=None, pins=None, out=None):
    """Re-decide an order that has already been planned, with `exclude` taken out of the run.

    WP-O. The panel needs the new order the instant a row is deselected, and it cannot read Anki
    again for it — that is slow, and the answer has to describe the same cards the preview on screen
    does. So the `Placement` rows are turned back into the card dicts they came from and handed to
    `plan` itself: the preview after a toggle is produced by the very function that produces the
    writes, rather than by a second sort living next to it and free to disagree (invariant I5).

    `type` and `queue` are restored as `0`, which is not an assumption: a card only becomes a
    `Placement` by passing those checks in the first place. `number`: the run's own numbering (the
    fast re-plan's preview, `plan`), so the preview after a click is numbered as the run will be.
    `pins`: the run's *Study its cards first* groups; None takes them from the rows themselves
    (`Placement.pinned`), so a click keeps the pinned cards first exactly as the run will.
    """
    rows = list(order or [])
    if pins is None:
        groups = {}
        for row in rows:
            if row.pinned is not None:
                groups.setdefault(row.pinned, []).append(row.card_id)
        pins = [groups[index] for index in sorted(groups)]
    if out is None:                     # P4.1 L2: the taken-out cards stay last after a click, as the run places them
        out = {row.card_id for row in rows if getattr(row, "out", None)}
    # `note` too: the touch-ups are planned per NOTE, and a row that lost its note id counted as no
    # note at all — the confirmation then promised 0 tagged / 0 overwritten after a single click,
    # while the run went on to tag and overwrite them. `tier`, `sort` and `why` too: a card the list
    # does not rank has only them, and without them it would fall to the back on the first click.
    cards = [{"card_id": row.card_id, "due": row.due, "type": 0, "queue": 0,
              "word": row.word, "deck": row.deck, "note": row.note_id,
              "tier": row.tier, "sort": row.sort, "why": row.why,
              "fallback": row.fallback, "suggestion": row.suggestion} for row in rows]
    # Only the words in scope, which is all the rows in scope can need. A word is either ranked in
    # every row that carries it or in none of them, so this cannot disagree with the real index.
    rank_of = {row.word: row.rank for row in rows
               if row.rank is not None and isinstance(row.word, str) and row.word}
    return plan(cards, rank_of, exclude=exclude, number=number, pins=pins, out=out)


def with_answers(order, ticked):
    """The rows as they stand once the user has ticked, or unticked, "Same word as one on your
    list?" (Junban_Backlog_Spec §16) — to hand to `replan`, so the preview after a tick comes from
    the planner itself, like a click in the table (WP-O).

    `ticked` is `{card_word: True | False}`. A row carrying a `suggestion` that is ticked takes the
    list word's place — its rank, its journey `sort`, "list #958 · you matched it" — and keeps where
    its sentence put it as its `fallback`, so clicking it off the list still works (§13). One that
    was matched (placed with the list by an earlier "yes") and is now unticked goes back to that
    fallback. Every other row is returned as it is. The run reaches the same places by reading the
    answers the panel records when Reorder is pressed (I5).
    """
    rows = []
    for row in order or []:
        want = (ticked or {}).get(row.word)
        if row.suggestion and want is True and row.tier != "list":
            _key, rank, sort, why = row.suggestion
            row = row._replace(rank=rank, tier="list", sort=sort, why=why,
                               fallback=(row.tier, row.sort, row.why))
        elif row.suggestion and want is False and row.tier == "list" and row.fallback:
            tier, sort, why = row.fallback
            row = row._replace(rank=None, tier=tier, sort=sort, why=why, fallback=None)
        rows.append(row)
    return rows


# --- Try it on my cards (backlog onboarding, 2026-10-29; Sonic's idea, the lead's lean, PROVISIONAL) ------------ #
TRY_CARDS = 5           # the next cards you'll meet *Try it* moves (tracks/pipeline/work/backlog-onboarding/scope.md)
TRY_NO_ROOM = ("Your next cards can't be put first without moving many others, so nothing was changed. Reorder "
               "places every card.")


def try_front(order, count=TRY_CARDS, floor=1, ceiling=999_999):
    """*Try it on my cards*: `(writes, front)` — the plan's first `count` cards moved to the front of the scope's new
    cards, in the plan's order, and as little else as can be. `order` is `[(card_id, due)]`: every new card in scope,
    in the PLANNED order (the preview's rows), each at its current number. `front` is the cards' ids, `writes` the
    `(card_id, new_due)` that change — empty when they're already first, in order.

    * Already below every other card: they swap numbers among themselves (none of the others moves).
    * Else, with room below the lowest other card (`floor` … that card − 1): they take the numbers just under it.
    * Else (a deck numbered from 1): they take the `count` lowest numbers, and the cards that held those take theirs,
      lowest first — at most 2 × `count` cards move, every one of them in the snapshot.

    Every number stays in `floor` … `ceiling` (spaced's bounds: Check Database folds 1,000,000 and up). A layout that
    would still leave one of the others level with or ahead of the last of them (cards that share a number, a note's
    siblings) raises `ValueError(TRY_NO_ROOM)`: nothing is written. Pure, like `plan`."""
    pairs = [(card_id, due) for card_id, due in order or () if _exact_int(card_id) and _exact_int(due)]
    count = min(max(int(count or 0), 0), len(pairs))
    front, rest = pairs[:count], pairs[count:]
    ids = [card_id for card_id, _due in front]
    if not front:
        return [], ids
    low = min((due for _id, due in rest), default=ceiling + 1)
    new = {}
    own = _rising(sorted(due for _id, due in front))
    if own[-1] < low:
        new.update(zip(ids, own))
    elif low - floor >= count:
        new.update((card_id, low - count + i) for i, card_id in enumerate(ids))
    else:
        lowest = sorted(range(len(pairs)), key=lambda i: (pairs[i][1], i))[:count]
        new.update(zip(ids, _rising(sorted(pairs[i][1] for i in lowest))))
        vacated = sorted(due for i, (_id, due) in enumerate(front) if i not in set(lowest))
        displaced = [pairs[i][0] for i in lowest if i >= count]
        new.update(zip(displaced, vacated))
    final = dict(pairs)
    final.update(new)
    ahead = [final[card_id] for card_id in ids]
    others = [final[card_id] for card_id, _due in rest]
    if (any(b <= a for a, b in zip(ahead, ahead[1:])) or (others and ahead[-1] >= min(others))
            or any(not floor <= due <= ceiling for due in new.values())):
        raise ValueError(TRY_NO_ROOM)
    return [(card_id, new[card_id]) for card_id, due in pairs if card_id in new and new[card_id] != due], ids


def _rising(values):
    """`values` (ascending) made strictly increasing: a tie is moved one up."""
    out = []
    for value in values:
        out.append(value if not out or value > out[-1] else out[-1] + 1)
    return out
