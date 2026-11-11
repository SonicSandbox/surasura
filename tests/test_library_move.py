"""3.0.1 — *Move my library* (`app/library_move.py`; Controlled folder access, QUESTIONS.md, Sonic 2026-11-10).

What a wrong answer would cost, worst first (CLAUDE.md §4: user data is sacred):
  * the old library changed or lost — a move that deletes or rewrites anything in it, or switches before the copy is
    whole and checked;
  * the library's order lost — the store rebuilt from a stale JSON copy (a blocked library's copy can't be written)
    instead of carried whole;
  * a half copy used as the library, or left behind as clutter the next try refuses;
  * a move into a folder that already holds something (it would mix two libraries), into the old folder itself, or
    into another folder Windows protects;
  * an Undo that loses what the new folder got since.

The library is the test root (an installed program's library.json names it: `installed`, the one switch path_utils
reads), with real Japanese and Chinese content, known words and a built store (`tests/test_library_store_support`);
the new folder is in a stand-in profile under tmp_path. Registry reads are faked (`tests/test_cfa.fake_registry`)."""
import hashlib
import json
import os
import shutil
import sqlite3
import stat

import pytest

from app import cfa, library_move, locks, path_utils
from app import library_store as ls
from app.services import first_run
from tests.test_cfa import fake_registry
from tests.test_library_store_support import library as build_library, write_manifest

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name, sub in (("USERPROFILE", "profile"), ("HOME", "profile"), ("APPDATA", "Roaming"),
                      ("LOCALAPPDATA", "Local"), ("XDG_DATA_HOME", "Roaming")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    (tmp_path / "profile").mkdir()
    fake_registry(monkeypatch, switch=0)            # Defender never asked for real
    return tmp_path


def _root():
    return os.environ["SURASURA_TEST_ROOT"]


def installed(monkeypatch, library, tmp_path):
    """An installed program: library.json (in the installer's shape) names its folder and `library`, and
    path_utils reads it as a frozen program does."""
    program = str(tmp_path / "Programs" / "Surasura")
    os.makedirs(program, exist_ok=True)
    note = os.path.join(path_utils.local_data_root(), path_utils.LIBRARY_NOTE)
    os.makedirs(os.path.dirname(note), exist_ok=True)
    with open(note, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "install": program, "library": library}, f)
    monkeypatch.setattr(path_utils, "installed_library", lambda: path_utils._read_library_note(note, program))
    return program


def _note():
    with open(library_move.note_path(), encoding="utf-8") as f:
        return json.load(f)


def _real_library():
    """The test root as a used library: both languages' content and stores, known words, a report, a word list in
    CRLF, a read-only file, an empty folder and a nested one, file names in Japanese and Chinese."""
    root = _root()
    for lang in ("ja", "zh"):
        data_dir, user_files_dir, doc = build_library(lang, shows=2, episodes=3)
        write_manifest(user_files_dir, doc)
        assert ls.maintain(lang, data_dir, user_files_dir) == ls.EXIT_DONE
        shutil.copy2(os.path.join(RESOURCES, lang, sorted(os.listdir(os.path.join(RESOURCES, lang)))[0]),
                     os.path.join(user_files_dir, "源" if lang == "zh" else "元.txt"))
    with open(os.path.join(root, "User Files", "ja", "IgnoreList.txt"), "wb") as f:
        f.write("# 無視する言葉\r\nこれ\r\nそれ\r\n".encode("utf-8"))
    os.makedirs(os.path.join(root, "results"), exist_ok=True)
    with open(os.path.join(root, "results", "reading_list.csv"), "w", encoding="utf-8") as f:
        f.write("Word,Frequency\n勉強,12\n")
    locked = os.path.join(root, "User Files", "ja", "GraduatedList.txt")
    with open(locked, "w", encoding="utf-8") as f:
        f.write("卒業\n")
    os.chmod(locked, stat.S_IREAD)
    os.makedirs(os.path.join(root, "data", "ja", "LowPriority", "空のフォルダ"), exist_ok=True)
    os.makedirs(os.path.join(root, "User Files", "ja", ".trash", "古い"), exist_ok=True)
    with open(os.path.join(root, "notes of mine.txt"), "w", encoding="utf-8") as f:
        f.write("not Surasura's: never copied, never touched\n")
    return root


