"""Sources (3.0, SRC K1b): a look at a folder Surasura reads where it is — headless, called on a worker.

A source (`Store.add_source`) is where Surasura *finds* text and videos; its own copy of every text lives in the data
folder, `Library/<show>/<file>` (SRC-4). One look (`scan`):

- **Lists** the folder with `os.scandir` (names and stats from the listing: nothing opened), skipping what no show
  lives in (`library_store.skip_dir`: dot folders, recycle bins, folder links — never followed) and cloud placeholders
  (`library_store.is_placeholder`: never read, a video's key neither, B3). **Only what changed is listed again** (S4):
  each folder's time is kept beside Connect's video index (`cache_path`), stamped with the store's `store_id` and
  `epoch` and written only after the look's take-ins committed; a folder whose time didn't move is not listed. The
  first look at a folder each run, setup's first scan and Refresh (`full=True`) list everything and compare the known
  files' stats.
- **Never a duplicate** (SRC-7, S7): one subtitle per episode per language (`.ja.ass`, then `.ja.srt`, then untagged;
  another language's tag skipped); then, cheapest first, (a) a video beside it already paired → that item, (b) an item
  holding the same bytes → that item, a `v2` of an episode already in → that item, its copy followed (S5), else (c) a
  copy (`.part`, then renamed; a file changed in the last SETTLE_S seconds, or while copied, waits for the next look).
  A removed item's path, bytes or video stay out (S6).
- **Hands each show's files to `Store.take_in`**, at most BATCH at a time (an EPUB's parts all in one: S11).
- **A changed original** (a full look): copied again over Surasura's copy — only a copy in `Library`, never from an
  empty file, one under half the copy's size or one that changed while read; the old copy *copied* into the data
  folder's `.trash` first (its clock restarted), then the new one put in its place at once (`os.replace`, S5).
- **An unreachable folder** (SRC-3): `{"reachable": False}`, nothing written or marked.

`due` is the cadence the shell asks (SRC-9); `local_or_network` tells it which folders a watch can follow (D5).
Nothing is ever written under a source folder. Standard library only.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import unicodedata

from app import library_store as ls
from app.path_utils import restart_trash_clock, write_source_marker

log = logging.getLogger("surasura-cli")

SETTLE_S = 5                    # a file (or the video beside it) modified this recently may still be being written
PROGRESS_S = 0.2                # `progress` at most this often
BATCH = 200                     # files per `take_in`, per show
FOCUS_S = 5 * 60                # a look on the window's focus: at most this often
HOURLY_S = 60 * 60              # else, while a window is in front
CACHE_VERSION = 1
EPUB = ".epub"

# A subtitle's language tag (`Show - 05.ja.srt`): ours is taken, another language's skipped (S7)
_TAGS = {"ja": frozenset({"ja", "jp", "jpn", "japanese", "ja-jp"}),
         "zh": frozenset({"zh", "zho", "chi", "chs", "cht", "sc", "tc", "gb", "big5", "chinese", "zh-cn", "zh-tw",
                          "zh-hk", "zh-sg", "zh-hans", "zh-hant"})}
_OTHER_TAGS = frozenset({"en", "eng", "english", "en-us", "en-gb", "ko", "kor", "korean", "ko-kr", "es", "spa",
                         "es-419", "fr", "fre", "fra", "de", "ger", "deu", "pt", "por", "pt-br", "ru", "rus", "it",
                         "ita", "ar", "ara", "vi", "vie", "th", "tha", "id", "ind", "ms", "msa", "may", "pl", "pol",
                         "tr", "tur", "nl", "dut", "nld", "sv", "swe", "hi", "hin", "uk", "ukr"})
_RANK = {".ass": 0, ".ssa": 0, ".srt": 1}           # of one episode's subtitles in one language: the first taken
# A folder that is only a season or the specials (S12): the source folder's name goes in front
_SEASON = re.compile(r"(?:season|series|s)\s*\d{1,2}|\d{1,2}(?:st|nd|rd|th)\s+season|specials?|sps?|extras?|"
                     r"ova|oad|第\s*\d{1,2}\s*[期季部]", re.I)

_GUARD = threading.Lock()
_RUNNING = set()                # stores a look is running on (their path keys): never two at once
_LOOKED = set()                 # (store, source) looked at in full this run: later looks list only what changed


def cache_path(language):
    """The folder-time cache, beside Connect's video index (`videos.index_path`'s folder)."""
    from app.connect import ledger
    return os.path.join(ledger.folder(), f"sources_{language}.json")


def due(now, focused, refreshed, last, shown=True):
    """Is a look due (SRC-9)? Pure: the shell asks on Refresh (`refreshed`), when its window comes to the front
    (`focused`) and on its hourly tick (neither); `last` = when the last look started (None: none yet this run);
    `shown` = False while the window is behind another or minimized. Refresh → now; the window's focus → at most once
    per FOCUS_S; else hourly; never while it is behind or minimized. A clock gone back counts as due."""
    if refreshed:
        return True
    if not shown:
        return False
    if last is None or now < last:
        return True
    return now - last >= (FOCUS_S if focused else HOURLY_S)


def local_or_network(path):
    """'local' (a watch follows it: S10 / D5) or 'network' (the cadence looks at it): a UNC path, a mapped share, a
    CD or a drive Windows can't name is 'network'. Elsewhere than Windows: 'local'."""
    if sys.platform != "win32":
        return "local"
    full = os.path.abspath(path)
    if full.startswith("\\\\"):
        return "network"
    drive = os.path.splitdrive(full)[0]
    if not drive:
        return "network"
    try:
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
    except (AttributeError, OSError):
        return "network"
    return "local" if kind in (2, 3, 6) else "network"   # REMOVABLE · FIXED · RAMDISK


