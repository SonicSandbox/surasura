# SPDX-License-Identifier: GPL-3.0-or-later
"""The shows behind the backlog (A, Michi-C 2026-10-29; Sonic: "yes to shows behind the backlog. Genius";
`tracks/pipeline/work/backlog-shows/scope.md`, leans A7B-1…A7B-5, PROVISIONAL).

Someone who comes to Surasura with a big Anki Miner backlog has a library already: the shows those cards came from.
Each new card of 順's deck names its show in `MiscInfo` (Anki Miner's source, `source_names` — the one rule the footer
and *Study its cards first* use too). This module reads those sources, finds the shows among the files the library's
looks found under the user's own folders, and makes ONE offer: *Your 2,300 new cards come from 14 shows: add the 3 on
this PC that aren't in your list?* — setup's *Card order* page and *Needs you* show it; **Add them** is the window's
writer placing those New arrivals (`Writer.place(ids, "soon")`, New arrivals' own ⋯ *Soon*: one Undo).

- **A show** (rule 2): the title (the store's work) of the file a card's source names; a source that names no file: the
  folder of a 3.5-form source (`source_names.series_of`), else the show its name says (`library_store.show_of_name`).
- **On this PC** (rule 3): a card's source names a file the looks already found, in any tier — only the folders the
  user chose; nothing else on the disk is ever looked at. A key two titles share names neither.
- **Offered** (rule 4, A7B-1): the show's files waiting in New arrivals with their text (a video still waiting for its
  subtitle can't be counted, so it isn't offered); a show in Current / Soon / 6+ Months is counted already, a Finished
  one stays Finished (Sonic's rule).
- **Reads only** (rule 6, A7B-5): Anki through `findNotes` (the deck's new note ids) and `notesInfo` only for notes not
  read before — the sources kept per note in `<local data>/backlog_shows_<lang>.json` (Surasura's own, never user data)
  with the last offer; no Anki write, the store opened as a reader.

No Qt, no Tk; `refresh` runs on a worker (the window's automation after a sync, the wizard's page).
"""
import hashlib
import json
import os
import threading
from collections import namedtuple

from modules.junban import source_names

COUNTED = ("now", "soon", "goal")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".webm", ".mov", ".m4v", ".ts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg")
FILE = "backlog_shows_{language}.json"

Item = namedtuple("Item", "id tier work title names text")
Show = namedtuple("Show", "title cards ids state")         # state: waiting · in · finished · away
_LOCK = threading.Lock()


def path(language):
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), FILE.format(language=language))


def _load(language):
    try:
        with open(path(language), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(language, data):
    target = path(language)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, target)


def deck_of(settings, language):
    """順's deck for `language` (setup's *Card order* deck), or None."""
    from app.services import setup_wizard
    return setup_wizard.junban_deck(settings or {}, language)


def read_deck(url, deck, known=None):
    """`{note id: MiscInfo}` for `deck`'s new cards (its subdecks too, as 順 gathers them): `findNotes` for the ids,
    `notesInfo` only for ids not in `known` (the last read's). Read-only; Anki's errors are the caller's."""
    from app import anki_connect
    from modules.junban.ankiconnect import new_card_query
    ids = anki_connect.find_notes(url, new_card_query(deck))
    known = {int(k): v for k, v in (known or {}).items() if str(k).lstrip("-").isdigit()}
    out = {i: known[i] for i in ids if i in known}
    fresh = [i for i in ids if i not in known]
    for note in anki_connect.notes_info(url, fresh) if fresh else ():
        field = (note.get("fields") or {}).get("MiscInfo")
        out[int(note.get("noteId"))] = str(field.get("value") or "") if isinstance(field, dict) else ""
    for i in fresh:
        out.setdefault(i, "")                       # a note gone between the two asks: no source
    return out


