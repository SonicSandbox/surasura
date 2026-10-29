"""*Needs you*'s entries (W3.2 S3; the window's spec A2 #69–70, G4–G7, 06 E8 / E10 / E11, G1.6's n15, P1.2-1; RUNBOOK
§1's *Needs you* row and §5a IK-2, IK-3, IK-8): what the page lists, in order, as plain tuples the window paints. Qt-free,
Tk-free, pandas-free (the import guard); nothing here reads or writes the store.

`entries(view, failures, connect, seen, offline_roots, asks, answered)` -> [Entry], in the page's order:
- **the bulk answer** at the top: *Find all missing videos (N in M shows)* once two shows or more have no video, *Keep
  all their words* · *Remove all* once two shows or more have files gone (lean 4). *Remove all* never counts a file
  under an offline root (IK-8): those are the offline entry's, never a show's.
- **each show, two kinds of card, never one** (IK-2): *a file gone* (`file-gone`: the content file itself isn't on disk,
  the store's `availability` = missing — the view's `Episode.missing`; one line per missing file of Current, wherever
  it stands: *Choose file…* · *Choose a folder…* → the writer's `relink`, *Keep its words*, *Remove*) and *no
  video* (`no-video`: the content is there and Connect's job for it waits on its video, `runner.NO_VIDEO`: *Find
  videos* · *Link these · N* → the writer's `link_video`, never `relink`; alpha 4 M1: never a book's, and no *Mine
  the text only*). Shows in Current's order; a show with both gets both cards, its gone files first.
- **9a's questions** (IK-3, `Store.rename_asks()` read on the reader's worker by `asks_of`): *Is this the one from …?*
  with the missing files it may be; *This one* → `relink`, *It's new* → `its_new`.
- **a source folder that is GONE** (T6, Sonic 2026-10-24: "Yes your lean is exactly what i'd do"): one card per
  folder the looks found moved or deleted while its drive is there (`source_looks.gone`: the summary's rows, handed in
  by the window as `gone_folders`) — never one only away (an unplugged drive, a NAS down: the offline line's). It names
  the folder, where it was and the shows it held: *Find its new folder…* (`SourceLooks.find_new_folder`, MV-1's join),
  *Stop reading it* (the writer's `stop_reading`, one Undo) and *Keep waiting* (the offline line's own dismissal). A
  Finished show's folder, or one whose episodes a look already reads elsewhere, leads with *Stop reading it*.
- **a folder whose files are mostly gone as ONE entry** (K3, alpha 4: a moved or deleted folder of copies made one card
  per show it held — 3,000 of them for Mattias): a library folder holding FOLDER_MIN gone files of two shows or more,
  more than half of its files gone, is one `files-folder` card (the top-most such folder) holding every gone line under
  it — *Choose a folder…* (`match_tree`: each file by its place under the folder, then by its name) · *Remove* (one
  Undo); its shows' cards keep only the files left outside it. **The library mostly gone** (K1, Mattias's note 3: a
  reinstall over the same folder found the old record with every file gone): LIBRARY_MIN gone files of two shows or
  more, more than half of Current's files, never under an offline root, is ONE `library-gone` card first, folding in
  every show's and folder's — *Start fresh* (`SourceLooks.fresh`: the old library backed up in the trash, never
  deleted) · *Choose a folder…*; a card until answered (asked once, Sonic 2026-10-27: "Your lean is good").
  **The library folder emptied** (A5K-2, Sonic ✅ 2026-10-28: Mattias's "fresh start" — he deleted Surasura's folder and
  unzipped it again in the same place; the record, kept elsewhere, came back with his removed files kept out): the
  store's note (`Store.note_emptied`, the run's first look, before a copy is put back; handed in as `emptied`) is ONE
  `library-emptied` card first — *Start fresh* (K1's: the old library in one dated backup, nothing deleted) · *Keep my
  old library* (the card off for good, `stop_asking`; emptied again later, it asks again).
- **an offline root as ONE entry** (E8, IK-8): *Drive E: is offline — 312 files* (`find_offline` finds the roots on a
  worker: the library folder not there, or a folder in it that links to a drive or share that isn't); it offers *Keep
  their words* and never *Remove*.
- **the failures** (`status.Snapshot.needs_you`, W3.5's: seen once looked at, still listed): *Open the logs folder* ·
  *Save logs to a file…*.
- **Connect's entries** (`read_connect`: `connect.status`'s record, newest first, plus the ledger's gaps): its own words
  and its kind's action — `not-timed` *Mine anyway* (`connect.actions.mine_anyway`), `no-pairing` *Ask hato again*
  (`connect.hato.backfill`), a failure Connect logged *Open the logs folder*; every one *Dismiss* (`status.dismiss`). A
  gap (*lost track*) offers *Make their cards* (no callable yet: hidden, `WIRED_LATER`) and *Leave them* (answered here).
- **Known from Anki's one-time question** (laptop round 7 #43, ⭐ B3-1 A): the cards you had already suspended / marked
  when *Count as known in Anki* first read them (or first after its states, decks or profile changed) are kept as an
  offer, never marked by themselves (`connect/known_signal.py`); this is where 3.0 asks it — *You'd already suspended
  and marked 40 cards in Anki: mark their words known?* · *Mark them known* (`known_signal.accept_offer`) · *Leave them*
  (`decline_offer`). Read with Connect's record (`known_offer`, read-only); answered, it is gone.
- **the shows behind the backlog** (Michi-C, A7B-1…A7B-3 PROVISIONAL; Sonic 2026-10-29 "Genius"): ONE card while a
  show 順's deck's new cards came from is on this PC and waits in New arrivals (`backlog_offer`: `modules/junban/
  backlog_shows`' last offer, read-only) — *Your 2,300 new cards come from 14 shows; 12 are on this PC. Add the 3
  that aren't in your list yet?* · *Add them* (the window's writer, `place(ids, "soon")`: one Undo) · *Leave them*
  (answered; a show placed since, or a new one waiting, asks again).
- **setup's first cards** (SRC S1 + D1, Sonic ✅ 2026-10-16): setup's first scan of the folders the shows and books are in
  logs nothing, so Connect makes no card for them by itself; once it took something in, it offers ONE line (`offer`,
  kept in the seen file): *Make cards for your first 20 episodes?* · *Not now* — either answer takes it off for good.

An entry's `actions` are names only; the window maps each to its call and hides the names in `WIRED_LATER` until a
callable is set. `badge(entries)` counts the unseen ones (P1.2-1: seen ones stay listed and stop counting).

**Seen and answered** (lean 5): the store's entries' keys live in the local data folder, `needs_seen_<lang>.json`
(never settings.json), written whole and atomically, on the window's worker (`mark_seen`, `answer`). An entry's key
names what it holds (a show's key moves when another of its files goes missing, so it counts again). *Keep its words*
and *Leave them* are answers kept in the same file (the file stays missing and counted, L2.2 05 §9b: nothing in the
store changes); Connect's entries are seen through Connect's own `seen_at` (`status.mark_seen`, `mark_all_seen`). No
key falls off by age or count: `prune` takes out those whose trouble is gone (a file back on disk, a drive plugged in
again — asked again the next time it goes offline).

`find_videos(language, need, settings)` (a worker; never writes, never opens a video, never a cloud placeholder): for each
line of a *no video* card, the show's own folder, then Connect's video folders (`connect_video_folders`, their
subfolders `videos.DEPTH` deep) for a video whose episode number (`view_rows.episode_number`) is the line's ->
[(label, path or None, why)]. The show's folder wins over the video folders; two in one place is no answer (Connect
never guesses), unless one of them sits in a folder named like the show. `find_all` does every card with one listing.
"""
import hashlib
import json
import os
import re
import threading
import time
from collections import namedtuple

from app import library_store, path_utils
from app.services import view_rows

Entry = namedtuple("Entry", "key kind title lines actions unseen say data", defaults=("", None))
#   key: stable while it holds the same things (its seen key); kind: one of KINDS or Connect's own kind; lines:
#   NeedLine; actions: names (the window maps them); say: the card's line of plain words; data: what its actions act on
NeedLine = namedtuple("NeedLine", "key text item_id label number rel_path actions")
#   one episode (or a 9a candidate): `item_id` the item its actions act on, `rel_path` its file in the library
Root = namedtuple("Root", "path rel label files", defaults=(None,))
#   an offline root: `path` the folder that isn't there, `rel` its place in the library ('' the whole library),
#   `label` *Drive E:*; `files` (None: Current's files under it, as the view holds them)

BULK, GONE, NO_VIDEO, ASK, OFFLINE, FAILURE, GAP = ("bulk", "file-gone", "no-video", "rename-ask", "offline", "failure",
                                                    "gap")
FIRST_CARDS = "first-cards"         # D1: setup's first scan took shows in; their cards are made only if you say so
KNOWN_OFFER = "known-offer"         # #43: Known from Anki's first read, asked once (B3-1 A)
# A3W-6 (Sonic, 2026-10-24 night): Connect's episodes wait on Anki for you (closed, a permission prompt, another
# profile or none: `runner.anki_needs_you`) — one line, read from Connect's record, gone by itself once Anki opens
ANKI_WAIT = "anki-wait"
# T6 (Sonic 2026-10-24): a source folder moved or deleted while its drive is there — never one only away
FOLDER_GONE = "folder-gone"
# K3 / K1 (alpha 4): a library folder's files mostly gone, and the library's — one card each, never one per show
FILES_FOLDER = "files-folder"
LIBRARY_GONE = "library-gone"
LIBRARY_EMPTIED = "library-emptied"   # A5K-2: the library folder held none of the record's files at this run's start
AUDIOBOOK_ASK = "audiobook-ask"       # Hon (H-8): is this audiobook that book? Asked once per pair, the answer kept
AUDIOBOOK_FIND = "audiobook-find"     # Hon (a5-2): after a *No*, find its book — or it has none (never asked again)
AUDIOBOOK_TRANSCRIPT = "audiobook-transcript"   # Hon (a6, H-13): an audiobook's transcript isn't its book's: not used
BACKLOG_SHOWS = "backlog-shows"       # Michi-C (A7B-3): the shows behind 順's deck's new cards, on this PC, not listed
FOLDER_MIN = 10                 # gone files (of two shows or more) before a folder is one card
LIBRARY_MIN = 20                # gone files (of two shows or more) before the library is one card
KINDS = (BULK, GONE, NO_VIDEO, ASK, OFFLINE, FAILURE, GAP, FIRST_CARDS, KNOWN_OFFER, ANKI_WAIT, FOLDER_GONE,
         FILES_FOLDER, LIBRARY_GONE, LIBRARY_EMPTIED, AUDIOBOOK_ASK, AUDIOBOOK_FIND, AUDIOBOOK_TRANSCRIPT, BACKLOG_SHOWS)
