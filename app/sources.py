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
  an `.sdh` / `.hi` / `.cc` one after the plain one, a `.forced` one and another language's tag skipped), one per video
  in a look, the latest release of an episode (`- 05v2` over `- 05`); then, cheapest first, (a) a video beside it
  already paired → that item, (b) an item holding the same bytes → that item, a `v2` of an episode already in → that
  item, its copy followed (S5), else (c) a copy (`.part`, then renamed; a file changed in the last SETTLE_S seconds, or
  while copied, waits for the next look). A removed item's path, bytes, video, or its episode's re-release stay out
  (S6).
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

# A subtitle's language tag (`Show - 05.ja.srt`, `.pt-BR`): ours is taken, another language's skipped (S7). ISO 639-1
# and 639-2 (B and T), a few names; `sc` / `tc` are Chinese here, never Sardinian; a tag not listed is no tag.
_ISO_639_1 = ("aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de "
              "dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he ho hr ht hu hy hz ia id ie "
              "ig ii ik in io is it iu iw jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu "
              "lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu "
              "rm rn ro ru rw sa sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts "
              "tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zu")
_ISO_639_2 = ("aar abk ave afr aka amh arg ara asm ava aym aze bak bel bul bih bis bam ben tib bod bre bos cat che "
              "cha cos cre cze ces chu chv wel cym dan ger deu div dzo ewe gre ell eng epo spa est baq eus per fas "
              "ful fin fij fao fre fra fry gle gla glg grn guj glv hau heb hin hmo hrv hat hun arm hye her ina ind "
              "ile ibo iii ipk ido ice isl ita iku jav geo kat kon kik kua kaz kal khm kan kor kau kas kur kom cor "
              "kir lat ltz lug lim lin lao lit lub lav mlg mah mao mri mac mkd mal mon mar may msa mlt bur mya nau "
              "nob nde nep ndo dut nld nno nor nbl nav nya oci oji orm ori oss pan pli pol pus por que roh run rum "
              "ron rus kin san srd snd sme sag sin slo slk slv smo sna som alb sqi srp ssw sot sun swe swa tam tel "
              "tgk tha tir tuk tgl tsn ton tur tso tat twi tah uig ukr urd uzb ven vie vol wln wol xho yid yor zha "
              "zul fil scc scr")
_LANGS = dict.fromkeys((_ISO_639_1 + " " + _ISO_639_2 + " english korean spanish french german portuguese russian "
                        "italian arabic vietnamese thai indonesian").split(), "other")
