# SPDX-License-Identifier: GPL-3.0-or-later
"""The only undo there is — `User Files/<lang>/junban_undo.json`.

AnkiConnect's `setSpecificValueOfCard` calls into the backend with `skip_undo_entry=True`
hardcoded, so a run that repositions 152 cards produces **zero** Anki undo entries. Anki's own
Undo must never be offered as the way back: `guiUndo` would revert whatever the user did *before*
the run — the note they just edited, the cards they just suspended — and leave every one of our
`due` writes in place, which is worse than doing nothing. So the snapshot below is the recovery
path, and invariant I3 says it reaches disk **before the first write of a run**, not after it.

What it holds is deliberately tiny — `{card_id: original_due}` plus the scope it was taken for:

```json
{"schema":1,"written_at":"2026-09-17T22:00:00","scope":["TheBank"],"cards":{"1789711432547":2832}}
```

Three rules this file exists to keep:

* **Never destructive.** The write is atomic (`.tmp` + `os.replace`), and a snapshot that will not
  parse is moved aside rather than replaced — mirroring `modules/reels/state.py`. Overwriting it
  would throw away the user's only route back to their original queue, and they would not find out
  until they pressed *Undo the last reorder* and got nothing.
* **It does not write to Anki.** Restoring means replaying the saved values through the same
  transport that made the mess; this module hands those pairs back and stops there. Keeping the
  snapshot free of the network is what lets it be tested without a collection anywhere near it.
* **A snapshot is only valid for the scope it was taken for.** Replaying `TheBank`'s positions into
  a run over every deck would write positions for cards that were never in the snapshot's scope,
  so a mismatch is refused with a message naming both scopes rather than half-applied.

WP-L's second section
---------------------
The optional touch-ups (a tag, a frequency entry) write **note content**, which
is a different class of damage from a queue position: a wrong `due` is annoying, a clobbered
`Glossary` is gone. So the same file grew two optional keys beside `cards`:

```json
{"fields": {"1789711432547": {"Frequency": {"before": "<ul><li>JPDBv2㋕: 54614</li></ul>",
                                            "after":  "<ul><li>JPDBv2㋕: 54614</li><li>Surasura: 42</li></ul>"}}},
 "tags": [1789711432547], "tag": "Surasura"}
```

Both `before` and `after` are kept, because restoring has to tell "junban put this here" apart from
"the user has edited it since" — and a field they have edited since is **never** reverted, only
counted and reported. `SCHEMA` is deliberately NOT bumped: these keys are additive and absent from
an ordinary reorder's snapshot, and a bump would make `restore_pairs` refuse every snapshot already
on a user's disk.

The cards NOT on the list (Junban_Backlog_Spec §13) add two more, on the same terms: `"suspended":
[card_id]` — the cards Junban suspended, and only those, so a restore never unsuspends one the user
suspended — and `"flags": {"<card_id>": flag_before}`. Their `Surasura::later` tag rides in
`marker_tags`, which already takes exactly one tag back off exactly the notes it went on.

Connect's runs (P1.4 row 1.4.2)
-------------------------------
A run Connect starts (`surasura-cli junban --auto`, `surasura-cli backfill`, while the preview is on) keeps a snapshot
of its own, never the window's: `<local data>/connect/junban-runs/<lang>/<run id>.json`, beside Connect's ledger, the
last `KEEP_RUNS` kept (K39). Same protocol — saved incomplete before the first write, completed after, and no run of
the same kind starts while one is incomplete (`unfinished`; the window's Reorder and Fill ask too) — and the same keys,
with two more: `after` (`{card_id: due}`, what the run wrote: a restore puts a position back only while the card still
holds it, so a later run's or your own move is never undone) and `unsuspended` (the returning words' cards it
unsuspended, MR-R3: a restore suspends them again). `cards` holds only the cards the run moved: "exactly what that run
changed".

Today's baseline (the fast re-plan's preview, E1.1 03 §5)
---------------------------------------------------------
With the preview on, Junban re-orders Anki on every move, after every Generate and at every catch-up —
far too often for each automatic write to take this file over, and an automatic write must never be
a reason to refuse anything. So the automatic re-orders keep **today's baseline** in a file of their
own, `junban_replan_baseline.json` (same folder, same shape, plus `day`, Anki's day): written before
the first automatic write of the day, never rewritten by later ones that day. *Undo the last reorder*
puts back the newer of the two (`restorable`): this file's snapshot from a manual run, or today's
baseline — the order your cards had before today's first automatic re-order. A manual run or a Restore
ends today's baseline (`end_baseline`); the next automatic write starts a new one. A manual run keeps
this file's protocol exactly (I3). 2.x-dev keeps I3 for every run; 3.0: an automatic run with actions marks the
snapshot it saves here (`"automatic": true`), and once cut by Anki closing it never stops the automation — the next
automatic job goes on, and the next one with an action to write takes it over (`save(cut=)`).

Beside it, `junban_ladder.json` remembers the bottom of each deck's spaced ladder (`ladder_floor`,
E2.1-1): taken afresh from the lowest current number, the bottom would climb with every card studied.
A run Connect starts while the fast re-plan's preview is on keeps both: today's baseline, and its own run
snapshot (the only way back from that run, so an unfinished one still refuses the next).

Paths resolve through `app.path_utils`, imported **inside** the functions: the tests' autouse
fixture redirects those names by patching `app.path_utils`, and a module-level binding would not be
reached by that patch (`docs/agent instructions/testing.md` §5.2). Keeping them deferred also keeps
this module cheap to import.
"""

import json
import os
import time

SCHEMA = 1
FILENAME = "junban_undo.json"
# The Anki Backfill window keeps its own snapshot beside the reorder's, so a fill and a reorder can
# never overwrite each other's way back (Patterns_Spec §8 P4). Same format, same protocol; its
# `cards` map is simply empty — a fill moves no card.
FILENAMES = {"reorder": FILENAME, "backfill": "junban_backfill_undo.json",
             "baseline": "junban_replan_baseline.json"}     # today's baseline (03 §5)
