"""WP-L3 of the library store (Library_Store_Spec.md §10): the JSON copy and the helper that keeps it.

Why these matter: `master_manifest.json` stays as a copy the store writes, because older versions,
Junban (by its mtime) and every reader still read it. The copy must be a complete manifest at every
instant (I5), written by the helper's process — never on a move's path — only when something it carries
changed, and the store must always tell its own copy (even a stale or half-recorded one) from an edit made
by something else. Every test runs for Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT.
"""

import json
import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, library, migrated, names, read_doc, roots,
                                              subprocess_env, touch, write_manifest)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _target(language):
    return ls.manifest_path(roots(language)[1])


def _mtime(language):
    return os.stat(_target(language)).st_mtime_ns


# --- 1. readers ---------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_every_reader_loads_the_copy_unchanged(language):
    """The Content Manager's `load_manifest`, `resolve_found_files`, the preview's reader and Reels'
    loader all read the copy as they read today's manifest."""
    from app import analyzer
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    before = analyzer.resolve_found_files(language, verbose=False)
    store = migrated_from_existing(language)
    copy = read_doc(user_files_dir)
    assert "surasura_library" in copy
    assert analyzer.resolve_found_files(language, verbose=False) == before

    from app.content_importer_gui import ContentImporterApp
    cm = ContentImporterApp.__new__(ContentImporterApp)
    cm.get_manifest_path = lambda: _target(language)
    cm._warn_manifest_once = lambda *a, **k: None
    assert cm.load_manifest() == copy

    reels = pytest.importorskip("modules.reels.library")
    assert reels.load_manifest(language) == copy
    preview = pytest.importorskip("modules.youtube_downloader.preview")
    src = touch(os.path.join(os.environ["SURASURA_TEST_ROOT"], "incoming"), names(language)[30] + " [abcdefghijk].txt")
    with patch.object(preview, "_library_mode", return_value="json"):   # 2.4.0's preview: 2.5's JSON mode
        added = preview.commit_to_front([src], language)      # 2.4.0's preview on a 2.5 copy
    after = read_doc(user_files_dir)
    assert added and after["surasura_library"] == copy["surasura_library"], "an older writer keeps the key"
    assert after["schedule"]["PHASE_1_NOW"][1:] == copy["schedule"]["PHASE_1_NOW"]
    store.close()