_LANGS.update(dict.fromkeys("ja jp jpn jap japanese".split(), "ja"))
_LANGS.update(dict.fromkeys("zh zho chi chs cht sc tc gb big5 chinese cmn yue".split(), "zh"))
_FLAGS = frozenset({"forced", "sdh", "hi", "cc"})   # a track's flags (Plex, Jellyfin, Bazarr), never a language
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
    """(the name's stem without its tags, the tag's language: 'ja', 'zh', 'other' or None, its flags), read from the
    right: `ep01.ja.forced.srt` → ('ep01', 'ja', {'forced'}); a flag either side of the language (`.hi` is Bazarr's
    hearing-impaired, never Hindi); a tag no list holds stays part of the stem (untagged)."""
    stem, language, flags = os.path.splitext(name)[0], None, set()
    while True:
        base, tag = os.path.splitext(stem)
        tag = tag[1:].casefold()
        if not base or not tag:
            break
        if tag in _FLAGS:
            flags.add(tag)
        elif language is None and (_LANGS.get(tag) or _LANGS.get(re.split(r"[-_]", tag)[0])):
            language = _LANGS.get(tag) or _LANGS[re.split(r"[-_]", tag)[0]]
        else:
            break
        stem = base
    return stem, language, flags


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
    """Our own unfinished `.part`, or the trash copy of a copy never replaced (never anything else): removed."""
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
                        # a folder the cloud hasn't brought down: listing it could download it (B3)
                        if not (ls.skip_dir(entry.name, entry) or ls.is_placeholder(entry.stat(follow_symlinks=False))):
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
        self.this_videos = set()     # the videos a subtitle was taken for this look (S7: one per video per language)
        self.made = set()            # the copies this look wrote (rels): trashed when take_in can't take them (N3)
        self.said = 0.0
        self.by_folder = None        # {folder key: {(show, episode): (version, Origin)}}: the releases already in
        self.books_in = None         # {an EPUB's sha256: {part: (item_id, rel)}}: the books already in
        self.shown = None            # the folder keys of the shows with an item that isn't waiting
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
        mine = held.get("path") == ls.path_key(path)
        dirs = held.get("dirs") if mine and isinstance(held.get("dirs"), dict) else {}
        self.full = self.full or looked not in _LOOKED or not dirs
        # EPUBs that gave no text, by their stats (K5): never parsed again until they change; a full look keeps only
        # the ones it saw
        self.no_text = (held.get("books") if mine and isinstance(held.get("books"), dict) else None) or {}
        self.no_text_kept = {} if self.full else dict(self.no_text)
        # A folder's show is read below the outermost source holding it, so overlapping sources never split it (K6)
        self.base = path
        for s in self.store.sources(all=True):
            k = ls.path_key(os.path.abspath(s["path"])).rstrip("/")
            if len(k) < len(ls.path_key(os.path.abspath(self.base)).rstrip("/")) and \
                    ls.path_key(os.path.abspath(path)).startswith(k + "/"):
                self.base = s["path"]
        self.origins = self.store.origins()
        excluded = self.store.excluded()
        self.ex_paths = set(excluded)
        self.ex_shas = {n["sha256"] for n in excluded.values() if n.get("sha256")}
        self.ex_videos = {n["video_key"] for n in excluded.values() if n.get("video_key")}
        self.ex_episodes = {(ls.search_fold(n["show"], self.language), n["episode"],
                             self._name_show(os.path.basename(p)))
                            for p, n in excluded.items() if n.get("show") and n.get("episode") is not None}
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
            self.sizes = self.store.items_of_size([c[2].st_size for c in new if len(c) == 6])
            self._take(new, books)
        self._say(final=True)
        self.out["shows"] = len(self.shows)
        if self.out["stopped"]:
            return self.out
        for k in self.unsettled:
            if k in seen:
                seen[k]["mtime_ns"] = None
        meta = self.store.meta()
        cache = _load_cache(self.language, (meta.get("store_id"), meta.get("epoch")))
        cache["roots"][str(self.root_id)] = {"path": ls.path_key(path), "dirs": seen, "books": self.no_text_kept}
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
        stack, visited = [root], set()
        while stack:
            if self.stopped():
                break
            folder = stack.pop()
            fkey = ls.path_key(folder)
            try:
                st = os.stat(folder)
            except OSError:
                if folder == root:
                    return None
                continue
            mtime = st.st_mtime_ns
            if st.st_ino:                                    # a loop no link shows (a share following links): once
                if (st.st_dev, st.st_ino) in visited:
                    continue
                visited.add((st.st_dev, st.st_ino))
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
            # a folder time in the last seconds may yet take a file in the same tick (FAT32, a coarse share): not kept
            seen[fkey] = {"path": folder, "mtime_ns": None if self._recent(st) else mtime, "subs": subs}
            stack.extend(reversed(subs))
            self.out["skipped"] += ghosts
            rel = os.path.relpath(folder, self.base)
            parts = [] if rel == "." else rel.replace("\\", "/").split("/")
            episodes = self._episodes(self.base, parts, texts, epubs)
            for name, path, st, show, kind in episodes:
                self.out["found"] += 1
                self.shows.add(ls.search_fold(show, self.language))
                if kind == "known":
                    known.append((folder, path, st))
                elif kind == "book":
                    books.append((folder, name, path, st, show))
                else:
                    new.append((folder, path, st, name, show, vids))
            if vids and not episodes and not epubs:          # videos and none of our text yet: they wait (K5)
                for path, st in sorted(vids.values()):
                    show = _show_of(self.base, parts, os.path.basename(path))
                    self.out["found"] += 1
                    self.shows.add(ls.search_fold(show, self.language))
                    new.append((folder, path, st, show))
            self._say()
        return seen, new, known, books

    def _episodes(self, root, parts, texts, epubs):
        """One folder's files as a look takes them (S7): another language's subtitles skipped; one per episode
        (`ep01.ja.ass`, then `ep01.ja.srt`, then `ep01.srt`) — an episode already in keeps its own and the rest are
        skipped -> [(name, path, stat, show, 'new' | 'known' | 'book')]."""
        out, groups = [], {}
        for t in texts:
            base, language, flags = _tag(t[0])
            if language not in (None, self.language) or "forced" in flags:   # a forced track holds only the signs
                self.out["skipped"] += 1
                continue
            groups.setdefault(base.casefold(), []).append((language, bool(flags), t))
        for members in groups.values():
            mine = [t for _l, _f, t in members if _key(t[1]) in self.origins]
            if mine:
                self.out["skipped"] += len(members) - len(mine)
                out.extend((n, p, st, _show_of(root, parts, n), "known") for n, p, st in mine)
                continue
            members.sort(key=lambda m: (m[0] != self.language, m[1],
                                        _RANK.get(os.path.splitext(m[2][0])[1].lower(), 2), m[2][0]))
            self.out["skipped"] += len(members) - 1
            n, p, st = members[0][2]
            out.append((n, p, st, _show_of(root, parts, n), "new"))
        # K1: of one episode's releases found new here (`- 05`, `- 05v2`), only the latest is taken
        latest = {}
        for n, _p, _st, _show, kind in out:
            episode, version = _episode_of(n)
            if kind == "new" and episode is not None:
                k = (self._name_show(n), episode)
                latest[k] = max(latest.get(k, 0), version)
        if latest:
            kept = []
            for e in out:
                episode, version = _episode_of(e[0])
                if e[4] == "new" and episode is not None and version < latest[(self._name_show(e[0]), episode)]:
                    self.out["skipped"] += 1
                else:
                    kept.append(e)
            out = kept
        prefixes = None
        for n, p, st in epubs:
            if prefixes is None:
                prefixes = {k.rsplit("#", 1)[0] for k in list(self.origins) + list(self.ex_paths) if "#" in k}
            k = _key(p)
            if k in prefixes:                                # a known EPUB is never split again
                continue
            if self.no_text.get(k) == [st.st_size, st.st_mtime_ns]:   # no text in it, and unchanged (K5)
                self.no_text_kept[k] = self.no_text[k]
                self.out["skipped"] += 1
                continue
            out.append((n, p, st, _show_of(root, parts, n), "book"))
        return out

    def _name_show(self, name):
        """K4's show of a file name, folded: two releases of one show's episode have the same."""
        return ls.search_fold(ls.show_of_name(name) or "", self.language)

    # --- new files (SRC-7) ----------------------------------------------------------------------------------------- #

    def _take(self, new, books=()):
        """Each show's new files, checked and copied, handed to `take_in` BATCH at a time, and each book (its own
        show, by its name) among them in name order (SRC-1); a stop ends the look after the files already copied are
        taken in."""
        from app.extract import clean_name
        by_show = {}
        for c in new:                                        # a text (6), a video waiting for its text (4)
            by_show.setdefault(c[4] if len(c) == 6 else c[3], []).append(c)
        for b in books:
            by_show.setdefault(clean_name(os.path.splitext(b[1])[0]) or "Book", []).append(b)
        for show in sorted(by_show, key=lambda s: (ls.search_fold(s, self.language), s)):
            batch = []
            for c in by_show[show]:
                if self.stopped():
                    break
                if len(c) == 5:                              # a book: taken in on its own, all its parts at once
                    try:
                        self._book(*c)
                    except OSError:                          # locked, or its Library folder unreadable: next look
                        self._wait(c[0])
                    continue
                try:
                    f = self._new(*c) if len(c) == 6 else self._video_only(*c)
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
        """`take_in` of one batch; a copy no item holds (the source stopped meanwhile — this batch's copies — or the
        store's `unused`: a file known or kept out after all, a second file of the same bytes) goes to the trash, never
        left in Library untracked (N3)."""
        if not found:
            return
        made = [f["rel"] for f in found if f.get("rel") in self.made]
        try:
            change = self.store.take_in(self.root_id, found, first=self.first, rules=self.rules)
        except ls.NotASource:
            self.out["stopped"] = True                       # stopped reading meanwhile
            for rel in made:
                ls.trash_file(self.data_dir, rel)
            return
        if change is None:
            return
        self.out["added"] += len(change.added)
        self.out["ids"].extend(change.added)
        self.out["attached"] += len(change.attached)
        self.out["skipped"] += sum(len(v) for v in change.skipped.values())
        for rel in change.unused:
            ls.trash_file(self.data_dir, rel)

    def _new(self, folder, path, st, name, show, vids):
        """One new text file -> its `found` entry for `take_in` (an `item_id` for an episode already in, else the
        copy's `rel`), or None (skipped, or waiting for the next look)."""
        from app.connect import runner, videos
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        episode, version = _episode_of(name)
        held = self._held(folder).get((self._name_show(name), episode)) if episode is not None else None
        if held is not None and held[0] > version:           # an earlier release of an episode already in (K1)
            self.out["skipped"] += 1
            return None
        if version > 1 and (ls.search_fold(show, self.language), episode,
                            self._name_show(ls.path_key(name))) in self.ex_episodes:
            self.out["skipped"] += 1                         # a re-release of an episode removed (K2)
            return None
        if self._recent(st):
            self._wait(folder)
            return None
        video, vkey = None, None
        stem = _tag(name)[0]
        for candidate in [stem + e for e in runner.VIDEO_EXTENSIONS] + videos.names_for(name):
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
        track = vkey or (ls.path_key(os.path.abspath(video[0])) if video else None)
        if track is not None and track in self.this_videos:  # one subtitle per video per language: the next look's
            self._wait(folder)
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
        if episode is not None:
            f["episode"] = episode
        if video:
            f["video_path"], f["video_size"] = os.path.abspath(video[0]), video[1].st_size
            if vkey:
                f["video_key"] = vkey
        item = (self._video_item(vkey) if vkey else None) or self._same_bytes(st.st_size, sha)
        if item is None and held is not None and held[0] < version:   # a v2 of an episode already in (S7)
            earlier = held[1]
            outcome, _sha = self._recopy(earlier.rel_path, earlier.sha256, path, st)
            if outcome == "wait":
                self._wait(folder)
                return None
            if outcome == "refused":                         # not followed: nor recorded (its bytes aren't the item's)
                self.out["skipped"] += 1
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
        if track is not None:
            self.this_videos.add(track)
        return f

    def _video_only(self, folder, path, st, show):
        """A video in a folder with none of our text yet (K5, SRC-2 (video)) -> its found-record for `take_in`: one
        item per video, waiting in New arrivals (*no subtitles yet*) at `Library/<show>/<video name>`, no file made,
        until its subtitle fills the gap in place — or None: recorded already, paired already (hato's), of a show
        already shown (its subtitles will join it), kept out (S6), or waiting for the next look."""
        from app.connect import videos
        if _key(path) in self.origins:
            return None
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return None
        if self._is_shown(show):
            return None
        name = os.path.basename(path)
        f = {"origin": os.path.abspath(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show,
             "rel": f"{ls.CONTENT_FOLDER}/{show}/{name}", "video_path": os.path.abspath(path), "video_size": st.st_size}
        if not ls.is_placeholder(st):                        # a placeholder's key is never read (B3): by its path
            if self._recent(st):
                self._wait(folder)
                return None
            vkey = videos.content_key(path)
            if vkey is None:                                 # changed while read
                self._wait(folder)
                return None
            if vkey in self.ex_videos:
                self.out["skipped"] += 1
                return None
            if self._video_item(vkey) is not None:
                return None
            f["video_key"] = vkey
        episode, _version = _episode_of(name)
        if episode is not None:
            f["episode"] = episode
        return f

    def _is_shown(self, show):
        """Has this show an item that isn't waiting (any place)? Its folder key, as the store groups a show's title
        (`Library/<show>` and a 2.x `HighPriority/<show>` are one). One read of the items per look, when needed."""
        if self.shown is None:
            self.shown = set()
            for tier in ls.TIERS:
                for _i, entry, availability in self.store.ordered(tier):
                    if availability != "waiting":
                        self.shown.add(ls.folder_key_of(str(entry.get("physical_path") or "")))
        return ls.folder_key_of(f"{ls.CONTENT_FOLDER}/{show}/x") in self.shown

    def _same(self, path, st):
        """The original as listed still (its size and time): else it is being written."""
        try:
            now = os.stat(path)
        except OSError:
            return False
        return (now.st_size, now.st_mtime_ns) == (st.st_size, st.st_mtime_ns)

    def _video_item(self, vkey):
        """(a) The live item whose record holds this video (hato's key, or an origin's `video_key`) — never a waiting
        one (K5: its gap is filled by `take_in` from the copy) — or None."""
        return self.store.item_of_video_key(vkey)

    def _same_bytes(self, size, sha, sizes=None):
        """(b) An item of this size whose file holds these bytes, or None."""
        for item_id, rel in (self.sizes if sizes is None else sizes).get(size, ()):
            if rel not in self.hashes:
                try:
                    self.hashes[rel] = ls.sha256_of(os.path.join(self.data_dir, *rel.split("/")))
                except OSError:
                    self.hashes[rel] = None
            if self.hashes[rel] == sha:
                return item_id
        return None

    def _held(self, folder):
        """S7: the releases already in from this folder -> {(K4's show of the name, episode): (version, Origin)}, the
        latest of each — a `v2` found is that episode (followed, S5), an earlier one found later is skipped. One
        pass over the origins per look."""
        if self.by_folder is None:
            self.by_folder = {}
            for o in self.origins.values():
                name = os.path.basename(o.origin or "")
                if not ls.is_content_name(name.lower()):     # a book's part, or a video waiting for its text (K5)
                    continue
                episode, version = _episode_of(name)
                if episode is None:
                    continue
                releases = self.by_folder.setdefault(ls.path_key(os.path.dirname(os.path.abspath(o.origin))), {})
                k = (self._name_show(name), episode)
                if k not in releases or releases[k][0] < version:
                    releases[k] = (version, o)
        return self.by_folder.get(ls.path_key(os.path.abspath(folder)), {})

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
            ls.rename_no_overwrite(part, full)
        except OSError:
            _drop(part)
            return None
        self.made.add(rel)
        return rel

    def _trash_copy(self, full):
        """The old copy *copied* into the data folder's `.trash` (purged 30 days on: a fresh time — `copyfile`, never
        the old copy's own — and its clock restarted) -> the trash file's path."""
        trash = os.path.join(self.data_dir, ".trash")
        os.makedirs(trash, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(full))
        stamp = time.strftime("%Y%m%d%H%M%S")
        name, n = f"{base}_{stamp}{ext}", 1
        while os.path.exists(os.path.join(trash, name)):
            name, n = f"{base}_{stamp}_{n}{ext}", n + 1
        dst = os.path.join(trash, name)
        shutil.copyfile(full, dst)
        restart_trash_clock(dst)
        return dst

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
            kept = self._trash_copy(full)
        except OSError:
            _drop(part)
            return "wait", None
        try:
            os.replace(part, full)
        except OSError:                                      # the copy held open: it stays as it was, the trash too
            _drop(part)
            _drop(kept)
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
        parts already written to the trash, the book waits). Each part's record holds the EPUB file's sha256, so the
        same book renamed or moved is known by its bytes — its parts recorded on the items already in, nothing read
        or written — and a removed one's bytes stay out (K4, S6); a part whose text an item already holds is that
        item (check b). A book that gave no text is remembered by its stats and not read again until it changes (K5)."""
        from app import extract
        if self._recent(st):
            self._wait(folder)
            return
        if _key(path) in self.ex_paths:
            self.out["skipped"] += 1
            return
        sha = ls.sha256_of(path)
        if not self._same(path, st):
            self._wait(folder)
            return
        if sha in self.ex_shas:
            self.out["skipped"] += 1
            return
        origin = os.path.abspath(path)
        known = self._books().get(sha)
        if known:
            self._commit([{"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                           "show": rel.split("/")[1] if rel.count("/") >= 2 else show, "item_id": item, "episode": i}
                          for i, (item, rel) in sorted(known.items())])
            return
        chunks, error = extract.chunks_of(path, self.language)
        if error or not chunks:                              # no text in it: nothing to read, until it changes
            self.no_text_kept[_key(path)] = [st.st_size, st.st_mtime_ns]
            self.out["skipped"] += 1
            return
        if not self._same(path, st):
            self._wait(folder)
            return
        base = extract.clean_name(os.path.splitext(name)[0]) or "Book"
        data = [c.encode("utf-8") for c in chunks]
        names = [f"{base}_{i:02d}.txt" if len(data) > 1 else f"{base}.txt" for i in range(1, len(data) + 1)]
        shas = [hashlib.sha256(d).hexdigest() for d in data]
        sizes = self.store.items_of_size([len(d) for d in data])
        held = [self._same_bytes(len(d), s, sizes) for d, s in zip(data, shas)]
        todo = [i for i, item in enumerate(held) if item is None]
        book, n = base, 1
        while todo:                                          # a free folder, or one a crash left with these parts
            rels = [f"{ls.CONTENT_FOLDER}/{book}/{x}" for x in names]
            if not os.path.exists(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book)) or all(
                    ls.content_target(self.data_dir, rels[i], len(data[i]), shas[i]) == (rels[i], True) for i in todo):
                break
            n += 1
            book = f"{base} ({n})"
        rels = [f"{ls.CONTENT_FOLDER}/{book}/{x}" for x in names]
        written, parts = [], []
        try:
            for i in todo:
                full = self._inside(rels[i])
                if full is None:
                    raise OSError(f"outside the content folder: {rels[i]}")
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if os.path.isfile(full):
                    continue                                 # the same bytes, left by a crash
                with open(full + ".part", "wb") as f:
                    parts.append(full + ".part")
                    f.write(data[i])
                    f.flush()
                    os.fsync(f.fileno())
            for p in parts:
                ls.rename_no_overwrite(p, p[:-len(".part")])
                written.append(p[:-len(".part")])
        except OSError:
            for p in parts:
                _drop(p)
            for w in written:
                ls.trash_file(self.data_dir, ls.library_rel(self.data_dir, w))
            self._wait(folder)
            return
        if todo:
            write_source_marker(os.path.join(self.data_dir, ls.CONTENT_FOLDER, book), "epub", origin=name)
        self.made.update(rels[i] for i in todo)
        found = []
        for i, (rel, item) in enumerate(zip(rels, held), 1):
            f = {"origin": f"{origin}#{i}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                 "show": book, "episode": i}
            if item is None:
                f["rel"] = rel
            else:
                f["item_id"] = item
            found.append(f)
        self._commit(found)

    def _books(self):
        """{an EPUB's sha256: {part number: (item_id, rel)}} of the books already in (their parts' records)."""
        if self.books_in is None:
            self.books_in = {}
            for o in self.origins.values():
                head, _sep, number = (o.origin or "").rpartition("#")
                if head and number.isdigit() and o.sha256:
                    self.books_in.setdefault(o.sha256, {})[int(number)] = (o.item_id, o.rel_path or "")
        return self.books_in