KEEP_RUNS = 20                  # Connect's runs: the last 20 snapshots kept (K39)
RUNS_FOLDER = "junban-runs"
LADDER_FILENAME = "junban_ladder.json"      # each deck's spaced ladder's bottom (E2.1-1)
# Anki's day begins at its rollover hour, 4 a.m. unless changed; AnkiConnect can't read the collection's
# own setting, so today's baseline follows Anki's default.
ROLLOVER_HOURS = 4


class RestoreRefused(Exception):
    """A restore that must not go ahead — wrong scope, unreadable format, or nothing saved at all.

    Carries a human-readable message because it is shown to the user verbatim: a restore is the one
    operation they reach for when something has already gone wrong, and "refused" without "for
    which deck" leaves them guessing. Refusing beats half-applying: replaying one deck's positions
    into another run writes real positions into cards the snapshot never covered.
    """


def snapshot_path(language="ja", kind="reorder", run_id=None):
    """Where the snapshot lives. Language-isolated like every other user file; `kind` is "reorder"
    (順) or "backfill" (the Anki Backfill window). With `run_id`, one of Connect's runs (`runs_folder`)."""
    if run_id is not None:
        return os.path.join(runs_folder(language), _run_name(run_id) + ".json")
    from app.path_utils import get_user_files_path
    return os.path.join(get_user_files_path(language), FILENAMES[kind])


def runs_folder(language="ja"):
    """Connect's run snapshots for one language, beside its ledger (per install, never under `User Files/`: the
    oldest are let go, K39)."""
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", RUNS_FOLDER, language)


def new_run_id(kind="reorder", language="ja"):
    """A run's id: its kind, the moment it started, to the millisecond, and the process that started it — sorts in the
    order the runs ran (two in one millisecond: the second takes the next number; two processes never share an id,
    though the id is taken before the run holds Anki's writer)."""
    now = time.time()
    stamp, ms = time.strftime('%Y%m%d-%H%M%S', time.localtime(now)), int(now * 1000) % 1000
    while True:
        run_id = f"{kind}-{stamp}-{ms:03d}-{os.getpid()}"
        if not os.path.exists(snapshot_path(language, run_id=run_id)):
            return run_id
        ms += 1


def _run_name(run_id):
    run_id = str(run_id or "")
    if not run_id or not all(ch.isalnum() or ch in "-_" for ch in run_id):
        raise RestoreRefused(f"That isn't a run Junban knows: {run_id!r}.")
    return run_id


def runs(language="ja", kind=None):
    """Connect's run snapshots, newest first: `[(run_id, snapshot)]` (`kind` "reorder" / "backfill" narrows them).
    Newest by the moment the run started (the id after its kind), never by the file's name: every `reorder-` would
    sort above every `backfill-`, and the last 20 kept would be the wrong 20. One that won't parse is moved aside, as
    `load` does, and left out; one that can't be opened just now (another program holds it) counts as unfinished."""
    folder = runs_folder(language)
    try:
        names = sorted((name[:-5] for name in os.listdir(folder) if name.endswith(".json")),
                       key=lambda run_id: (run_id.partition("-")[2], run_id), reverse=True)
    except OSError:
        return []
    out = []
    for run_id in names:
        saved = load(language, run_id=run_id)
        if (saved is None and all(ch.isalnum() or ch in "-_" for ch in run_id)
                and os.path.isfile(os.path.join(folder, run_id + ".json"))):
            # Not quarantined (`load`): held by an antivirus or a cloud folder. Its run may be the one that died, so
            # it refuses the next run until it reads again — never lifted by a file that was only busy.
            saved = {"kind": run_id.partition("-")[0], "complete": False, "unreadable": True}
        if saved is not None and (kind is None or saved.get("kind") == kind):
            out.append((run_id, saved))
    return out


def unfinished(language="ja", kind="reorder"):
    """The newest of Connect's runs of `kind` that never finished (its snapshot still incomplete), or None. A new
    run of that kind — Connect's or the window's — is refused until it is restored (§7.2)."""
    for run_id, saved in runs(language, kind):
        if saved.get("complete") is False:
            return run_id
    return None


def prune_runs(language="ja", keep=KEEP_RUNS):
    """Let the oldest finished run snapshots go, keeping the newest `keep` (K39). Never an unfinished one: it is the
    only way back from a run that died. Returns the run ids let go."""
    gone = []
    for run_id, saved in runs(language)[keep:]:
        if saved.get("complete") is False:
            continue
        try:
            os.remove(snapshot_path(language, run_id=run_id))
            gone.append(run_id)
        except OSError:
            pass
    return gone


def normalize_scope(scope):
    """A scope as it is compared and stored: sorted, de-duplicated, blanks dropped.

    Comparing raw lists would make `["A","B"]` and `["B","A"]` — the same two decks, gathered in
    whatever order `deckNames` happened to return them — look like different runs and refuse a
    perfectly good restore.
    """
    if scope is None:
        return []
    if isinstance(scope, str):
        scope = [scope]
    return sorted({str(name).strip() for name in scope if str(name).strip()})