def _tree(folder, parts=library_move.PARTS):
    """{relative path: (sha256, size, mtime_ns)} of every file, and every folder (None), under `parts`."""
    out = {}
    for part in parts:
        top = os.path.join(folder, part)
        if not os.path.exists(top):
            continue
        for here, dirs, names in os.walk(top):
            for d in dirs:
                out[os.path.relpath(os.path.join(here, d), folder)] = None
            for n in names:
                path = os.path.join(here, n)
                with open(path, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
                st = os.stat(path)
                out[os.path.relpath(path, folder)] = (digest, st.st_size, st.st_mtime_ns)
    return out


def _whole(folder):
    """Every file in the library's own parts and loose beside them (a test root also holds the stores' `index` and the
    local data folder: those are the stores', checked by their rows)."""
    out = {n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))}
    for part in library_move.PARTS:
        for h, _d, names in os.walk(os.path.join(folder, part)):
            out |= {os.path.relpath(os.path.join(h, n), folder) for n in names}
    return out


def _rows(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        items = conn.execute("SELECT id, rel_path, tier, ord FROM items ORDER BY id").fetchall()
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()
    return items, meta


def _db(library, lang):
    return ls.library_db_path(lang, os.path.join(library, "data", lang))


@pytest.fixture
def chmod_back():
    yield
    for here, _d, names in os.walk(_root()):
        for n in names:
            try:
                os.chmod(os.path.join(here, n), stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass


# --- the move ---------------------------------------------------------------------------------------------------

def test_a_used_library_moves_whole_with_its_store_and_the_old_folder_is_left_exactly_as_it_was(
        tmp_path, monkeypatch, chmod_back):
    old = _real_library()
    program = installed(monkeypatch, old, tmp_path)
    before, everything = _tree(old), _whole(old)
    stores = {lang: _rows(_db(old, lang)) for lang in ("ja", "zh")}
    new = str(tmp_path / "profile" / "Surasura")
    ticks = []

    result = library_move.move(new, progress=lambda done, total: ticks.append((done, total)))

    assert result["status"] == "done", result
    assert result["files"] == len([v for v in before.values() if v]) and ticks[-1] == (result["files"],) * 2
    # every file and folder there, byte for byte, with its times (the store knows its JSON copy by its stat)
    assert _tree(new) == before
    assert not os.path.exists(os.path.join(new, "notes of mine.txt")), "only Surasura's own folders are copied"
    # the old folder: nothing changed, nothing removed, nothing added
    assert _tree(old) == before and _whole(old) == everything
    # the one switch, in the installer's shape: its install kept
    assert _note() == {"version": 1, "install": program, "library": new}
    assert path_utils.installed_library() == new
    # the stores carried whole under their new names (never rebuilt from the copy: the same store_id and rows)
    for lang in ("ja", "zh"):
        items, meta = _rows(_db(new, lang))
        assert items == stores[lang][0] and meta["store_id"] == stores[lang][1]["store_id"]
        assert ls.maintain(lang, os.path.join(new, "data", lang), os.path.join(new, "User Files", lang)) in (
            ls.EXIT_DONE, ls.EXIT_NOTHING)
        assert _rows(_db(new, lang))[1]["store_id"] == meta["store_id"], "its copy was its own: no re-import"
        assert _rows(_db(old, lang)) == stores[lang], "the old store is untouched"
    record = library_move.read_record()
    assert record["from"] == old and record["to"] == new and record["undone"] is None
    assert first_run.read_note()["libraries"][first_run._key(new)]["library"] == new
    assert not [n for n in os.listdir(tmp_path / "profile") if ".moving-" in n], "no half copy left"


def test_the_store_carries_an_order_its_blocked_json_copy_never_got(tmp_path, monkeypatch):
    # Under Controlled folder access the store (in the local data folder) keeps saving while its JSON copy in the
    # blocked library can't be written: rebuilding from that copy would lose the newest order.
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    db = _db(old, "ja")
    conn = sqlite3.connect(db)
    with conn:
        first = conn.execute("SELECT id FROM items ORDER BY ord LIMIT 1").fetchone()[0]
        conn.execute("UPDATE items SET ord = ord + 1000 WHERE id = ?", (first,))
        conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'state_version'")
    conn.close()
    expected = _rows(db)
    new = str(tmp_path / "profile" / "Surasura")
    assert library_move.move(new)["status"] == "done"
    assert _rows(_db(new, "ja")) == expected


def test_a_database_already_under_the_new_name_is_set_aside_never_deleted(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    new = str(tmp_path / "profile" / "Surasura")
    stale = _db(new, "ja")
    os.makedirs(os.path.dirname(stale), exist_ok=True)
    with open(stale, "wb") as f:
        f.write(b"an earlier library's store at this path")
    assert library_move.move(new)["status"] == "done"
    kept = [n for n in os.listdir(os.path.dirname(stale)) if n.startswith(os.path.basename(stale) + ".before-move-")]
    assert len(kept) == 1
    with open(os.path.join(os.path.dirname(stale), kept[0]), "rb") as f:
        assert f.read() == b"an earlier library's store at this path"


def test_a_library_never_made_yet_moves_by_pointing_the_note_at_an_empty_new_folder(tmp_path, monkeypatch):
    old = str(tmp_path / "Documents" / "Surasura")            # a new install's library, never made (CFA refused it)
    installed(monkeypatch, old, tmp_path)
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["status"] == "done" and result["files"] == 0
    assert os.path.isdir(new) and os.listdir(new) == [] and not os.path.exists(old)
    assert _note()["library"] == new


def test_an_empty_folder_waiting_at_the_target_is_used(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    new = tmp_path / "profile" / "Surasura"
    new.mkdir()
    assert library_move.move(str(new))["status"] == "done" and _tree(str(new)) == _tree(old)


def test_the_default_target_is_the_users_own_folder(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    result = library_move.move()
    assert result["status"] == "done" and result["new"] == os.path.join(str(tmp_path / "profile"), "Surasura")


# --- Undo ---------------------------------------------------------------------------------------------------------

def test_undo_points_back_at_the_old_folder_and_keeps_the_copy_with_what_it_got_since(tmp_path, monkeypatch):
    old = _real_library()
    program = installed(monkeypatch, old, tmp_path)
    before = _tree(old)
    new = str(tmp_path / "profile" / "Surasura")
    assert library_move.move(new)["status"] == "done"
    assert library_move.can_undo() is not None
    with open(os.path.join(new, "User Files", "ja", "since.txt"), "w", encoding="utf-8") as f:
        f.write("移動のあとで\n")

    result = library_move.undo()

    assert result["status"] == "done", result
    assert _note() == {"version": 1, "install": program, "library": old} and path_utils.installed_library() == old
    assert _tree(old) == before
    aside = result["aside"]
    assert aside and os.path.basename(aside).startswith("Surasura (moved back ") and not os.path.exists(new)
    with open(os.path.join(aside, "User Files", "ja", "since.txt"), encoding="utf-8") as f:
        assert f.read() == "移動のあとで\n"
    assert library_move.read_record()["undone"] and library_move.can_undo() is None
    assert library_move.undo()["status"] == "refused", "one Undo"
    # and the move can be made again: the target is free
    assert library_move.move(new)["status"] == "done"


def test_undo_is_refused_once_library_json_names_another_folder(tmp_path, monkeypatch):
    old = _real_library()
    program = installed(monkeypatch, old, tmp_path)
    new = str(tmp_path / "profile" / "Surasura")
    assert library_move.move(new)["status"] == "done"
    with open(library_move.note_path(), "w", encoding="utf-8") as f:   # Setup run again with another folder
        json.dump({"version": 1, "install": program, "library": str(tmp_path / "其他")}, f)
    assert library_move.can_undo() is None and library_move.undo()["reason"] == "none"
    assert os.path.isdir(new)


def test_an_undo_that_cant_rename_the_copy_still_points_back_and_says_where_it_stays(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    new = str(tmp_path / "profile" / "Surasura")
    assert library_move.move(new)["status"] == "done"

    def held(_a, _b):
        raise PermissionError(32, "The process cannot access the file because it is being used", new)
    monkeypatch.setattr(library_move.os, "rename", held)
    result = library_move.undo()
    assert result["status"] == "done" and result["aside"] is None and new in result["words"]
    assert _note()["library"] == old and os.path.isdir(new)


# --- refused: nothing made, nothing changed ---------------------------------------------------------------------------

def _nothing_changed(old, before, note, new, made=False):
    assert _tree(old) == before and _note() == note
    assert os.path.exists(new) == made
    assert not [n for n in os.listdir(os.path.dirname(new)) if ".moving-" in n]
    assert library_move.read_record() is None


def test_a_target_already_holding_files_is_refused_and_left_alone(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    new = tmp_path / "profile" / "Surasura"
    new.mkdir()
    (new / "家計簿.xlsx").write_bytes(b"someone else's file")
    result = library_move.move(str(new))
    assert result["status"] == "refused" and result["reason"] == "not_empty" and str(new) in result["words"]
    _nothing_changed(old, before, note, str(new), made=True)
    assert os.listdir(new) == ["家計簿.xlsx"]


@pytest.mark.parametrize("where", ["inside", "parent"])
def test_a_target_inside_the_library_or_holding_it_is_refused(tmp_path, monkeypatch, where):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    new = os.path.join(old, "results", "Surasura") if where == "inside" else os.path.dirname(old)
    result = library_move.move(new)
    assert result["status"] == "refused" and result["reason"] in ("inside", "not_empty")
    assert _tree(old) == before and _note() == note and library_move.read_record() is None


def test_a_target_windows_protects_too_is_refused(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    fake_registry(monkeypatch, switch=1, documents=str(tmp_path / "profile" / "Documents"))
    new = str(tmp_path / "profile" / "Documents" / "Surasura")
    os.makedirs(os.path.dirname(new))
    result = library_move.move(new)
    assert result["status"] == "refused" and result["reason"] == "protected"
    _nothing_changed(old, before, note, new)


def test_a_portable_or_source_run_moves_nothing(monkeypatch):
    monkeypatch.setattr(path_utils, "installed_library", lambda: None)
    assert library_move.move()["reason"] == "not_installed"


def test_another_surasura_program_running_is_waited_for_then_named(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    monkeypatch.setattr(locks, "running_others", lambda: [{"kind": "cli", "pid": 4242}])
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new, wait=0.05)
    assert result["status"] == "refused" and "command line" in result["words"]
    _nothing_changed(old, before, note, new)


def test_an_update_waiting_moves_nothing(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    monkeypatch.setattr(ls, "update_staged", lambda *a, **k: True)
    assert library_move.move(str(tmp_path / "profile" / "Surasura"))["reason"] == "update"


def test_too_little_room_is_said_before_anything_is_copied(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    monkeypatch.setattr(library_move, "_free", lambda _folder: 1024)
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["reason"] == "room" and "MB" in result["words"]
    _nothing_changed(old, before, note, new)


def test_a_link_to_another_folder_is_refused_before_anything_is_copied(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    elsewhere = tmp_path / "外の箱"
    elsewhere.mkdir()
    try:
        os.symlink(str(elsewhere), os.path.join(old, "data", "ja", "リンク"), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this PC can't make a folder link without admin")
    before, note = _tree(old), _note()
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["reason"] == "link"
    _nothing_changed(old, before, note, new)


# --- stopped part way: the copy removed, nothing switched -----------------------------------------------------------

def test_a_cancel_between_files_removes_the_copy_and_switches_nothing(tmp_path, monkeypatch, chmod_back):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    seen = []
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new, progress=lambda done, total: seen.append(done), cancel=lambda: len(seen) >= 3)
    assert result["status"] == "cancelled" and old in result["words"]
    _nothing_changed(old, before, note, new)


def test_a_copy_that_doesnt_match_its_original_stops_the_move(tmp_path, monkeypatch, chmod_back):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()
    real, calls = library_move._copy_one, []

    def bad(src, dst):
        calls.append(src)
        read, back = real(src, dst)
        return (read, "0" * 64) if len(calls) == 4 else (read, back)
    monkeypatch.setattr(library_move, "_copy_one", bad)
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["status"] == "failed" and result["reason"] == "mismatch" and calls[3] in result["words"]
    _nothing_changed(old, before, note, new)


def test_an_original_that_changes_while_it_is_copied_stops_the_move(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    note = _note()
    target = os.path.join(old, "results", "reading_list.csv")
    real = library_move.shutil.copystat

    def meanwhile(src, dst, **kw):
        real(src, dst, **kw)
        if src == target:                       # another program saved it just as it was copied
            with open(target, "a", encoding="utf-8") as f:
                f.write("新しい,1\n")
    monkeypatch.setattr(library_move.shutil, "copystat", meanwhile)
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["reason"] == "changed" and target in result["words"]
    assert _note() == note and not os.path.exists(new)


def test_a_store_that_cant_be_copied_stops_the_move_after_the_files(tmp_path, monkeypatch, chmod_back):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()

    def broken(_old, _new):
        raise sqlite3.DatabaseError("disk I/O error")
    monkeypatch.setattr(library_move, "_copy_db", broken)
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["status"] == "failed" and result["reason"] == "store"
    _nothing_changed(old, before, note, new)


def test_a_library_json_that_cant_be_written_switches_nothing(tmp_path, monkeypatch, chmod_back):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before, note = _tree(old), _note()

    def refused(*_a, **_k):
        raise PermissionError(13, "Access is denied", library_move.note_path())
    monkeypatch.setattr(library_move, "_write_note", refused)
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["status"] == "failed" and result["reason"] == "note"
    _nothing_changed(old, before, note, new)


def test_the_copy_check_finds_a_real_difference(tmp_path):
    # `_copy_one` reads the copy back from disk: what it returns is the copy's own hash, not the bytes it wrote.
    src = tmp_path / "元.txt"
    src.write_text("こんにちは\r\n", encoding="utf-8")
    read, back = library_move._copy_one(str(src), str(tmp_path / "写.txt"))
    assert read == back == hashlib.sha256(src.read_bytes()).hexdigest()
    assert os.stat(tmp_path / "写.txt").st_mtime_ns == os.stat(src).st_mtime_ns
    with pytest.raises(FileExistsError):
        library_move._copy_one(str(src), str(tmp_path / "写.txt")), "never over a file already there"


# --- what the local data folder keeps under the library's key (Opus adversary B1, B2, S7) ---------------------------

def test_the_kept_text_and_the_stores_own_backups_move_with_it_and_the_store_stays_wal(tmp_path, monkeypatch):
    from app import token_index
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    kept = token_index.kept_text_path("ja", os.path.join(old, "data", "ja"))
    conn = sqlite3.connect(kept)
    conn.execute("PRAGMA journal_mode=WAL")
    with conn:
        conn.execute("CREATE TABLE kept (path TEXT PRIMARY KEY, text TEXT)")
        conn.execute("INSERT INTO kept VALUES ('Library/消えた.srt', '覚えている文')")
    conn.close()
    backup = _db(old, "ja") + ".bak.20261110-120000"
    shutil.copy2(_db(old, "ja"), backup)
    new = str(tmp_path / "profile" / "Surasura")
    assert library_move.move(new)["status"] == "done"
    moved = token_index.kept_text_path("ja", os.path.join(new, "data", "ja"))
    conn = sqlite3.connect(f"file:{moved}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT text FROM kept").fetchall() == [("覚えている文",)]
    finally:
        conn.close()
    for db in (_db(new, "ja"), moved):
        conn = sqlite3.connect(db)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal", db
        finally:
            conn.close()
    with open(_db(new, "ja") + ".bak.20261110-120000", "rb") as f, open(backup, "rb") as g:
        assert f.read() == g.read()
    assert {r["role"] for r in library_move.read_record()["stores"]} == {"store", "kept_text"}
    assert not [n for n in os.listdir(os.path.dirname(moved)) if ".moving-" in n]


# --- a move a kill stopped part way (S3) ---------------------------------------------------------------------------

def _killed_after(stage, old, new):
    """What a kill leaves: the in-progress record, and the copy as staging or already renamed to the target."""
    staging = new + ".moving-20261110-115900"
    folder = staging if stage == "copying" else new
    os.makedirs(os.path.join(folder, "User Files", "ja"))
    with open(os.path.join(folder, "User Files", "ja", "KnownWord.json"), "w", encoding="utf-8") as f:
        f.write('{"words": []}')
    library_move._write_json(library_move.record_path(), {"version": 1, "status": library_move.MOVING, "from": old,
                                                          "to": new, "staging": staging, "started": "x"})
    return staging


@pytest.mark.parametrize("stage", ["copying", "renamed"])
def test_a_move_a_kill_stopped_is_cleared_and_the_next_one_runs(tmp_path, monkeypatch, stage):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    before = _tree(old)
    new = str(tmp_path / "profile" / "Surasura")
    staging = _killed_after(stage, old, new)
    assert library_move.can_undo() is None, "a move under way is never undone"
    result = library_move.move(new)
    assert result["status"] == "done", result
    assert not os.path.exists(staging) and _tree(new) == before and _tree(old) == before


def test_a_leftover_target_holding_someone_elses_file_is_never_removed(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    new = str(tmp_path / "profile" / "Surasura")
    _killed_after("renamed", old, new)
    with open(os.path.join(new, "日記.txt"), "w", encoding="utf-8") as f:
        f.write("私のもの\n")
    result = library_move.move(new)
    assert result["reason"] == "not_empty"
    with open(os.path.join(new, "日記.txt"), encoding="utf-8") as f:
        assert f.read() == "私のもの\n"


# --- Undo with the library to itself (S4); an offline library (S6) ---------------------------------------------------

def test_undo_waits_for_other_programs_and_names_one_still_running(tmp_path, monkeypatch):
    old = _real_library()
    installed(monkeypatch, old, tmp_path)
    new = str(tmp_path / "profile" / "Surasura")
    assert library_move.move(new)["status"] == "done"
    monkeypatch.setattr(locks, "running_others", lambda: [{"kind": "connect", "pid": 4242}])
    result = library_move.undo(wait=0.05)
    assert result["status"] == "refused" and "Connect" in result["words"]
    assert _note()["library"] == new and os.path.isdir(new) and library_move.can_undo() is not None


def test_a_library_seen_here_but_offline_now_is_never_moved_to_an_empty_folder(tmp_path, monkeypatch):
    old = str(tmp_path / "OneDrive" / "Documents" / "Surasura")       # not synced yet
    installed(monkeypatch, old, tmp_path)
    first_run.record(old)
    note = _note()
    new = str(tmp_path / "profile" / "Surasura")
    result = library_move.move(new)
    assert result["status"] == "refused" and result["reason"] == "missing" and old in result["words"]
    assert _note() == note and not os.path.exists(new)


def test_only_a_real_link_or_junction_is_a_link(tmp_path):
    plain = tmp_path / "普通.txt"
    plain.write_text("ふつう", encoding="utf-8")
    assert not library_move._is_link(str(plain)) and not library_move._is_link(str(tmp_path))
