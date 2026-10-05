"""Shared helpers for the library store's tests (`app/library_store.py`, L1.2). No tests here.

Every library these build is synthetic and lives under the per-test SURASURA_TEST_ROOT that
tests/conftest.py sets (never the user's `User Files/`, `data/` or `results/`). File and show names are
real Japanese and Chinese words taken from tests/Test Resources/ (ja = zh: every proof runs for both).
"""

import json
import os
import re

from app import library_store as ls

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
LANGUAGES = ("ja", "zh")
_CJK = re.compile(r"[ぁ-ヿ㐀-鿿]{2,6}")
_NAMES = {}


def names(language):
    """Distinct words of 2–6 Japanese or Chinese characters from the language's real test texts, in the
    order they first appear: show names, episode titles."""
    if language not in _NAMES:
        seen = []
        folder = os.path.join(RESOURCES, language)
        for fname in sorted(os.listdir(folder)):
            if not fname.endswith((".txt", ".srt")):
                continue
            with open(os.path.join(folder, fname), encoding="utf-8", errors="replace") as f:
                for word in _CJK.findall(f.read()):
                    if word not in seen:
                        seen.append(word)
        _NAMES[language] = seen
    return _NAMES[language]


def roots(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    return (os.path.join(root, "data", language), os.path.join(root, "User Files", language))


def touch(data_dir, rel, text=None):
    """A content file with a line of real text (its size tells files apart, like real subtitles)."""
    path = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text is not None else f"{rel}\n")
    return path


def entry(rel, origin="Manual Import", source_type="subtitle"):
    return ls.make_entry(rel, origin, source_type if rel.endswith(".srt") else "text")


def write_manifest(user_files_dir, doc):
    """As today's `save_manifest` writes it: indent=2, raw UTF-8, text mode (CRLF on Windows)."""
    os.makedirs(user_files_dir, exist_ok=True)
    path = ls.manifest_path(user_files_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return path


def read_doc(user_files_dir):
    with open(ls.manifest_path(user_files_dir), encoding="utf-8-sig") as f:
        return json.load(f)


def library(language, shows=3, episodes=4, loose=1, tiers=("now", "soon", "goal"), create=True):
    """A small library whose folders match their tiers: per tier, `shows` show folders of `episodes`
    episodes and `loose` loose files, named with real words. Returns (data_dir, user_files_dir, doc)."""
    data_dir, user_files_dir = roots(language)
    words = names(language)
    n = 0
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for tier in tiers:
        folder = ls.FOLDER_OF_TIER[tier]
        rows = []
        for s in range(shows):
            show = words[n % len(words)]
            n += 1
            for e in range(1, episodes + 1):
                rel = f"{folder}/{show}/{show}_第{e:02d}話.srt"
                if create:
                    touch(data_dir, rel, f"{show} {e}\n")
                rows.append(entry(rel))
        for i in range(loose):
            word = words[n % len(words)]
            n += 1
            rel = f"{folder}/{word}.txt"
            if create:
                touch(data_dir, rel, f"{word}\n")
            rows.append(entry(rel))
        doc["schedule"][ls.TIERS[tier][0]] = rows
    return data_dir, user_files_dir, doc


def migrated(language, **kw):
    """A library migrated into a fresh store; returns an open Store (role 'window')."""
    data_dir, user_files_dir, doc = library(language, **kw)
    write_manifest(user_files_dir, doc)
    code = ls.maintain(language, data_dir, user_files_dir)
    assert code == ls.EXIT_DONE, code
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store is not None
    return store


def paths(store, tier):
    return [e["physical_path"] for _i, e, _a in store.ordered(tier)]


def subprocess_env():
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def big_store(language, n, available=True):
    """A synthetic store of `n` items built in one transaction, the 100k shape the reviews measured
    (NOW 1 %, Soon 44.5 %, 6+ Months the rest), names from the real word list. No files on disk:
    availability is set as asked, so the mine line counts them."""
    data_dir, user_files_dir = roots(language)
    db = ls.library_db_path(language, data_dir)
    store = ls._helper_store(db, language, data_dir, user_files_dir)
    ls._ensure_schema(store)
    words = names(language)
    now, soon = max(20, n // 100), int(n * 0.445)
    items = []
    for i in range(n):
        tier = "now" if i < now else "soon" if i < now + soon else "goal"
        show = words[(i // 12) % len(words)]
        rel = f"{ls.FOLDER_OF_TIER[tier]}/{show}{i // 12}/{show}_{i:06d}.srt"
        item = ls._item_from_entry(ls.make_entry(rel, "Disk Sync", "subtitle"), tier, data_dir, ls._now())
        if available:
            item["availability"], item["size"], item["mtime_ns"] = "available", 100, 1
        items.append(item)
    meta = ls._fresh_meta("bench" + language, 1, 1)
    with store._writing():
        ls._write_image(store, {"items": items, "tables": {}}, meta)
        store._set_meta({"migrated_at": ls._now()})
    store.close()
    return ls.open_store(language, data_dir, user_files_dir)
