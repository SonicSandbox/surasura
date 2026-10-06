"""Shared by P2.1's suites (register, place, finish, the inbox, Connect on demand, the placing rules, the start-up
notice): a library of real subtitles with its store built, hato-style drops and pairing records, under the test's own
root (`SURASURA_TEST_ROOT`). Titles and video paths are synthetic; the subtitles are the suite's real Japanese and
Chinese test files.
"""
import copy
import hashlib
import json
import os
import subprocess
import sys

from app import library_store
from tests import cli_helpers as h

RECORD = os.path.join(h.RESOURCES, "connect", "pairing_v1.json")
SUBTITLE = {"ja": ("ja", "phrases_sample.srt"), "zh": ("zh", "chinese_text_1.txt")}


def dirs(lang="ja"):
    return os.path.join(h.root(), "data", lang), os.path.join(h.root(), "User Files", lang)


def library(lang="ja", connect=True, arrivals=False, extra=3, **settings):
    """The suite's real files in NOW (plus `extra` more subtitles, so Chinese holds several too), settings (Connect on
    or off), the library store built from the folders and, for the 3.0 behaviour, its `arrivals_on` switch. Returns
    the data folder."""
    h.seed_library(lang, templates=False)
    for n in range(extra):
        drop(f"Notes {n + 1}.{lang}.srt", lang, folder="HighPriority")
    h.write_settings(target_language=lang, connect_enabled=connect, **settings)
    data_dir, user_files = dirs(lang)
    assert library_store.maintain(lang, data_dir, user_files, from_folders=True) == library_store.EXIT_DONE
    if arrivals:
        with store(lang) as s:
            s.bookkeeping({"arrivals_on": 1}, copy_carries=True)
    return data_dir


def store(lang="ja"):
    data_dir, user_files = dirs(lang)
    s = library_store.open_store(lang, data_dir, user_files)
    assert s is not None
    return s


def drop(name, lang="ja", folder=library_store.HATO_FOLDER):
    """A subtitle copied where hato copies it (`HighPriority/Hato/<name>`), as hato's file -> its path."""
    data_dir, _u = dirs(lang)
    target = os.path.join(data_dir, *folder.split("/"), name)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    sub_lang, sub_name = SUBTITLE[lang]
    with open(os.path.join(h.RESOURCES, sub_lang, sub_name), "rb") as f:
        data = f.read()
    with open(target, "wb") as f:
        f.write(data + f"\n{name}\n".encode("utf-8"))     # each copy its own bytes, as each episode's subtitle
    return target


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def record(path, video, lang="ja", show=None, **more):
    """hato's pairing record v1 for the library copy at `path`: the fixture with this file's sha256, a content key
    made from `video` (any text: tests need distinct videos, not real ones) and the show it names."""
    with open(RECORD, encoding="utf-8") as f:
        rec = json.load(f)
    rec = copy.deepcopy(rec)
    rec.update({"language": lang, "library_path": path, "subtitle_sha256": sha256(path),
                "content_key": "v1-" + hashlib.sha256(video.encode("utf-8")).hexdigest()})
    if show is not None:
        rec["show"] = show
    rec.update(more)
    return rec


def write_record(rec, name="record.json"):
    path = os.path.join(h.root(), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    return path


def register_stdin(data, *args, env=None):
    """`surasura-cli register --pairing -` as hato calls it: the record's bytes on stdin -> (exit code, JSON lines)."""
    proc = subprocess.run([sys.executable, "-m", "app.cli", "register", "--pairing", "-", *args], input=data,
                          cwd=os.path.dirname(h.root()), env=h.child_env(**(env or {})), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=180)
    return proc.returncode, [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]


def events(s, after=0):
    """(item_id, kind, by) of the placement log after `after`."""
    return [tuple(r) for r in s.conn.execute("SELECT item_id, kind, by FROM placement_log WHERE id > ? ORDER BY id",
                                             (after,))]


def store_state(lang="ja"):
    """What a store write would move: every meta value, and the items, pairings and log rows counted."""
    with store(lang) as s:
        count = lambda table: s.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]     # noqa: E731
        return s.meta(), count("items"), count("pairings"), count("placement_log")


def snapshot():
    """Every file under the root a call must not write: all but the command line's own logs and locks and SQLite's
    side files — (size, modified time, sha256) each."""
    seen = {}
    for folder, _dirs, files in os.walk(h.root()):
        rel = os.path.relpath(folder, h.root())
        if rel.split(os.sep)[:2] in (["local", "logs"], ["local", "locks"]):
            continue
        for name in files:
            if name.endswith(("-wal", "-shm")):
                continue
            path = os.path.join(folder, name)
            st = os.stat(path)
            seen[os.path.relpath(path, h.root())] = (st.st_size, st.st_mtime_ns, sha256(path))
    return seen