# action names the window hides until P4.1 sets their callable (RUNBOOK §2). Alpha 4 M1: *Mine the text only* is gone
# (it opened Anki Miner's own window — Sonic 2026-10-27: "I honestly don't want to ever have to open anki miner. Ever.")
WIRED_LATER = frozenset(("make_cards",))   # (K1's *Start fresh*: the window's `SourceLooks.fresh`)
# Connect's kinds and their one action beside *Dismiss* (`connect_window.HOW`'s, as the Qt window offers them now)
CONNECT_ACTIONS = {"not-timed": ("mine_anyway",), "no-pairing": ("ask_hato",), "repick": ("open_logs",),
                   "mine-failed": ("open_logs",), "error": ("open_logs",)}
SEEN_VERSION = 1
_NO_VIDEO_REASON = "No video: its video isn't on this computer (or isn't downloaded yet)."   # runner.NO_VIDEO's words

STRINGS = {
    # Hon (H-8 PROVISIONAL): an audiobook Surasura isn't sure reads that book
    "abook_title": "Is this audiobook 「{audio}」 the book 「{book}」?",
    "abook_say": "{files}. Surasura isn't sure they're the same book: your answer is kept, and it never asks about "
                 "these two again.",
    "abook_files_one": "1 file", "abook_files": "{n} files", "abook_files_more": "{first} … {last}",
    # Hon (a5-2, Sonic 2026-10-28: after a *No*, "offer that they find the book")
    "abook_find_title": "Which book does the audiobook 「{audio}」 read?",
    "abook_find_say": "{files}. Not 「{book}」, you said. Find its book in your library or on your computer, or tell "
                      "Surasura it has none: it won't ask again.",
    "abook_find_say_none": "{files}. Not that book, you said. Find its book in your library or on your computer, or "
                           "tell Surasura it has none: it won't ask again.",
    # Hon (a6, H-13 PROVISIONAL): a transcript beside an audiobook that its book doesn't hold — never used in silence
    "abook_transcript_title": "The transcript beside 「{audio}」 doesn't match 「{book}」",
    "abook_transcript_say": "Only {share} of its lines are in that book, so it's another edition's or another "
                            "book's: Surasura doesn't use it. The book's words count, as they did.",
    "abook_transcript_say_none": "Its lines aren't in that book, so it's another edition's or another book's: "
                                 "Surasura doesn't use it. The book's words count, as they did.",
    "anki_closed_title": "Anki isn't open: {n} wait for it",
    "anki_needs_title": "Anki needs you: {n} wait for it",
    "anki_one": "1 episode", "anki_n": "{n:,} episodes",
    "bulk_title_files": "{n:,} files are gone in {m:,} shows",
    "bulk_title_videos": "{n:,} episodes in {m:,} shows have no video",
    "bulk_title_both": "{m:,} shows are missing files or videos",
    "bulk_say": "One answer for every show below, or answer each card on its own.",
    "find_all": "Find all missing videos ({n:,} in {m:,} shows)", "keep_all": "Keep all their words ({n:,})",
    "remove_all": "Forget every missing file ({n:,})",
    "gone_title_one": "{title} · {ep}'s file is gone", "gone_title_n": "{title} · {n:,} {unit}' files are gone",
    "gone_say": "Its words still count until you choose: point it at its file, keep its words, or remove it to the "
                "trash (30 days).",
    "gone_line": "{label} · not at {rel}",
    "ask_title_one": "Is {name} the one from {old}?", "ask_title_n": "Is {name} one of these {n} missing files?",
    "ask_say": "It turned up at {rel} with the name, size and date of a missing file. Surasura never guesses: choose "
               "the one it is, or say it's new.",
    "ask_line": "{title} · was {rel}",
    "folder_title": "{name} isn't in {parent} any more",
    "folder_held": "It held {shows} · {episodes}.", "folder_held_none": "It held {shows}.",
    "folder_finished": "It held {shows} · {episodes}, all Finished: nothing is left to mine from it.",
    "folder_read_now": "Its episodes are read from {found} now: stop reading the old folder.",
    "folder_found": "They're in {found} too: Find its new folder… joins them there, never as a second copy.",
    "folder_found_finished": "They're read from {found} too: stop reading the old folder, or Find its new folder… "
                             "joins them there.",
    "folder_moved": "Moved it? Find its new folder…: its episodes join their show there, never as a second copy.",
    "folder_stay": "Whatever you choose, its episodes stay in your library.",
    "shows_more": "{shows} and {n:,} more", "shows_and": "{a} and {b}",
    "episode_one": "1 episode", "episode_n": "{n:,} episodes",
    "offline_title": "{label} is offline — {n} files", "offline_title_one": "{label} is offline — 1 file",
    "files_folder_title": "{n} files are gone from {folder}",
    "files_folder_title_library": "{n} files are gone from your library folder",
    "files_folder_say": "{shows} were in it. Moved it? Choose its folder… to point them at their files there, or "
                        "remove them from your library (Undo brings them back).",
    "library_title": "Most of your library's files are gone ({n} of {total})",
    "library_say": "Was Surasura installed again, or its library moved? Start fresh sets this library aside in a backup "
                   "(nothing is deleted) and reads your folders again; choose a folder… if you moved its files.",
    "emptied_title": "Your library folder was emptied: start a fresh library?",
    "emptied_say": "Surasura found this library from before ({n} files), but its folder holds none of them now. Start "
                   "fresh sets it aside in a backup (nothing is deleted) and reads your folders again. Keep my old "
                   "library carries on with it: its places, and the files you removed stay out.",
    "offline_say": "Its files keep their places and their words. They come back by themselves once it's connected.",
    "drive": "Drive {d}", "folder": "The folder {p}",
    "gap_title": "Connect lost track of your moves {span}: {n} {noun} in the top 20 {have} no cards",
    "gap_span": "from {a} to {b}", "gap_until": "until {b}",
    "first_title": "Make cards for your first {n} episodes?", "first_title_one": "Make cards for your first episode?",
    "first_say": "Your shows came in from your folders without cards: Surasura asks before it makes any.",
    "known_title": "You'd already {states} {n} cards in Anki: mark their words known?",
    "known_title_one": "You'd already {states} a card in Anki: mark its word known?",
    "known_say": "Count as known in Anki (Settings › Anki) found them there when it first looked, so it asks once. "
                 "Every card you {states} from now on counts by itself.",
    # Michi-C (A7B-1…A7B-3 PROVISIONAL): the shows behind the backlog
    "behind_cards": "Your {n:,} new cards", "behind_cards_one": "Your new card",
    "behind_cards_some": "{n:,} of your new cards",
    "behind_from": "{cards} {come} from {s} shows; {found} are on this PC.",
    "behind_from_found_one": "{cards} {come} from {s} shows; one is on this PC.",
    "behind_from_none": "{cards} {come} from {s} shows; none of them is on this PC.",
    "behind_from_one": "{cards} {come} from 1 show, on this PC.",
    "behind_from_one_away": "{cards} {come} from 1 show, not on this PC.",
    "behind_add": "Add the {k} that aren't in your list yet?", "behind_add_one": "Add the one that isn't in your list yet?",
    "behind_add_all": "Add them to your list?", "behind_add_it": "Add it to your list?",
    "behind_waiting": "Waiting in New arrivals: {names}.", "behind_away": "Not on this PC: {names}.",
    "behind_name": "{title} ({n:,})", "behind_more": "and {k} more",
    "why_found": "→ …\\{name} ✓ found", "why_found_own": "→ …\\{name} ✓ found in its own folder ({k} more in your "
                                                         "video folders)",
    "why_found_named": "→ …\\{name} ✓ found: the one in a folder named like the show",
    "why_none": "✗ nothing with \"{n}\" in its name", "why_many": "✗ {k} videos have \"{n}\" in their names: choose one",
    "why_cloud": "✗ \"{n}\" is still in the cloud: download it first",
    "why_no_number": "✗ its name has no episode number to look for",
    # alpha 4 D2: one line over 3+ cards that share a reason (`_reason_lines`)
    "reason_ask": "{n} new files may be ones you had", "reason_folder": "{n} source folders are gone",
    "reason_offline": "{n} drives or folders are offline", "reason_failure": "{n} things didn't finish",
    "reason_not_timed": "{n} episodes' subtitles aren't timed to their video",
    "reason_no_pairing": "{n} episodes wait for hato's videos", "reason_cards": "{n} cards couldn't be made",
    "reason_gap": "{n} times Connect lost track of your moves",
    "reason_say": "One answer for all of them, or answer each card below on its own.",
}
# kinds whose cards share a reason (3+ of one: one line over them, `_reason_lines`), and its words
REASONS = {ASK: "reason_ask", FOLDER_GONE: "reason_folder", OFFLINE: "reason_offline", FAILURE: "reason_failure",
           "not-timed": "reason_not_timed", "no-pairing": "reason_no_pairing",
           "repick": "reason_cards", "mine-failed": "reason_cards", "error": "reason_cards", GAP: "reason_gap"}
REASON_AT = 3                       # cards of one reason that bring its line (the bulk answer's own: two shows)
# the cards whose own two answers both end them: no ⋯ (its *Not now* would say the same as their own)
NO_LATER = frozenset((FIRST_CARDS, KNOWN_OFFER, BACKLOG_SHOWS))