def library(language, bare=True):
    """Every item of the library as `Item(id, tier, work, title, names, text)` — `names` the keys Anki Miner's source
    can carry for it (its file, its original under the user's folder, its paired video; the old bare name, an
    audiobook's files and a fetched video's title in Anki Miner's fixed series only with `bare`); `text` False for a
    video still waiting for its subtitle — or None without a store (JSON mode, a 2.x library)."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    store = library_store.open_store(language, get_data_path(language), get_user_files_path(language), role="reader")
    if store is None:
        return None
    with store:
        rows = store.conn.execute("SELECT i.id, i.tier, i.rel_path, i.work_id, w.title FROM items i "
                                  "LEFT JOIN works w ON w.id = i.work_id").fetchall()
        from app.connect import library as connect_library
        records = connect_library.pairings(store)
    items = []
    for item_id, tier, rel, work, title in rows:
        paths, names = [rel], set()
        for record in records.get(item_id) or ():
            if isinstance(record, dict):
                paths += [record.get("origin"), record.get("video_path")]
                names |= source_names.names_of_record(record, bare=bare)    # `Audio — …`, `YouTube — …` (Junban-X3)
        for one in dict.fromkeys(p for p in paths if p):
            names |= source_names.names_of(one, bare=bare)
        text = os.path.splitext(str(rel or ""))[1].lower() not in VIDEO_EXTENSIONS
        items.append(Item(item_id, tier, work, title or library_store.show_of_name(os.path.basename(rel or "")) or "",
                          frozenset(names), text))
    return items


def library_version(language):
    """The store's state version (every command moves it), or None without a store: an offer worked out at another
    version is worked out again — the looks may have taken the backlog's shows in since."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    try:
        store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                         role="reader")
        if store is None:
            return None
        with store:
            return store.meta().get("state_version")
    except Exception:
        return None


def counted_names(language, bare=True):
    """Every key of the files the list counts (Current, Soon, 6+ Months) — their originals and paired videos too — or
    None without a store (the footer's `reposition._banner`: a hato copy's own name never was the video's)."""
    items = library(language, bare=bare)
    if items is None:
        return None
    return {name for item in items if item.tier in COUNTED for name in item.names}


def look(notes, items):
    """The offer for `notes` (`{note id: MiscInfo}`) against `items` (`library`'s) -> `{"cards", "all", "shows":
    [Show…]}` (most cards first), or None when no card names a source. `all`: the deck's new cards, sourced or not.
    A card of Anki Miner's fixed series (`Audio`, `YouTube`) is no show's: counted in `all` only. A card that names no
    file (its episode deleted since) whose folder one title alone owns is that title's (never a second, "away" show)."""
    tally, sample = {}, {}
    for misc in notes.values():
        k = source_names.card_key(misc)
        if k and not source_names.fixed_series(misc):
            tally[k] = tally.get(k, 0) + 1
            sample.setdefault(k, misc)
    if not tally:
        return None
    items = list(items or ())
    by_id = {i.id: i for i in items}
    shared = source_names.shared_names({i.id: i.names for i in items}, lambda item_id: by_id[item_id].work)
    by_name = {}
    for item in items:
        for name in item.names - shared:
            by_name.setdefault(name, []).append(item)
    of_work, folders = {}, {}
    for item in items:
        if item.work is not None:
            of_work.setdefault(item.work, []).append(item)
        for name in item.names:
            if "/" in name:
                folders.setdefault(name.split("/", 1)[0], set()).add(item.work if item.work is not None else
                                                                     ("item", item.id))
    shows = {}
    for k, n in tally.items():
        hits = by_name.get(k) or ()
        owners = folders.get(k.split("/", 1)[0]) if not hits and "/" in k else None
        if owners and len(owners) == 1:
            owner = next(iter(owners))
            hits = of_work.get(owner) if not isinstance(owner, tuple) else [by_id[owner[1]]]
        if hits:
            first = hits[0]
            title = _show_title(first.title)
            group = ("name", source_names.plain(title)) if title else ("item", first.id)
            members = [i for hit in hits for i in (of_work.get(hit.work) if hit.work is not None else (hit,))]
        else:
            misc = sample[k]
            text = source_names.source_text(misc) or ""
            title = source_names.series_of(misc) or _show_of(text) or text
            group, members = ("name", source_names.plain(title) or k), ()
        show = shows.setdefault(group, {"title": title, "cards": 0, "members": {}})
        show["cards"] += n
        for item in members or ():
            show["members"][item.id] = item
    out = []
    for show in shows.values():
        members = list(show["members"].values())
        ids = tuple(sorted(i.id for i in members if i.tier == "arrivals" and i.text))
        if not members:
            state = "away"
        elif ids:
            state = "waiting"
        elif any(i.tier in COUNTED for i in members):
            state = "in"
        elif any(i.tier == "graduated" for i in members):
            state = "finished"
        else:
            state = "in"                            # only a video waiting for its subtitle: nothing to add yet
        out.append(Show(show["title"], show["cards"], ids, state))
    out.sort(key=lambda s: (-s.cards, s.title))
    return {"cards": sum(tally.values()), "all": len(notes), "shows": out}


