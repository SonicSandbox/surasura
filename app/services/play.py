"""The file an episode's ▶ opens (laptop fix "play", FEEDBACK row 5; review AD-2 – AD-6, IK-3, R2-2). A worker's; never writes.

Found as Connect finds the episode's video (`app/connect/runner.Runner.video`), through Connect's own rules, so ▶ and
the row's status agree: a paired episode (hato's, or a source folder's scan that found the video beside the original)
opens the video its pairing names, or — moved — the one of that name and size Connect's index holds whose bytes say it
is that video (`runner.paired_video`); any other opens a video beside its content file — or, for a file a source
folder holds, beside the original: the content file is a copy in `Library/`, the video stays where the folder was read
— by name (`runner.beside`); else one Connect's video index holds by name. A book or a text opens its original, else
the file itself.

Connect's index is read as Connect last saved it (`videos.Index.find` with no refresh): never listed or written here
(Connect owns it). Each folder is listed once (one round trip on a share), and an original's folder that can't be
listed (a share offline) is said, never waited on.

Whether ▶ is shown at all (FEEDBACK row 55, Sonic: "if it doesn't find the media, there shouldn't be a play button"):
the same lookup (`_find`, the click's), asked of many episodes at once (`look`: the pairings read through one store
open, each folder listed once a round, Connect's index read once) by `Looks`, which keeps each episode's answer, looks
on a worker of its own — never the window's thread, nor the reader's — and only when what an answer rests on changed
(S19; the window track's `work/row55/NOTES.md`).

The journey page's ▶ (Kiku-L, F3 / F19: a line's own audio, looped): `files`, the file each timed source the report
shows plays from — the same lookup, so the page and the window never disagree; an audiobook's line plays from its one
file (its record's, whatever the transcript is called), one of several files from none (the transcript's times run
across them all).
"""
import contextlib
import itertools
import json
import os
import re
import sys
import threading

AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".flac", ".wav")
WHY = {
    "not-on-disk": "it isn't on disk",
    "no-media": "no {word} beside it on disk",
    "unreachable": "its folder can't be reached just now",        # the original's folder: a share offline (AD-2)
    "unreadable": "the library can't be read just now",           # read-only, busy or damaged: its record unread (AD-6)
    "moved": "its {word} isn't where it was ({folder})",           # MV-2: it left its folder, the source still there
    "no-link": "its video's address wasn't kept",                 # an online video's: no id, no page (try a9.1)
}
SITES = {"youtube": "YouTube", "bilibili": "bilibili.tv"}      # an online item's `source_type` -> its site's name
_UNLISTED = object()                # `runner.beside`'s answer for a folder that can't be listed


class MovedAway(str):
    """`look`'s answer for an episode whose video left its folder (MV-2): falsy — ▶ has nothing to open — and its
    value the folder it was in, so the row says Connect's line and offers *Find its folder…* without Connect."""

    def __bool__(self):
        return False


class _Left(str):
    """`_find`'s why for a video that left its folder (`WHY["moved"]`), carrying the folder."""

    def __new__(cls, text, folder):
        made = super().__new__(cls, text)
        made.folder = folder
        return made
_NEVER = object()                   # `Looks`: an episode never looked at
BATCH = 200                         # `Looks`: episodes looked at a time, their answers handed on together


def pairing(language, item_id):
    """The item's pairing record (`connect.library.pairing_of`: hato's, else a source folder's origin row), {} with
    none (no record, or no store: a 2.x library), or None when the store is there but can't be read just now."""
    return _pairings(language, [item_id])[item_id]


def _pairings(language, ids, moved=None, handed=None):
    """{item_id: its record, as `pairing` says it} for every one of `ids`, read through one store open; `moved` (a
    dict): each one's `connect.library.Moved` put in it (D5 / MV-2: a source folder's root, its marked videos).
    `handed`: the caller's open library store (the journey's render, ONE-READ 3), read through and left open."""
    from app import library_store, path_utils
    from app.connect import library
    data_dir = path_utils.get_data_path(language)
    try:
        if handed is not None:
            store = handed
        else:
            # the mode is probed once (R2-5): a store that turns read-only between two probes never reads as a 2.x
            # library
            mode = library_store.check_mode(language, data_dir, busy_wait=0.0)[0]
            if mode != "store":
                return dict.fromkeys(ids, None if mode == "read-only" else {})
            store = library_store.open_store(language, data_dir, path_utils.get_user_files_path(language),
                                             role="reader")
            if store is None:
                return dict.fromkeys(ids)       # a store, not ready since the probe: can't be read just now
        with (contextlib.nullcontext() if handed is not None else store):
            records = {i: library.pairing_of(store, i) for i in ids}
            if moved is not None:
                roots = {}                          # the sources read once for all of them
                moved.update((i, library.moved_of(store, i, r, roots)) for i, r in records.items())
    except Exception as e:
        print(f"Play: the episode's pairing couldn't be read ({e!r})")
        return dict.fromkeys(ids)
    return {i: r if isinstance(r, dict) else {} for i, r in records.items()}