# --- small pieces ---------------------------------------------------------------------------------------------------- #
def _digest(values):
    return hashlib.sha1(",".join(str(v) for v in values).encode("utf-8")).hexdigest()[:10]


def _norm(rel):
    return (rel or "").replace("\\", "/").strip("/")


def shown(rel):
    """A library path as a learner reads it: the tier folder left out (HighPriority/Hato/1.srt → Hato/1.srt). A 2.x
    tier folder is never a place in 3.0 (an item dragged to Goal still lives in HighPriority/…), so naming it, or its
    tier, could name the wrong place (Sonic's lean, 2026-10-24, PROVISIONAL; CLAUDE.md §6: never the folder names). A
    bare tier folder reads as its tier's name. Words only; the path itself is never changed."""
    head, sep, rest = _norm(rel).partition("/")
    tier = library_store.TIER_OF_FOLDER.get(head)
    return (rest or library_store.TIER_LABELS[tier]) if tier else _norm(rel)


def _under(rel, prefix):
    """Is library path `rel` under the library folder `prefix` ('' = the whole library)?"""
    rel, prefix = _norm(rel).casefold(), _norm(prefix).casefold()
    return not prefix or rel == prefix or rel.startswith(prefix + "/")


def _group(row):
    return row.work_id if row.work_id is not None else row.key


def _unit(media):
    return view_rows.STRINGS["unit_eps"] if media in view_rows.EPISODIC else view_rows.STRINGS["unit_files"] \
        if media == "youtube" else view_rows.STRINGS["unit_parts"]


def _no_video_reason():
    try:
        from app.connect.runner import NO_VIDEO
        return NO_VIDEO
    except Exception:
        return _NO_VIDEO_REASON


def _waits_on_video(reason):
    """A Connect job's reason that is *No video* — `runner.NO_VIDEO`, or MV-2's line naming the folder its video left
    (`runner.no_video`)."""
    try:
        from app.connect.runner import no_video
    except Exception:
        return reason == _NO_VIDEO_REASON
    return no_video(reason)


def item_key(item_id):
    """The answer key of one file (*Keep its words*)."""
    return f"item:{item_id}"


# --- the entries ----------------------------------------------------------------------------------------------------- #
def entries(view, failures=(), connect=None, seen=frozenset(), offline_roots=(), asks=(), answered=frozenset(),
            mine_line=20, offers=frozenset(), cards_on=False, miner_found=True, gone_folders=(), settled=False,
            hidden=frozenset(), emptied=None, backlog=None):
    """The page's entries in order (see the module's doc). `view`: the reader's `View` (None: no library); `failures`:
    `status` Entries (text, at, seen); `connect`: one language's Connect record (`read_connect`; None: Connect off);
    `seen` / `answered`: `read_seen` / `read_answered`; `offline_roots`: `find_offline`'s Roots; `asks`: `asks_of`'s
    (or `Store.rename_asks()` as it is: candidates by id); `offers`: `read_offers` (D1's line); `cards_on`: Connect's
    switch (`connect_enabled`, setup's page 5) — on, D1's line asks only about these episodes (its `_on` actions);
    `miner_found`: Anki Miner is installed (`anki_miner.find`) — without it D1's line waits, kept offered (row 13: its
    cards could never be made); `gone_folders` (T6): the looks' rows of the source folders that are GONE
    (`source_looks.gone`, those *Keep waiting* hid left out by the window), one card each; `settled` (K1): every folder
    read had its look this run (the window's `gone_in(judged=True)`) — a copy a look can put back from its original
    (item 8a) is gone only until then, so the library's card waits for it; `hidden` (alpha 4 D2: `read_hidden`, *Not now* today and *Stop asking*): the cards
    left out, and every count for many with them; `emptied` (A5K-2): the store's `emptied()` note, the first card;
    `backlog` (Michi-C): `backlog_offer`'s record — one card while a show behind 順's deck's new cards waits in New
    arrivals (only the files New arrivals still holds), until *Leave them* (a new show asks again)."""
    seen, answered, hidden = frozenset(seen or ()), frozenset(answered or ()), frozenset(hidden or ())
    rows = tuple(view.rows) if view is not None and view.mode == "store" else ()
    by_id = {e.id: (r, e) for r in rows for e in r.episodes}
    order = list(dict.fromkeys(_group(r) for r in rows))
    roots = [r if isinstance(r, Root) else Root(*r) for r in offline_roots or ()]

    def offline(rel):
        return any(_under(rel, r.rel) for r in roots)

    # a file gone: every file of Current the store marks missing (E8) — not only `view.needs`' (W2.2's rule: in the
    # top, unmined, before the last file on disk), which hides a show whose every file is gone, E8's moved folder —
    # never one under an offline root (that root's entry holds it) nor one the user kept
    gone = {}
    for r in rows:
        for e in r.episodes:
            if e.missing and not offline(e.rel_path) and item_key(e.id) not in answered:
                gone.setdefault(_group(r), []).append((r, e))
    # no video: Connect's jobs waiting on their video, by show
    novideo, unplaced = {}, []
    for job in (connect or {}).get("jobs") or ():
        if not _waits_on_video(job.get("reason")) or job.get("item") is None:
            continue
        hit = by_id.get(job["item"])
        if hit is None:
            unplaced.append(job)
            continue
        if hit[1].text:
            continue                        # alpha 4 M1: a book waits for Anki Miner (Connect's next look sets it aside)
        novideo.setdefault(_group(hit[0]), []).append(hit)
    big, folded = ([], set()) if view is None or getattr(view, "cached", False) else \
        _fold_gone(rows, gone, offline, seen, getattr(view, "counts", None), settled and not roots)   # K3 / K1
    #                                                         (never the first screen's cache: a part of Current)
    if folded:
        gone = {g: [hit for hit in hits if hit[1].id not in folded] for g, hits in gone.items()}
        gone = {g: hits for g, hits in gone.items() if hits}
    shows = []
    for group in order:
        if group in gone:
            shows.append(_gone_entry(group, gone[group], seen))
        if group in novideo:
            shows.append(_video_entry(group, novideo[group], seen, mine_line))
    shows = [e for e in shows if e.key not in hidden]
    out = []
    if emptied:
        out.append(_emptied_entry(emptied, seen))   # A5K-2 leads the page (hidden: off below, as every card)
    if big and big[0].kind == LIBRARY_GONE:
        if big[0].key not in hidden:
            out.append(big[0])                      # K1 leads the page
        big = big[1:]
    if FIRST_CARDS in frozenset(offers or ()) and FIRST_CARDS not in answered and miner_found:
        out.append(_first_cards_entry(rows, seen, mine_line, cards_on))
    offer = (connect or {}).get("known_offer")
    if offer:
        out.append(_known_entry(offer, seen))
    behind = _backlog_entry(backlog, view, seen) if backlog else None
    if behind is not None and behind.key not in answered:
        out.append(behind)
    anki = _anki_entry(connect, seen) if cards_on else None    # Connect may run (it clears the line by itself: A-5)
    if anki is not None:
        out.append(anki)
    bulk = _bulk(shows)
    if bulk is not None:
        out.append(bulk)
    lines_at = len(out)                                         # the lines for many other reasons go here
    for row in gone_folders or ():                              # (alpha 4: on top — 届's press opens the page at it)
        out.append(_folder_entry(row, seen))
    out += [e for e in big if e.key not in hidden]
    out += shows
    for ask in asks or ():
        entry = _audiobook_entry(ask, seen) if ask.get("kind") == AUDIOBOOK_ASK else \
            _audiobook_find_entry(ask, seen) if ask.get("kind") == AUDIOBOOK_FIND else \
            _transcript_entry(ask, seen) if ask.get("kind") == AUDIOBOOK_TRANSCRIPT else _ask_entry(ask, by_id, seen)
        if entry is not None:
            out.append(entry)
    for root in roots:
        entry = _offline_entry(root, by_id, seen)
        if entry.key not in answered:
            out.append(entry)
    for f in failures or ():
        key = f"failure:{f.at}:{_digest([f.text])}"
        out.append(Entry(key=key, kind=FAILURE, title=f.text, lines=(), actions=("open_logs", "save_logs"),
                         unseen=not f.seen, say="", data={"at": f.at}))
    for n in (connect or {}).get("needs") or ():
        kind = n.get("kind")
        title = n.get("say") or ""
        out.append(Entry(key=f"connect:{n['id']}", kind=kind, title=title, lines=(),
                         actions=CONNECT_ACTIONS.get(kind, ()) + ("dismiss",), unseen=not n.get("seen_at"), say="",
                         data={"need_id": n["id"], "item_id": n.get("item"), "connect": True, "at": n.get("at")}))
    for gap in reversed((connect or {}).get("gaps") or ()):
        entry = _gap_entry(gap, seen)
        if entry.key not in answered:
            out.append(entry)
    out = [e for e in out if e.kind == BULK or e.key not in hidden]
    out[lines_at:lines_at] = _reason_lines(out)
    return out


def _reason_lines(cards):
    """Alpha 4 D2 (Sonic: "what do they do if they have a hundred of these?"): ONE line for every reason 3+ cards
    share (`REASONS`; a show's gone files and missing videos have the bulk answer) — *38 source folders are gone ·
    Not now for all · ⋯* — in the order the reasons' first cards come. Its `data["keys"]`: the cards it answers."""
    by = {}
    for e in cards:
        if e.kind in REASONS:
            by.setdefault(REASONS[e.kind], []).append(e)
    out = []
    for words, group in by.items():
        if len(group) < REASON_AT:
            continue
        keys = tuple(e.key for e in group)
        out.append(Entry(key=f"bulk:{words}", kind=BULK, title=STRINGS[words].format(n=view_rows.thousands(len(group))),
                         lines=(), actions=("later_all",), unseen=False, say=STRINGS["reason_say"],
                         data={"keys": keys, "reason": words}))
    return out