def scan(store, language, root, first=False, progress=None, stop=None, full=False, rules=None):
    """One look at the source `root` (its id) -> {reachable, found, shows, added, attached, skipped, waiting,
    recopied, stopped, busy, ids}. `first`: setup's own first scan (SRC-1: Current, quiet); `full`: Refresh (S4);
    `progress(found, shows)` every PROGRESS_S; `stop()` is asked between files (a stopped look keeps what it took in,
    whole); `rules`: the placing rules `take_in` applies to an arrival. A source not being read raises NotASource.
    Another look at the same store running → {"busy": True}, nothing done."""
    key = _store_key(store)
    with _GUARD:
        if key in _RUNNING:
            return _result(busy=True)
        _RUNNING.add(key)
    try:
        return _Look(store, language, root, first, progress, stop, full, rules).run()
    finally:
        with _GUARD:
            _RUNNING.discard(key)


def _store_key(store):
    return ls.path_key(os.path.abspath(store.db_path))


def _result(**values):
    out = {"reachable": True, "found": 0, "shows": 0, "added": 0, "attached": 0, "skipped": 0, "waiting": 0,
           "recopied": 0, "stopped": False, "busy": False, "ids": []}
    out.update(values)
    return out


def _key(path):
    """An origin's key in `origins()` / `excluded()`: the path key of its absolute path."""
    return ls.origin_key(path)[len(ls.SOURCE_KEY):]


def _tag(name):
    """(the name's stem without a language tag, the tag's language: 'ja', 'zh', 'other' or None)."""
    stem = os.path.splitext(name)[0]
    base, tag = os.path.splitext(stem)
    tag = tag[1:].casefold()
    if base:
        for language, tags in _TAGS.items():
            if tag in tags:
                return base, language
        if tag in _OTHER_TAGS:
            return base, "other"
    return stem, None


def _episode_of(name):
    """(the episode number K4's patterns read in a file name, or None; its version: 2 for `- 05v2`, else 1)."""
    text = unicodedata.normalize("NFKC", name)
    text = ls._NAME_EXT.sub("", text)
    while ls._NAME_LANG.search(text):
        text = ls._NAME_LANG.sub("", text)
    text = ls._NAME_TAGS.sub(" ", text).replace("_", " ")
    if " " not in text.strip() and text.count(".") >= 2:
        text = text.replace(".", " ")
    m = ls._NAME_SEASON_EP.search(text)
    if m:
        number = re.search(r"E(\d{1,4})", m.group(0), re.I).group(1)
        rest = text[m.end():]
    else:
        m = ls._NAME_EPISODE.search(text)
        if not m:
            return None, 1
        number = re.search(r"\d{1,4}(?:\.\d)?", m.group(0)).group(0)
        rest = m.group(0)[m.group(0).index(number) + len(number):] + text[m.end():]
    version = re.match(r"\s?v(\d+)", rest, re.I)
    value = float(number)
    return (int(value) if value.is_integer() else value), (int(version.group(1)) if version else 1)


