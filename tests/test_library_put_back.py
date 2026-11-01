"""Fresh library (3.0.1) WP2: *Put back…* a Sorted-again backup (`library_store.put_back_library`), the free-space
preflight (`room_for`), a Put back killed after its commit finished at the next look (`finish_put_back`, P10b), and the
byte check on every copy put back (`_put_back`).

What a wrong answer would cost a learner:
  * his order, tiers, Finished and New arrivals not exactly as they were (a row, an id, a skip lost);
  * the library he has now lost by the Put back (it must go into a backup of its own first, Q1);
  * a card Connect made, or one he deleted, made again (the never-again sets must be the union);
  * a backup damaged by being put back (its bytes must never change), or one from a newer Surasura put back by an
    older one;
  * a crash between the store's write and the files coming back: the library pointing at copies still in the backup.

The libraries are `test_library_reset`'s world (a 2.x upgrade's tiers, a source folder of two shows with real Japanese
and Chinese subtitles, a Remove, hato's drop, an order of his own, Connect's records) under SURASURA_TEST_ROOT.
"""
import hashlib
import json
import os
import shutil
import sqlite3

import pytest

from app import library_store as ls
from app import locks, profile_reset, sources
from tests.test_library_reset import _Killed, _backups, _bytes, _fresh_module_state, _record, _world  # noqa: F401
from tests.test_library_store_support import LANGUAGES, names, schema1_store
from tests.test_sources_scan import _look, _text, _write

TABLES = ("roots", "exclusions", "items", "pieces", "works", "pairings", "trash", "placement_log", "anki_links",
          "anki_changes", "gone")


def _rows(store):
    """Every row of every table a Put back replaces, in a stable order (ids, order, tiers, roots, every exclusion)."""
    out = {}
    for table in TABLES:
        cols = [r[1] for r in store.conn.execute(f"PRAGMA table_info({table})") if r[1] != "content_sha256"]
        out[table] = sorted(tuple(r) for r in store.conn.execute(f"SELECT {', '.join(cols)} FROM {table}"))
    return out