def save(pairs, scope, language="ja", fields=None, tags=None, tag="", marker_tags=None,
         mode="deck", suspended=None, flags=None, kind="reorder", run_id=None, after=None, unsuspended=None,
         automatic=False, cut=None, profile=None, later_back=None, tried=None, finished_automatic=False):
    """Write the snapshot and return its path. Call this BEFORE the first write of a run (I3).

    The snapshot is saved INCOMPLETE and only `mark_complete` says the run finished. A run that died
    halfway leaves it incomplete, and `reposition.run` then refuses to start another until it is
    restored: the next run's snapshot would otherwise record the half-written order and replace the
    only copy of how the deck really was. `mode` is the scope mode ("deck" / "all"); see
    `restore_pairs` for why "all" is recorded.

    `pairs` is whatever describes the cards about to be touched — a mapping, or an iterable of
    `(card_id, original_due)`. Values are stored as ints: `due` is an int32 protobuf field, and a
    string replayed through `setSpecificValueOfCard` fails silently with `error: null`, leaving the
    wrong position in place.

    `fields`, `tags` and `tag` are WP-L's second section and are **optional**: a run with every
    touch-up off writes exactly the file it always did. They are additive rather than a new schema
    on purpose — bumping `SCHEMA` would make `restore_pairs` refuse every snapshot already sitting
    in a user's `User Files/`, throwing away the one route back from their last reorder.

    `run_id`: one of Connect's runs (P1.4) — its own file (`snapshot_path`), carrying its `run` and `kind`, `after`
    (what it wrote per card) and `unsuspended` (the returning words' cards it unsuspended); the oldest beyond
    `KEEP_RUNS` are let go once it is saved. Without it, the window's snapshot, exactly as before.

    `later_back` (laptop round 8 #50): `{the ::later tag: [note ids]}` — the tag the run takes off the returning
    words' notes it unsuspends (a card back on your list no longer says "not on your list"); a restore puts it back
    on the notes of the cards it sets aside again, before it suspends them (`restore_later_back`).

    `automatic` (3.0): an automatic job with actions saves the window's snapshot — `"automatic": true`, so an
    automatic job that finds it unfinished goes on (`reposition._run`). Additive, like the keys above: a snapshot
    without it reads as manual, so 2.5's files keep I3. `cut`: such a snapshot, unfinished, that this one takes over —
    its values win (`_take_over`), so one Restore undoes both runs; or a list of them (the window's own cut run and one
    of Connect's, lead 2026-11-07), the oldest's values winning.

    `tried` (backlog onboarding, 2026-10-29): *Try it on my cards* — `{card_id: due}`, where it puts each card it moves
    (`cards` holds only those, as a Connect run's does). A later run carries their numbers from before Try it forward
    while they're still there (`carry_forward_tried`), so one Restore after Try it → Reorder puts back the order from
    before Try it. Additive, like the keys above.

    FT (D4, K8): given the open Anki `profile`, what this call itself means to suspend, unsuspend, flag and tag goes in
    the first-touch journal (`first_touch.note`) BEFORE the snapshot is written — a journal that can't be written
    raises `OSError` as a snapshot that can't be saved does, so nothing is written to Anki and no snapshot is left
    unfinished. Only this call's own values, never a cut run's (`cut`: journalled when that run saved). Fields are
    journalled by the caller, which alone knows what it writes (`fields` carries earlier snapshots' too).
    """
    if profile is not None:
        _journal(language, kind, profile, scope, tags, tag, marker_tags, suspended, flags, unsuspended)
    payload = {
        "schema": SCHEMA,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scope": normalize_scope(scope),
        "cards": {str(int(card_id)): int(due) for card_id, due in _as_pairs(pairs)},
        "complete": False,
    }
    if mode == "all":
        payload["mode"] = "all"

    # Only written when there is something to write, so an ordinary reorder's snapshot is unchanged
    # from the one previous versions produced and reads identically by eye.
    saved_fields = _clean_fields(fields)
    if saved_fields:
        payload["fields"] = saved_fields
    saved_tags = _clean_tag_notes(tags)
    if saved_tags and str(tag or "").strip():
        payload["tags"] = saved_tags
        payload["tag"] = str(tag).strip()
    # WP-N's hierarchical marker tags, kept as their own map rather than folded into `tags`: each
    # one went on a different subset of the notes, and a restore has to take exactly the right tag
    # off exactly the right notes — never `Surasura::star` off a word junban only marked 📖.
    saved_markers = _clean_marker_tags(marker_tags)
    if saved_markers:
        payload["marker_tags"] = saved_markers
    # §13, the cards not on the list: which ones Junban suspended (so a restore unsuspends exactly
    # those, never one the user suspended), and each flagged card's flag before Junban's purple.
    saved_suspended = _clean_card_ids(suspended)
    if saved_suspended:
        payload["suspended"] = saved_suspended
    saved_flags = _clean_flags(flags)
    if saved_flags:
        payload["flags"] = saved_flags
    if run_id is not None:
        payload["run"], payload["kind"] = _run_name(run_id), kind
        payload["after"] = {str(int(card_id)): int(due) for card_id, due in _as_pairs(after or {})}
    # MR-R3 (Connect's preview): the returning words' cards this run unsuspends, so a restore sets them aside again.
    saved_back = _clean_card_ids(unsuspended)
    if saved_back or run_id is not None:
        payload["unsuspended"] = saved_back
    saved_later = _clean_marker_tags(later_back)
    if saved_later:
        payload["later_back"] = saved_later
    if automatic:
        payload["automatic"] = True
    if finished_automatic:              # Disc-T1: a run you started took over an automatic one cut short — its Undo
        payload["finished_automatic"] = True        # puts back both, and says so (`junban_view.restore_question`)
    if tried:
        payload["tried"] = {str(int(card_id)): int(due) for card_id, due in _as_pairs(tried)}
    cuts = [c for c in (cut if isinstance(cut, (list, tuple)) else [cut]) if c]
    for earlier in sorted(cuts, key=lambda c: c.get("written_at") or "", reverse=True):
        _take_over(payload, earlier)        # newest first: the oldest run's values win, as the order before them

    path = snapshot_path(language, kind, run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)             # atomic: an interrupted save cannot truncate the undo
    if run_id is not None:
        prune_runs(language)
    return path


def _journal(language, kind, profile, scope, tags, tag, marker_tags, suspended, flags, unsuspended):
    """`save`'s first-touch journal line (FT D4): the values handed in, cleaned as the snapshot cleans them."""
    from modules.junban import first_touch
    from modules.junban.unlisted import FLAG_PURPLE
    added = dict(_clean_marker_tags(marker_tags))
    tag = str(tag or "").strip()
    if tag and _clean_tag_notes(tags):
        added[tag] = sorted(set(added.get(tag) or []) | set(_clean_tag_notes(tags)))
    first_touch.note(language, kind, profile, scope, suspended=_clean_card_ids(suspended),
                     unsuspended=_clean_card_ids(unsuspended),
                     flags={card_id: [before, FLAG_PURPLE] for card_id, before in _clean_flags(flags).items()},
                     tags=added)