def _show_of(root, parts, name):
    """`Library/<show>`'s show (§1, S12): the folder below the source as written (`Frieren/Season 1`); a season or
    specials folder alone gets the source folder's name in front; a loose file's show is K4's reading of its name,
    else the source folder's name."""
    from app.extract import clean_name
    root_name = clean_name(os.path.basename(os.path.normpath(root))) or "Source"
    if parts:
        if _SEASON.fullmatch(unicodedata.normalize("NFKC", parts[0]).strip()):
            parts = [root_name] + list(parts)
        return "/".join(parts)
    return clean_name(ls.show_of_name(name) or "") or root_name


def _copy_part(origin, part):
    """The original's bytes into `part` (ours: a `.part` in the data folder) -> their sha256."""
    h = hashlib.sha256()
    with open(origin, "rb") as src, open(part, "wb") as dst:
        for block in iter(lambda: src.read(1 << 20), b""):
            h.update(block)
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    return h.hexdigest()


def _drop(part):
    """Our own unfinished `.part` (never anything else): removed."""
    try:
        os.remove(part)
    except OSError:
        pass


def _load_cache(language, stamp):
    """The folder times, dropped whole when another store (or a rebuilt one: a new epoch) wrote them."""
    try:
        with open(cache_path(language), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION and isinstance(data.get("roots"), dict) \
                and (data.get("store_id"), data.get("epoch")) == stamp:
            return data
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "store_id": stamp[0], "epoch": stamp[1], "roots": {}}


def _save_cache(language, data):
    """Written whole (a temp file, then replaced); a cache that can't be written only means a fuller look next time."""
    path = cache_path(language)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        log.warning("The source folders' times couldn't be saved (%s); they're listed again next look", path)


def _listing(folder):
    """(texts, epubs, videos {name lower: (path, stat)}, subfolders, placeholders) of one folder, from the listing
    alone; None when it can't be listed (gone, offline)."""
    from app.connect import runner
    texts, epubs, vids, subs, ghosts = [], [], {}, [], 0
    try:
        with os.scandir(folder) as found:
            for entry in found:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not ls.skip_dir(entry.name, entry):
                            subs.append(entry.path)
                        continue
                    if entry.is_symlink():
                        continue
                    low = entry.name.lower()
                    kind = "text" if ls.is_content_name(low) else "epub" if low.endswith(EPUB) else \
                        "video" if low.endswith(runner.VIDEO_EXTENSIONS) else None
                    if kind is None:
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if kind == "video":
                    vids[low] = (entry.path, st)             # a placeholder too: it is beside, its key never read
                elif ls.is_placeholder(st):
                    ghosts += 1
                else:
                    (texts if kind == "text" else epubs).append((entry.name, entry.path, st))
    except OSError:
        return None
    return sorted(texts), sorted(epubs), vids, sorted(subs), ghosts