def _content(root):
    """Every file under `root` by its path and bytes (times left out: a put-back .trash gets a new clock)."""
    out = {}
    for where, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(where, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return out


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _made(store):
    return sorted(tuple(r) for r in store.conn.execute("SELECT item_id, word, note_ids FROM made_words"))


def _sorted_again(language, forget_known=False):
    """A library sorted again and read again (new items with new ids), Connect's card made for one of them: what a
    learner has when he asks to put the old one back."""
    store, data_dir, user_files_dir, src, root = _world(language)
    from app.connect import library
    library.record_batch(store, store.ids("now")[0], {names(language)[3]: [111]}, ls._now())
    before = (_rows(store), _content(data_dir), _made(store), store.meta())
    answer = ls.start_fresh(store, forget_known=forget_known)
    for row in store.sources():
        _look(store, language, row["id"], first=True)
    library.record_batch(store, store.ids("now")[0], {names(language)[5]: [222]}, ls._now())
    return store, data_dir, user_files_dir, answer["backup"], before


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_brings_every_row_back_and_sets_the_library_now_aside_in_a_backup_of_its_own(language):
    """SA → PB-s: every replaced table equal row for row to before the Sort again (ids, order, tiers, roots, every
    exclusion); the data folder's files back; the never-again sets the union (the card made since stays never made
    again); a new store_id and an epoch above both; a fresh JSON copy naming it. The library as it was just before
    is in a put-back-over backup, which itself can be put back."""
    store, data_dir, user_files_dir, backup, (rows, content, made, meta) = _sorted_again(language)
    with store:
        now_rows, now_made, now_meta = _rows(store), _made(store), store.meta()
        answer = ls.put_back_library(store, backup)
        assert _rows(store) == rows
        assert _content(data_dir) == content
        assert set(made) <= set(_made(store)) and set(now_made) <= set(_made(store))
        after = store.meta()
        assert after["store_id"] not in (meta["store_id"], now_meta["store_id"])
        assert int(after["epoch"]) > max(int(meta["epoch"]), int(now_meta["epoch"]))
        assert ls.PUT_BACK_PENDING not in after
        with open(ls.manifest_path(user_files_dir), encoding="utf-8") as f:
            assert json.load(f)["surasura_library"]["store_id"] == after["store_id"]
        over = _record(answer["backup"])
        assert over["kind"] == ls.RESET_KIND_OVER and over["status"] == "done"
        assert over["put_back_of"] == os.path.basename(backup)
        assert _record(backup)["status"] == "put-back"
        listed = [(b["kind"], b["folder"]) for b in profile_reset.backups()]
        assert (profile_reset.PUT_BACK_OVER, answer["backup"]) in listed
        assert all(folder != backup for _kind, folder in listed)           # put back: no longer offered
        ls.put_back_library(store, answer["backup"])                       # Put back can itself be put back
        assert _rows(store) == now_rows


def test_what_comes_back_into_the_data_folders_trash_gets_a_new_30_day_clock():
    """A removed episode's copy waited in the backup: back in `data/<lang>/.trash`, its clock starts again, so the
    next clean-up never purges it at once for the days it spent in the backup."""
    import time
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    trashed = [m["to"] for m in _record(backup)["moves"] if os.path.basename(m["from"]) == ".trash"][0]
    old = time.time() - 40 * 86400
    for where, _d, files in os.walk(trashed):
        for n in files:
            os.utime(os.path.join(where, n), (old, old))
    with store:
        ls.put_back_library(store, backup)
    files = [os.path.join(w, n) for w, _d, fs in os.walk(os.path.join(data_dir, ".trash")) for n in fs]
    assert files and all(os.path.getmtime(f) > time.time() - 600 for f in files)


def test_ids_are_never_reused_after_a_put_back():
    """The sequences stand at the higher of the two libraries: the next item is newer than both."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    with store:
        highest = store.conn.execute("SELECT MAX(id) FROM items").fetchone()[0]
        ls.put_back_library(store, backup)
        a, _b = _SHOWS_PAIR("ja")
        src = os.path.join(os.environ["SURASURA_TEST_ROOT"], "elsewhere", "driveB")
        _write(os.path.join(src, a, f"{a} - 09.srt"), _text("ja", 9))
        root = store.add_source(src)
        ids = _look(store, "ja", root, first=True)["ids"]
        assert ids and min(ids) > highest


def _SHOWS_PAIR(language):
    from tests.test_sources_scan import _SHOWS
    return _SHOWS[language]


def test_a_30_backup_without_kind_or_version_and_one_made_with_forget_my_known_words_puts_back_the_library_only():
    """3.0's records (no `kind`, no `app_version`) are Sorted-again backups; one made with *Also forget my known
    words* puts back the library and leaves today's known words as they are (P9): its copy stays in the backup."""
    store, data_dir, user_files_dir, backup, (rows, _c, _m, _meta) = _sorted_again("zh", forget_known=True)
    record = _record(backup)
    for key in ("kind", "app_version"):
        record.pop(key, None)
    ls._write_record(backup, record)
    known = os.path.join(user_files_dir, "KnownWord.json")
    today = _bytes(known)
    assert [b for b in profile_reset.backups() if b["folder"] == backup][0]["forgot_known"]
    with store:
        ls.put_back_library(store, backup)
        assert _rows(store) == rows
    assert _bytes(known) == today and os.path.exists(os.path.join(backup, "KnownWord.json"))


def test_a_backup_from_an_older_store_is_brought_up_to_date_on_a_scratch_copy_and_its_bytes_never_change(
        monkeypatch, tmp_path):
    """A copy older than this program's schema is migrated on a scratch copy beside the store; the backup's file is
    byte for byte what it was, and no scratch is left."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    record = _record(backup)
    with monkeypatch.context() as patched:                       # a 2.5–2.7 store, made in a root of its own
        patched.setenv("SURASURA_TEST_ROOT", str(tmp_path))
        from tests.test_library_store_support import library as lib
        _d, _u, doc = lib("ja", shows=1, episodes=2)
        _d1, _u1, old_db = schema1_store("ja", doc)
        old_items = sqlite3.connect(old_db).execute("SELECT COUNT(*) FROM items").fetchone()[0]
    for suffix in ("-wal", "-shm"):
        if os.path.exists(old_db + suffix):
            sqlite3.connect(old_db).execute("PRAGMA wal_checkpoint(TRUNCATE)").close()
    shutil.copyfile(old_db, record["db_copy"])
    before = _sha(record["db_copy"])
    with store:
        ls.put_back_library(store, backup)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == old_items
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == ls.STORE_SCHEMA
    assert _sha(record["db_copy"]) == before
    assert not [n for n in os.listdir(os.path.dirname(store.db_path)) if ".put-back" in n]


@pytest.mark.parametrize("how", ["schema", "record"])
def test_a_backup_from_a_newer_surasura_is_refused_update_first_and_nothing_changes(how):
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    record = _record(backup)
    if how == "schema":
        conn = sqlite3.connect(record["db_copy"])
        conn.execute(f"PRAGMA user_version = {ls.STORE_SCHEMA + 1}")
        conn.close()
    else:
        ls._write_record(backup, dict(record, app_version="99.0.0"))
    with store:
        rows, content = _rows(store), _content(data_dir)
        with pytest.raises(ls.ResetRefused) as e:
            ls.put_back_library(store, backup)
        assert "update first" in e.value.reason
        assert _rows(store) == rows and _content(data_dir) == content
    assert len(_backups(user_files_dir)) == 1                  # no backup of the library now was made


@pytest.mark.parametrize("damage", ["part", "record", "status", "copy"])
def test_a_backup_that_isnt_whole_is_refused_and_nothing_changes(damage):
    """A part deleted by hand, a record that can't be read, a backup that never finished, a store copy damaged:
    refused before anything moves."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    record = _record(backup)
    if damage == "part":
        shutil.rmtree([m["to"] for m in record["moves"] if m["step"] == "data"][0])
    elif damage == "record":
        with open(os.path.join(backup, ls.RESET_RECORD), "w", encoding="utf-8") as f:
            f.write("{ half")
    elif damage == "status":
        ls._write_record(backup, dict(record, status="undone"))
    else:
        with open(record["db_copy"], "r+b") as f:
            f.seek(0)
            f.write(b"not a database at all, sorry")
    with store:
        rows, content = _rows(store), _content(data_dir)
        with pytest.raises(ls.ResetRefused):
            ls.put_back_library(store, backup)
        assert _rows(store) == rows and _content(data_dir) == content


def test_too_little_free_space_refuses_sort_again_and_put_back_naming_how_much(monkeypatch):
    """P3: 2 × the store + 100 MB (+ any data entry on another drive), else refused with the megabytes and drive."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    need = ls.room_for(store)
    assert need >= 2 * os.path.getsize(store.db_path) + ls.ROOM_SPARE
    usage = shutil.disk_usage(user_files_dir)
    with monkeypatch.context() as patched:
        patched.setattr(shutil, "disk_usage", lambda _p: usage._replace(free=need - 1024 * 1024))
        with store:
            rows = _rows(store)
            with pytest.raises(ls.ResetRefused) as e:
                ls.put_back_library(store, backup)
            assert "MB free" in e.value.reason and _rows(store) == rows
            with pytest.raises(ls.ResetRefused):
                ls.start_fresh(store)
            patched.setattr(shutil, "disk_usage", lambda _p: usage._replace(free=need))
            ls.put_back_library(store, backup)


def test_connect_is_taken_for_the_whole_put_back_and_one_running_refuses_it():
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    with store:
        held = locks.take("connect", "making cards")
        try:
            with pytest.raises(ls.ResetRefused) as e:
                ls.put_back_library(store, backup)
            assert e.value.reason == ls.RESET_CONNECT
        finally:
            held.release()
        seen = []
        ls.put_back_library(store, backup, _step=lambda name: seen.append(locks.held_in_process("connect")))
        assert seen and all(seen)


@pytest.mark.parametrize("step", ["scratch", "folder", "backup", "manifest", "cache", "data"])
def test_an_error_before_the_commit_puts_everything_back_and_the_library_is_as_it_was(step):
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    with store:
        rows, content, meta = _rows(store), _content(data_dir), store.meta()

        def fail(name):
            if name == step:
                raise RuntimeError("the disk went away")
        with pytest.raises(Exception):
            ls.put_back_library(store, backup, _step=fail)
        assert _rows(store) == rows and _content(data_dir) == content
        assert store.meta()["store_id"] == meta["store_id"]
        assert ls.PUT_BACK_PENDING not in store.meta()
        assert "old" not in [r[1] for r in store.conn.execute("PRAGMA database_list")]
    assert _record(backup)["status"] in ("done", "written")          # still there to put back
    assert not [n for n in os.listdir(os.path.dirname(store.db_path)) if ".put-back" in n]


@pytest.mark.parametrize("step", ["committed", "back:" + os.path.join("data", "Library")])
def test_a_put_back_killed_after_its_commit_is_finished_at_the_next_look_before_it_reads_a_folder(step):
    """P10b: the store already is the old library, so forward is the only consistent way: the next look first moves
    the backup's files back (`finish_put_back`), clears the mark, exports a fresh copy, then reads the folders."""
    store, data_dir, user_files_dir, backup, (rows, content, _m, _meta) = _sorted_again("ja")

    def kill(name):
        if name == step:
            raise _Killed(name)
    with store:
        with pytest.raises(_Killed):
            ls.put_back_library(store, backup, _step=kill)
        locks._registry.clear()                                 # the OS lets the killed process's locks go
        assert store.meta()[ls.PUT_BACK_PENDING] == os.path.basename(backup)
        assert _rows(store) == rows
        sources._LOOKED.clear()
        calls = []
        real = ls.finish_put_back
        ls.finish_put_back = lambda s: calls.append(_content(data_dir)) or real(s)
        try:
            for row in store.sources():
                _look(store, "ja", row["id"])
        finally:
            ls.finish_put_back = real
        assert calls                                              # before the look read anything
        assert ls.PUT_BACK_PENDING not in store.meta()
        assert _record(backup)["status"] == "put-back"
        assert set(content) <= set(_content(data_dir))
        assert ls.finish_put_back(store) is None                 # one meta read when there is none


def test_a_kill_before_the_commit_leaves_the_library_as_it_was_and_a_stopped_backup_to_put_back():
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")

    def kill(name):
        if name == "data":
            raise _Killed(name)
    with store:
        rows = _rows(store)
        with pytest.raises(_Killed):
            ls.put_back_library(store, backup, _step=kill)
        store.conn.execute("ROLLBACK") if store.conn.in_transaction else None
        store.conn.execute("DETACH DATABASE old") if "old" in [r[1] for r in store.conn.execute(
            "PRAGMA database_list")] else None
        assert _rows(store) == rows                               # nothing written
    stopped = [b for b in profile_reset.backups() if b["stopped"]]
    assert len(stopped) == 1 and stopped[0]["kind"] == profile_reset.PUT_BACK_OVER


def test_a_copy_put_back_whose_bytes_dont_match_is_never_left_and_raises(tmp_path, monkeypatch):
    """F4: `_put_back`'s copy fallback checks every file it copies: a bad copy is removed again, never left in the
    library as if whole."""
    src, dst = tmp_path / "library", tmp_path / "backup"
    (dst / "Library").mkdir(parents=True)
    (dst / "Library" / "a.srt").write_text(_text("ja", 1), encoding="utf-8")
    (src / "Library").mkdir(parents=True)                         # something there: copied, never renamed
    real = shutil.copy2

    def bad(a, b, **kw):
        real(a, b, **kw)
        with open(b, "ab") as f:
            f.write(b"!")
    with monkeypatch.context() as patched:
        patched.setattr(shutil, "copy2", bad)
        with pytest.raises(OSError):
            ls._put_back(str(dst), str(src))
    assert not (src / "Library" / "a.srt").exists()
    ls._put_back(str(dst), str(src))
    assert (src / "Library" / "a.srt").read_text(encoding="utf-8") == _text("ja", 1)


def test_sort_again_twice_then_put_back_the_first_brings_back_the_library_before_both():
    store, data_dir, user_files_dir, first, (rows, content, _m, _meta) = _sorted_again("ja")
    with store:
        ls.start_fresh(store)
        ls.put_back_library(store, first)
        assert _rows(store) == rows and _content(data_dir) == content


def test_new_records_name_their_kind_and_the_program_that_made_them():
    store, data_dir, user_files_dir, src, root = _world("ja")
    with store:
        folder = ls.start_fresh(store)["backup"]
    record = _record(folder)
    assert record["kind"] == ls.RESET_KIND_SORT and record["app_version"]


# --- review round 1 (the register's rows) ------------------------------------------------------------------------- #

def test_put_it_back_undoes_a_sort_again_a_kill_stopped_before_its_write():
    """Adversary #7: *Put it back* for a backup stopped part way (the library still in the store, some of its
    folder's entries moved): every recorded move undone, newest first; the record says undone; the library as it was."""
    store, data_dir, user_files_dir, src, root = _world("ja")

    def kill(name):
        if name == "data":
            raise _Killed(name)
    with store:
        rows, content = _rows(store), _content(data_dir)
        with pytest.raises(_Killed):
            ls.start_fresh(store, _step=kill)
        locks._registry.clear()
        (folder,) = _backups(user_files_dir)
        assert _record(folder)["status"] == "started"
        assert [b for b in profile_reset.backups() if b["folder"] == folder][0]["stopped"]
        ls.put_back_library(store, folder)
        assert _rows(store) == rows and _content(data_dir) == content
    assert _record(folder)["status"] == "undone"
    assert not [b for b in profile_reset.backups() if b["folder"] == folder]


def test_a_sort_again_killed_after_its_write_but_before_its_record_is_a_whole_backup():
    """Adversary #8: a record left `started` after the commit (the store already holds a new library): never *Put
    it back* (that would pour the old folder's copies into the new library), but a whole backup put back as any."""
    store, data_dir, user_files_dir, src, root = _world("ja")
    with store:
        rows = _rows(store)
        real = ls._write_record

        def no_written(folder, record):
            if record.get("status") == "written":
                raise _Killed("written")
            real(folder, record)
        ls._write_record = no_written
        try:
            with pytest.raises(_Killed):
                ls.start_fresh(store)
        finally:
            ls._write_record = real
        locks._registry.clear()
        (folder,) = _backups(user_files_dir)
        assert _record(folder)["status"] == "started"
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0     # the write committed
        ls.put_back_library(store, folder)
        assert _rows(store) == rows


def test_a_look_waits_while_a_put_back_still_owes_its_files_and_the_helper_holds_the_store():
    """Adversary #9: the files not back yet and the maintenance lock held elsewhere: the look answers busy instead
    of reading a folder whose copies are missing (it would call the library emptied)."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")

    def kill(name):
        if name == "committed":
            raise _Killed(name)
    with store:
        with pytest.raises(_Killed):
            ls.put_back_library(store, backup, _step=kill)
        locks._registry.clear()
        held = ls.MaintenanceLock(store.db_path)
        assert held.try_acquire()
        try:
            assert ls.finish_put_back(store) is False
            row = store.sources()[0]
            assert sources.scan(store, "ja", row["id"])["busy"] is True
        finally:
            held.close()
        assert ls.finish_put_back(store) is True and ls.finish_put_back(store) is None


def test_a_sort_again_while_a_put_back_still_owes_its_files_brings_them_back_first():
    """Adversary #18: the one write rewrites meta: the files owed come back before it, never stranded."""
    store, data_dir, user_files_dir, backup, (rows, content, _m, _meta) = _sorted_again("ja")

    def kill(name):
        if name == "committed":
            raise _Killed(name)
    with store:
        with pytest.raises(_Killed):
            ls.put_back_library(store, backup, _step=kill)
        locks._registry.clear()
        ls.start_fresh(store)
        assert _record(backup)["status"] == "put-back"
        assert ls.PUT_BACK_PENDING not in store.meta()


def test_files_that_didnt_come_back_keep_the_backup_listed_and_a_second_put_back_brings_them():
    """Adversary #19: a Put back whose files didn't all come back stays listed (*files-back*, what's missing
    named); putting it back again brings the rest."""
    store, data_dir, user_files_dir, backup, (rows, content, _m, _meta) = _sorted_again("ja")
    real = ls._put_back
    calls = []

    def flaky(dst, src):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError(13, "held open", dst)
        real(dst, src)
    with store:
        ls._put_back = flaky
        try:
            ls.put_back_library(store, backup)
        finally:
            ls._put_back = real
        record = _record(backup)
        assert record["status"] == "files-back" and record["not_put_back"]
        assert [b for b in profile_reset.backups() if b["folder"] == backup][0]["stopped"]
        ls.put_back_library(store, backup)
        assert _record(backup)["status"] == "put-back" and _content(data_dir) == content


def test_a_put_back_owed_whose_record_cant_be_read_lets_the_looks_go_on():
    """Adversary #25: nothing can be read to bring back: the mark goes (said in the log), never a busy look for ever."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")

    def kill(name):
        if name == "committed":
            raise _Killed(name)
    with store:
        with pytest.raises(_Killed):
            ls.put_back_library(store, backup, _step=kill)
        locks._registry.clear()
        with open(os.path.join(backup, ls.RESET_RECORD), "w", encoding="utf-8") as f:
            f.write("{ half")
        assert ls.finish_put_back(store) is True
        assert ls.PUT_BACK_PENDING not in store.meta() and ls.finish_put_back(store) is None


def test_the_room_needed_is_two_of_the_store_and_the_spare_exactly():
    """Mutant S01: P3's number, to the byte, for a library whose data folder is on the backup's drive."""
    store, data_dir, user_files_dir, backup, _before = _sorted_again("ja")
    size = sum(os.path.getsize(store.db_path + s) for s in ("", "-wal") if os.path.exists(store.db_path + s))
    assert ls.room_for(store) == 2 * size + ls.ROOM_SPARE


def test_a_never_again_row_only_the_backup_holds_comes_back_with_it():
    """Mutant S09: the union is both ways — a row the library now lacks (a store rebuilt since) comes back from the
    backup's copy."""
    store, data_dir, user_files_dir, backup, (_r, _c, made, _meta) = _sorted_again("ja")
    with store:
        with store._writing():
            store.conn.execute("DELETE FROM made_words")
        ls.put_back_library(store, backup)
        assert set(made) <= set(_made(store))