def _finder(language, listings=None):
    """Connect's video index, as last saved (`videos.Index.find` with no refresh: nothing listed, nothing written),
    read once, at its first lookup -> find(names, size=None). With a round's `listings`, an indexed video in a folder
    the round couldn't reach is never stat'ed again (`_on_disk`, fix round A-5)."""
    from app.connect import videos
    held = []
    there = None if listings is None else (lambda path: _on_disk(path, listings))

    def find(names, size=None):
        try:
            if not held:
                held.append(videos.Index(language))
            return held[0].find(names, size, on_disk=there)
        except Exception as e:
            print(f"Play: Connect's video index couldn't be read ({e!r})")
            return None
    return find


def _reachable(path, listings=None):
    """Whether the folder holding `path` is there (one stat; none for a folder this round listed, or failed to): an
    original's that isn't is a share offline — remembered in `listings` (False), so it is waited on once a round."""
    folder = os.path.dirname(path)
    if listings is not None and folder in listings:
        return listings[folder] is not False
    there = os.path.isdir(folder)
    if not there and listings is not None:
        listings[folder] = False
    return there


def _on_disk(path, listings, check=None):
    """`check(path)` (Connect's `runner._on_disk` unless given) — never for a file in a folder this round couldn't
    reach; a miss whose folder isn't there either is remembered (`_reachable`): a share offline is waited on once a
    round, never once an episode (fix round A-5: hato's video, a book's original, an indexed video)."""
    from app.connect import runner
    folder = os.path.dirname(path)
    if listings.get(folder) is False:
        return False
    if (check or runner._on_disk)(path):
        return True
    if folder not in listings:
        _reachable(path, listings)
    return False


PROGRAM_EXTS = (".exe", ".com")    # Windows: a program ▶ may hand a file to — never a .bat / .cmd (cmd reads its line)


def program_allowed(program, platform=None):
    """Whether `program` may be the one ▶ hands a file to: on Windows an .exe or .com only (a .bat or .cmd runs through
    cmd, which would read `&` in a file's name as a command); elsewhere any (a macOS .app, a Linux binary)."""
    platform = platform or sys.platform
    return platform != "win32" or os.path.splitext(str(program))[1].lower() in PROGRAM_EXTS


def program_for(settings, path, media=None):
    """What ▶ opens `path` with (Settings → Content, *Videos open in* / *Books open in*; Sonic 2026-11-05): the program
    chosen there (its path), or None — the program Windows opens it with. An EPUB follows *Books open in*; the file a
    video's ▶ found (`media` a video's type — `MEDIA_WORD` "video", None too — and no audio file) *Videos open in*; a
    link (YouTube, bilibili: always their site), audio, a text: None. A choice of "program" with no program kept reads
    as the default. `settings`: a dict or the window's frozen copy."""
    from app.services.view_rows import MEDIA_WORD
    if not path or "://" in path or not hasattr(settings, "get"):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        key = "open_book"
    elif MEDIA_WORD.get(media, "video") == "video" and ext not in AUDIO_EXTS:
        key = "open_video"
    else:
        return None
    program = settings.get(f"{key}_program")
    if settings.get(key) != "program" or not isinstance(program, str) or not program.strip():
        return None
    return program.strip()


def to_open(language, item_id, rel_path, media, online=None):
    """-> (path, None), or (None, why: plain words for the bar's *Couldn't open X: why*). `online` (the item's
    `source_type`, "youtube" or "bilibili"): its video's own page instead (`online_link`)."""
    if online:
        return online_link(language, rel_path, pairing(language, item_id))
    record, moved = pairing(language, item_id), {}
    if isinstance(record, dict) and record.get("producer") == "source":
        _pairings(language, [item_id], moved)       # D5 / MV-2: a source record's move, as `look` reads it
    return _find(language, rel_path, media, record, {}, _finder(language), moved.get(item_id))