def _take_over(payload, cut):
    """`payload` takes over `cut`, an automatic run's snapshot left unfinished (3.0): the cut run's values win. Every
    card's original due from either (the cut's where both hold it), the union of what each suspended, tagged and
    unsuspended, and each card's flag from before the cut run. `fields` come already carried
    (`carry_forward_fields`). A tag of another name than this run's is kept with the marker tags, which a restore
    takes off exactly the same way."""
    payload["cards"].update(cut.get("cards") or {})
    for key in ("suspended", "unsuspended"):
        merged = sorted(set(payload.get(key) or []) | set(_clean_card_ids(cut.get(key))))
        if merged:
            payload[key] = merged
    flags = dict(payload.get("flags") or {}, **_clean_flags(cut.get("flags")))
    if flags:
        payload["flags"] = flags
    later = {name: list(ids) for name, ids in (payload.get("later_back") or {}).items()}
    for name, ids in _clean_marker_tags(cut.get("later_back")).items():
        later[name] = sorted(set(later.get(name) or []) | set(ids))
    if later:
        payload["later_back"] = later
    markers = {name: list(ids) for name, ids in (payload.get("marker_tags") or {}).items()}
    for name, ids in _clean_marker_tags(cut.get("marker_tags")).items():
        markers[name] = sorted(set(markers.get(name) or []) | set(ids))
    cut_tag, cut_notes = str(cut.get("tag") or "").strip(), _clean_tag_notes(cut.get("tags"))
    if cut_tag and cut_notes:
        if payload.get("tag", cut_tag) == cut_tag:
            payload["tags"] = sorted(set(payload.get("tags") or []) | set(cut_notes))
            payload["tag"] = cut_tag
        else:
            markers[cut_tag] = sorted(set(markers.get(cut_tag) or []) | set(cut_notes))
    if markers:
        payload["marker_tags"] = markers