def _anki_waits(connect):
    """{reason: episodes} of Connect's episodes waiting on Anki for you, told as the strip tells them (`feed.build`'s
    ANKI items: one an episode, never a not-timed one or a refusal you dismissed that a blanket wait reached —
    review A-3), in the record's order."""
    if not (connect or {}).get("jobs"):
        return {}
    try:
        from app.connect import feed
        items = feed.build({"running": True, "languages": {"_": connect}}, "_").items
    except Exception:
        return {}
    out = {}
    for it in items.values():
        if it.kind == feed.ANKI:
            out[it.tip] = out.get(it.tip, 0) + 1
    return out


def _anki_entry(connect, seen):
    """A3W-6: ONE line while Connect's episodes wait on Anki for you — *Anki isn't open: 19 episodes wait for it* (with
    *Open Anki* where Surasura can start it: `anki_openable`, `read_connect`'s), or *Anki needs you* with Anki's own
    reason (a permission prompt, another profile). No *Dismiss*: it goes by itself once Anki opens (Connect's next look
    gives its episodes another reason). Its key holds the reason: closed again later after it went, it counts again
    (`prune`)."""
    waits = _anki_waits(connect)
    if not waits:
        return None
    n = sum(waits.values())
    episodes = STRINGS["anki_one"] if n == 1 else STRINGS["anki_n"].format(n=n)
    closed = _anki_closed() in waits
    reason = _anki_closed() if closed else max(waits, key=waits.get)
    title = STRINGS["anki_closed_title" if closed else "anki_needs_title"].format(n=episodes)
    if n == 1:
        title = title.replace(" wait for it", " waits for it")
    key = f"anki:{_digest([reason])}:{_SESSION}"     # this window's run: closed again after a restart, it counts again
                                                      # (A-4); `prune` takes an earlier run's key out
    actions = ("open_anki",) if closed and (connect or {}).get("anki_openable") else ()
    return Entry(key=key, kind=ANKI_WAIT, title=title, lines=(), actions=actions, unseen=key not in seen,
                 say="" if closed else reason, data={"episodes": n, "reason": reason})


def _gone_entry(group, hits, seen):
    hits = sorted(hits, key=lambda hit: hit[1].id)   # order-free (C1, the M4.1 adversary's N1): two pieces of one work
    row = hits[0][0]                                 # swapped in Current keep the card's key, lines, title and folder
    word = view_rows.MEDIA_WORD.get(row.media, "video")
    ids = [e.id for _r, e in hits]
    if len(hits) == 1:
        title = STRINGS["gone_title_one"].format(title=row.title, ep=hits[0][1].label)
    else:
        title = STRINGS["gone_title_n"].format(title=row.title, n=len(hits), unit=_unit(row.media))
    lines = tuple(NeedLine(key=item_key(e.id), text=STRINGS["gone_line"].format(label=e.label, rel=shown(e.rel_path)),
                           item_id=e.id, label=e.label, number=e.number, rel_path=e.rel_path,
                           actions=("choose_file", "keep_words", "remove")) for _r, e in hits)
    key = f"gone:{group}:{_digest(ids)}"
    return Entry(key=key, kind=GONE, title=title, lines=lines, actions=("choose_folder", "keep_words", "remove"),
                 unseen=key not in seen, say=STRINGS["gone_say"],
                 data={"work_id": row.work_id, "title": row.title, "media_word": word, "item_ids": tuple(ids),
                       "folder": _folder(hits[0][1].rel_path), "group": group})


def _video_entry(group, hits, seen, mine_line):
    row = hits[0][0]
    word = view_rows.MEDIA_WORD.get(row.media, "video")
    ids = [e.id for _r, e in hits]
    s = view_rows.STRINGS
    if len(hits) == 1:
        title = s["need_title_one"].format(title=row.title, ep=hits[0][1].label, word=word)
        say = s["need_line_one"].format(line=mine_line, word=word)
    else:
        title = s["need_title_n"].format(title=row.title, n=len(hits), unit=_unit(row.media), word=word)
        say = s["need_line_n"].format(line=mine_line, word=word)
    lines = tuple(NeedLine(key=item_key(e.id), text=f"{e.label} · " + s["need_ep"].format(word=word), item_id=e.id,
                           label=e.label, number=e.number, rel_path=e.rel_path,
                           actions=("choose_video",)) for _r, e in hits)
    key = f"video:{group}:{_digest(ids)}"
    return Entry(key=key, kind=NO_VIDEO, title=title, lines=lines, actions=("find_videos", "link_these"),
                 unseen=key not in seen, say=say,
                 data={"work_id": row.work_id, "title": row.title, "media_word": word, "item_ids": tuple(ids),
                       "folder": _folder(hits[0][1].rel_path), "group": group})


def _folder(rel):
    rel = _norm(rel)
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _line(e):
    return NeedLine(key=item_key(e.id), text=STRINGS["gone_line"].format(label=e.label, rel=shown(e.rel_path)),
                    item_id=e.id, label=e.label, number=e.number, rel_path=e.rel_path,
                    actions=("choose_file", "keep_words", "remove"))


def _prefixes(rel):
    """A library path's folders, top first, as (key, as written): `Library/A/ep01.srt` -> Library, Library/A."""
    parts = _norm(rel).split("/")[:-1]
    return [("/".join(parts[:i]).casefold(), "/".join(parts[:i])) for i in range(1, len(parts) + 1)]


def _fold_gone(rows, gone, offline, seen, counts=None, settled=False):
    """K1 / K3: the cards that hold many shows' gone files -> ([Entry], {item_id folded into them}). The library
    first, once `settled` (every folder looked at this run, no root offline): LIBRARY_MIN gone files or more, of two
    shows or more, more than half of the LIBRARY's files (Current's, not under an offline root, and Goal's, Finished's
    and New arrivals' as `counts` holds them — Goal's 2,000 files never read as "most gone" for Current's 24) -> one
    `library-gone` card holding them all. Else each gone file goes to the top-most library folder
    above it holding FOLDER_MIN gone files or more, of two shows or more, more than half of its files gone -> one
    `files-folder` card each, in the order of their first gone file. Pure: the view's own flags, no file looked at."""
    hits = [hit for g in gone for hit in gone[g]]
    if len(hits) < min(FOLDER_MIN, LIBRARY_MIN) or len({_group(r) for r, _e in hits}) < 2:
        return [], set()
    files, names, total = {}, {}, 0
    for r in rows:
        for e in r.episodes:
            if offline(e.rel_path):
                continue
            total += 1
            for key, name in _prefixes(e.rel_path):
                files[key] = files.get(key, 0) + 1
                names.setdefault(key, name)
    if counts is not None:
        total += (counts.goal_files or 0) + (counts.finished or 0) + (counts.arrival_files or 0)
    if settled and len(hits) >= LIBRARY_MIN and 2 * len(hits) > total:
        return [_library_entry(hits, total, seen)], {e.id for _r, e in hits}
    lost, groups = {}, {}
    for r, e in hits:
        for key, _name in _prefixes(e.rel_path):
            lost[key] = lost.get(key, 0) + 1
            groups.setdefault(key, set()).add(_group(r))
    held = {}
    for r, e in hits:
        for key, _name in _prefixes(e.rel_path):
            if lost[key] >= FOLDER_MIN and len(groups[key]) >= 2 and 2 * lost[key] > files.get(key, 0):
                held.setdefault(key, []).append((r, e))
                break
    out = [_files_folder_entry(names[k], held[k], files.get(k, 0), seen) for k in held]
    return out, {e.id for k in held for _r, e in held[k]}


def _common_folder(rels):
    """The deepest library folder every one of `rels` lies under, as the first one writes it ('' none), compared as
    the store compares paths (a case apart is one folder)."""
    common = None
    for rel in rels:
        keys = [k for k, _n in _prefixes(rel)]
        if common is None:
            common = keys
            continue
        n = 0
        while n < len(common) and n < len(keys) and common[n] == keys[n]:
            n += 1
        common = common[:n]
    if not common:
        return ""
    return _prefixes(rels[0])[len(common) - 1][1]


def _titles(hits):
    return list(dict.fromkeys(r.title for r, _e in hits))


def _files_folder_entry(folder, hits, total, seen):
    hits = sorted(hits, key=lambda hit: hit[1].id)
    ids = [e.id for _r, e in hits]
    key = f"files:{_digest([folder.casefold()] + ids)}"
    plain = "/" not in _norm(folder) and library_store.TIER_OF_FOLDER.get(_norm(folder))   # a bare 2.x tier folder:
    title = STRINGS["files_folder_title_library" if plain else "files_folder_title"]       # never named (#7)
    return Entry(key=key, kind=FILES_FOLDER, title=title.format(n=view_rows.thousands(len(ids)), folder=shown(folder)),
                 lines=tuple(_line(e) for _r, e in hits), actions=("choose_folder", "remove"), unseen=key not in seen,
                 say=STRINGS["files_folder_say"].format(shows=_shows(_titles(hits))),
                 data={"folder": folder, "item_ids": tuple(ids), "shows": tuple(_titles(hits)), "n": len(ids),
                       "files": total})


def _emptied_entry(note, seen):
    """A5K-2: the library folder emptied under its record -> ONE card, *Start fresh* · *Keep my old library*; its key
    names the note's time (emptied again later, it asks again)."""
    key = f"emptied:{note.get('at') or ''}"
    files = note.get("files") or 0
    return Entry(key=key, kind=LIBRARY_EMPTIED, title=STRINGS["emptied_title"], lines=(),
                 actions=("start_fresh", "keep_old"), unseen=key not in seen,
                 say=STRINGS["emptied_say"].format(n=view_rows.thousands(int(files))), data={"files": files})


