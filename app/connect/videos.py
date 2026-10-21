"""Where Connect looks for an episode's video (P2.5 row 2.5.8; G1.3-12, the lean held: "the folders your paired videos
are in, plus any you add in Settings; checked when Connect starts; never downloads a cloud placeholder"; 06-edges E15).

- **The named video first:** hato's pairing names it; on disk → it (the runner's `_on_disk`: a cloud placeholder is
  never opened, RD-S1).
- **Else the index:** the folders the library's paired videos are in (that folder only) and the ones you add
  (`connect_video_folders`: a list, or `{lang: list}`; their subfolders too, 4 deep — both limits are defaults this
  step chose, not rulings; the source folders the store reads are indexed as these, SRC M1), each video file by its
  name — and by its size when the pairing gives one (`video_size`), so another file of the same name is never taken.
  Two on this computer that fit → *No video*: Connect never guesses (a cloud placeholder of the same name doesn't
  count: it is never taken).
  Without a pairing (a subtitle you added), a video named like the subtitle (`beside`'s names) anywhere in them.
- **Only what changed** (S19): the index is kept in `<local data>/connect/videos-<lang>.json`, each folder with its
  modified time; a folder whose time hasn't moved is never listed again (one `stat`). Built once a run, the first
  time a video is missing — never while every video is where its pairing says.
- **A share whose folder times don't move** (a NAS, a FAT drive; P3.1 row 3.1.7): a video still not found is looked
  for once more, once a run — the folders whose time didn't move listed again, at most RELIST_MAX entries in all (a
  folder with more than are left keeps what it had, and the rest goes on to the next); a second miss in the run lists
  nothing again.
- **Keyed by language** (D31): one index file per language, under local data (where a profile folder can sit above).
- **A paired video found away from its named path** (moved; found by name and size) is the paired one only when its
  `content_key` is the pairing's (09-hato-layer v2 §1.1: hato's `video_hash`, at most 128 KiB read); the named path on
  disk is trusted as it is, never read (P3.2 row 3.2.3).

A placeholder (a cloud file not downloaded) is indexed by name but never opened or taken: *No video* until it's on
this computer. Standard library only.
"""
import hashlib
import json
import logging
import os
import struct

from app.connect import runner

log = logging.getLogger("surasura-cli")

INDEX_VERSION = 2               # 2: each folder keeps its own spelling (`path`)
DEPTH = 4                       # the folders you add: their subfolders this deep
RELIST_MAX = 2000               # a missing video's re-list (once a run): at most this many folder entries read
KEY_PART = 65536                # the content key: a file over 2 × this is read as its first and last KEY_PART bytes


def configured(loaded, lang):
    """The folders you added for `lang` (`connect_video_folders`: a list for every language, or `{lang: [...]}`)."""
    value = (loaded or {}).get("connect_video_folders") or []
    if isinstance(value, dict):
        value = value.get(lang) or []
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value if isinstance(v, str) and v.strip()]


def index_path(lang):
    from app.connect import ledger
    return os.path.join(ledger.folder(), f"videos-{lang}.json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == INDEX_VERSION and isinstance(data.get("dirs"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": INDEX_VERSION, "dirs": {}}


class _Full(Exception):
    """The re-list's cap reached inside a folder: that folder keeps what it had."""


def _list(folder, limit=None, skip=False):
    """(videos {name lower: [name, size]}, subfolders [path], entries read) of one folder (names and sizes: nothing
    is opened); None when it can't be read (gone, offline). Raises _Full past `limit` entries. `skip` (a source
    folder's own, SRC B3; never a folder you added: the batch 1 intent review): a subfolder a source's look skips is not
    listed (`library_store.skip_dir`: dot folders, the recycle bins, a folder link or junction), so a trashed copy is
    no second match and a link is never followed."""
    from app.library_store import skip_dir
    videos, subs, seen = {}, [], 0
    try:
        with os.scandir(folder) as found:
            for entry in found:
                seen += 1
                if limit is not None and seen > limit:
                    raise _Full()
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not (skip and skip_dir(entry.name, entry)):
                            subs.append(entry.path)
                        continue
                    if not entry.name.lower().endswith(runner.VIDEO_EXTENSIONS):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                # a cloud placeholder is indexed too (its download moves no folder's time) but never opened:
                # `find` takes a file only once it is on this computer
                videos[entry.name.lower()] = [entry.name, st.st_size]
    except OSError:
        return None
    return videos, sorted(subs), seen


