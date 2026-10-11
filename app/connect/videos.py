"""Where Connect looks for an episode's video (P2.5 row 2.5.8; G1.3-12, the lean held: "the folders your paired videos
are in, plus any you add in Settings; checked when Connect starts; never downloads a cloud placeholder"; 06-edges E15).

- **The named video first:** hato's pairing names it; on disk → it (the runner's `_on_disk`: a cloud placeholder is
  never opened, RD-S1).
- **Else the index:** the folders the library's paired videos are in (that folder only) and the ones you add
  (`connect_video_folders`: a list, or `{lang: list}`; their subfolders too, 4 deep — both limits are defaults this
  step chose, not rulings), each video file by its name — and by its size when the pairing gives one (`video_size`),
  so another file of the same name is never taken. Two on this computer that fit → *No video*: Connect never
  guesses (a cloud placeholder of the same name doesn't count: it is never taken).
  Without a pairing (a subtitle you added), a video named like the subtitle (`beside`'s names) anywhere in them.
- **Only what changed** (S19): the index is kept in `<local data>/connect/videos-<lang>.json`, each folder with its
  modified time; a folder whose time hasn't moved is never listed again (one `stat`). Built once a run, the first
  time a video is missing — never while every video is where its pairing says.
- **Keyed by language** (D31): one index file per language, under local data (where a profile folder can sit above).

A placeholder (a cloud file not downloaded) is indexed by name but never opened or taken: *No video* until it's on
this computer. Standard library only.
"""
import json
import logging
import os

from app.connect import runner

log = logging.getLogger("surasura-cli")

INDEX_VERSION = 2               # 2: each folder keeps its own spelling (`path`)
DEPTH = 4                       # the folders you add: their subfolders this deep


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


def _list(folder):
    """(videos {name lower: [name, size]}, subfolders [path]) of one folder (names and sizes: nothing is opened);
    None when it can't be read (gone, offline)."""
    videos, subs = {}, []
    try:
        with os.scandir(folder) as found:
            for entry in found:
                try:
                    if entry.is_dir(follow_symlinks=False):
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
    return videos, sorted(subs)


class Index:
    """One language's video index, refreshed at most once (`refresh`) and saved only when a folder changed."""

    def __init__(self, lang, path=None):
        self.path = path or index_path(lang)
        self.data = _load(self.path)
        self.listed = 0             # folders listed again this refresh (the rest: one stat each)

    def refresh(self, shallow, deep):
        """Every folder of `shallow` (alone) and `deep` (with subfolders, DEPTH deep), listed again only when its
        modified time moved; folders no longer looked at are dropped from the file."""
        old, new = self.data["dirs"], {}
        self.listed = 0
        todo = [(os.path.abspath(f), 0, False) for f in shallow] + [(os.path.abspath(f), 0, True) for f in deep]
        reached = {}                # folder -> the shallowest depth it was walked at with its subfolders
        while todo:
            where, depth, recurse = todo.pop()
            folder = os.path.normcase(where)        # the key; `where` keeps the folder's own spelling for its paths
            if folder in new and (not recurse or reached.get(folder, DEPTH + 1) <= depth):
                continue            # done already (an added folder inside another is walked from its own top too)
            if recurse:
                reached[folder] = depth
            had = old.get(folder)
            try:
                mtime = os.stat(where).st_mtime_ns
            except OSError:
                mtime = None
            if had and (mtime is None or had.get("mtime_ns") == mtime):
                entry = dict(had)           # unchanged, or offline now: kept as listed (never listed again for it)
            elif mtime is None:
                continue                    # never listed and not there: looked at again next run
            else:
                got = _list(where)
                if got is None:
                    if not had:
                        continue
                    entry = dict(had)       # can't be read just now: kept as it was
                else:
                    self.listed += 1
                    entry = {"mtime_ns": mtime, "path": where, "videos": got[0], "subs": got[1]}
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
        there's none, or more than one — Connect never guesses (E5's rule; intent keeper P2.5 #6)."""
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


def names_for(subtitle):
    """The video names a subtitle without a pairing goes with (`Show - 05.mkv` for `Show - 05.ja.srt`)."""
    stem = os.path.splitext(os.path.basename(subtitle))[0]
    stems = [stem]
    base, tag = os.path.splitext(stem)
    if base and 1 < len(tag) <= 4:
        stems.append(base)
    return [s + ext for s in stems for ext in runner.VIDEO_EXTENSIONS]