def online_link(language, rel_path, record=None):
    """(A worker; never writes.) What ▶ opens for an online video (try a9.1, Sonic: "the play button for a youtube
    video should be the video … opens up in the web browser"): its own page in the browser — YouTube's
    `watch?v=<id>`, bilibili.tv's episode page — from what the downloader kept: the pairing record (`video_id`,
    `url`), else the cue sidecar beside the transcript, else the id its name ends with (YouTube's; a bilibili.tv page
    can't be built from its id). -> (link, None), or (None, why)."""
    from app import path_utils
    record = record if isinstance(record, dict) else {}
    rel = rel_path or ""
    stem = os.path.splitext(rel.rsplit("/", 1)[-1])[0]
    held = []

    def side():
        """The cue sidecar beside the transcript, read once and only when the record lacks what is wanted."""
        if not held:
            got = {}
            if rel:
                try:
                    path = os.path.join(path_utils.get_data_path(language), *rel.split("/"))
                    with open(os.path.splitext(path)[0] + path_utils.SIDECAR_SUFFIX, encoding="utf-8") as f:
                        got = json.load(f)
                except (OSError, ValueError):
                    pass
            held.append(got if isinstance(got, dict) else {})
        return held[0]
    if path_utils._BILIBILI_ID_RE.search(stem) or str(record.get("content_key") or "").startswith("bilibili:"):
        url = str(record.get("url") or side().get("url") or "").split("#", 1)[0]     # (yt-dlp's season fragment)
        return (url, None) if url.startswith(("https://", "http://")) else (None, WHY["no-link"])
    m = path_utils._YOUTUBE_ID_RE.search(stem)
    for kept in (lambda: record.get("video_id"), lambda: side().get("video_id"), lambda: m.group(1) if m else None):
        video = str(kept() or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video):                # the first true id of the three
            return f"https://www.youtube.com/watch?v={video}", None
    return None, WHY["no-link"]


_UNSURE = (WHY["unreachable"], WHY["unreadable"])     # `look`'s None: can't tell just now (a share offline, a busy store)


def look(language, asks, listings=None, find=None):
    """{item_id: (rel_path, media)} -> {item_id: True when ▶ has a file to open, False when it hasn't, None when it
    can't tell just now (its folder unreachable, its record unread: A-2)}: `_find`, ▶'s own lookup, for each — the
    pairings read through one store open, each folder listed once (`listings`: a round's, across calls), Connect's
    index read once (`find`). A video that left its folder (MV-2) is False: ▶ has nothing to open. A worker's; never
    writes."""
    moved = {}
    records = _pairings(language, list(asks), moved)
    listings = {} if listings is None else listings
    find = find or _finder(language, listings)
    out = {}
    for item_id, (rel_path, media) in asks.items():
        try:
            path, why = _find(language, rel_path, media, records.get(item_id), listings, find, moved.get(item_id))
            out[item_id] = True if path is not None else None if why in _UNSURE else \
                MovedAway(why.folder) if isinstance(why, _Left) else False
        except Exception as e:                      # one episode's fault never stops the others
            print(f"Play: an episode's file couldn't be looked for ({e!r})")
            out[item_id] = False
    return out


PLAYABLE = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wav", ".mp4", ".m4v", ".webm")
# ^ the files a browser's <audio> plays from the journey's file:// page (Chromium: Edge, Chrome) — the journey's ▶
#   (Kiku-L). Not .mkv / .avi / .wmv / .ts / .flv, nor .mov (its codecs vary).