def _show_title(title):
    """A title as one show, as Anki Miner cleans a folder's name (`[SubsPlease] Show (1080p)` is `Show`): the store
    names a show's season folders `Show/Season 1`, `Show/2` — one show here."""
    head = str(title or "").split("/", 1)[0].strip()
    return source_names.clean(head) if head else ""


def _show_of(name):
    from app import library_store
    try:
        return library_store.show_of_name(name)
    except Exception:
        return None


def offer_record(result):
    """`look`'s result as the record kept on disk (JSON) — None when there is nothing to say."""
    if not result:
        return None
    shows = [s._asdict() for s in result["shows"]]
    for s in shows:
        s["ids"] = list(s["ids"])
    ids = sorted(i for s in result["shows"] for i in s.ids)
    return {"cards": result["cards"], "all": result["all"], "shows": shows,
            "id": hashlib.sha1(json.dumps(ids).encode()).hexdigest()[:12] if ids else "", "deck": result.get("deck")}


def refresh(language, settings, url=None, force=False, deck=None):
    """(A worker.) Read 順's deck's new cards' sources again (only the notes not read before) and write the offer ->
    the offer record, or None (順 off, no deck, Anki not reachable, no sourced card). `deck`: the one setup's *Card
    order* page shows (not saved yet), else the settings'. `force`: work the offer out again from the library even when
    the deck's notes are the same (the page; a look may have taken files in). Never raises."""
    try:
        from app import anki_connect
        deck = None if (settings or {}).get("enable_junban") is False else (deck or deck_of(settings, language))
        if not deck:
            with _LOCK:                             # 順 off, no deck: an offer kept from before says nothing more
                kept = _load(language)
                if "offer" in kept:                 # (worked out again, never served from here, when it's back)
                    _save(language, {k: v for k, v in kept.items() if k not in ("offer", "version")})
            return None
        url = url or anki_connect.address(settings)
        with _LOCK:
            kept = _load(language)
            known = kept.get("notes") if kept.get("deck") == deck else None
            notes = read_deck(url, deck, known)
            version = library_version(language)
            same = known is not None and set(map(str, notes)) == set(map(str, known))
            if same and not force and "offer" in kept and kept.get("version") == version:
                return kept.get("offer")
            bare = any(source_names.only_counted(source_names.card_key(m)) for m in notes.values())
            items = library(language, bare=bare)
            result = look(notes, items or ())
            record = offer_record(dict(result, deck=deck) if result else None)
            _save(language, {"deck": deck, "version": version, "notes": {str(k): v for k, v in notes.items()},
                             "offer": record})
            return record
    except Exception as e:
        print(f"Backlog shows: skipped ({e})")
        return None


def offer(language, deck=None):
    """The last offer worked out for `language` (read-only), or None — None too when `deck` is given and the offer was
    worked out for another (setup's page looked at a deck that was never saved)."""
    with _LOCK:                                     # (never while `refresh` replaces the file: Windows refuses that)
        record = _load(language).get("offer")
    if not isinstance(record, dict) or (deck is not None and record.get("deck") != deck):
        return None
    return record


def waiting_ids(record, arrivals=None):
    """The item ids *Add them* places: every waiting show's, kept to `arrivals` (the ids New arrivals holds now) when
    given — a show placed by hand since is no longer offered."""
    ids = [i for s in (record or {}).get("shows") or () if s.get("state") == "waiting" for i in s.get("ids") or ()]
    if arrivals is not None:
        arrivals = set(arrivals)
        ids = [i for i in ids if i in arrivals]
    return ids