def _library_entry(hits, total, seen):
    hits = sorted(hits, key=lambda hit: hit[1].id)
    ids = [e.id for _r, e in hits]
    base = _common_folder([e.rel_path for _r, e in hits])
    key = f"library:{_digest(ids)}"
    return Entry(key=key, kind=LIBRARY_GONE,
                 title=STRINGS["library_title"].format(n=view_rows.thousands(len(ids)),
                                                       total=view_rows.thousands(total)),
                 lines=tuple(_line(e) for _r, e in hits), actions=("start_fresh", "choose_folder"),
                 unseen=key not in seen, say=STRINGS["library_say"],
                 data={"folder": base, "item_ids": tuple(ids), "shows": tuple(_titles(hits)), "n": len(ids),
                       "files": total})


def match_tree(folder, base, lines):
    """*Choose a folder…* on a folder's or the library's card (a worker): each gone line's file in `folder` at its own
    place under `base` (its library folder: `Library/A/ep01.srt` under `Library` is `<folder>/A/ep01.srt`), else the
    one file under `folder` with its name -> [(line, path)]. One walk of `folder`; never a name two files share, nor
    two gone lines share (each would take the one file), and never one file for two lines."""
    by_name = None
    base = [p.casefold() for p in _norm(base).split("/") if p]
    shared = {}                                      # how many gone lines carry each name
    for ln in lines:
        name = _norm(ln.rel_path).rsplit("/", 1)[-1].casefold()
        shared[name] = shared.get(name, 0) + 1
    claimed = set()
    out = []
    for ln in lines:
        parts = [p for p in _norm(ln.rel_path).split("/") if p]
        inside = parts[len(base):] if base and [p.casefold() for p in parts[:len(base)]] == base else parts
        there = os.path.join(folder, *inside) if inside else ""
        if there and os.path.isfile(there) and os.path.normcase(there) not in claimed:
            claimed.add(os.path.normcase(there))
            out.append((ln, there))
            continue
        if by_name is None:                          # walked once, only when a file isn't at its place
            by_name = {}
            for where, dirs, names in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]   # never the trash (its files go in 30 days)
                for name in names:
                    by_name.setdefault(name.casefold(), []).append(os.path.join(where, name))
        name = parts[-1].casefold() if parts else ""
        same = by_name.get(name) or ()
        if len(same) == 1 and shared.get(name) == 1 and os.path.normcase(same[0]) not in claimed:
            claimed.add(os.path.normcase(same[0]))
            out.append((ln, same[0]))
    return out


def _bulk(shows):
    """The one answer for many shows (lean 4: two shows or more of a kind), or None."""
    gone = [e for e in shows if e.kind == GONE]
    video = [e for e in shows if e.kind == NO_VIDEO]
    n_gone = sum(len(e.lines) for e in gone)
    n_video = sum(len(e.lines) for e in video)
    actions, labels = [], {}
    if len(video) >= 2:
        actions.append("find_all")
        labels["find_all"] = STRINGS["find_all"].format(n=n_video, m=len(video))
    if len(gone) >= 2:
        actions += ["keep_all", "remove_all"]
        labels["keep_all"] = STRINGS["keep_all"].format(n=n_gone)
        labels["remove_all"] = STRINGS["remove_all"].format(n=n_gone)
    if not actions:
        return None
    m = len({e.data["work_id"] if e.data["work_id"] is not None else e.key for e in (gone if len(gone) >= 2 else [])
             + (video if len(video) >= 2 else [])})
    if len(gone) >= 2 and len(video) >= 2:
        title = STRINGS["bulk_title_both"].format(m=m)
    elif len(gone) >= 2:
        title = STRINGS["bulk_title_files"].format(n=n_gone, m=len(gone))
    else:
        title = STRINGS["bulk_title_videos"].format(n=n_video, m=len(video))
    data = {"labels": labels, "videos": (n_video, len(video)), "files": (n_gone, len(gone)),
            "video_keys": tuple(e.key for e in video),
            "keys": tuple(sorted(e.key for e in shows if (e.kind == GONE and len(gone) >= 2) or   # order-free
                                 (e.kind == NO_VIDEO and len(video) >= 2))),                       # (C1)
            "item_ids": tuple(sorted(i for e in gone for i in e.data["item_ids"])) if len(gone) >= 2 else ()}
    return Entry(key="bulk", kind=BULK, title=title, lines=(), actions=tuple(actions), unseen=False,
                 say=STRINGS["bulk_say"], data=data)


def _ask_entry(ask, by_id, seen):
    rel = _norm(ask.get("rel"))
    if not rel:
        return None
    lines = []
    for c in ask.get("candidates") or ():
        if isinstance(c, dict):
            cid, crel, ctitle = c.get("id"), c.get("rel_path"), c.get("title")
        else:
            cid, crel, ctitle = c, None, None
        hit = by_id.get(cid)
        if hit is not None:
            ctitle = f"{hit[0].title} · {hit[1].label}"
            crel = crel or hit[1].rel_path
        crel = _norm(crel)
        ctitle = ctitle or view_rows.stem(crel.rsplit("/", 1)[-1]) or f"#{cid}"
        lines.append(NeedLine(key=item_key(cid), text=STRINGS["ask_line"].format(title=ctitle, rel=shown(crel) or "?"),
                              item_id=cid, label=ctitle, number=None, rel_path=crel, actions=("this_one",)))
    if not lines:
        return None
    name = rel.rsplit("/", 1)[-1]
    if len(lines) == 1:
        title = STRINGS["ask_title_one"].format(name=name, old=shown(lines[0].rel_path) or lines[0].label)
    else:
        title = STRINGS["ask_title_n"].format(name=name, n=len(lines))
    key = f"ask:{_digest([rel.casefold()] + [ln.item_id for ln in lines])}"
    return Entry(key=key, kind=ASK, title=title, lines=tuple(lines), actions=("its_new",), unseen=key not in seen,
                 say=STRINGS["ask_say"].format(rel=shown(rel)), data={"rel": rel})


def _offline_entry(root, by_id, seen):
    ids = tuple(sorted(i for i, (_r, e) in by_id.items() if _under(e.rel_path, root.rel)))   # order-free (C1: a
    #                                                                     reorder of Current rebuilds no card)
    n = root.files if root.files is not None else len(ids)
    title = STRINGS["offline_title_one"].format(label=root.label) if n == 1 else \
        STRINGS["offline_title"].format(label=root.label, n=view_rows.thousands(n))
    key = f"offline:{os.path.normcase(os.path.abspath(root.path)) if root.path else root.rel}"
    # IK-8: no *Remove* here — a drive that's only unplugged must never go to the trash
    return Entry(key=key, kind=OFFLINE, title=title, lines=(), actions=("keep_words",), unseen=key not in seen,
                 say=STRINGS["offline_say"], data={"path": root.path, "rel": root.rel, "files": n, "item_ids": ids})


def folder_key(path):
    """A gone folder's card key: the folder, as the store compares paths (a case or slash apart is one)."""
    return f"folder:{library_store.path_key(os.path.abspath(path))}"


def _shows(titles):
    """The shows a folder held, in plain words: *A*, *A and B*, *A, B and C*, *A, B, C and 2 more*."""
    titles = [t for t in titles or () if t]
    if len(titles) <= 2:
        return STRINGS["shows_and"].format(a=titles[0], b=titles[1]) if len(titles) == 2 else "".join(titles)
    if len(titles) == 3:
        return STRINGS["shows_and"].format(a=", ".join(titles[:2]), b=titles[2])
    return STRINGS["shows_more"].format(shows=", ".join(titles[:3]), n=len(titles) - 3)


def _folder_entry(row, seen):
    """T6: a gone source folder's card — the folder and where it was (its title), the shows it held and what each
    answer does (its line). *Stop reading it* leads where nothing is left for it to find: every episode Finished, or
    a look reads them elsewhere already (the folder holds none now)."""
    path = os.path.normpath(row["path"])
    name, parent = os.path.basename(path) or path, os.path.dirname(path) or path
    n = int(row.get("items") or 0)
    found = list(row.get("found_in") or ())
    shows = _shows(row.get("shows")) or name
    episodes = STRINGS["episode_one"] if n == 1 else STRINGS["episode_n"].format(n=n)
    finished = bool(row.get("finished"))
    if n and finished:
        said = [STRINGS["folder_finished"].format(shows=shows, episodes=episodes)]
    elif n:
        said = [STRINGS["folder_held"].format(shows=shows, episodes=episodes)]
    else:
        said = [STRINGS["folder_held_none"].format(shows=shows)]
    if found and not n:
        said.append(STRINGS["folder_read_now"].format(found=found[0]))
    elif found:
        said.append(STRINGS["folder_found_finished" if finished else "folder_found"].format(found=found[0]))
    elif not finished:
        said.append(STRINGS["folder_moved"])
    said.append(STRINGS["folder_stay"])
    stop_first = finished or bool(found and not n)
    actions = (("stop_reading", "find_folder") if stop_first else ("find_folder", "stop_reading")) + ("keep_waiting",)
    key = folder_key(path)
    return Entry(key=key, kind=FOLDER_GONE, title=STRINGS["folder_title"].format(name=name, parent=parent), lines=(),
                 actions=actions, unseen=key not in seen, say=" ".join(said),
                 data={"root": row["id"], "path": row["path"], "name": name, "items": n, "found_in": tuple(found),
                       "finished": finished, "shows": tuple(row.get("shows") or ()), "language": row.get("language")})


def _gap_entry(gap, seen):
    items = list(dict.fromkeys(gap.get("items") or ()))
    since, until = gap.get("since"), gap.get("until") or ""
    span = STRINGS["gap_span"].format(a=since[:10], b=until[:10]) if since else STRINGS["gap_until"].format(b=until[:10])
    n = len(items)
    title = STRINGS["gap_title"].format(span=span, n=n, noun="episode" if n == 1 else "episodes",
                                        have="has" if n == 1 else "have")
    key = f"gap:{gap.get('id')}"
    return Entry(key=key, kind=GAP, title=title, lines=(), actions=("make_cards", "leave_them"),
                 unseen=key not in seen, say="", data={"gap_id": gap.get("id"), "item_ids": tuple(items)})