def files(language, rel_paths, memo=None, explain=False, cut_kinds=(), library=None):
    """{rel path: the file its lines play from, or None} for the journey page's ▶ (Kiku-L): the report's render asks
    once for every timed source it shows — at a cost the render barely feels where nothing can play (most anime
    libraries) and only while something changed where it can.

    **What the store knows, in one open** (`_rows`): each source's item, its title's type and every pairing row it has,
    and the library's sources. **The gate:** each folder a source's file could be in (`_places`: the copy's, the
    original's, a named or moved video's, an audiobook's) is listed once — the listings `_find` reuses — and only a
    source with a `PLAYABLE` file in one of them goes on; a source with no pairing row also when Connect's index holds a
    playable file (`_index_playable`: a video only the index knows). A book or a text never goes on (its ▶ opens the
    book). **The lookup**, for those alone and only when the memo can't answer: the record `pairing_of` picks
    (`_pairings`) and `_find`, the window's ▶'s own lookup — except an audiobook's (its record's `files`: one plays,
    several don't). The render's worker; never writes; one source's fault is its None alone.

    `memo` (the render's, kept between renders: {rel: [answer, key, its folder's digest, ...the caller's own]}): an
    answer stands while `_memo_key` (its title's type, its pairing rows, the sources, the listings of its folders,
    Connect's index file) and the listing of the answer's own folder are what they were; else it is looked for again
    and written as a new entry of three.

    `explain` (the badge is shown: its hover says why a line has no ▶): a source the gate keeps out answers the media
    file named as it is in one of its folders' listings (`_named_beside`: an `.mkv` the browser can't play), else
    None — a hint from the listings already made, never a lookup.

    `cut_kinds` (the journey's render, J-CLIP: the one cutter's videos, `runner.VIDEO_EXTENSIONS`): files of these
    kinds pass the gate too — the journey's ▶ cuts a line the browser can't play (`clips`); the old page asks none.

    `library`: the render's open library store (ONE-READ 3: one open a render), read through and left open by `_rows`
    and `_pairings`; False: the render's open found none (no store read, never a second open); None: each opens its
    own."""
    from app import path_utils
    from app.services.view_rows import MEDIA_WORD
    rel_paths = list(dict.fromkeys(rel_paths))
    out = dict.fromkeys(rel_paths)
    known, sources = _rows(language, rel_paths, library=library)
    data_dir = path_utils.get_data_path(language)
    listings, playable, digests, stamps, copies = {}, {}, {}, {}, {}
    kinds = PLAYABLE + tuple(cut_kinds)
    gated = {}
    for rel in rel_paths:
        item_id, media, texts, rows = known.get(rel, _UNKNOWN)
        if MEDIA_WORD.get(media, "video") in ("video", "audio"):
            gated[rel] = _places(data_dir, rel, rows, copies)
    _list_all({p for places in gated.values() for p in places}, listings)
    asks = {}
    for rel, places in gated.items():
        if any(_holds_playable(p, listings, playable, kinds) for p in places) or \
                (not known.get(rel, _UNKNOWN)[3] and _index_playable(language, stamps, kinds)):
            asks[rel] = places
        elif explain:
            out[rel] = _named_beside(rel, places, listings)
    misses = {}
    for rel, places in asks.items():
        item_id, media, texts, _records = known.get(rel, _UNKNOWN)
        key = _memo_key(language, media, texts, sources, places, listings, digests, stamps)
        kept = memo.get(rel) if memo is not None else None
        if isinstance(kept, list) and len(kept) >= 3 and kept[1] == key and \
                (kept[0] is None or (isinstance(kept[0], str) and
                                     _digest(_folder_of(kept[0]), listings, digests) == kept[2])):
            out[rel] = kept[0]
        else:
            misses[rel] = key
    if not misses:
        return out
    ids = sorted({known[r][0] for r in misses if r in known})
    moved = {}
    records = _pairings(language, ids, moved, handed=library) if ids else {}
    find = _finder(language, listings)
    for rel, key in misses.items():
        item_id, media = known.get(rel, _UNKNOWN)[:2]
        record = records.get(item_id) if item_id is not None else {}
        try:
            book = (record or {}).get("audiobook")
            if isinstance(book, dict):
                parts = book.get("files") or []
                out[rel] = parts[0] if len(parts) == 1 and _on_disk(parts[0], listings) else None
            else:
                out[rel] = _find(language, rel, media, record, listings, find, moved.get(item_id))[0]
            if memo is not None and record is not None:    # (a record that couldn't be read is never kept)
                memo[rel] = [out[rel], key, _digest(_folder_of(out[rel]), listings, digests) if out[rel] else None]
        except Exception as e:                      # one source's fault never stops the others
            print(f"Play: a line's file couldn't be looked for ({e!r})")
    return out


_UNKNOWN = (None, None, (), ())         # `_rows`' answer for a source the store doesn't hold (or no store)