def mark_complete(language="ja", kind="reorder", run_id=None, restored=False, after=None, taken_over=False,
                  finished_automatic=False):
    """Record that the run (or restore) this snapshot belongs to finished cleanly. Returns success.

    Best-effort and atomic. Failing leaves the snapshot marked incomplete, which only ever errs on
    the safe side: the next run asks for a Restore first instead of overwriting it. `restored`: one of
    Connect's runs was put back (`restored_at`), so it is never offered again. `after`: one of Connect's
    runs wrote fewer cards than it planned (the fast re-plan's re-check left some, E2.1) — what it did write.
    `taken_over`: one of Connect's runs left unfinished, taken over by an automatic job's window snapshot.
    `finished_automatic`: a cut automatic run's snapshot that a run you started finished with nothing left to write
    (Disc-T1): its Undo is both."""
    path = snapshot_path(language, kind, run_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return False
        data["complete"] = True
        if restored:
            data["restored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if taken_over:              # its way back is now the window's snapshot that took it over (`reposition._run`)
            data["taken_over_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if finished_automatic:
            data["finished_automatic"] = True
        if after is not None and run_id is not None:
            data["after"] = {str(int(card_id)): int(due) for card_id, due in _as_pairs(after)}
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        return True
    except (OSError, ValueError):
        return False


def carry_forward_fields(previous, fields):
    """`fields` for the next snapshot, with each field's TRUE original kept across runs.

    A field junban overwrote last time (the FreqSort number, say) now holds junban's own value, and
    a new run would record THAT as "before" — so after any later run the user's own value existed
    nowhere, though the panel promises Restore puts it back. So:

      * a field this run touches again keeps the earlier original, when the earlier snapshot shows it
        still holding what junban wrote;
      * a field this run leaves alone keeps its earlier entry outright — otherwise its original would
        vanish with the old snapshot just because the value didn't need to change.

    Unlike card positions (derived, and undone one run at a time), a field's original is the user's
    own data. Carrying it is safe because `restore_fields` only ever writes a field back while it
    still holds exactly junban's value, and leaves anything the user has edited since alone."""
    carried = _clean_fields(fields)
    earlier = _clean_fields((previous or {}).get("fields"))
    for note_id, changes in carried.items():
        for field, change in changes.items():
            old = earlier.get(note_id, {}).get(field)
            if old and change["before"] == old["after"]:
                change["before"] = old["before"]
    for note_id, changes in earlier.items():
        for field, old in changes.items():
            carried.setdefault(note_id, {}).setdefault(field, dict(old))
    return carried


def carry_forward_tried(previous, pairs):
    """`pairs` (`[(card_id, due)]`, a run's cards at their numbers now) with each card *Try it on my cards* moved — and
    still holds the number it gave it — at its number from before Try it (`previous`: the window's snapshot, a Try's
    while it's the last). A card moved since (Restore, a review, you) keeps the number it has now: carried only while
    it's exactly where Try it left it, as `carry_forward_fields` carries a field."""
    tried = (previous or {}).get("tried")
    if not isinstance(tried, dict) or not tried:
        return list(pairs)
    before = previous.get("cards") or {}
    out = []
    for card_id, due in pairs:
        key = str(card_id)
        if key in tried and key in before and tried[key] == due and _whole(before[key]):
            due = int(before[key])
        out.append((card_id, due))
    return out


def has_reordered(language="ja"):
    """Has this language's deck been reordered — a window snapshot on disk that isn't only *Try it*'s, today's
    baseline (an automatic re-order) or the spaced ladder's record (any spaced run: the window's, the automatic one,
    Connect's)? (The backlog's picture shows only before the first, Sonic 2026-10-29.) Read raw, never through `load`
    (a preview holds no lock: a file another writer is replacing must never be moved aside). A file that won't read
    counts as one: a picture shown again is worse than one missed."""
    from app.path_utils import get_user_files_path
    folder = get_user_files_path(language)
    if any(os.path.exists(os.path.join(folder, name)) for name in (FILENAMES["baseline"], LADDER_FILENAME)):
        return True
    path = snapshot_path(language)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, ValueError):
        return True
    return not (isinstance(snapshot, dict) and snapshot.get("tried"))


def newer_baseline(language, snapshot):
    """Is today's baseline newer than `snapshot` (the window's)? An automatic re-order wrote after it then."""
    baseline = load(language, "baseline")
    return bool(snapshot and baseline
                and (baseline.get("written_at") or "") > (snapshot.get("written_at") or ""))


def tried_pairs(snapshot, pairs, current):
    """`(pairs, moved_on)`: a Try's snapshot (`tried`) puts back only the cards still where Try it put them
    (`current`: `{card_id: due}` now); the others are left where they are and listed. Any other snapshot: `pairs` as
    they are."""
    tried = (snapshot or {}).get("tried")
    if not isinstance(tried, dict) or not tried:
        return pairs, []
    keep, moved_on = [], []
    for card_id, due in pairs:
        (keep if tried.get(str(card_id)) == current.get(card_id) else moved_on).append((card_id, due))
    return keep, [card_id for card_id, _due in moved_on]


def load(language="ja", kind="reorder", run_id=None):
    """The saved snapshot, or `None` when there is none. Never raises, never destroys.

    A file that will not parse — or that parses into something this code cannot replay — is
    quarantined and reported as absent, so the caller degrades to "no previous order to restore"
    instead of inheriting half a snapshot. `run_id`: one of Connect's runs.
    """
    try:
        path = snapshot_path(language, kind, run_id)
    except RestoreRefused:
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError:
        if run_id is None:
            _quarantine(path)
        return None             # a run's snapshot another program holds is kept: `runs` counts it unfinished
    except ValueError:
        _quarantine(path)
        return None

    if not _is_replayable(data):
        _quarantine(path)
        return None
    data.setdefault("schema", SCHEMA)
    data["scope"] = normalize_scope(data.get("scope"))
    # WP-L's second section, sanitised rather than validated: a malformed `fields` block must never
    # quarantine a snapshot whose `cards` map is perfectly good. The positions are the part a user
    # cannot reconstruct by hand; losing them to a typo in an optional section would be the exact
    # destruction this file exists to prevent.
    data["fields"] = _clean_fields(data.get("fields"))
    data["tags"] = _clean_tag_notes(data.get("tags"))
    data["tag"] = str(data.get("tag") or "").strip()
    if not data["tag"]:
        data["tags"] = []               # no tag name means nothing we could take back off
    data["marker_tags"] = _clean_marker_tags(data.get("marker_tags"))
    data["suspended"] = _clean_card_ids(data.get("suspended"))
    data["flags"] = _clean_flags(data.get("flags"))
    if run_id is not None:
        data["after"] = {key: due for key, due in (data.get("after") or {}).items()
                         if _is_int_key(key) and isinstance(due, int) and not isinstance(due, bool)}
    if run_id is not None or "unsuspended" in data:
        data["unsuspended"] = _clean_card_ids(data.get("unsuspended"))
    if "later_back" in data:
        data["later_back"] = _clean_marker_tags(data.get("later_back"))
    return data


def restore_pairs(snapshot, scope, existing_ids=None, mode="deck"):
    """The `[(card_id, due)]` that puts the scope back as it was. **This module writes nothing.**

    `mode="all"` against a snapshot also taken for "All decks" skips the deck-list comparison. That
    list is "every deck that still holds a new card", and it changes the moment the user finishes a
    small deck's last new card or a miner creates a deck — which left no way to restore at all. The
    card-id filter below already confines the writes to cards that are still new and in scope.

    The caller (WP-G, through WP-C) owns the transport; handing back plain data keeps the one file
    that guards against a bad reposition testable without a collection in reach.

    `existing_ids`, when given, is the set of card ids the run actually found in Anki. Cards absent
    from it are dropped: a note deleted since the snapshot was taken would otherwise be written to
    by id, and a stale id is a write we cannot reason about. They come back in `skipped` so the
    panel can say how many rather than quietly restoring fewer cards than it promised.

    Raises `RestoreRefused` when the snapshot belongs to another scope, or carries a schema this
    version cannot replay.
    """
    check_restorable(snapshot, scope, mode)
    present = None if existing_ids is None else {int(card_id) for card_id in existing_ids}
    pairs, skipped = [], []
    for raw_id, due in (snapshot.get("cards") or {}).items():
        card_id = int(raw_id)
        if present is not None and card_id not in present:
            skipped.append(card_id)
            continue
        pairs.append((card_id, int(due)))

    # Ascending by the position being restored, so a partial run that dies halfway has still put the
    # front of the queue — the cards the user sees first — back where it belongs.
    pairs.sort(key=lambda pair: (pair[1], pair[0]))
    return pairs, sorted(skipped)


def check_restorable(snapshot, scope, mode="deck"):
    """Raise `RestoreRefused` unless `snapshot` may be replayed into `scope` — the refusals of
    `restore_pairs`, on their own, so a restore can ask BEFORE its first write (it unsuspends cards
    before it can even see their positions)."""
    if not snapshot:
        raise RestoreRefused("There is no saved order to restore — Junban has not repositioned any "
                            "cards yet.")

    stored_schema = snapshot.get("schema", SCHEMA)
    if stored_schema != SCHEMA:
        raise RestoreRefused(
            f"That saved order was written by a newer version of Junban (format {stored_schema}, "
            f"this version reads {SCHEMA}). It has been left untouched.")

    saved_scope = normalize_scope(snapshot.get("scope"))
    asked_scope = normalize_scope(scope)
    every_deck = mode == "all" and snapshot.get("mode") == "all"
    if saved_scope != asked_scope and not every_deck:
        raise RestoreRefused(
            "That saved order was taken for a different scope, so restoring it here would write "
            "positions into the wrong deck.\n\n"
            f"Saved for: {', '.join(saved_scope) or '(nothing)'}\n"
            f"Restoring: {', '.join(asked_scope) or '(nothing)'}")


def restore_later_back(snapshot, notes):
    """Laptop round 8 #50: `{tag: [note ids]}` — the `::later` tag a run took off returning cards' notes, to put back
    on `notes` (the notes of the cards a restore sets aside again) — never on a note whose card stays in."""
    notes = set(notes or ())
    out = {}
    for tag, ids in _clean_marker_tags((snapshot or {}).get("later_back")).items():
        kept = sorted(set(ids) & notes)
        if kept:
            out[tag] = kept
    return out


def restore_suspended(snapshot):
    """The cards Junban suspended (§13), to unsuspend — only ever those it recorded, so a card the
    user suspended themselves stays suspended."""
    return _clean_card_ids((snapshot or {}).get("suspended"))


def restore_flags(snapshot, current, ours):
    """`([(card_id, flag)], skipped)` — each card's flag from before Junban's, put back only while
    the card still carries Junban's own flag `ours`. `current` is `{card_id: flag}` as Anki holds it
    NOW; a card the user has re-flagged since is left alone and counted, as an edited field is, and
    one that is gone is simply absent from `current`."""
    pairs, skipped = [], 0
    for card_id, before in _clean_flags((snapshot or {}).get("flags")).items():
        now = (current or {}).get(int(card_id))
        if now is None:
            continue
        if now == ours:
            if before != ours:
                pairs.append((int(card_id), before))
        elif now != before:
            skipped += 1
    return sorted(pairs), skipped


def restore_fields(snapshot, current):
    """The note edits that put WP-L's field writes back. Returns `(edits, skipped)`.

    `current` is `{note_id: {field: value}}` as the fields stand in Anki **now**; `edits` comes back
    in the same shape, holding only the fields that should be written back.

    Three outcomes per field, and the middle one is the reason this function exists:

      * the value still matches what junban wrote  -> put the prior value back;
      * it already matches the prior value          -> nothing to do, and **not** a skip (a run that
        half-finished never wrote this one);
      * it matches neither                          -> **the user has edited it since**, and it is
        left exactly as it is and counted in `skipped`. Reverting here would destroy something they
        wrote after the run, which is worse than any queue position this module could get wrong.

    A note that no longer exists is simply absent from `current` and is left alone.
    """
    edits, skipped = {}, 0
    for note_id, changes in (_clean_fields(snapshot.get("fields")).items() if snapshot else []):
        note = (current or {}).get(int(note_id))
        if not isinstance(note, dict):
            continue
        for field, change in changes.items():
            if field not in note:
                continue                # the field is gone from the note type; nothing to write into
            now = note.get(field) or ""
            if now == change["after"]:
                if now != change["before"]:
                    edits.setdefault(int(note_id), {})[field] = change["before"]
            elif now != change["before"]:
                skipped += 1
    return edits, skipped


def restore_tag(snapshot, existing_ids=None):
    """`(tag, [note_id])` — junban's own tag, and the notes it was put on. `("", [])` when none.

    Only ever the notes recorded at the time, and only ever a tag this module added: a note that
    already carried the tag was never recorded, so a restore cannot take away a tag the user put
    there themselves.
    """
    if not snapshot:
        return "", []
    tag = str(snapshot.get("tag") or "").strip()
    notes = _clean_tag_notes(snapshot.get("tags"))
    if not tag or not notes:
        return "", []
    if existing_ids is not None:
        present = {int(note_id) for note_id in existing_ids}
        notes = [note_id for note_id in notes if int(note_id) in present]
    return tag, [int(note_id) for note_id in notes]


def restore_marker_tags(snapshot, existing_ids=None):
    """`{tag: [note_id]}` — WP-N's marker tags, and the notes junban put each one on.

    Only ever a tag this module added to that exact note: a note that already carried
    `Surasura::star` was never recorded, so a restore cannot take away a tag the user applied
    themselves.
    """
    if not snapshot:
        return {}
    out = {}
    present = None if existing_ids is None else {int(note_id) for note_id in existing_ids}
    for name, ids in _clean_marker_tags(snapshot.get("marker_tags")).items():
        kept = [int(note_id) for note_id in ids
                if present is None or int(note_id) in present]
        if kept:
            out[name] = kept
    return out


def note_ids(snapshot):
    """Every note the snapshot's second section touches — what `notesInfo` has to be asked for."""
    if not snapshot:
        return []
    ids = {int(note_id) for note_id in _clean_fields(snapshot.get("fields"))}
    ids.update(int(note_id) for note_id in _clean_tag_notes(snapshot.get("tags")))
    for note_list in _clean_marker_tags(snapshot.get("marker_tags")).values():
        ids.update(int(note_id) for note_id in note_list)
    return sorted(ids)


def describe(snapshot):
    """One line for the panel: what the saved order covers, or why there is nothing to offer."""
    if not snapshot:
        return "No saved order — Junban has not repositioned any cards yet."
    count = len(snapshot.get("cards") or {})
    where = ", ".join(normalize_scope(snapshot.get("scope"))) or "(unrecorded)"
    when = snapshot.get("written_at") or "an unknown date"
    line = f"{count} card{'' if count == 1 else 's'} saved from {where} on {when}"
    if is_baseline(snapshot):           # today's baseline (03 §5): say which order it is
        line += ", before that day's first automatic re-order"
    elif snapshot.get("tried"):         # backlog onboarding: Try it on my cards
        line += ", before Try it moved them to the front"

    # Named separately, because restoring a field is the half a user would want to know about
    # before pressing the button — a position is a position, a field is something they wrote.
    extras = []
    edited = len(_clean_fields(snapshot.get("fields")))
    if edited:
        extras.append(f"{edited} note{'' if edited == 1 else 's'} edited")
    tag, tagged = restore_tag(snapshot)
    if tagged:
        extras.append(f"{len(tagged)} tagged '{tag}'")
    marked = {note_id for ids in restore_marker_tags(snapshot).values() for note_id in ids}
    if marked:
        extras.append(f"{len(marked)} marker-tagged")
    suspended = len(restore_suspended(snapshot))
    if suspended:
        extras.append(f"{suspended} suspended")
    flagged = len(_clean_flags(snapshot.get("flags")))
    if flagged:
        extras.append(f"{flagged} flagged")
    return line + (f" ({', '.join(extras)})" if extras else "")


def describe_run(language, run_id):
    """One line for a window's Restore: one of Connect's runs that never finished (P1.4) — what it changed, where and
    when, by its id."""
    saved = load(language, run_id=run_id)
    if not saved:
        return f"{run_id}: its saved copy can't be read just now. Try again in a moment."
    where = ", ".join(normalize_scope(saved.get("scope"))) or "(unrecorded)"
    when = saved.get("written_at") or "an unknown date"
    if saved.get("kind") == "backfill":
        count, what = len(saved.get("fields") or {}), "note{} filled"
    else:
        count, what = len(saved.get("cards") or {}), "card{} moved"
    return f"{count} {what.format('' if count == 1 else 's')} in {where} on {when} ({run_id})"


def restore_run_pairs(snapshot, current):
    """`([(card_id, due)], skipped)` — the positions one of Connect's runs moved, put back only while a card still
    sits where that run put it. `current` is `{card_id: due}` for the cards still new in Anki NOW (`after`); a card
    moved since (a later run, or you) is left where it is and counted, one that is gone or studied is simply absent."""
    after = (snapshot or {}).get("after") or {}
    pairs, skipped = [], 0
    for raw_id, before in ((snapshot or {}).get("cards") or {}).items():
        card_id = int(raw_id)
        if card_id not in (current or {}):
            continue
        now, wrote = current[card_id], after.get(str(card_id))
        if wrote is not None and now == wrote:
            if now != before:
                pairs.append((card_id, int(before)))
        elif now != before:
            skipped += 1
    pairs.sort(key=lambda pair: (pair[1], pair[0]))
    return pairs, skipped


def restore_unsuspended(snapshot):
    """The returning words' cards one of Connect's runs unsuspended (MR-R3), to suspend again on its restore."""
    return _clean_card_ids((snapshot or {}).get("unsuspended"))


# --- today's baseline, and the ladder's bottom (the fast re-plan's preview) ------------------------ #
def anki_day(now=None):
    """Anki's day, as `YYYY-MM-DD`: the local date `ROLLOVER_HOURS` back, so the hours after midnight
    still count as yesterday, as they do in Anki."""
    moment = (time.time() if now is None else now) - ROLLOVER_HOURS * 3600
    return time.strftime("%Y-%m-%d", time.localtime(moment))


def save_baseline(pairs, scope, language="ja", mode="deck", day=None):
    """Today's baseline, before an automatic re-order's first write (03 §5). Returns `(path, written)`.

    Written only when there is none for `day` (Anki's day, `anki_day`) and this scope, or the last was
    ended by a manual run or a Restore — so it keeps the order the cards had before today's FIRST
    automatic write, and a later automatic write the same day leaves it alone. Another deck's baseline
    (the automatic deck changed) gives way to this deck's: it couldn't be restored here anyway. Same shape as the snapshot, `complete` from the
    start (it never blocks anything), plus `day`. Raises `OSError` when it can't be saved: the automatic
    write then doesn't happen, as a reorder without its snapshot doesn't (I3)."""
    day = day or anki_day()
    path = snapshot_path(language, "baseline")
    current = load(language, "baseline")
    if (current and current.get("day") == day and not current.get("ended_at")
            and normalize_scope(current.get("scope")) == normalize_scope(scope)):
        return path, False
    payload = {
        "schema": SCHEMA,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scope": normalize_scope(scope),
        "cards": {str(int(card_id)): int(due) for card_id, due in _as_pairs(pairs)},
        "complete": True,
        "day": day,
    }
    if mode == "all":
        payload["mode"] = "all"
    _write_json(path, payload)
    return path, True


def end_baseline(language="ja"):
    """A manual run or a Restore ends today's baseline: the next automatic write starts a new one.
    Marked, not deleted (`ended_at`); no file, nothing written. Best-effort: returns success."""
    path = snapshot_path(language, "baseline")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or data.get("ended_at"):
            return False
        data["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_json(path, data)
        return True
    except (OSError, ValueError):
        return False


def is_baseline(snapshot):
    """Is this today's baseline (it carries Anki's `day`) rather than a manual run's snapshot?"""
    return bool(snapshot) and "day" in snapshot


ALL_DECKS = ("all decks",)     # `restorable`'s scope for an All-decks Restore (the decks are Anki's to name)


def restorable(language="ja", scope=None):
    """What *Undo the last reorder* puts back (03 §5): the newer of the manual run's snapshot and the
    baseline — the manual run's whenever it is unfinished (then the only way back from that run), and
    the manual run's on a tie. `scope` (the decks Restore is for), when given, prefers a snapshot taken
    for it; `ALL_DECKS` prefers one taken for All decks (a one-deck baseline would only be refused
    there, again and again — review 3 #5). Ending a baseline only tells the next automatic write to start a new one: a second Restore
    offers the same order again, as 2.5's does, never an older manual run's. A baseline from an earlier
    day is still the newest way back when nothing was re-ordered since (`describe` names its day). With
    no baseline at all, exactly `load()`."""
    manual = load(language)
    if manual and manual.get("complete") is False:
        return manual
    found = [snapshot for snapshot in (manual, load(language, "baseline")) if snapshot]
    if scope is ALL_DECKS:
        found = [snapshot for snapshot in found if snapshot.get("mode") == "all"] or found
    elif scope is not None:
        asked = normalize_scope(scope)
        found = [snapshot for snapshot in found if normalize_scope(snapshot.get("scope")) == asked] or found
    if not found:
        return None
    return max(found, key=lambda snapshot: (snapshot.get("written_at") or "", not is_baseline(snapshot)))


def ladder(language, scope):
    """This scope's spaced ladder as last recorded: `{"floor": its bottom (E2.1-1), "seen": the highest card
    id the last spaced run placed}` — each None when unknown (no record, or one that won't read)."""
    from app.path_utils import get_user_files_path
    path = os.path.join(get_user_files_path(language), LADDER_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        entry = (data.get("scopes") or {}).get(_scope_key(scope)) or {}
        if not isinstance(entry, dict):
            entry = {}
    except (OSError, ValueError, AttributeError):
        entry = {}
    return {key: entry.get(key) if _whole(entry.get(key)) else None for key in ("floor", "seen")}


def ladder_floor(language, scope):
    """The bottom of this scope's spaced ladder as last recorded (E2.1-1), or None."""
    return ladder(language, scope)["floor"]


def record_ladder(language, scope, floor=None, seen=None):
    """Remember the ladder's bottom (`floor`, the one `spaced.number` used) and/or the highest card id the
    run placed (`seen`), for the next run; a None leaves that value as it was. Only written when
    something changed; best-effort — a failure only costs room, or lets a new card's tie go by its
    position for one more run. Returns success."""
    from modules.junban.spaced import CEILING
    if floor is not None and not (_whole(floor) and floor <= CEILING):
        return False
    if seen is not None and not _whole(seen):
        return False
    current = ladder(language, scope)
    wanted = {"floor": current["floor"] if floor is None else floor,
              "seen": current["seen"] if seen is None else seen}
    if wanted == current:
        return True
    from app.path_utils import get_user_files_path
    path = os.path.join(get_user_files_path(language), LADDER_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("scopes"), dict):
            data = {}
    except (OSError, ValueError):
        data = {}                       # Junban's own record, nothing of the user's in it: started afresh
    data["schema"] = 1
    entry = {key: value for key, value in wanted.items() if value is not None}
    entry["written_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data.setdefault("scopes", {})[_scope_key(scope)] = entry
    try:
        _write_json(path, data)
    except OSError:
        return False
    return True


def record_floor(language, scope, floor):
    """`record_ladder(floor=)`: refuses a bottom outside 1–999,999."""
    if floor is None:
        return False
    return record_ladder(language, scope, floor=floor)


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _scope_key(scope):
    return "|".join(normalize_scope(scope))


def _write_json(path, data):
    """Atomic, as every file here: `.tmp` + `os.replace`, so an interrupted write never truncates one."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


# --- internals ------------------------------------------------------------------------------------- #
def _is_int_key(key):
    try:
        int(key)
        return True
    except (TypeError, ValueError):
        return False


def _as_pairs(pairs):
    """Accept either a mapping or an iterable of pairs, so the caller need not care which it holds."""
    if isinstance(pairs, dict):
        return pairs.items()
    return pairs


def _clean_fields(fields):
    """`{"<note_id>": {field: {"before": str, "after": str}}}`, keeping only entries we could replay.

    Both halves are kept, and that is the WP-L design decision worth naming: `before` is what to put
    back, `after` is what junban wrote, and without the second a restore cannot tell its own work
    apart from an edit the user has made since. Anything missing either half is dropped rather than
    guessed at — half a change is not a change we may reverse.

    Keys are stored as strings because JSON has no integer keys, and normalising here means `save`
    and `load` cannot disagree about the shape.
    """
    out = {}
    for note_id, edits in ((fields or {}).items() if isinstance(fields, dict) else []):
        if not isinstance(edits, dict):
            continue
        try:
            key = str(int(note_id))
        except (TypeError, ValueError):
            continue
        kept = {}
        for field, change in edits.items():
            if not isinstance(change, dict) or "before" not in change or "after" not in change:
                continue
            before, after = change["before"], change["after"]
            if not isinstance(before, str) or not isinstance(after, str):
                continue
            kept[str(field)] = {"before": before, "after": after}
        if kept:
            out[key] = kept
    return out


def _clean_tag_notes(tags):
    """The note ids junban's tag was added to, de-duplicated and sorted. Never the tag itself."""
    if isinstance(tags, dict):          # tolerate a `{note_id: true}` shape from a hand-edited file
        tags = list(tags.keys())
    if not isinstance(tags, (list, tuple, set)):
        return []
    out = set()
    for note_id in tags:
        if isinstance(note_id, bool):
            continue
        try:
            out.add(int(note_id))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _clean_marker_tags(marker_tags):
    """`{"Surasura::star": [note_id]}`, keeping only entries we could actually take back off.

    A tag name that is not a string, or that carries no notes, is dropped rather than guessed at:
    removing the wrong tag from a user's notes is exactly the damage this file exists to prevent.
    """
    out = {}
    for name, ids in ((marker_tags or {}).items() if isinstance(marker_tags, dict) else []):
        name = str(name or "").strip()
        notes = _clean_tag_notes(ids)
        if name and notes:
            out[name] = notes
    return out


def _clean_card_ids(ids):
    """Card ids as sorted, de-duplicated ints; anything that is not a whole number is dropped."""
    return _clean_tag_notes(ids)


def _clean_flags(flags):
    """`{"<card_id>": flag}` with each flag one of Anki's 0-7, keeping only what could be put back."""
    out = {}
    for card_id, flag in ((flags or {}).items() if isinstance(flags, dict) else []):
        if isinstance(flag, bool) or not isinstance(flag, int) or not 0 <= flag <= 7:
            continue
        try:
            out[str(int(card_id))] = flag
        except (TypeError, ValueError):
            continue
    return out


def _is_replayable(data):
    """Is this a snapshot we could actually replay? Anything else counts as corrupt.

    Type-checking the values here rather than at restore time is deliberate: a card id or a `due`
    that is not a whole number cannot be written back, and discovering that mid-restore would leave
    the queue half-repositioned with no way to finish.
    """
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        return False
    scope = data.get("scope")
    if scope is not None and not isinstance(scope, (list, tuple, str)):
        return False
    for raw_id, due in data["cards"].items():
        if isinstance(due, bool) or not isinstance(due, int):
            return False                    # `True` is an int in Python; a due of 1 by accident is not
        try:
            int(raw_id)
        except (TypeError, ValueError):
            return False
    return True


def _quarantine(path):
    """Move an unreadable snapshot aside instead of overwriting it.

    The user may still need it — by hand, or by a later version that understands it. Replacing it
    would destroy the only record of where their cards used to be, which CLAUDE.md §4 forbids for
    anything under `User Files/`.
    """
    moved = f"{path}.corrupt-{time.strftime('%Y%m%d%H%M%S')}"
    try:
        os.replace(path, moved)
    except OSError:
        return None
    return moved