def _first_cards_entry(rows, seen, mine_line, cards_on=False):
    """D1's one line: the first `mine_line` episodes of Current (fewer while Current holds fewer). `cards_on` (Connect's
    switch already on, setup's page 5 said yes): the same question, its actions' words never offering to turn it on
    (SRC W1 fix, Decision 1)."""
    have = sum(1 for r in rows if r.tier in ("now", "soon") for e in r.episodes if not e.missing)
    n = min(mine_line, have) if have else mine_line
    title = STRINGS["first_title_one"] if n == 1 else STRINGS["first_title"].format(n=n)
    actions = ("first_cards_on", "not_now_on") if cards_on else ("first_cards", "not_now")
    return Entry(key=FIRST_CARDS, kind=FIRST_CARDS, title=title, lines=(), actions=actions,
                 unseen=FIRST_CARDS not in seen, say=STRINGS["first_say"], data={"n": n})


FLAG_WORDS = ("red", "orange", "green", "blue", "pink", "turquoise", "purple")


def signal_words(terms):
    """Known from Anki's states as the question says them: *suspended and marked*, *flagged red*."""
    words = []
    for term in terms or ("suspended",):
        if term.startswith("flag:") and term[5:].isdigit() and 1 <= int(term[5:]) <= len(FLAG_WORDS):
            words.append(f"flagged {FLAG_WORDS[int(term[5:]) - 1]}")
        else:
            words.append(term)
    return " and ".join(words)


def _known_entry(offer, seen):
    n, states = int(offer.get("cards") or 0), signal_words(offer.get("terms"))
    title = (STRINGS["known_title_one"].format(states=states) if n == 1
             else STRINGS["known_title"].format(states=states, n=n))
    key = f"{KNOWN_OFFER}:{offer.get('id') or n}"         # the offer's own cards: a new offer counts again
    return Entry(key=key, kind=KNOWN_OFFER, title=title, lines=(), actions=("mark_known", "leave_known"),
                 unseen=key not in seen, say=STRINGS["known_say"].format(states=states), data={"cards": n})


def backlog_offer(language):
    """The shows behind 順's deck's new cards (`modules/junban/backlog_shows`'s last offer, read-only), or None (no
    offer, 順 not in this Surasura)."""
    try:
        from modules.junban import backlog_shows
        return backlog_shows.offer(language)
    except Exception:
        return None


def _names(shows, most=5):
    words = [STRINGS["behind_name"].format(title=s.get("title") or "?", n=int(s.get("cards") or 0))
             for s in shows[:most]]
    if len(shows) > most:
        words.append(STRINGS["behind_more"].format(k=len(shows) - most))
    return ", ".join(words)


def backlog_head(record):
    """The offer's first sentence (the card's and setup's *Card order* line): *Your 2,300 new cards come from 14 shows;
    12 are on this PC.*"""
    shows = [s for s in (record or {}).get("shows") or () if isinstance(s, dict)]
    n, every = int((record or {}).get("cards") or 0), int((record or {}).get("all") or 0)
    cards = (STRINGS["behind_cards_one"] if n == 1 and every <= 1 else
             STRINGS["behind_cards"].format(n=n) if every <= n else STRINGS["behind_cards_some"].format(n=n))
    found = sum(1 for s in shows if s.get("state") != "away")
    come = "comes" if n == 1 and every <= 1 else "come"
    if len(shows) == 1:
        return STRINGS["behind_from_one" if found else "behind_from_one_away"].format(cards=cards, come=come)
    key = "behind_from" if found > 1 else "behind_from_found_one" if found == 1 else "behind_from_none"
    return STRINGS[key].format(cards=cards, come=come, s=len(shows), found=found)


def _backlog_entry(record, view, seen):
    """ONE card for the shows behind the backlog (A7B-3), or None when none of their files waits in New arrivals now
    (`view.arrivals`: one placed by hand, or by *Add them*, since the offer was worked out is no longer offered)."""
    arrivals = {i for a in (getattr(view, "arrivals", None) or ()) for i in (a.item_ids or ())}
    shows = [s for s in record.get("shows") or () if isinstance(s, dict)]
    waiting = [dict(s, ids=[i for i in s.get("ids") or () if i in arrivals])
               for s in shows if s.get("state") == "waiting"]
    waiting = [s for s in waiting if s["ids"]]
    if not waiting:
        return None
    head, found = backlog_head(record), sum(1 for s in shows if s.get("state") != "away")
    k = len(waiting)
    ask = (STRINGS["behind_add_it"] if k == 1 and found == 1 else STRINGS["behind_add_all"] if k == found else
           STRINGS["behind_add_one"] if k == 1 else STRINGS["behind_add"].format(k=k))
    away = [s for s in shows if s.get("state") == "away"]
    say = " ".join([STRINGS["behind_waiting"].format(names=_names(waiting))] +
                   ([STRINGS["behind_away"].format(names=_names(away))] if away else []))
    ids = sorted(i for s in waiting for i in s["ids"])
    key = f"{BACKLOG_SHOWS}:{_digest([str(i) for i in ids])}"      # a show placed or a new one waiting: asked again
    return Entry(key=key, kind=BACKLOG_SHOWS, title=f"{head} {ask}", lines=(), actions=("add_shows", "leave_shows"),
                 unseen=key not in seen, say=say, data={"ids": ids, "shows": len(waiting)})


def badge(entries_):
    """The tab's number: the unseen entries (P1.2-1: a seen one stays listed and stops counting)."""
    return sum(1 for e in entries_ if e.unseen)


def answer_keys(thing):
    """What *Keep its words* / *Keep all their words* / *Leave them* records for an Entry or a NeedLine -> [key]."""
    if isinstance(thing, NeedLine):
        return [item_key(thing.item_id)]
    if thing.kind in (GONE, BULK, FILES_FOLDER, LIBRARY_GONE):
        return [item_key(i) for i in (thing.data or {}).get("item_ids") or ()]
    return [thing.key]


# --- seen and answered (the local data folder; never settings.json) ------------------------------------------------- #
_lock = threading.Lock()         # the one writer, and every read in this process (alpha 4 E: a read holding the file
#                                  open made the write's replace fail on Windows — PermissionError, the answer lost)
_FIELDS = ("seen", "answered", "offered", "stopped")   # `offered`: the lines a step asked for (D1's), until answered;
#                                                        `stopped`: *Stop asking* (alpha 4 D2), until its trouble goes
REPLACE_WAITS = (0.01, 0.03, 0.1, 0.25)   # s: another program (a virus scan, a sync, a child process) reading the file
#                                            as it is replaced — waited out, then the write fails as before


def seen_path(language):
    return os.path.join(path_utils.get_local_data_path(), f"needs_seen_{language}.json")


def _read(language):
    """The seen file's lists (and *Not now*'s days), read under `_lock`: never while it is being replaced (alpha 4 E)."""
    with _lock:
        return _load(language)