def _rows(language, rel_paths, library=None):
    """({rel path: (item id, its title's type, its pairing rows as stored, each row's (origin, video_path, audiobook
    files as JSON) as SQLite reads them)}, the library's sources as one string) through one store open, 500 at a time; ({}, "") with no store or one that can't be read now (each
    source then looked at as a 2.x library's file). No record is picked here (`pairing_of` picks, for the few the
    gate and the memo send on). `library`: the caller's open library store (the journey's render: its one open,
    ONE-READ 3), read through and left open; False: the caller's open found none (({}, ""), never a second open);
    None: opened here."""
    from app import library_store, path_utils
    data_dir = path_utils.get_data_path(language)
    if library is False:
        return {}, ""
    try:
        if library is not None:
            store = library
        else:
            if library_store.check_mode(language, data_dir, busy_wait=0.0)[0] != "store":
                return {}, ""
            store = library_store.open_store(language, data_dir, path_utils.get_user_files_path(language),
                                             role="reader")
            if store is None:
                return {}, ""
        with (contextlib.nullcontext() if library is not None else store):
            ids = {rel: i for rel, i in zip(rel_paths, store.item_ids(rel_paths)) if i is not None}
            wanted = sorted(set(ids.values()))
            works, texts, fields = {}, {}, {}
            pick = "CASE WHEN json_valid(pairing) THEN json_extract(pairing, '$.{}') END"
            for at in range(0, len(wanted), 500):
                chunk = wanted[at:at + 500]
                marks = ",".join("?" * len(chunk))
                works.update(store.conn.execute(f"SELECT id, work_id FROM items WHERE id IN ({marks})", chunk))
                # the gate's fields read by SQLite (no record parsed here); the rows as stored for the memo's key
                for item_id, text, origin, video, files in store.conn.execute(
                        f"SELECT item_id, pairing, {pick.format('origin')}, {pick.format('video_path')}, "
                        f"{pick.format('audiobook.files')} FROM pairings WHERE item_id IN ({marks}) ORDER BY rowid",
                        chunk):
                    texts.setdefault(item_id, []).append(text if isinstance(text, str) else "")
                    fields.setdefault(item_id, []).append((origin, video, files))
            types = {w: (store.media_type(w)[0] if w is not None else None) for w in set(works.values())}
            sources = json.dumps(sorted((s.get("id"), s.get("path")) for s in store.sources(all=True, counts=False)),
                                 default=str)
        known = {rel: (item_id, types.get(works.get(item_id)), texts.get(item_id, []), fields.get(item_id, []))
                 for rel, item_id in ids.items()}
        return known, sources
    except Exception as e:
        print(f"Play: the lines' records couldn't be read ({e!r})")
        return {}, ""


def _places(data_dir, rel, rows, copies):
    """Every folder a source's file could be found in by `_find` (a superset): its copy's (`copies`: once a folder),
    and each pairing row's original's, named video's (moved ones too) and audiobook files' (`_rows`' fields)."""
    folder = rel.rpartition("/")[0]
    if folder not in copies:
        copies[folder] = os.path.join(data_dir, *folder.split("/")) if folder else data_dir
    places = [copies[folder]]
    for origin, video, files in rows:
        for value in (origin, video):
            if isinstance(value, str):
                if "#" in value:
                    value = re.sub(r"#\d+$", "", value)
                where = _folder_of(value)
                if where:
                    places.append(where)
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except ValueError:
                files = None
            if isinstance(files, list):
                places += [w for w in map(_folder_of, (f for f in files if isinstance(f, str))) if w]
    return list(dict.fromkeys(places))


def _folder_of(path):
    """An absolute path's folder ("" for a relative one) — `os.path.dirname` by string work for the paths the store
    keeps (`C:\\…\\name`, `\\\\server\\share\\…\\name`): a 20k-source render calls it twice a source."""
    i = max(path.rfind("\\"), path.rfind("/"))
    if i > 2 and (path[1:3] == ":\\" or path[1:3] == ":/") and path[0].isalpha():
        return path[:i]
    return os.path.dirname(path) if os.path.isabs(path) else ""


def _list_all(folders, listings):
    """Each folder not listed yet, listed once (`_listing`'s form) — side by side when there are many: a listing waits
    on the disk (a share most of all), not on Python."""
    todo = [f for f in folders if f not in listings]
    if len(todo) < 16:
        for f in todo:
            _listing(f, listings)
        return
    from concurrent.futures import ThreadPoolExecutor

    def one(folder):
        try:
            return folder, {n.lower(): n for n in os.listdir(folder or ".")}
        except OSError:
            return folder, False
    with ThreadPoolExecutor(max_workers=8) as pool:
        listings.update(pool.map(one, todo))