class Index:
    """One language's video index, refreshed at most once (`refresh`) and saved only when a folder changed."""

    def __init__(self, lang, path=None):
        self.path = path or index_path(lang)
        self.data = _load(self.path)
        self.listed = 0             # folders listed again this refresh (the rest: one stat each)
        self.roots = None           # the last refresh's folders (shallow, deep, sources): what a re-list walks
        self.relisted = False       # the re-list ran (once a run: this index lives one run)

    def refresh(self, shallow, deep, budget=None, sources=()):
        """Every folder of `shallow` (alone) and `deep` (with subfolders, DEPTH deep), listed again only when its
        modified time moved; folders no longer looked at are dropped from the file. `budget` (a missing video's
        re-list): the folders whose time didn't move are listed again too, at most `budget` entries kept in all — a
        folder with more entries than are left keeps what it had, and what's left goes on to the folders after it.
        `sources` (SRC M1): the folders the store reads, walked as `deep` ones but by a source's skip rule (`_list`'s
        `skip`, marked `"skip"` on their entries) — except inside a folder of `deep`, which is listed as before."""
        self.roots = (list(shallow), list(deep), list(sources))
        old, new = self.data["dirs"], {}
        self.listed = 0
        left = budget
        own = [os.path.normcase(os.path.abspath(f)) for f in deep]
        theirs = [os.path.normcase(os.path.abspath(f)) for f in sources]
        under = lambda folder, tops: any(folder == t or folder.startswith(t.rstrip(os.sep) + os.sep)  # noqa: E731
                                         for t in tops)
        todo = [(os.path.abspath(f), 0, False) for f in shallow] + \
            [(os.path.abspath(f), 0, True) for f in list(deep) + list(sources)]
        reached = {}                # folder -> the shallowest depth it was walked at with its subfolders
        while todo:
            where, depth, recurse = todo.pop()
            folder = os.path.normcase(where)        # the key; `where` keeps the folder's own spelling for its paths
            if folder in new and (not recurse or reached.get(folder, DEPTH + 1) <= depth):
                continue            # done already (an added folder inside another is walked from its own top too)
            if recurse:
                reached[folder] = depth
            had = old.get(folder)
            skip = bool(theirs) and under(folder, theirs) and not under(folder, own)
            try:
                mtime = os.stat(where).st_mtime_ns
            except OSError:
                mtime = None
            again = bool(left) and mtime is not None    # the re-list, under its cap: listed whatever its time says
            if had and (mtime is None or (had.get("mtime_ns") == mtime and bool(had.get("skip")) == skip)) \
                    and not again:
                entry = dict(had)           # unchanged, or offline now: kept as listed (never listed again for it)
            elif mtime is None:
                continue                    # never listed and not there: looked at again next run
            else:
                try:
                    got = _list(where, left, skip=True) if skip else _list(where, left)
                except _Full:
                    got = None              # over what's left of the cap: it keeps what it had, the rest goes on
                if got is not None and left is not None:
                    left -= got[2]
                if got is None:
                    if not had:
                        continue
                    entry = dict(had)       # can't be read just now: kept as it was
                else:
                    self.listed += 1
                    entry = {"mtime_ns": mtime, "path": where, "videos": got[0], "subs": got[1]}
                    if skip:
                        entry["skip"] = True
            entry["deep"] = bool(recurse) or bool((new.get(folder) or {}).get("deep"))
            new[folder] = entry
            if recurse and depth < DEPTH:
                todo += [(os.path.abspath(s), depth + 1, True) for s in entry.get("subs") or ()]
        changed = new != old
        self.data["dirs"] = new
        if changed:
            self._save()
        return changed

    def _save(self):
        """Written whole (a temp file, then replaced); a folder that can't be written keeps the old file: the index
        is only a cache, so the lookup goes on with what this run listed."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Connect's video index couldn't be saved (%s); it's listed again next run", self.path)

    def find(self, names, size=None):
        """The one indexed video (on disk now) with one of `names` (and `size`, when given) -> its path; None when
        there's none, or more than one — Connect never guesses (E5's rule; intent keeper P2.5 #6). None the first
        time this run: the folders are listed again (`refresh`'s re-list, RELIST_MAX entries) and looked in once
        more."""
        found = self._find(names, size)
        if found is None and not self.relisted and self.roots is not None:
            self.relisted = True
            shallow, deep, sources = self.roots
            self.refresh(shallow, deep, budget=RELIST_MAX, sources=sources)
            found = self._find(names, size)
        return found

    def _find(self, names, size):
        wanted = [n.lower() for n in names if n]
        found = set()
        for folder in sorted(self.data["dirs"]):
            entry = self.data["dirs"][folder]
            videos = entry.get("videos") or {}
            for name in wanted:
                hit = videos.get(name)
                if hit:
                    path = os.path.join(entry.get("path") or folder, hit[0])
                    # the size as it is now (a copy still growing or a file replaced in place moves no folder's time)
                    if runner._on_disk(path) and (size is None or _size(path) == size):
                        found.add(path)
        return found.pop() if len(found) == 1 else None


def _size(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return None


def content_key(path):
    """The video's identity as hato keys it (09-hato-layer v2 §1.1, hato's `video_hash`): "v1-" + sha256 of the size
    as 8 bytes little-endian, then the whole file when it is 2 × KEY_PART bytes or less, else its first and last
    KEY_PART bytes. None when it can't be read, or its size or modified time moved while it was read (a file being
    copied or replaced is not the paired video)."""
    try:
        before = os.stat(path)
        body = _key_body(path, before.st_size)
        after = os.stat(path)
    except OSError:
        return None
    if body is None or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        return None
    return "v1-" + hashlib.sha256(struct.pack("<Q", before.st_size) + body).hexdigest()


def _key_body(path, size):
    """The bytes the key reads from a file of `size` bytes, or None when fewer are there."""
    with open(path, "rb") as f:
        if size <= 2 * KEY_PART:
            body = f.read(size + 1)                 # one more: a file grown since the stat is caught here too
            return body if len(body) == size else None
        head = f.read(KEY_PART)
        f.seek(size - KEY_PART)
        tail = f.read(KEY_PART)
    return head + tail if len(head) == len(tail) == KEY_PART else None


def names_for(subtitle):
    """The video names a subtitle without a pairing goes with (`Show - 05.mkv` for `Show - 05.ja.srt`): its stem and its
    stem without the marks LM1a's rule reads (`episode_names.video_stems`), each in NFC and NFD."""
    from app.episode_names import video_stems
    return [s + ext for s in video_stems(subtitle) for ext in runner.VIDEO_EXTENSIONS]
