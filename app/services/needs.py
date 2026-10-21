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
  videos* · *Link these · N* → the writer's `link_video`, never `relink`; *Mine the text only*, hidden until P4.1 wires
  it). Shows in Current's order; a show with both gets both cards, its gone files first.
- **9a's questions** (IK-3, `Store.rename_asks()` read on the reader's worker by `asks_of`): *Is this the one from …?*
  with the missing files it may be; *This one* → `relink`, *It's new* → `its_new`.
- **an offline root as ONE entry** (E8, IK-8): *Drive E: is offline — 312 files* (`find_offline` finds the roots on a
  worker: the library folder not there, or a folder in it that links to a drive or share that isn't); it offers *Keep
  their words* and never *Remove*.
- **the failures** (`status.Snapshot.needs_you`, W3.5's: seen once looked at, still listed): *Open the logs folder* ·
  *Save logs to a file…*.
- **Connect's entries** (`read_connect`: `connect.status`'s record, newest first, plus the ledger's gaps): its own words
  and its kind's action — `not-timed` *Mine anyway* (`connect.actions.mine_anyway`), `no-pairing` *Ask hato again*
  (`connect.hato.backfill`), a failure Connect logged *Open the logs folder*; every one *Dismiss* (`status.dismiss`). A
  gap (*lost track*) offers *Make their cards* (no callable yet: hidden, `WIRED_LATER`) and *Leave them* (answered here).
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
from collections import namedtuple

from app import path_utils
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
KINDS = (BULK, GONE, NO_VIDEO, ASK, OFFLINE, FAILURE, GAP, FIRST_CARDS)
# action names the window hides until P4.1 sets their callable (RUNBOOK §2; IK-2: *Mine the text only*)
WIRED_LATER = frozenset(("mine_text_only", "make_cards"))
# Connect's kinds and their one action beside *Dismiss* (`connect_window.HOW`'s, as the Qt window offers them now)
CONNECT_ACTIONS = {"not-timed": ("mine_anyway",), "no-pairing": ("ask_hato",), "repick": ("open_logs",),
                   "mine-failed": ("open_logs",), "error": ("open_logs",)}
SEEN_VERSION = 1
_NO_VIDEO_REASON = "No video: its video isn't on this computer (or isn't downloaded yet)."   # runner.NO_VIDEO's words

STRINGS = {
    "bulk_title_files": "{n} files are gone in {m} shows",
    "bulk_title_videos": "{n} episodes in {m} shows have no video",
    "bulk_title_both": "{m} shows are missing files or videos",
    "bulk_say": "One answer for every show below, or answer each card on its own.",
    "find_all": "Find all missing videos ({n} in {m} shows)", "keep_all": "Keep all their words ({n})",
    "remove_all": "Remove all ({n})",
    "gone_title_one": "{title} · {ep}'s file is gone", "gone_title_n": "{title} · {n} {unit}' files are gone",
    "gone_say": "Its words still count until you choose: point it at its file, keep its words, or remove it to the "
                "trash (30 days).",
    "gone_line": "{label} · not at {rel}",
    "ask_title_one": "Is {name} the one from {old}?", "ask_title_n": "Is {name} one of these {n} missing files?",
    "ask_say": "It turned up at {rel} with the name, size and date of a missing file. Surasura never guesses: choose "
               "the one it is, or say it's new.",
    "ask_line": "{title} · was {rel}",
    "offline_title": "{label} is offline — {n} files", "offline_title_one": "{label} is offline — 1 file",
    "offline_say": "Its files keep their places and their words. They come back by themselves once it's connected.",
    "drive": "Drive {d}", "folder": "The folder {p}",
    "gap_title": "Connect lost track of your moves {span}: {n} {noun} in the top 20 {have} no cards",
    "gap_span": "from {a} to {b}", "gap_until": "until {b}",
    "first_title": "Make cards for your first {n} episodes?", "first_title_one": "Make cards for your first episode?",
    "first_say": "Your shows came in from your folders without cards: Surasura asks before it makes any.",
    "why_found": "→ …\\{name} ✓ found", "why_found_own": "→ …\\{name} ✓ found in its own folder ({k} more in your "
                                                         "video folders)",
    "why_found_named": "→ …\\{name} ✓ found: the one in a folder named like the show",
    "why_none": "✗ nothing with \"{n}\" in its name", "why_many": "✗ {k} videos have \"{n}\" in their names: choose one",
    "why_cloud": "✗ \"{n}\" is still in the cloud: download it first",
    "why_no_number": "✗ its name has no episode number to look for",
}


# --- small pieces ---------------------------------------------------------------------------------------------------- #
def _digest(values):
    return hashlib.sha1(",".join(str(v) for v in values).encode("utf-8")).hexdigest()[:10]


def _norm(rel):
    return (rel or "").replace("\\", "/").strip("/")


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


def item_key(item_id):
    """The answer key of one file (*Keep its words*)."""
    return f"item:{item_id}"


# --- the entries ----------------------------------------------------------------------------------------------------- #
def entries(view, failures=(), connect=None, seen=frozenset(), offline_roots=(), asks=(), answered=frozenset(),
            mine_line=20, offers=frozenset(), cards_on=False, miner_found=True):
    """The page's entries in order (see the module's doc). `view`: the reader's `View` (None: no library); `failures`:
    `status` Entries (text, at, seen); `connect`: one language's Connect record (`read_connect`; None: Connect off);
    `seen` / `answered`: `read_seen` / `read_answered`; `offline_roots`: `find_offline`'s Roots; `asks`: `asks_of`'s
    (or `Store.rename_asks()` as it is: candidates by id); `offers`: `read_offers` (D1's line); `cards_on`: Connect's
    switch (`connect_enabled`, setup's page 5) — on, D1's line asks only about these episodes (its `_on` actions);
    `miner_found`: Anki Miner is installed (`anki_miner.find`) — without it D1's line waits, kept offered (row 13: its
    cards could never be made)."""
    seen, answered = frozenset(seen or ()), frozenset(answered or ())
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
    reason = _no_video_reason()
    novideo, unplaced = {}, []
    for job in (connect or {}).get("jobs") or ():
        if job.get("reason") != reason or job.get("item") is None:
            continue
        hit = by_id.get(job["item"])
        if hit is None:
            unplaced.append(job)
            continue
        novideo.setdefault(_group(hit[0]), []).append(hit)
    shows = []
    for group in order:
        if group in gone:
            shows.append(_gone_entry(group, gone[group], seen))
        if group in novideo:
            shows.append(_video_entry(group, novideo[group], seen, mine_line))
    out = []
    if FIRST_CARDS in frozenset(offers or ()) and FIRST_CARDS not in answered and miner_found:
        out.append(_first_cards_entry(rows, seen, mine_line, cards_on))
    bulk = _bulk(shows)
    if bulk is not None:
        out.append(bulk)
    out += shows
    for ask in asks or ():
        entry = _ask_entry(ask, by_id, seen)
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
    return out


def _gone_entry(group, hits, seen):
    hits = sorted(hits, key=lambda hit: hit[1].id)   # order-free (C1, the M4.1 adversary's N1): two pieces of one work
    row = hits[0][0]                                 # swapped in Current keep the card's key, lines, title and folder
    word = view_rows.MEDIA_WORD.get(row.media, "video")
    ids = [e.id for _r, e in hits]
    if len(hits) == 1:
        title = STRINGS["gone_title_one"].format(title=row.title, ep=hits[0][1].label)
    else:
        title = STRINGS["gone_title_n"].format(title=row.title, n=len(hits), unit=_unit(row.media))
    lines = tuple(NeedLine(key=item_key(e.id), text=STRINGS["gone_line"].format(label=e.label, rel=e.rel_path),
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
                           actions=("choose_video", "mine_text_only")) for _r, e in hits)
    key = f"video:{group}:{_digest(ids)}"
    return Entry(key=key, kind=NO_VIDEO, title=title, lines=lines, actions=("find_videos", "link_these",
                                                                           "mine_text_only"),
                 unseen=key not in seen, say=say,
                 data={"work_id": row.work_id, "title": row.title, "media_word": word, "item_ids": tuple(ids),
                       "folder": _folder(hits[0][1].rel_path), "group": group})


def _folder(rel):
    rel = _norm(rel)
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


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
        lines.append(NeedLine(key=item_key(cid), text=STRINGS["ask_line"].format(title=ctitle, rel=crel or "?"),
                              item_id=cid, label=ctitle, number=None, rel_path=crel, actions=("this_one",)))
    if not lines:
        return None
    name = rel.rsplit("/", 1)[-1]
    if len(lines) == 1:
        title = STRINGS["ask_title_one"].format(name=name, old=lines[0].rel_path or lines[0].label)
    else:
        title = STRINGS["ask_title_n"].format(name=name, n=len(lines))
    key = f"ask:{_digest([rel.casefold()] + [ln.item_id for ln in lines])}"
    return Entry(key=key, kind=ASK, title=title, lines=tuple(lines), actions=("its_new",), unseen=key not in seen,
                 say=STRINGS["ask_say"].format(rel=rel), data={"rel": rel})


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


def badge(entries_):
    """The tab's number: the unseen entries (P1.2-1: a seen one stays listed and stops counting)."""
    return sum(1 for e in entries_ if e.unseen)


def answer_keys(thing):
    """What *Keep its words* / *Keep all their words* / *Leave them* records for an Entry or a NeedLine -> [key]."""
    if isinstance(thing, NeedLine):
        return [item_key(thing.item_id)]
    if thing.kind in (GONE, BULK):
        return [item_key(i) for i in (thing.data or {}).get("item_ids") or ()]
    return [thing.key]


# --- seen and answered (the local data folder; never settings.json) ------------------------------------------------- #
_lock = threading.Lock()
_FIELDS = ("seen", "answered", "offered")       # `offered`: the lines a step asked for (D1's), until answered


def seen_path(language):
    return os.path.join(path_utils.get_local_data_path(), f"needs_seen_{language}.json")


def _read(language, strict=False):
    """The seen file's two lists. `strict` (a write-back's read, W3.2 H W5): only a file that isn't there reads as
    empty — one that can't be read, isn't JSON or is another version raises, so a write never goes over earlier answers
    (a held file, a newer Surasura's)."""
    empty = {k: [] for k in _FIELDS}
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
    return {k: [x for x in data.get(k) or () if isinstance(x, str)] for k in _FIELDS}


def _write(language, data):
    path = seen_path(language)
    tmp = path + ".tmp"
    data = {k: v for k, v in data.items() if k != "offered" or v}     # no offer: the file as it always was
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": SEEN_VERSION, **data}, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _add(language, field, keys):
    keys = [k for k in dict.fromkeys(keys or ()) if isinstance(k, str)]
    if not keys:
        return 0
    with _lock:
        data = _read(language, strict=True)
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


def prune(language, view, offline_roots=None, connect=None, asks=None):
    """(S3, N10; a worker's call, after the reads `entries` is given.) The keys whose trouble is gone leave the seen
    file — never by age or by count. Judged only by what the caller read (a key of a kind it didn't read stays): a
    file's answer (`item:`) while Current holds it missing, a show's card while it is listed; with `offline_roots`, an
    offline root's while it is still offline — back, its *Keep their words* goes, so offline again later it is asked
    again; with `connect`, the video cards' and the gaps'; with `asks`, the rename asks'. A view that isn't the
    store's prunes nothing. Nothing gone → nothing written. -> how many keys went."""
    if view is None or view.mode != "store":
        return 0
    judged = {"item", "gone"} | ({"offline"} if offline_roots is not None else set()) | \
        ({"video", "gap"} if connect is not None else set()) | ({"ask"} if asks is not None else set())
    roots = [r if isinstance(r, Root) else Root(*r) for r in offline_roots or ()]
    with _lock:
        data = _read(language, strict=True)
        present = {item_key(e.id) for r in view.rows for e in r.episodes if e.missing}
        present |= {e.key for e in entries(view, connect=connect, offline_roots=roots, asks=asks or (),
                                          answered=frozenset(data["answered"]))}
        present |= {_offline_entry(r, {}, frozenset()).key for r in roots}          # answered ones too
        present |= {f"gap:{g.get('id')}" for g in (connect or {}).get("gaps") or ()}
        kept = {f: [k for k in data[f] if k.split(":", 1)[0] not in judged or k in present]
                for f in ("seen", "answered")}
        gone = sum(len(data[f]) - len(kept[f]) for f in kept)
        kept["offered"] = data["offered"]
        if gone:
            _write(language, kept)
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
        return rec
    except Exception:
        return None


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
    candidates: [{id, rel_path, title}]}]; a candidate no longer in the library is left out."""
    out = []
    for ask in store.rename_asks():
        cands = []
        for c in ask.get("candidates") or ():
            item = store.item(c)
            if item is not None:
                cands.append({"id": c, "rel_path": item.get("rel_path"), "title": item.get("title")})
        out.append({"rel": ask.get("rel"), "candidates": cands})
    return out


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
                            elif entry.name.lower().endswith(runner.VIDEO_EXTENSIONS):
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
    shown = f"{line.number:02d}"
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