def _listing(folder, listings):
    """A folder's one listing in `runner.beside`'s own form ({lower name: name}; False when it can't be listed), kept in
    `listings` — the same dict `_find` is handed, so it is never listed twice."""
    names = listings.get(folder)
    if names is None:
        try:
            names = {n.lower(): n for n in os.listdir(folder or ".")}
        except OSError:
            names = False
        listings[folder] = names
    return names


def _holds_playable(folder, listings, playable, kinds=PLAYABLE):
    """Whether a folder holds a file of `kinds` (`PLAYABLE`; its listing; the answer kept in `playable`)."""
    if folder not in playable:
        names = _listing(folder, listings)
        playable[folder] = bool(names) and any(n.endswith(kinds) for n in names)
    return playable[folder]


def _digest(folder, listings, digests):
    """A folder's listing as a short digest — it moves when a file in it is added, removed or renamed."""
    if folder not in digests:
        import hashlib
        names = _listing(folder, listings)
        text = "\0".join(sorted(names)) if names else ("" if names == {} else "\1unlistable")
        digests[folder] = hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=8).hexdigest()
    return digests[folder]


def _named_beside(rel, places, listings):
    """A video or audio file named as the subtitle is (`Show - 05.ja.srt` → `Show - 05.mkv`: its name without its last
    one or two extensions) in one of `places`' listings (already made by the gate) -> its path, else None."""
    from app.connect import runner
    name = rel.rsplit("/", 1)[-1].lower()
    stems = [name.rsplit(".", n)[0] for n in (1, 2) if name.count(".") >= n]
    for folder in places:
        names = listings.get(folder)
        if names:
            for stem in stems:
                for ext in runner.VIDEO_EXTENSIONS + AUDIO_EXTS:
                    found = names.get(stem + ext)
                    if found:
                        return os.path.join(folder, found)
    return None


def _index_playable(language, stamps, kinds=PLAYABLE):
    """Whether Connect's video index (as last saved) holds any file of `kinds` (`PLAYABLE`) — once a call."""
    if "index_playable" not in stamps:
        try:
            from app.connect import videos
            dirs = videos.Index(language).data.get("dirs") or {}
            stamps["index_playable"] = any(str(name).lower().endswith(kinds) for entry in dirs.values()
                                           if isinstance(entry, dict) for name in (entry.get("videos") or {}))
        except Exception:
            stamps["index_playable"] = True             # unknown: look, as before the gate
    return stamps["index_playable"]


def _memo_key(language, media, texts, sources, places, listings, digests, stamps):
    """What `files`' answer rests on, as one short digest: its title's type, its pairing rows as stored (the record
    `pairing_of` picks and the MV-2 marks are read from them), the library's sources (a moved video's root), the
    listings of the folders it could be found in (`_places`) and Connect's index file (a video only it knows)."""
    import hashlib
    if "index" not in stamps:
        try:
            from app.connect import videos
            stamps["index"] = str(os.stat(videos.index_path(language)).st_mtime_ns)
        except OSError:
            stamps["index"] = ""
    raw = "\x1f".join([str(media), sources, stamps["index"], *sorted(texts),
                       *(_digest(p, listings, digests) for p in places)])
    return hashlib.blake2b(raw.encode("utf-8", "surrogatepass"), digest_size=12).hexdigest()


