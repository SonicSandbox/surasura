"""Where Connect looks for an episode's video (P2.5 row 2.5.8; G1.3-12, the lean held: "the folders your paired videos
are in, plus any you add in Settings; checked when Connect starts; never downloads a cloud placeholder"; 06-edges E15).

- **The named video first:** hato's pairing names it; on disk → it (the runner's `_on_disk`: a cloud placeholder is
  never opened, RD-S1).
- **Else the index:** the folders the library's paired videos are in (that folder only) and the ones you add
  (`connect_video_folders`: a list, or `{lang: list}`; their subfolders too, 4 deep — both limits are defaults this
  step chose, not rulings), each video file by its name — and by its size when the pairing gives one (`video_size`),
  so another file of the same name is never taken. Two that fit → *No video*: Connect never guesses.
  Without a pairing (a subtitle you added), a video named like the subtitle (`beside`'s names) anywhere in them.
- **Only what changed** (S19): the index is kept in `<local data>/connect/videos-<lang>.json`, each folder with its
  modified time; a folder whose time hasn't moved is never listed again (one `stat`). Built once a run, the first
  time a video is missing — never while every video is where its pairing says.
- **Keyed by language** (D31): one index file per language, under local data (where a profile folder can sit above).

A placeholder (a cloud file not downloaded) is indexed by name but never opened or taken: *No video* until it's on
this computer. Standard library only.
"""
import json
import os

from app.connect import runner

INDEX_VERSION = 1
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
        todo = [(os.path.normcase(os.path.abspath(f)), 0, False) for f in shallow]
        todo += [(os.path.normcase(os.path.abspath(f)), 0, True) for f in deep]
        while todo:
            folder, depth, recurse = todo.pop()
            if folder in new and (not recurse or new[folder].get("deep")):
                continue
            try:
                mtime = os.stat(folder).st_mtime_ns
            except OSError:
                continue                    # gone or offline: looked at again next run
            had = old.get(folder)
            if had and had.get("mtime_ns") == mtime:
                entry = dict(had)
            else:
                got = _list(folder)
                if got is None:
                    continue
                self.listed += 1
                entry = {"mtime_ns": mtime, "videos": got[0], "subs": got[1]}
            entry["deep"] = bool(recurse) or bool((new.get(folder) or {}).get("deep"))
            new[folder] = entry
            if recurse and depth < DEPTH:
                todo += [(os.path.normcase(os.path.abspath(s)), depth + 1, True) for s in entry.get("subs") or ()]
        changed = new != old
        self.data["dirs"] = new
        if changed:
            self._save()
        return changed

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def find(self, names, size=None):
        """The one indexed video (on disk now) with one of `names` (and `size`, when given) -> its path; None when
        there's none, or more than one — Connect never guesses (E5's rule; intent keeper P2.5 #6)."""
        wanted = [n.lower() for n in names if n]
        found = set()
        for folder in sorted(self.data["dirs"]):
            videos = self.data["dirs"][folder].get("videos") or {}
            for name in wanted:
                hit = videos.get(name)
                if hit and (size is None or hit[1] == size):
                    path = os.path.join(folder, hit[0])
                    if runner._on_disk(path):
                        found.add(path)
        return found.pop() if len(found) == 1 else None


def names_for(subtitle):
    """The video names a subtitle without a pairing goes with (`Show - 05.mkv` for `Show - 05.ja.srt`)."""
    stem = os.path.splitext(os.path.basename(subtitle))[0]
    stems = [stem]
    base, tag = os.path.splitext(stem)
    if base and 1 < len(tag) <= 4:
        stems.append(base)
    return [s + ext for s in stems for ext in runner.VIDEO_EXTENSIONS]