def migrated_from_existing(language):
    data_dir, user_files_dir = roots(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store(language, data_dir, user_files_dir)


# --- 2. shape ------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_copy_is_its_manifest_plus_one_key(language):
    data_dir, user_files_dir, doc = library(language)
    doc["metadata"] = {"generated": "2026-06-12", "strategy": "retired"}
    doc["schedule"]["PHASE_X_EXTRA"] = ["kept"]
    doc["custom_top_level"] = {"a": 1}
    doc["schedule"]["PHASE_1_NOW"][0]["reason"] = "the Immersion Architect's unknown entry key"
    write_manifest(user_files_dir, doc)
    store = migrated_from_existing(language)
    copy = read_doc(user_files_dir)
    lib = copy.pop("surasura_library")
    assert copy == doc
    assert lib["arrivals"] == [] and lib["graduated"] == [] and lib["store_id"] == store.meta()["store_id"]
    assert lib["meta"] == {"epoch": 1, "log_seq": 0, "mine_line": 20, "arrivals_on": 0}
    assert lib["content_sha"] == ls.content_sha(dict(copy, surasura_library=lib))
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_extra_state_survives_a_rebuild(language):
    """pairings, the placement log, pins, the epoch, log_seq, soon_line, mine_line, arrivals_on and the
    readers' watermarks go out in the copy and come back through a rebuild (a new PC)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    store.register_reader("connect")
    store.register_reader("window")                            # hasn't read: the helper prunes nothing
    store.register(os.path.join(data_dir, store.item(ids[2])["rel_path"]), {"content_key": "pair-1", "v": 1})
    store.move([ids[0]], "now", after_id=ids[3])
    store.pin([ids[1]])
    store.set_watched([ids[4]])
    with store._writing():
        store._set_meta({"soon_line": len(store.ids("now")), "mine_line": 25, "arrivals_on": 1})
    events, _gap = store.read_events("connect")
    store.advance_reader("connect", events[-1][0])
    before = {"order": {t: store.ids(t) for t in ls.TIERS}, "meta": store.meta(),
              "pin": store.item(ids[1])["pinned"], "log": store.conn.execute("SELECT * FROM placement_log").fetchall()}
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):                        # a new PC: no database at all
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    meta = store.meta()
    assert {t: store.ids(t) for t in ls.TIERS} == before["order"]
    assert store.item(ids[1])["pinned"] == before["pin"] and store.item(ids[4])["watched"] == 1
    assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = 'pair-1'").fetchone()[0] == ids[2]
    assert before["log"] and store.conn.execute("SELECT * FROM placement_log").fetchall() == before["log"]
    for key in ("soon_line", "mine_line", "arrivals_on", "reader:connect"):
        assert str(meta[key]) == str(before["meta"][key]), key
    assert meta["epoch"] == before["meta"]["epoch"] + 1 and meta["store_id"] != before["meta"]["store_id"]
    assert meta["log_seq"] >= before["meta"].get("log_seq", 0)
    store.close()


# --- 3. nothing to do; dirty bookkeeping --------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_nothing_to_do_and_dirty_bookkeeping(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    mtime = _mtime(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING
    assert _mtime(language) == mtime, "an unchanged state never touches the copy (consumers key on its mtime)"
    store.register_reader("connect")
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    version = store.versions()["state_version"]
    events, _gap = store.read_events("connect")
    store.advance_reader("connect", events[-1][0])             # a watermark advance alone
    assert store.versions()["state_version"] == version
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert read_doc(user_files_dir)["surasura_library"]["meta"]["reader:connect"] == events[-1][0]
    assert store.meta()["copy_dirty"] == 0
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING
    store.close()


# --- 4. a held-open target ----------------------------------------------------------------------- #

@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses to replace a file held open")
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_held_open_target_succeeds_after_release(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    handle = open(_target(language), "rb")
    threading.Timer(0.3, handle.close).start()
    started = time.perf_counter()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert time.perf_counter() - started >= 0.25
    assert read_doc(user_files_dir)["surasura_library"]["version"] == store.versions()["state_version"]
    store.close()


# --- 5. stale exports, crashes, the copy lock ---------------------------------------------------- #

def _export_doc(store):
    doc, _v, _d = store.export_snapshot()
    return ls.finish_doc(doc)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_stale_export_is_ours_and_replaced(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    stale = _export_doc(store)
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    write_manifest(user_files_dir, stale)                      # an older export lands after the newer one
    v = store.versions()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.versions() == v, "recognised as ours: never re-imported"
    assert read_doc(user_files_dir)["surasura_library"]["version"] == v["state_version"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_helper_killed_before_its_bookkeeping(language):
    """Killed after the final rename, before the bookkeeping: the next run adopts the file's stat and does
    nothing more, and the run after it has nothing to do (no loop)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.move([store.ids("soon")[0]], "soon", after_id=store.ids("soon")[3])
    write_manifest(user_files_dir, _export_doc(store))         # the replace happened; the bookkeeping didn't
    v = store.versions()
    mtime = _mtime(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.versions() == v and _mtime(language) == mtime
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_our_export_re_saved_unchanged_by_another_program(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    doc = read_doc(user_files_dir)
    with open(_target(language), "w", encoding="utf-8", newline="\n") as f:   # LF, compact: same content
        json.dump(doc, f, ensure_ascii=False)
    mtime = _mtime(language)
    v = store.versions()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.versions() == v and _mtime(language) == mtime, "adopted: no export, no re-import"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_our_lower_export_edited_by_an_older_version_is_re_imported(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    old = _export_doc(store)
    store.move([store.ids("goal")[0]], "goal", after_id=store.ids("goal")[2])
    now = old["schedule"]["PHASE_1_NOW"]
    now.insert(0, now.pop(5))                                  # 2.4.0's Content Manager moved one row
    write_manifest(user_files_dir, old)
    moved_path = now[0]["physical_path"]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.ids("now")[0] == store.item_id(moved_path), "re-imported, not replaced"
    assert read_doc(user_files_dir)["surasura_library"]["version"] == store.versions()["state_version"]
    store.close()


_JSON_SAVE = """
import sys, json
from app import library_store as ls
lang, data, uf, path = sys.argv[1:5]
doc = json.load(open(ls.manifest_path(uf), encoding="utf-8"))
doc["schedule"]["PHASE_1_NOW"].insert(0, doc["schedule"]["PHASE_2_SOON"].pop(0))
print("saving", flush=True)
ls.json_mode_save(lang, data, uf, doc)
print("saved", flush=True)
"""


def _json_save(language):
    data_dir, user_files_dir = roots(language)
    return subprocess.Popen([sys.executable, "-c", _JSON_SAVE, language, data_dir, user_files_dir, ""],
                            cwd=REPO, env=subprocess_env(), stdout=subprocess.PIPE, text=True)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_save_between_the_look_and_the_replace(language, monkeypatch):
    """Released between the helper's look and its re-stat: the helper leaves its temp unused and the next
    run re-imports the save. Nothing lost."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.move([store.ids("goal")[0]], "goal", after_id=store.ids("goal")[2])
    moved = read_doc(user_files_dir)["schedule"]["PHASE_2_SOON"][0]["physical_path"]
    real = ls._write_temp

    def write_then_save(target, doc):
        out = real(target, doc)
        proc = _json_save(language)                            # a second process saves meanwhile
        assert proc.wait(60) == 0
        return out

    monkeypatch.setattr(ls, "_write_temp", write_then_save)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING
    monkeypatch.setattr(ls, "_write_temp", real)
    leftovers = [f for f in os.listdir(user_files_dir) if f.endswith(".tmp")]
    assert leftovers == [], "a temp left unused is removed"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.ids("now")[0] == store.item_id(moved), "the save was re-imported"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_save_waits_for_the_copy_lock(language):
    """A JSON-mode save attempted while the helper holds the copy lock waits, then lands after the
    replace, and is re-imported. Nothing lost."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.move([store.ids("goal")[0]], "goal", after_id=store.ids("goal")[2])
    lock = ls._copy_lock(store.db_path)
    assert lock.acquire(5, 0.01)
    proc = _json_save(language)
    assert proc.stdout.readline().strip() == "saving"
    time.sleep(0.5)
    assert proc.poll() is None, "the save waits for the copy lock"
    temp, temp_stat = ls._write_temp(_target(language), _export_doc(store))
    os.replace(temp, _target(language))                       # the helper's replace, under its lock
    with store._writing():
        store._set_meta({"last_export_version": store.versions()["state_version"], "last_export_stat": temp_stat})
    lock.close()
    assert proc.wait(60) == 0
    moved = read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"][0]["physical_path"]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.ids("now")[0] == store.item_id(moved)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_move_never_waits_for_the_copy_lock(language):
    store = migrated(language)
    lock = ls._copy_lock(store.db_path)
    assert lock.acquire(5, 0.01)
    ids = store.ids("now")
    started = time.perf_counter()
    store.move([ids[0]], "now", after_id=ids[3])
    # never the copy lock's 5 s wait; 50 ms on this desktop's timed run, a slower test machine more
    assert time.perf_counter() - started < (0.05 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 0.5)
    lock.close()
    store.close()


_TAKE_COPY_LOCK = """
import sys
from app import library_store as ls
lock = ls._copy_lock(sys.argv[1])
print("took" if lock.acquire(3, 0.005) else "never", flush=True)
lock.close()
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_sharing_violation_releases_the_lock_between_retries(language, monkeypatch):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    real = os.replace
    calls = []
    other = []

    def flaky(src, dst):
        if str(dst).endswith(ls.MANIFEST_NAME):
            calls.append(src)
            if len(calls) == 2:                                # another process tries during the backoff
                other.append(subprocess.Popen([sys.executable, "-c", _TAKE_COPY_LOCK, store.db_path], cwd=REPO,
                                              env=subprocess_env(), stdout=subprocess.PIPE, text=True))
                time.sleep(0.01)
            if len(calls) < 4:
                raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert len(calls) == 4 and other[0].communicate(timeout=60)[0].strip() == "took"
    assert read_doc(user_files_dir)["surasura_library"]["version"] == store.versions()["state_version"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_the_last_retry_the_temp_is_kept(language, monkeypatch):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    before = open(_target(language), "rb").read()
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    real = os.replace

    def denied(src, dst):
        if str(dst).endswith(ls.MANIFEST_NAME):
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", denied)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING
    assert open(_target(language), "rb").read() == before, "the target untouched"
    assert [f for f in os.listdir(user_files_dir) if f.endswith(".tmp")], "the temp kept"
    assert store.meta()["last_export_version"] < store.versions()["state_version"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_target_is_a_complete_manifest_at_every_instant(language, monkeypatch):
    """A watcher thread parses the target throughout 1,000 exports. (The replace's back-off is shortened
    here: Windows holds a freshly written file for a moment, and what this proves is atomicity.)"""
    monkeypatch.setattr(ls, "REPLACE_BACKOFF", (0.002, 0.004, 0.008, 0.016, 0.032))
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    helper = ls.Store(store.db_path, language, data_dir, user_files_dir, "helper")
    stop = threading.Event()
    seen, bad = [0], []

    def watch():
        while not stop.is_set():
            try:
                with open(_target(language), "rb") as f:
                    raw = f.read()
            except PermissionError:
                continue
            finally:
                time.sleep(0.002)                               # a reader opens it briefly, as real ones do
            try:
                doc = json.loads(raw.decode("utf-8"))
                assert isinstance(doc["schedule"]["PHASE_1_NOW"], list)
                seen[0] += 1
            except Exception as exc:                             # noqa: BLE001 — any half-file is a failure
                bad.append(repr(exc))

    t = threading.Thread(target=watch)
    t.start()
    ids = store.ids("now")
    exported = 0
    for n in range(1000):
        store.move([ids[0]], "now", after_id=ids[5]) if n % 2 == 0 else store.move([ids[0]], "now")
        exported += ls.export_copy(helper)
    stop.set()
    t.join()
    helper.close()
    assert not bad, bad[:3]
    assert exported == 1000 and seen[0] > 100
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watermark_export_lost_to_a_json_save_is_retried(language, monkeypatch):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.register_reader("connect")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[1])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    events, _gap = store.read_events("connect")
    store.advance_reader("connect", events[-1][0])
    real = ls._write_temp

    def write_then_save(target, doc):
        out = real(target, doc)
        assert _json_save(language).wait(60) == 0
        return out

    monkeypatch.setattr(ls, "_write_temp", write_then_save)
    ls.maintain(language, data_dir, user_files_dir)
    monkeypatch.setattr(ls, "_write_temp", real)
    assert store.meta()["copy_dirty"], "the temp went unused: copy_dirty stays set"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert read_doc(user_files_dir)["surasura_library"]["meta"]["reader:connect"] == events[-1][0]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_old_temps_are_cleaned_up(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    old = _target(language) + ".999.abc.tmp"
    fresh = _target(language) + ".998.def.tmp"
    for p in (old, fresh):
        open(p, "w").close()
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    ls.maintain(language, data_dir, user_files_dir)
    assert not os.path.exists(old) and os.path.exists(fresh)
    store.close()


# --- 6. order; 7. the recorded stat; 8. fingerprints ---------------------------------------------- #

_MAINTAIN = """
import sys
from app import library_store as ls
lang, data, uf = sys.argv[1:4]
sys.exit(ls.maintain(lang, data, uf))
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_helpers_at_once_export_in_version_order(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    for n in range(3):
        store.move([store.ids("now")[n]], "now", after_id=store.ids("now")[6])
    procs = [subprocess.Popen([sys.executable, "-c", _MAINTAIN, language, data_dir, user_files_dir],
                              cwd=REPO, env=subprocess_env()) for _ in range(2)]
    codes = sorted(p.wait(60) for p in procs)
    assert codes in ([0, 3], [0, 0], [0, 5])
    assert read_doc(user_files_dir)["surasura_library"]["version"] == store.versions()["state_version"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_recorded_stat_is_the_replaced_files(language):
    store = migrated(language)
    st = os.stat(_target(language))
    assert store.meta()["last_export_stat"] == f"{st.st_mtime_ns} {st.st_size}"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_replace_waits_for_the_copy_lock_and_never_runs_without_it(language, monkeypatch):
    """Review R5: after the copy lock's wait ran out, the replace went ahead unlocked, reopening the window
    the lock closes (a JSON-mode save landing between the re-stat and the replace). Now it gives up and
    the next run exports."""
    store = migrated(language)
    ids = store.ids("now")
    store.move([ids[0]], "now", after_id=ids[3])
    target = ls.manifest_path(store.user_files_dir)
    before = open(target, "rb").read()
    other = ls._copy_lock(store.db_path)                       # a second handle: refused like another process
    assert other.try_acquire()
    monkeypatch.setattr(ls, "LOCK_TIMEOUT", 0.2)
    try:
        assert ls.export_copy(store) is False
        assert open(target, "rb").read() == before
    finally:
        other.close()
    assert ls.export_copy(store) is True
    assert open(target, "rb").read() != before
    store.close()


def test_fingerprints_ignore_line_ends_bom_indent_and_key_order():
    data = {"schedule": {"PHASE_1_NOW": [{"title": "冒険.srt", "physical_path": "HighPriority/冒険.srt"}]},
            "metadata": {"b": 1, "a": 2}, "surasura_library": {"version": 3}}
    variants = [json.dumps(data, indent=2, ensure_ascii=False).replace("\n", "\r\n"),
                "﻿" + json.dumps(data, ensure_ascii=False),
                json.dumps(data, indent=7, ensure_ascii=True),
                json.dumps(dict(reversed(list(data.items()))), ensure_ascii=False)]
    shas = {ls.content_sha(json.loads(v.encode("utf-8").decode("utf-8-sig"))) for v in variants}
    assert len(shas) == 1


# --- 9. no dialogs; 10. an update staged --------------------------------------------------------- #

def test_the_helper_never_opens_a_dialog():
    import re
    source = open(ls.__file__, encoding="utf-8").read()
    assert not re.search(r"^\s*(import|from)\s+(tkinter|PyQt\w*|pandas)", source, re.M)
    assert "messagebox" not in source
    script = ("import sys\nfrom app import library_store as ls\ncode = ls.main(sys.argv[1:])\n"
              "assert 'tkinter' not in sys.modules and 'pandas' not in sys.modules\nsys.exit(code)")
    env = subprocess_env()
    usage = subprocess.run([sys.executable, "-c", script, "nonsense"], cwd=REPO, env=env, timeout=60)
    assert usage.returncode == ls.EXIT_USAGE
    env.pop("SURASURA_TEST_ROOT", None)                         # an error: STORE_LIVE refuses → 1, no dialog
    failed = subprocess.run([sys.executable, "-c", script, "maintain", "--language", "ja"], cwd=REPO, env=env,
                            timeout=60)
    assert failed.returncode == ls.EXIT_FAILED


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_command_line_runs_maintain(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    out = subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language",
                          language, "--check"], cwd=REPO, env=subprocess_env(), timeout=60)
    assert out.returncode == ls.EXIT_DONE
    assert "surasura_library" in read_doc(user_files_dir)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_update_staged_stops_everything_new(language, monkeypatch, real_store_helper):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    marker = ls.update_staged_path()
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    open(marker, "w").close()
    mtime = _mtime(language)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_BUSY
    assert _mtime(language) == mtime
    spawned = []
    with monkeypatch.context() as m:
        m.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
        assert ls.spawn_maintain(language) is None and spawned == []
    path = touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[33]}.srt")
    assert ls.register_headless(language, path, {"content_key": "x"}, data_dir, user_files_dir) == ls.EXIT_BUSY
    os.utime(marker, (time.time() - 3700, time.time() - 3700))  # an hour old: a crashed update, ignored
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_spawn_maintain_runs_the_helper_detached(language, real_store_helper):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    proc = ls.spawn_maintain(language)
    assert proc is not None and proc.wait(60) == ls.EXIT_DONE
    assert "surasura_library" in read_doc(user_files_dir)