def _find(language, rel_path, media, record, listings, find, moved=None):
    """The one lookup, ▶'s click and whether ▶ shows: `record` the item's pairing (None: unread), `listings` the
    folders listed this round ({folder: names}, False for one that couldn't be), `find` Connect's index (`_finder`),
    `moved` its `connect.library.Moved` (D5 / MV-2; None: nothing known) — Connect's own two rules on it, a marked
    origin's video still on disk (`runner.moved_video`) and a video that left its folder (`runner.video_left`)."""
    from app import path_utils
    from app.connect import library, runner, videos
    from app.services.view_rows import MEDIA_WORD
    rel = rel_path or ""
    path = os.path.join(path_utils.get_data_path(language), *rel.split("/")) if rel else None   # AD-5
    unread = record is None
    record = record or {}
    origin = runner.origin_of(record)
    origin = origin if origin and os.path.isabs(origin) else None
    word = MEDIA_WORD.get(media, "video")
    if word in ("EPUB", "file"):
        book = origin and re.sub(r"#\d+$", "", origin)              # an EPUB's part (`<book>.epub#3`): the book
        if book and _on_disk(book, listings, os.path.exists):
            return book, None
        if book and not _reachable(book, listings):
            return None, WHY["unreachable"]                         # never the copy in its place, unsaid (R2-6)
        if path and os.path.exists(path):
            return path, None
        return None, WHY["unreadable" if unread else "not-on-disk"]
    moved = moved or library.NOT_MOVED
    named = record.get("video_path")
    there = lambda p: _on_disk(p, listings)                         # noqa: E731
    if isinstance(named, str) and os.path.isabs(named):             # AD-4: a relative one is no pairing here
        found = runner.paired_video(record, find, on_disk=there, was=moved.was)
        if found:
            return found, None
        left = runner.video_left(record, moved.root, lambda root: _reachable(os.path.join(root, ""), listings))
        if left:
            return None, _Left(WHY["moved"].format(word=word, folder=left), left)
        return None, WHY["no-media"].format(word=word) if _reachable(named, listings) else WHY["unreachable"]
    exts = AUDIO_EXTS if word == "audio" else None
    unreachable = False
    for p in (path, origin):
        if not p:
            continue
        # beside the copy, then beside the original: Connect's own two looks (`beside`, `beside_origin`), one rule each
        found = runner.beside(p, exts, _UNLISTED, listings) if p is path else \
            runner.beside_origin(record, exts, _UNLISTED, listings)
        if found is _UNLISTED:
            unreachable = unreachable or p is origin    # the copy's folder not there: nothing beside it
        elif found:
            return found, None
    if word == "video":
        found = (runner.moved_video(moved.was, there) if record.get("producer") == "source" else None) or \
            find([n for p in (path, origin) if p for n in videos.names_for(p)])
        if found:
            return found, None
    if unreachable:
        return None, WHY["unreachable"]
    return None, WHY["unreadable"] if unread else WHY["no-media"].format(word=word)