def _load(language, strict=False):
    """(Under `_lock`.) The seen file's lists, and `later` ({key: the day it was put off}). `strict` (a write-back's
    read, W3.2 H W5): only a file that isn't there reads as empty — one that can't be read, isn't JSON or is another
    version raises, so a write never goes over earlier answers (a held file, a newer Surasura's)."""
    empty = dict({k: [] for k in _FIELDS}, later={}, library=None)
    try:
        with open(seen_path(language), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty
    except (OSError, ValueError):
        if strict:
            raise
        return empty
    if not isinstance(data, dict) or data.get("version") != SEEN_VERSION:
        if strict:
            raise ValueError(f"the seen file isn't version {SEEN_VERSION}: left as it is")
        return empty
    later = data.get("later")
    out = {k: [x for x in data.get(k) or () if isinstance(x, str)] for k in _FIELDS}
    out["later"] = {k: v for k, v in later.items() if isinstance(k, str) and isinstance(v, str)} \
        if isinstance(later, dict) else {}
    library = data.get("library")
    out["library"] = library if isinstance(library, str) and library else None    # IK-10: whose answers they are
    return out


def _write(language, data):
    """(Under `_lock`: the one writer.) The whole file, atomically — a temporary file, then one replace."""
    path = seen_path(language)
    tmp = path + ".tmp"
    data = {k: v for k, v in data.items() if k in ("seen", "answered") or v}   # none offered, stopped or put off:
    with open(tmp, "w", encoding="utf-8") as f:                                 # the file as it always was
        json.dump({"version": SEEN_VERSION, **data}, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    for wait in REPLACE_WAITS + (None,):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if wait is None:
                raise
            time.sleep(wait)


def _add(language, field, keys):
    keys = [k for k in dict.fromkeys(keys or ()) if isinstance(k, str)]
    if not keys:
        return 0
    with _lock:
        data = _load(language, strict=True)
        have = data[field]
        new = [k for k in keys if k not in set(have)]
        if not new:
            return 0                                # nothing new: nothing written (S19)
        data[field] = have + new                    # never capped: a key goes only with its trouble (`prune`)
        _write(language, data)
    return len(new)


def read_seen(language):
    """The store's entries' keys the user has seen -> frozenset."""
    return frozenset(_read(language)["seen"])


def mark_seen(language, keys):
    """The page was shown: `keys` stop counting (still listed) -> how many were new. A worker's call (a file write)."""
    return _add(language, "seen", keys)


def read_answered(language):
    """The answers kept here (*Keep its words*: `item:<id>`; *Leave them* and an offline root's *Keep*: the entry's key)."""
    return frozenset(_read(language)["answered"])


def answer(language, keys):
    """Record *Keep its words* / *Leave them* (`answer_keys`): those leave the page; nothing in the store changes."""
    return _add(language, "answered", keys)


def read_offers(language):
    """The lines a step offered (`offer`) -> frozenset of their keys."""
    return frozenset(_read(language)["offered"])


def offer(language, key=FIRST_CARDS):
    """(A worker: a file write.) A step's one line offered (D1: setup's first scan took something in): listed until it
    is answered, then never again (never pruned) -> 1 when it was new."""
    return _add(language, "offered", [key])


def prune(language, view, offline_roots=None, connect=None, asks=None, lines=None, gone_folders=None):
    """(S3, N10; a worker's call, after the reads `entries` is given.) The keys whose trouble is gone leave the seen
    file — never by age or by count. Judged only by what the caller read (a key of a kind it didn't read stays): a
    file's answer (`item:`) while Current holds it missing, a show's card while it is listed; with `offline_roots`, an
    offline root's while it is still offline — back, its *Keep their words* goes, so offline again later it is asked
    again; with `connect`, the video cards' and the gaps'; with `asks`, the rename asks'. A view that isn't the
    store's prunes none of those. With `lines` (round 8 row 54: the standing lines still standing,
    `standing.not_back`), a hidden offline line's (`line:`) while its folder is still away; with `gone_folders` (T6:
    the looks' gone rows, as the window holds them), a gone folder's card while it is still gone — back, it counts
    again the next time it goes. Nothing gone → nothing written. -> how many keys went."""
    store = view is not None and view.mode == "store"
    if not store and lines is None:
        return 0
    judged = ({"item", "gone", "files", "library"} | ({"offline"} if offline_roots is not None else set()) |
              ({"video", "gap", KNOWN_OFFER, "anki"} if connect is not None else set()) |
              ({"ask"} if asks is not None else set()) |
              ({"folder"} if gone_folders is not None else set())) if store else set()
    if lines is not None:
        judged.add("line")
    roots = [r if isinstance(r, Root) else Root(*r) for r in offline_roots or ()]
    with _lock:
        data = _load(language, strict=True)
        present = set(lines or ())
        if store:
            present |= {item_key(e.id) for r in view.rows for e in r.episodes if e.missing}
            present |= {e.key for e in entries(view, connect=connect, offline_roots=roots, asks=asks or (),
                                              answered=frozenset(data["answered"]), settled=True)}   # K1's card too
            present |= {_offline_entry(r, {}, frozenset()).key for r in roots}          # answered ones too
            present |= {f"gap:{g.get('id')}" for g in (connect or {}).get("gaps") or ()}
            present |= {folder_key(r["path"]) for r in gone_folders or () if r.get("path")}
        kept = {f: [k for k in data[f] if k.split(":", 1)[0] not in judged or k in present]
                for f in ("seen", "answered", "stopped")}
        gone = sum(len(data[f]) - len(kept[f]) for f in kept)
        today = _today()                                         # *Not now*: back the next day, or with its trouble
        kept["later"] = {k: d for k, d in data["later"].items()
                         if d >= today and (k.split(":", 1)[0] not in judged or k in present)}
        gone += len(data["later"]) - len(kept["later"])
        kept["offered"] = data["offered"]
        kept["library"] = data["library"]
        if gone:
            _write(language, kept)
    return gone


# --- alpha 4 D2: *Not now* (hidden until tomorrow) and *Stop asking* (never again, with Undo) --------------------- #
def _today():
    return time.strftime("%Y-%m-%d")


def read_hidden(language):
    """The cards left off the page: *Stop asking*'s, and *Not now*'s put off today -> frozenset of keys."""
    data, today = _read(language), _today()
    return frozenset(data["stopped"]) | {k for k, d in data["later"].items() if d >= today}


def put_off(language, keys):
    """*Not now*: `keys` hidden for the rest of today (local time) -> how many were new."""
    keys = [k for k in dict.fromkeys(keys or ()) if isinstance(k, str)]
    if not keys:
        return 0
    today = _today()
    with _lock:
        data = _load(language, strict=True)
        new = [k for k in keys if data["later"].get(k) != today]
        if not new:
            return 0                                # nothing new: nothing written (S19)
        data["later"] = dict({k: d for k, d in data["later"].items() if d >= today}, **dict.fromkeys(new, today))
        _write(language, data)
    return len(new)


def stop_asking(language, keys):
    """*Stop asking*: `keys` never asked again (the item and its words kept; a key goes with its trouble, `prune`)
    -> how many were new."""
    return _add(language, "stopped", keys)


def ask_again(language, keys):
    """The Undo of *Not now* / *Stop asking*: `keys` asked again -> how many were hidden."""
    keys = {k for k in keys or () if isinstance(k, str)}
    if not keys:
        return 0
    with _lock:
        data = _load(language, strict=True)
        n = sum(1 for k in data["stopped"] if k in keys) + sum(1 for k in data["later"] if k in keys)
        if not n:
            return 0
        data["stopped"] = [k for k in data["stopped"] if k not in keys]
        data["later"] = {k: d for k, d in data["later"].items() if k not in keys}
        _write(language, data)
    return n


def keep_to_library(language, library):
    """(IK-10; a worker's call, before the gather's reads.) The seen file's answers are one library's — `library`, its
    store id (`LibraryReader.store_id`). A file naming none takes it as its own, every answer kept (an older file, the
    first gather). One naming another library (a reinstall, *Start fresh*: a new store id, its item ids from 1 again)
    lets go of that library's *Stop asking* and *Not now* and of every answer keyed by a file's id (`item:`, which
    names another file now); a line's or a step's answer stays. `library` None (not read yet): nothing judged. Nothing
    moved, nothing written (S19). -> how many answers went."""
    if not library:
        return 0
    with _lock:
        data = _load(language, strict=True)
        have = data["library"]
        if have == library:
            return 0
        if have is None and not any(data[f] for f in _FIELDS) and not data["later"]:
            return 0                                # nothing answered yet: nothing to tie to it
        gone = 0
        if have is not None:
            gone = len(data["stopped"]) + len(data["later"])
            data["stopped"], data["later"] = [], {}
            for f in ("seen", "answered"):
                kept = [k for k in data[f] if not k.startswith("item:")]
                gone += len(data[f]) - len(kept)
                data[f] = kept
        data["library"] = library
        _write(language, data)
    return gone


def mark_all_seen(language, entries_, connect_path=None):
    """Every unseen entry shown, marked seen where it lives: the store's here, Connect's through `status.mark_seen`
    (failures are the status service's own: `StatusService.mark_seen`). A worker's call -> (here, Connect's)."""
    mine = [e.key for e in entries_ if e.unseen and e.kind not in (FAILURE,) and not (e.data or {}).get("connect")]
    theirs = [e.data["need_id"] for e in entries_ if e.unseen and (e.data or {}).get("connect")]
    n_connect = 0
    if theirs:
        try:
            from app.connect import status
            n_connect = status.mark_seen(theirs, path=connect_path)
        except Exception:
            n_connect = 0                           # Connect's ledger busy or gone: they count until the next look
    return mark_seen(language, mine), n_connect


# --- what the entries are read from (each on a worker, never the window's thread) ------------------------------------ #
def read_connect(language, path=None):
    """Connect's record for `language` (`status.read`, read-only) with its gaps (`ledger.gaps`' rows, read-only: the
    window never makes or writes the ledger here) -> dict, or None when it can't be read."""
    try:
        from app.connect import ledger, status
        rec = status.language_record(status.read([language], path=path), language)
        rec["gaps"] = _gaps(language, path or ledger.path())
        rec["known_offer"] = known_offer(language)
        if _anki_closed() in _anki_waits(rec):          # A3W-6's *Open Anki*: Anki looked for only then
            rec["anki_openable"] = _anki_openable()
        return rec
    except Exception:
        return None


_SESSION = f"{os.getpid()}-{int(time.time())}"     # the Anki line's seen key holds this window's run (A-4)


def _anki_closed():
    """Connect's *Anki isn't open* reason (`runner.ANKI_CLOSED`)."""
    from app.connect.runner import ANKI_CLOSED
    return ANKI_CLOSED


def _anki_openable():
    """Can Surasura start Anki here (`open_anki.find`: where its installers put it)? A worker's look (disk, registry)."""
    try:
        from app.connect import open_anki
        return open_anki.find() is not None
    except Exception:
        return False


def known_offer(language):
    """Known from Anki's one-time question still to answer (#43) -> {"cards": n, "terms": [...], "id": its cards'
    digest}, or None (none, an
    answered one, an empty one, a record that can't be read). Read-only: the record is `known_signal`'s."""
    try:
        from app.connect import known_signal
        state = known_signal.load(language)
    except Exception:
        return None
    offer = state.get("offer") or {}
    cards = offer.get("cards") or ()
    if offer.get("state") != "pending" or not cards:
        return None
    ids = sorted(str(c.get("card")) for c in cards if isinstance(c, dict))
    return {"cards": len(cards), "terms": list(state.get("terms") or ()), "id": _digest(ids)}


def _gaps(language, path):
    import pathlib
    import sqlite3
    if not os.path.exists(path):
        return []
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=2.0)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gaps'").fetchone() is None:
            return []
        cur = conn.execute("SELECT id, since, until, items, noticed FROM gaps WHERE language = ? ORDER BY id",
                           (language,))
        out = []
        for gid, since, until, items, noticed in cur.fetchall():
            try:
                items = json.loads(items)
            except (TypeError, ValueError):
                items = []
            out.append({"id": gid, "since": since, "until": until, "items": items, "noticed": noticed})
        return out
    finally:
        conn.close()


def asks_of(store):
    """9a's questions with their candidates' paths and titles (the reader's store handle, on its worker) -> [{rel,
    candidates: [{id, rel_path, title}]}]; a candidate no longer in the library is left out. Then H-8's (Hon): each
    audiobook asking about a book (`Store.audiobook_asks`), `kind` AUDIOBOOK_ASK."""
    out = []
    for ask in store.rename_asks():
        cands = []
        for c in ask.get("candidates") or ():
            item = store.item(c)
            if item is not None:
                cands.append({"id": c, "rel_path": item.get("rel_path"), "title": item.get("title")})
        out.append({"rel": ask.get("rel"), "candidates": cands})
    if hasattr(store, "audiobook_asks"):
        out += [dict(a, kind=AUDIOBOOK_ASK) for a in store.audiobook_asks()]
    if hasattr(store, "audiobook_finds"):                # a5-2: after a *No*, find its book
        out += [dict(a, kind=AUDIOBOOK_FIND) for a in store.audiobook_finds()]
    if hasattr(store, "transcript_mismatches"):          # a6 (H-13): a transcript its book doesn't hold
        out += [dict(a, kind=AUDIOBOOK_TRANSCRIPT) for a in store.transcript_mismatches()]
    return out


def _audiobook_files(ask):
    """An audiobook card's files and length: `8 files (01.mp3 … 08.mp3) · 1 h 25 min`."""
    from app.audiobooks import length_text
    names = [os.path.basename(str(f)) for f in ask.get("files") or ()]
    files = STRINGS["abook_files_one"] if len(names) == 1 else STRINGS["abook_files"].format(n=len(names))
    if len(names) > 1:
        files += f" ({STRINGS['abook_files_more'].format(first=names[0], last=names[-1])})"
    elif names:
        files += f" ({names[0]})"
    length = length_text(ask.get("seconds"))
    return f"{files} · {length}" if length else files


def _audiobook_find_entry(ask, seen):
    """a5-2's card, after a *No* left an audiobook alone: *Which book does the audiobook 「…」 read?* — *Find its
    book…* (`find_book`: the library's books, likeliest first, then an EPUB on the computer; the pick pairs as a *Yes*
    does, with Undo) · *It has no book* (`no_book`: alone, never asked again). Keyed by its item."""
    if ask.get("item_id") is None:
        return None
    key = f"find:{_digest(['audiobook-find', str(ask['item_id'])])}"
    files = _audiobook_files(ask)
    say = STRINGS["abook_find_say"].format(files=files, book=ask["said_no"]) if ask.get("said_no") else \
        STRINGS["abook_find_say_none"].format(files=files)
    return Entry(key=key, kind=AUDIOBOOK_FIND,
                 title=STRINGS["abook_find_title"].format(audio=ask.get("title") or "?"), lines=(),
                 actions=("find_book", "no_book"), unseen=key not in seen, say=say,
                 data={"item_id": ask["item_id"], "title": ask.get("title") or ""})


def _transcript_entry(ask, seen):
    """a6's line (H-13): *The transcript beside 「…」 doesn't match 「…」* — how much of it the book holds, and that it
    isn't used (the book's words count). Nothing to answer: its ⋯ (*Not now*, *Stop asking*) takes it away. Keyed by
    the transcript's bytes and the book's (another of either is a new line)."""
    if ask.get("item_id") is None or not ask.get("key"):
        return None
    key = f"transcript:{_digest(['audiobook-transcript', str(ask['key'])])}"
    share = ask.get("share")
    say = STRINGS["abook_transcript_say"].format(share=f"{share:.0%}") if isinstance(share, (int, float)) and share \
        else STRINGS["abook_transcript_say_none"]
    return Entry(key=key, kind=AUDIOBOOK_TRANSCRIPT,
                 title=STRINGS["abook_transcript_title"].format(audio=ask.get("title") or "?",
                                                                book=ask.get("book") or "?"),
                 lines=(), actions=(), unseen=key not in seen, say=say,
                 data={"item_id": ask["item_id"], "transcript": ask.get("transcript") or ""})


def _audiobook_entry(ask, seen):
    """H-8's card: *Is this audiobook 「…」 the book 「…」?* — its files (the first and last, how many) and length;
    *Yes, the same book* (`same_book`) · *No* (`not_book`), both the store's `answer_audiobook` (kept, never asked
    again). Keyed by the pair's answer key: a new edition of either is a new question."""
    if not ask.get("key") or ask.get("item_id") is None:
        return None
    names = [os.path.basename(str(f)) for f in ask.get("files") or ()]
    key = f"ask:{_digest(['audiobook', str(ask['key'])])}"
    return Entry(key=key, kind=AUDIOBOOK_ASK,
                 title=STRINGS["abook_title"].format(audio=ask.get("title") or (names[0] if names else "?"),
                                                     book=(ask.get("book") or {}).get("title") or "?"),
                 lines=(), actions=("same_book", "not_book"), unseen=key not in seen,
                 say=STRINGS["abook_say"].format(files=_audiobook_files(ask)),
                 data={"item_id": ask["item_id"], "key": ask["key"]})


def _label(path):
    target = path
    try:
        target = os.readlink(path)
    except (OSError, ValueError, NotImplementedError):
        pass
    target = str(target)
    for prefix in ("\\\\?\\UNC\\", "\\??\\UNC\\"):
        if target.startswith(prefix):
            target = "\\\\" + target[len(prefix):]
    for prefix in ("\\\\?\\", "\\??\\"):
        if target.startswith(prefix):
            target = target[len(prefix):]
    drive = os.path.splitdrive(target)[0]
    if re.fullmatch(r"[A-Za-z]:", drive or ""):
        return STRINGS["drive"].format(d=drive.upper())
    return STRINGS["folder"].format(p=drive or target)


def find_offline(language, rel_paths, data_dir=None):
    """The roots that aren't there (a worker: one stat per folder looked at) -> [Root]: the library folder itself, or a
    folder in it that is a link (a junction, a symlink) to a drive or share that isn't connected. A folder that is
    simply gone (moved, deleted) is no offline root: its files are a show's *gone* files."""
    data_dir = data_dir or path_utils.get_data_path(language)
    if not os.path.isdir(data_dir):
        return [Root(path=data_dir, rel="", label=_label(data_dir))]
    found, looked = {}, {}
    for rel in rel_paths or ():
        parts = [p for p in _norm(rel).split("/")[:-1] if p]
        for i in range(1, len(parts) + 1):
            sub = "/".join(parts[:i]).casefold()
            if sub not in looked:
                path = os.path.join(data_dir, *parts[:i])
                there = os.path.exists(path)
                looked[sub] = "there" if there else "link" if os.path.lexists(path) else "gone"
                if looked[sub] == "link":
                    found[sub] = Root(path=path, rel="/".join(parts[:i]), label=_label(path))
            if looked[sub] != "there":
                break
    return list(found.values())


# --- Find videos (a worker; never writes) ------------------------------------------------------------------------- #
class _Lister:
    """One look's folder listings (each folder listed once a call, `find_all`'s shows sharing them): the videos in a
    folder, by name — nothing opened."""

    def __init__(self):
        self._got = {}

    def videos(self, folder, deep):
        key = (os.path.normcase(os.path.abspath(folder)), deep)
        if key not in self._got:
            self._got[key] = self._list(folder, deep)
        return self._got[key]

    @staticmethod
    def _list(folder, deep):
        from app.connect import runner, videos
        out, todo = [], [(folder, 0)]
        while todo:
            where, depth = todo.pop()
            try:
                with os.scandir(where) as found:
                    for entry in found:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if deep and depth < videos.DEPTH:
                                    todo.append((entry.path, depth + 1))
                            elif runner.video_file(entry.name, entry.stat(follow_symlinks=False).st_size):
                                # Connect's one rule for a video file: never a Mac `._` copy or a small `.ts`
                                out.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue                            # offline, gone, not readable: nothing from it
        return sorted(out)


def _fold(text):
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def find_videos(language, need, settings, data_dir=None, _lister=None):
    """A *no video* card's lines looked for (see the module's doc) -> [(label, path or None, why)], in its order."""
    if need.kind != NO_VIDEO:
        raise ValueError("find_videos serves the no-video card only: a gone file is relinked, never given a video")
    from app.connect import videos
    data_dir = data_dir or path_utils.get_data_path(language)
    lister = _lister or _Lister()
    folders = videos.configured(settings, language)
    title = (need.data or {}).get("title")
    return [_find_one(line, data_dir, folders, title, lister) for line in need.lines]


def find_all(language, entries_, settings, data_dir=None):
    """*Find all missing videos*: every *no video* card's lines, one listing per folder -> {entry key: results}."""
    lister = _Lister()
    return {e.key: find_videos(language, e, settings, data_dir, lister) for e in entries_ if e.kind == NO_VIDEO}


def _find_one(line, data_dir, folders, title, lister):
    from app.connect import runner
    if line.number is None:
        return line.label, None, STRINGS["why_no_number"]
    shown = f"{line.number:02d}" if isinstance(line.number, int) else str(line.number)   # LM1a: `- 12.5` is 12.5
    show = os.path.join(data_dir, *[p for p in _norm(line.rel_path).split("/")[:-1] if p])

    def matching(paths):
        return [p for p in paths if view_rows.episode_number(os.path.basename(p)) == line.number]

    own = matching(lister.videos(show, False))
    own_keys = {os.path.normcase(p) for p in own}
    others, seen_keys = [], set(own_keys)
    for folder in folders:
        for p in matching(lister.videos(folder, True)):
            k = os.path.normcase(p)
            if k not in seen_keys:
                seen_keys.add(k)
                others.append((p, folder))
    here = [p for p in own if runner._on_disk(p)]
    there = [(p, f) for p, f in others if runner._on_disk(p)]
    if len(here) == 1:
        why = STRINGS["why_found_own"].format(name=os.path.basename(here[0]), k=len(there)) if there else \
            STRINGS["why_found"].format(name=os.path.basename(here[0]))
        return line.label, here[0], why
    if len(here) > 1:
        return line.label, None, STRINGS["why_many"].format(k=len(here), n=shown)
    if len(there) == 1:
        return line.label, there[0][0], STRINGS["why_found"].format(name=os.path.basename(there[0][0]))
    if len(there) > 1:
        names = [_fold(title), _fold(os.path.basename(show))]
        named = [p for p, f in there if any(n and n in _fold(os.path.relpath(os.path.dirname(p), f)) for n in names)]
        if len(named) == 1:
            return line.label, named[0], STRINGS["why_found_named"].format(name=os.path.basename(named[0]))
        return line.label, None, STRINGS["why_many"].format(k=len(there), n=shown)
    if own or others:                               # every match a cloud placeholder: never opened, never taken
        return line.label, None, STRINGS["why_cloud"].format(n=shown)
    return line.label, None, STRINGS["why_none"].format(n=shown)