class _Look:
    def __init__(self, store, language, root, first, progress, stop, full, rules):
        self.store, self.language, self.root_id = store, language, root
        self.first, self.progress, self.stop, self.rules = first, progress, stop, rules
        self.full = bool(full or first)
        self.data_dir = store.data_dir
        self.out = _result()
        self.shows = set()
        self.unsettled = set()       # folders (path keys) a file in which waits: listed again next look
        self.this_look = set()       # the bytes taken this look (the same bytes twice wait for the next look)
        self.said = 0.0
        self.video_items = None
        self.hashes = {}

    # --- the look ------------------------------------------------------------------------------------------------- #

    def run(self):
        path = next((s["path"] for s in self.store.sources() if s["id"] == self.root_id), None)
        if path is None:
            raise ls.NotASource("That folder isn't being read any more.")
        meta = self.store.meta()
        stamp = (meta.get("store_id"), meta.get("epoch"))
        looked = (_store_key(self.store), self.root_id)
        cache = _load_cache(self.language, stamp)
        held = cache["roots"].get(str(self.root_id)) or {}
        dirs = held.get("dirs") if held.get("path") == ls.path_key(path) and isinstance(held.get("dirs"), dict) else {}
        self.full = self.full or looked not in _LOOKED or not dirs
        self.origins = self.store.origins()
        excluded = self.store.excluded()
        self.ex_paths = set(excluded)
        self.ex_shas = {n["sha256"] for n in excluded.values() if n.get("sha256")}
        self.ex_videos = {n["video_key"] for n in excluded.values() if n.get("video_key")}
        walked = self._walk(path, dirs)
        if walked is None:
            return _result(reachable=False)
        seen, new, known, books = walked
        if not self.stopped():
            if self.full:
                for item in known:
                    if self.stopped():
                        break
                    try:
                        self._changed(*item)
                    except OSError:                          # gone or locked meanwhile: the next look
                        self._wait(item[0])
            self.sizes = self.store.items_of_size([c[2].st_size for c in new])
            self._take(new)
            for book in books:
                if self.stopped():
                    break
                self._book(*book)
        self._say(final=True)
        self.out["shows"] = len(self.shows)
        if self.out["stopped"]:
            return self.out
        for k in self.unsettled:
            if k in seen:
                seen[k]["mtime_ns"] = None
        meta = self.store.meta()
        cache = _load_cache(self.language, (meta.get("store_id"), meta.get("epoch")))
        cache["roots"][str(self.root_id)] = {"path": ls.path_key(path), "dirs": seen}
        _save_cache(self.language, cache)
        _LOOKED.add(looked)
        return self.out

    def stopped(self):
        if not self.out["stopped"] and self.stop is not None and self.stop():
            self.out["stopped"] = True
        return self.out["stopped"]

    def _say(self, final=False):
        now = time.monotonic()
        if self.progress is not None and (final or now - self.said >= PROGRESS_S):
            self.said = now
            self.progress(self.out["found"], len(self.shows))

    def _wait(self, folder):
        self.out["waiting"] += 1
        self.unsettled.add(ls.path_key(folder))

    def _recent(self, st):
        """Modified in the last SETTLE_S seconds (or as far ahead: a share whose clock runs ahead never blocks a file
        for good — the copy's own check still catches one being written)."""
        return abs(time.time() - st.st_mtime_ns / 1e9) < SETTLE_S

    # --- listing (S4) ---------------------------------------------------------------------------------------------- #

    def _walk(self, root, dirs):
        """-> (the folders seen {key: {path, mtime_ns, subs}}, new files, known files, EPUBs) or None (unreachable).
        A folder whose time didn't move (not a full look) is not listed: its subfolders come from the cache."""
        seen, new, known, books = {}, [], [], []
        stack = [root]
        while stack:
            if self.stopped():
                break
            folder = stack.pop()
            fkey = ls.path_key(folder)
            try:
                mtime = os.stat(folder).st_mtime_ns
            except OSError:
                if folder == root:
                    return None
                continue
            held = dirs.get(fkey)
            if not self.full and held and held.get("mtime_ns") == mtime:
                seen[fkey] = held
                stack.extend(reversed(held.get("subs") or []))
                continue
            listed = _listing(folder)
            if listed is None:
                if folder == root:
                    return None
                continue
            texts, epubs, vids, subs, ghosts = listed
            seen[fkey] = {"path": folder, "mtime_ns": mtime, "subs": subs}
            stack.extend(reversed(subs))
            self.out["skipped"] += ghosts
            rel = os.path.relpath(folder, root)
            parts = [] if rel == "." else rel.replace("\\", "/").split("/")
            for name, path, st, show, kind in self._episodes(root, parts, texts, epubs):
                self.out["found"] += 1
                self.shows.add(ls.search_fold(show, self.language))
                if kind == "known":
                    known.append((folder, path, st))
                elif kind == "book":
                    books.append((folder, name, path, st, show))
                else:
                    new.append((folder, path, st, name, show, vids))
            self._say()
        return seen, new, known, books

    def _episodes(self, root, parts, texts, epubs):
        """One folder's files as a look takes them (S7): another language's subtitles skipped; one per episode
        (`ep01.ja.ass`, then `ep01.ja.srt`, then `ep01.srt`) — an episode already in keeps its own and the rest are
        skipped -> [(name, path, stat, show, 'new' | 'known' | 'book')]."""
        out, groups = [], {}
        for t in texts:
            base, language = _tag(t[0])
            if language not in (None, self.language):
                self.out["skipped"] += 1
                continue
            groups.setdefault(base.casefold(), []).append((language, t))
        for members in groups.values():
            mine = [t for _l, t in members if _key(t[1]) in self.origins]
            if mine:
                self.out["skipped"] += len(members) - len(mine)
                out.extend((n, p, st, _show_of(root, parts, n), "known") for n, p, st in mine)
                continue
            members.sort(key=lambda m: (m[0] != self.language, _RANK.get(os.path.splitext(m[1][0])[1].lower(), 2),
                                        m[1][0]))
            self.out["skipped"] += len(members) - 1
            n, p, st = members[0][1]
            out.append((n, p, st, _show_of(root, parts, n), "new"))
        prefixes = None
        for n, p, st in epubs:
            if prefixes is None:
                prefixes = {k.rsplit("#", 1)[0] for k in list(self.origins) + list(self.ex_paths) if "#" in k}
            if _key(p) in prefixes:                          # a known EPUB is never split again
                continue
            out.append((n, p, st, _show_of(root, parts, n), "book"))
        return out

    # --- new files (SRC-7) ----------------------------------------------------------------------------------------- #

    def _take(self, new):
        """Each show's new files, checked and copied, handed to `take_in` BATCH at a time; a stop ends the look after
        the files already copied are taken in."""
        by_show = {}
        for c in new:
            by_show.setdefault(c[4], []).append(c)
        for show in sorted(by_show, key=lambda s: (ls.search_fold(s, self.language), s)):
            batch = []
            for c in by_show[show]:
                if self.stopped():
                    break
                try:
                    f = self._new(*c)
                except OSError:                              # gone or locked meanwhile: the next look
                    self._wait(c[0])
                    f = None
                if f is not None:
                    batch.append(f)
                if len(batch) >= BATCH:
                    self._commit(batch)
                    batch = []
            self._commit(batch)
            if self.out["stopped"]:
                return

    def _commit(self, found):
        if not found:
            return
        try:
            change = self.store.take_in(self.root_id, found, first=self.first, rules=self.rules)
        except ls.NotASource:
            self.out["stopped"] = True                       # stopped reading meanwhile: the copies wait, re-used
            return
        if change is None:
            return
        self.out["added"] += len(change.added)
        self.out["ids"].extend(change.added)
        self.out["attached"] += len(change.attached)
        self.out["skipped"] += sum(len(v) for v in change.skipped.values())

    def _new(self, folder, path, st, name, show, vids):
        """One new text file -> its `found` entry for `take_in` (an `item_id` for an episode already in, else the
        copy's `rel`), or None (skipped, or waiting for the next look)."""
        from app.connect import videos
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        if self._recent(st):
            self._wait(folder)
            return None
        video, vkey = None, None
        for candidate in videos.names_for(name):
            video = vids.get(candidate.lower())
            if video:
                break
        if video and not ls.is_placeholder(video[1]):
            if self._recent(video[1]):
                self._wait(folder)
                return None
            vkey = videos.content_key(video[0])
            if vkey is None:                                 # changed while read
                self._wait(folder)
                return None
            if vkey in self.ex_videos:
                self.out["skipped"] += 1
                return None
        sha = ls.sha256_of(path)
        if not self._same(path, st):
            self._wait(folder)
            return None
        if sha in self.ex_shas:
            self.out["skipped"] += 1
            return None
        if sha in self.this_look:                            # the same bytes twice: the next look attaches it
            self._wait(folder)
            return None
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
             "show": show}
        episode, version = _episode_of(name)
        if episode is not None:
            f["episode"] = episode
        if video:
            f["video_path"], f["video_size"] = os.path.abspath(video[0]), video[1].st_size
            if vkey:
                f["video_key"] = vkey
        item = (self._video_item(vkey) if vkey else None) or self._same_bytes(st.st_size, sha)
        if item is None and version > 1 and episode is not None:
            earlier = self._earlier(folder, name, episode, version)
            if earlier is not None:
                outcome, _sha = self._recopy(earlier.rel_path, earlier.sha256, path, st)
                if outcome == "wait":
                    self._wait(folder)
                    return None
                self.out["recopied"] += outcome == "done"
                item = earlier.item_id
        if item is not None:
            f["item_id"] = item
        else:
            rel = self._copy(path, st, show, name, sha)
            if rel is None:
                self._wait(folder)
                return None
            f["rel"] = rel
        self.this_look.add(sha)
        return f

    def _same(self, path, st):
        """The original as listed still (its size and time): else it is being written."""
        try:
            now = os.stat(path)
        except OSError:
            return False
        return (now.st_size, now.st_mtime_ns) == (st.st_size, st.st_mtime_ns)

    def _video_item(self, vkey):
        """(a) The live item whose record holds this video (hato's key, or an origin's `video_key`) — never a waiting
        one (K5: its gap is filled by `take_in` from the copy) — or None. One read per look."""
        if self.video_items is None:
            self.video_items = {}
            with self.store._reading():
                rows = self.store.conn.execute(
                    "SELECT p.content_key, json_extract(p.pairing, '$.video_key'), p.item_id FROM pairings p "
                    "JOIN items i ON i.id = p.item_id WHERE i.availability != 'waiting' ORDER BY p.item_id").fetchall()
            for content_key, video_key, item_id in rows:
                for k in (content_key, video_key):
                    if isinstance(k, str) and not k.startswith(ls.SOURCE_KEY):
                        self.video_items.setdefault(k, item_id)
        return self.video_items.get(vkey)

    def _same_bytes(self, size, sha):
        """(b) An item of this size whose file holds these bytes, or None."""
        for item_id, rel in self.sizes.get(size, ()):
            if rel not in self.hashes:
                try:
                    self.hashes[rel] = ls.sha256_of(os.path.join(self.data_dir, *rel.split("/")))
                except OSError:
                    self.hashes[rel] = None
            if self.hashes[rel] == sha:
                return item_id
        return None

    def _earlier(self, folder, name, episode, version):
        """S7: the episode already in that this `v2` is — an origin in the same folder, of the same show (K4's
        reading of both names) and episode number, at an earlier version — or None."""
        show = ls.search_fold(ls.show_of_name(name) or "", self.language)
        fkey = ls.path_key(os.path.abspath(folder))
        for o in self.origins.values():
            if not o.origin or ls.path_key(os.path.dirname(os.path.abspath(o.origin))) != fkey:
                continue
            theirs = os.path.basename(o.origin)
            if ls.search_fold(ls.show_of_name(theirs) or "", self.language) != show:
                continue
            number, v = _episode_of(theirs)
            if number == episode and v < version:
                return o
        return None

    # --- writing into Library -------------------------------------------------------------------------------------- #

    def _inside(self, rel):
        """The full path of `rel` when it is inside the data folder's `Library` (through any folder link too: a
        `Library` that leads elsewhere is never written), else None."""
        if not rel:
            return None
        parts = rel.split("/")
        if len(parts) < 2 or ls.path_key(parts[0]) != ls.path_key(ls.CONTENT_FOLDER) or ".." in parts:
            return None
        full = os.path.join(self.data_dir, *parts)
        home = ls.path_key(os.path.realpath(self.data_dir)).rstrip("/")
        lib = ls.path_key(os.path.realpath(os.path.join(self.data_dir, ls.CONTENT_FOLDER))).rstrip("/")
        real = ls.path_key(os.path.realpath(full))
        if not lib.startswith(home + "/") or not real.startswith(lib + "/"):
            return None
        return full

    def _checked_copy(self, path, st, part):
        """The original into `part`, as listed: its sha256, or None (it changed while copied: `part` removed)."""
        try:
            digest = _copy_part(path, part)
        except OSError:
            _drop(part)
            return None
        if not self._same(path, st):
            _drop(part)
            return None
        return digest

    def _copy(self, path, st, show, name, sha):
        """(c) The original copied into `Library/<show>/` (`.part`, then renamed; never over another file: a free
        `name (2)` or, after a crash, the same bytes already there re-used) -> the copy's rel, or None."""
        rel, reuse = ls.content_target(self.data_dir, f"{ls.CONTENT_FOLDER}/{show}/{name}", st.st_size, sha)
        if reuse:
            return rel
        full = self._inside(rel)
        if full is None:
            return None
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
        except OSError:
            return None
        part = full + ".part"
        if self._checked_copy(path, st, part) != sha:
            _drop(part)
            return None
        try:
            ls._rename_no_overwrite(part, full)
        except OSError:
            _drop(part)
            return None
        return rel

    def _trash_copy(self, full):
        """The old copy *copied* into the data folder's `.trash` (purged 30 days on: its clock restarted)."""
        trash = os.path.join(self.data_dir, ".trash")
        os.makedirs(trash, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(full))
        stamp = time.strftime("%Y%m%d%H%M%S")
        name, n = f"{base}_{stamp}{ext}", 1
        while os.path.exists(os.path.join(trash, name)):
            name, n = f"{base}_{stamp}_{n}{ext}", n + 1
        dst = os.path.join(trash, name)
        shutil.copy2(full, dst)
        restart_trash_clock(dst)

    def _recopy(self, rel, old_sha, path, st):
        """S5: the original's new text over Surasura's copy at `rel` -> ('done' | 'same' | 'refused' | 'wait', sha).
        Refused: a copy outside `Library` (a hato / 2.x file is never rewritten), none there, an empty original or
        one under half the copy's size. Wait: it changed while read, or the trash couldn't take the old copy."""
        full = self._inside(rel)
        if full is None:
            return "refused", None
        try:
            held = os.stat(full).st_size
        except OSError:
            return "refused", None
        if st.st_size == 0 or st.st_size * 2 < held:
            return "refused", None
        part = full + ".part"
        sha = self._checked_copy(path, st, part)
        if sha is None:
            return "wait", None
        if sha == old_sha:
            _drop(part)
            return "same", sha
        try:
            self._trash_copy(full)
            os.replace(part, full)
        except OSError:                                      # the copy held open: it stays as it was
            _drop(part)
            return "wait", None
        return "done", sha

    def _changed(self, folder, path, st):
        """A known original (a full look): when its size or time moved, its text followed (S5) and its record's
        stats rewritten; a refused one is left as it is (looked at again next full look, by its stats alone)."""
        o = self.origins.get(_key(path))
        if o is None or (st.st_size, st.st_mtime_ns) == (o.size, o.mtime_ns):
            return
        if self._recent(st):
            self._wait(folder)
            return
        outcome, sha = self._recopy(o.rel_path, o.sha256, path, st)
        if outcome == "wait":
            self._wait(folder)
        elif outcome in ("done", "same"):
            self.store.update_origin(o.origin or path, st.st_size, st.st_mtime_ns, sha)
            self.out["recopied"] += outcome == "done"

    # --- an EPUB (S11) --------------------------------------------------------------------------------------------- #

    def _book(self, folder, name, path, st, show):
        """An EPUB split by Extract's reader and default split into a free `Library/<book>` folder (each part via a
        `.part`), each part's origin `<epub>#<n>`, all taken in at once — or none (a part that can't be written: the
        parts already written to the trash, the book waits)."""
        from app import extract
        if self._recent(st):
            self._wait(folder)
            return
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return
        chunks, error = extract.chunks_of(path, self.language)
        if error or not chunks:                              # no text in it: nothing to read
            self.out["skipped"] += 1
            return
        if not self._same(path, st):
            self._wait(folder)
            return
        base = extract.clean_name(os.path.splitext(name)[0]) or "Book"
        data = [c.encode("utf-8") for c in chunks]
        names = [f"{base}_{i:02d}.txt" if len(data) > 1 else f"{base}.txt" for i in range(1, len(data) + 1)]
        shas = [hashlib.sha256(d).hexdigest() for d in data]
        book, n = base, 1
        while True:                                          # a free folder, or one a crash left with these parts
            rels = [f"{ls.CONTENT_FOLDER}/{book}/{x}" for x in names]
            if not os.path.exists(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book)) or all(
                    ls.content_target(self.data_dir, r, len(d), s) == (r, True) for r, d, s in zip(rels, data, shas)):
                break
            n += 1
            book = f"{base} ({n})"
        written, parts = [], []
        try:
            for rel, d in zip(rels, data):
                full = self._inside(rel)
                if full is None:
                    raise OSError(f"outside the content folder: {rel}")
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if os.path.isfile(full):
                    continue                                 # the same bytes, left by a crash
                with open(full + ".part", "wb") as f:
                    parts.append(full + ".part")
                    f.write(d)
                    f.flush()
                    os.fsync(f.fileno())
            for p in parts:
                ls._rename_no_overwrite(p, p[:-len(".part")])
                written.append(p[:-len(".part")])
        except OSError:
            for p in parts:
                _drop(p)
            for w in written:
                ls.trash_file(self.data_dir, ls.library_rel(self.data_dir, w))
            self._wait(folder)
            return
        write_source_marker(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book), "epub", origin=name)
        origin = os.path.abspath(path)
        found = [{"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": s,
                  "show": book, "rel": r, "episode": i} for i, (r, s) in enumerate(zip(rels, shas), 1)]
        self._commit(found)