# --- row 55: whether ▶ shows, each episode's answer kept ----------------------------------------------------------- #
class Looks:
    """Whether each episode's ▶ has a file to open, kept and looked at again only when it may have changed (S19).

    - `want(asks)` (the reader's thread, after a build: the asks of the rows it built anew — {item_id: (rel_path,
      media)}, or None where ▶ can't be anyway): an ask unlike the one last answered is looked at; None forgets it.
      `forget(ids)`: episodes that left Current (fix round A-8: never looked at again).
    - `again(folders)`: the episodes in those library folders and every folder under them (the watch's sync:
      '/'-separated, any case — A-4); `again()`: every one not found (a full sync, a source folder's look that found
      a video). `recheck(ids)`: those episodes (a ▶ press that found nothing: A-7). `index_moved()`: every one not
      found, once Connect's index file changed on disk (asked when Connect's feed moves; each round checks it too:
      A-3). All three walk on the looks' worker, after any round running (IK-6, A-1).
    - The looks run on a worker of their own (`look`), `BATCH` at a time in the order asked (the first screen's rows
      first); each batch that moved an answer hands them all on (`on_change({item_id: found})`, the reader's
      `set_playable`). An answer stays until its new one lands: ▶ never goes and comes back. A round's listings are
      made afresh when a new ask came meanwhile (A-1); an episode it can't tell for just now (a share offline, a busy
      store: `look`'s None) is never kept as looked at — tried once more that round, then at its next ask (A-2), its
      last answer kept meanwhile (none yet: not found). `close()` ends a round at its next batch (A-6).
    - `seed(found)`: answers known before any look (the first screen's cache), kept until a look answers."""

    def __init__(self, language, on_change=None, worker=None):
        from app.services.automation import Worker
        self.language = language
        self.on_change = on_change
        self._worker = worker or Worker(f"play-looks-{language}")
        self._lock = threading.Lock()
        self._asks = {}                     # item_id -> its newest ask
        self._looked = {}                   # item_id -> the ask its answer was looked for
        self._found = {}                    # item_id -> found
        self._owed = {}                     # item_id -> None: to look at, in the order asked
        self._flight = {}                   # item_id -> the ask being looked at now (A-12)
        self._stale = False                 # an ask owed since the round's listings were made (A-1)
        self._busy = False
        self._closed = False
        self._index = _NEVER                # Connect's index file (size, time) as the last round found it
        self.looked = 0                     # episodes looked at (tests)

    def answers(self):
        with self._lock:
            return dict(self._found)

    def seed(self, found):
        with self._lock:
            for item_id, f in found.items():
                self._found.setdefault(item_id, bool(f))

    def want(self, asks):
        with self._lock:
            for item_id, ask in asks.items():
                self._asks[item_id] = ask
                if ask is None:
                    self._looked.pop(item_id, None)     # back from missing (or online): looked at afresh
                    self._owed.pop(item_id, None)
                elif self._looked.get(item_id, _NEVER) != ask and self._flight.get(item_id, _NEVER) != ask:
                    self._owed[item_id] = None
                    self._stale = True
        self._kick()

    def forget(self, ids):
        with self._lock:
            for item_id in ids:
                for kept in (self._asks, self._looked, self._found, self._owed):
                    kept.pop(item_id, None)

    def again(self, folders=None):
        wanted = None if folders is None else {f.lower().rstrip("/") for f in folders}
        self._worker.put(self._again, wanted)

    def recheck(self, ids):
        self._worker.put(self._recheck, list(ids))

    def index_moved(self):
        self._worker.put(self._check_index)

    def close(self):
        with self._lock:
            self._closed = True
        self._worker.close()

    def idle(self, timeout=None):
        """Everything asked looked at (a test's)."""
        return self._worker.idle(timeout)

    def _again(self, wanted):
        """(The worker.) `again`'s walk."""
        with self._lock:
            for item_id, ask in self._asks.items():
                if ask is None:
                    continue
                if wanted is None:
                    hit = not self._found.get(item_id)
                else:
                    folder = (ask[0] or "").rsplit("/", 1)[0].lower()
                    hit = any(folder == f or folder.startswith(f + "/") for f in wanted)
                if hit:
                    self._looked.pop(item_id, None)
                    self._owed[item_id] = None
        self._kick()

    def _recheck(self, ids):
        """(The worker.) `recheck`'s episodes owed again."""
        with self._lock:
            for item_id in ids:
                if self._asks.get(item_id) is not None:
                    self._looked.pop(item_id, None)
                    self._owed[item_id] = None
        self._kick()

    def _index_now(self):
        from app.connect import videos
        try:
            st = os.stat(videos.index_path(self.language))
        except OSError:
            return None
        return st.st_size, st.st_mtime_ns

    def _check_index(self):
        """(The worker.) Connect's index file changed since the last round read it: the ones not found, again."""
        now = self._index_now()
        if self._index is not _NEVER and now != self._index:
            self._index = now
            self._again(None)

    def _kick(self):
        with self._lock:
            if self._busy or self._closed or not self._owed:
                return
            self._busy = True
        if not self._worker.put(self._round):
            with self._lock:
                self._busy = False

    def _round(self):
        """(The worker.) Every owed episode looked at; a fault never leaves it thought running (IK-9)."""
        try:
            self._look_owed()
        except BaseException:
            with self._lock:
                self._busy = False
                self._flight = {}
            raise

    def _look_owed(self):
        """`BATCH` at a time: one listing a folder, one index read — both made afresh when an ask came meanwhile."""
        self._check_index()                 # A-3: an index saved since the last round is noticed here too
        self._index = self._index_now()
        listings, find, retried = None, None, set()
        while True:
            with self._lock:
                if self._closed:
                    self._busy = False
                    return
                if listings is None or self._stale:
                    listings, self._stale = {}, False
                    find = _finder(self.language, listings)
                ids = list(itertools.islice(self._owed, BATCH))
                if not ids:
                    self._busy = False
                    return
                for item_id in ids:
                    del self._owed[item_id]
                batch = {i: self._asks[i] for i in ids if self._asks.get(i) is not None}
                self._flight = dict(batch)
            found = look(self.language, batch, listings, find) if batch else {}
            with self._lock:
                self._flight = {}
                if self._closed:
                    self._busy = False
                    return
                self.looked += len(found)
                moved = False
                for item_id, f in found.items():
                    if item_id not in self._asks:
                        continue                    # forgotten meanwhile (A-8)
                    if f is None:                   # can't tell just now: tried once more this round, never kept
                        if item_id not in retried:
                            retried.add(item_id)
                            self._owed[item_id] = None
                        if item_id in self._found:
                            continue                # its last answer stays
                        f = False
                    elif self._asks[item_id] == batch[item_id]:
                        self._looked[item_id] = batch[item_id]      # A-12: never for an ask gone meanwhile
                    if self._found.get(item_id) is not f:
                        self._found[item_id] = f
                        moved = True
                out = dict(self._found) if moved else None
            if out is not None and self.on_change is not None and not self._closed:
                try:
                    self.on_change(out)
                except Exception as e:
                    print(f"Play: the answers couldn't be handed on ({e!r})")
