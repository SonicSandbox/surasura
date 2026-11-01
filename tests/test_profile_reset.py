"""Fresh library (3.0.1) WP1: *Start over completely* and *Put back* a Started-over backup (`app/profile_reset.py`),
the running marks and the profile-move lock (`app/locks.py`), and the start gate's `profile-move` state.

What a wrong answer would cost a learner — everything Surasura keeps moves here:
  * a half-moved profile (a kill, a power cut, a file held open between two renames) opening a window that makes
    empty files in the moved places: neither the old Surasura nor the new one, and no clean way back;
  * a Put back that isn't exactly what was there (a byte changed, a part left in the backup, the newer state lost);
  * a move while another Surasura program writes (Connect making cards, Piyo's server, a window in another
    sign-in): the rename may succeed on one OS and refuse on another, so the marks must catch every holder;
  * a move run unasked (a request found on an ordinary start), a network opt-out turned back on, the telemetry id or
    the installer's notes taken (the library then looks missing).

Every place lives under the test root (`path_utils.profile_places`); the libraries are real stores (both languages)
with real Japanese and Chinese text from tests/Test Resources/. A profile is proven unchanged by hashing every part.
"""
import hashlib
import json
import os
import subprocess
import sys
import textwrap

import pytest

from app import library_store as ls
from app import locks, path_utils, profile_reset
from app.services import first_run
from tests.test_library_store_support import LANGUAGES, library, names, touch, write_manifest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Killed(BaseException):
    """A process killed between two steps: no `except Exception` (or OSError) sees it, so nothing is undone for it."""


@pytest.fixture(autouse=True)
def _no_mark_of_our_own():
    """The test process holds no running mark of its own, and lets go of any a test took."""
    yield
    while locks._mark:
        locks.release_running()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _profile(settings=None):
    """A learner's profile in every place: a real store per language (two shows each), known words, results, the
    settings, a word store and パターン, Koe's key, a saved report, Connect's folder, the window's files and covers; and
    what stays: the telemetry id, logs, the start gate's and installer's notes."""
    places = path_utils.profile_places()
    for lang in LANGUAGES:
        data_dir, user_files_dir, doc = library(lang, shows=2, episodes=2)
        write_manifest(user_files_dir, doc)
        assert ls.maintain(lang, data_dir, user_files_dir) == ls.EXIT_DONE
        _write(os.path.join(user_files_dir, "KnownWord.json"),
               json.dumps({"words": [{"dictForm": w} for w in names(lang)[:4]]}, ensure_ascii=False))
        _write(os.path.join(places["index"], f"token_store_{lang}.db"), names(lang)[5] * 40)
        _write(os.path.join(places["install"], f"window_cache_{lang}.json"), names(lang)[6])
    _write(os.path.join(places["library"], "results", "reading_list_static.html"), names("ja")[7])
    _write(path_utils.get_settings_path(), json.dumps(settings if settings is not None else
                                                     {"onboarding_completed": True, "target_language": "ja"}))
    _write(os.path.join(places["roaming"], "patterns_ja.db"), names("ja")[8] * 20)
    _write(os.path.join(places["roaming"], "koe_credentials.json"), '{"key": "not a real key"}')
    _write(os.path.join(places["roaming"], "reports", "report.json"), names("zh")[2])
    _write(os.path.join(places["roaming"], "telemetry_id.json"), '{"uid": "u-1", "open_count": 3}')
    _write(os.path.join(places["install"], "connect", "ledger.json"), names("zh")[3])
    _write(os.path.join(places["install"], "window_state.json"), "{}")
    _write(os.path.join(places["install"], "covers", "cover.jpg"), names("ja")[9])
    _write(os.path.join(places["install"], "logs", "app_debug_log.txt"), "a line\n")
    _write(first_run.note_path(), json.dumps({"version": 1, "libraries": {}}))
    return places


def _hash(path):
    """A tree's (or a file's) every name and byte, as one digest; None when it isn't there."""
    if not os.path.lexists(path):
        return None
    h = hashlib.sha256()
    if os.path.isfile(path):
        with open(path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()
    for where, dirs, files in os.walk(path):
        dirs.sort()
        for n in sorted(files):
            full = os.path.join(where, n)
            h.update(os.path.relpath(full, path).encode("utf-8"))
            with open(full, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def _snapshot():
    """Every part of the profile (moves and stays) -> {(place, rel): its hash}; the lock files and logs a run writes
    left out (they stay, and change with every run)."""
    out = {}
    for part in path_utils.profile_parts():
        if part["role"] in ("locks", "logs", "backups", "journal", "window_lock") or part["rel"].endswith(".lock") \
                or part["rel"].endswith(".wlock"):
            continue
        out[(part["place"], part["rel"])] = _hash(part["path"])
    return out


def _moving():
    return {(p["place"], p["rel"]) for p in path_utils.profile_parts() if p["start_over"] == path_utils.MOVES}


def _start_over(**kw):
    profile_reset.request(profile_reset.START_OVER)
    return profile_reset.run(wait=0, **kw)


def _stamp_of(answer):
    assert answer["status"] == "done", answer
    return answer["backup"]


def _in_backup(places, stamp, place, rel):
    return os.path.join(places[place], path_utils.BACKUPS, profile_reset.PREFIX + stamp, *rel.split("/"))


# --- the round trip ------------------------------------------------------------------------------------------------ #

@pytest.fixture
def renames_only(monkeypatch):
    """The renames alone: P4's own writes after a Put back (a new store_id, a fresh JSON copy) left out, so every
    tree can be compared byte for byte (P4 has its own test)."""
    monkeypatch.setattr(profile_reset, "_renew_stores", lambda places, stamp: None)


def test_start_over_renames_every_part_that_moves_into_its_places_backup_and_put_back_brings_each_back_byte_for_byte(
        renames_only):
    """SO → PB-o: what moved is in each place's `Backups/start-over-<stamp>/`, byte for byte; what stays never moved;
    the window would open on an empty profile (setup runs: no settings). Put back sets the new profile aside first
    (kind put-back-over) and every part comes back exactly; the new profile is in its own backup, exactly."""
    places = _profile()
    before, moving = _snapshot(), _moving()
    assert ("index", os.path.basename(ls.library_db_path("ja", path_utils.get_data_path("ja")))) in moving
    assert ("roaming", "telemetry_id.json") not in moving and ("local", "first_run.json") not in moving
    stamp = _stamp_of(_start_over())
    for place, rel in moving:
        assert not os.path.lexists(os.path.join(places[place], *rel.split("/"))), rel
        assert _hash(_in_backup(places, stamp, place, rel)) == before[(place, rel)], rel
    after = _snapshot()
    for key, digest in before.items():
        if key not in moving:
            assert after[key] == digest, key                    # what stays never moved
    assert not os.path.exists(path_utils.get_settings_path())  # no settings: setup runs from the start
    assert profile_reset.pending() is None
    record = json.load(open(profile_reset.record_path(stamp), encoding="utf-8"))
    assert record["status"] == "done" and record["kind"] == "start-over"
    assert {(m["place"], m["rel"]) for m in record["moves"]} == moving
    assert all(set(m) >= {"place", "role", "rel", "dst"} for m in record["moves"])    # parts by role, never only paths

    # the new profile: a new library begun (setup's), new settings
    _write(path_utils.get_settings_path(), json.dumps({"target_language": "zh"}))
    _write(os.path.join(path_utils.get_user_files_path("zh"), "KnownWord.json"), names("zh")[9])
    newer = _snapshot()
    newer_moving = _moving()

    profile_reset.request(profile_reset.PUT_BACK, stamp)
    over = _stamp_of(profile_reset.run(wait=0))
    now = _snapshot()
    for key, digest in before.items():
        assert now.get(key) == digest, key                      # every part exactly as it was
    for place, rel in newer_moving:
        assert _hash(_in_backup(places, over, place, rel)) == newer[(place, rel)]
    chosen = json.load(open(profile_reset.record_path(stamp), encoding="utf-8"))
    assert chosen["status"] == "put-back" and chosen["put_back_over"] == over
    listed = [(b["kind"], b["stamp"]) for b in profile_reset.backups()]
    assert listed == [(profile_reset.PUT_BACK_OVER, over)]     # the one put back is no longer offered


def test_put_back_over_a_newer_profile_twice_is_the_identity(renames_only):
    """Q1: a Put back can itself be put back — the newer state is its own backup, nothing merged; a swap twice gives
    the newer profile back exactly."""
    _profile()
    stamp = _stamp_of(_start_over())
    _write(path_utils.get_settings_path(), json.dumps({"target_language": "zh", "theme": "dark"}))
    newer = _snapshot()
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    over = _stamp_of(profile_reset.run(wait=0))
    profile_reset.request(profile_reset.PUT_BACK, over)
    _stamp_of(profile_reset.run(wait=0))
    assert _snapshot() == newer


def test_after_a_put_back_each_store_has_a_new_id_and_epoch_and_a_fresh_json_copy():
    """P4: Connect's jobs queued for the store as it was drop (a new store_id), every window reads it in full (epoch
    + 1), and the JSON copy names the new id (the old manifest never stands beside it)."""
    _profile()
    old = {}
    for lang in LANGUAGES:
        store = ls.open_store(lang, path_utils.get_data_path(lang), path_utils.get_user_files_path(lang))
        old[lang] = (store.meta()["store_id"], int(store.meta()["epoch"]))
        store.close()
    stamp = _stamp_of(_start_over())
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    _stamp_of(profile_reset.run(wait=0))
    for lang in LANGUAGES:
        store = ls.open_store(lang, path_utils.get_data_path(lang), path_utils.get_user_files_path(lang))
        try:
            meta = store.meta()
            assert meta["store_id"] != old[lang][0] and int(meta["epoch"]) == old[lang][1] + 1
        finally:
            store.close()
        with open(ls.manifest_path(path_utils.get_user_files_path(lang)), encoding="utf-8") as f:
            assert json.load(f)["surasura_library"]["store_id"] == meta["store_id"]


# --- refusals: nothing moved --------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("at", ["first", "middle", "last"])
def test_a_rename_refused_at_any_step_undoes_every_rename_done_and_names_the_part(at):
    """A file held open (OneDrive, an antivirus, another sign-in's window): the rename refuses → every rename done
    is undone, newest first; the profile is exactly as it was, the record says undone and which part was held, the
    request is cleared, the empty backup folders are gone."""
    places = _profile()
    before = _snapshot()
    n = len(_moving())
    refuse = {"first": 0, "middle": n // 2, "last": n - 1}[at]
    calls = []

    def rename(a, b):
        calls.append((a, b))
        if len(calls) == refuse + 1:
            raise PermissionError(13, "held open", a)
        os.rename(a, b)
    answer = _start_over(_rename=rename)
    assert answer["status"] == "undone" and answer["reason"] == "held" and answer["part"]
    assert profile_reset.WHAT.get(answer["part"]["role"], answer["part"]["rel"]) in answer["words"]
    assert _snapshot() == before
    assert profile_reset.pending() is None
    stamp = [n for n in os.listdir(os.path.join(places["library"], path_utils.BACKUPS))][0][len(profile_reset.PREFIX):]
    record = json.load(open(profile_reset.record_path(stamp), encoding="utf-8"))
    assert record["status"] == "undone" and record["held"]["rel"] == answer["part"]["rel"]
    for place, folder in places.items():
        if place != "library":
            assert not os.path.exists(os.path.join(folder, path_utils.BACKUPS, profile_reset.PREFIX + stamp))
    assert profile_reset.backups() == []                    # one that never happened is never offered


@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses a rename while a file inside is open")
def test_a_file_really_held_open_refuses_the_rename_and_nothing_changes():
    """The probe's finding, live: a file open inside `data/` refuses that folder's rename."""
    _profile()
    held = open(os.path.join(path_utils.get_data_path("ja"), "held.txt"), "a", encoding="utf-8")
    try:
        held.write(names("ja")[1])
        held.flush()
        mid = _snapshot()
        answer = _start_over()
    finally:
        held.close()
    assert answer["status"] == "undone" and answer["part"]["role"] == "data"
    assert _snapshot() == mid


def test_a_put_back_refused_in_its_second_half_undoes_both_halves_newest_first(renames_only):
    """PB-o's one journal: the live profile set aside, then the backup's parts renamed back; a refusal among the
    second half undoes the parts already back AND the setting-aside, newest first (the same path is free only in that
    order) — the newer profile exactly as it was, the backup still offered."""
    _profile()
    stamp = _stamp_of(_start_over())
    _write(path_utils.get_settings_path(), json.dumps({"target_language": "zh"}))
    newer = _snapshot()
    n_aside = len(_moving())
    calls = []

    def rename(a, b):
        calls.append(a)
        if len(calls) == n_aside + 3:                    # the third part coming back
            raise PermissionError(13, "held open", a)
        os.rename(a, b)
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    answer = profile_reset.run(wait=0, _rename=rename)
    assert answer["status"] == "undone" and _snapshot() == newer
    assert [b["stamp"] for b in profile_reset.backups()] == [stamp]


def test_a_rename_that_cant_be_undone_keeps_the_journal_and_says_which_part():
    """A rollback refused (a file opened in between): the journal stays, the window never opens (the gate says which
    part and *Try again*); once free, recover() finishes the rollback and the profile is as it was."""
    _profile()
    before = _snapshot()
    calls = []

    def rename(a, b):
        calls.append(a)
        if len(calls) == 3:
            raise PermissionError(13, "held open", a)
        if len(calls) == 4:                                # the first undo refused too
            raise PermissionError(13, "opened meanwhile", a)
        os.rename(a, b)
    answer = _start_over(_rename=rename)
    assert answer["status"] == "stuck" and answer["part"]
    journal = profile_reset.pending()
    assert journal["status"] == profile_reset.MOVING
    assert first_run.state()["state"] == first_run.PROFILE_MOVE
    again = profile_reset.recover()
    assert again["status"] == "rolled-back"
    assert _snapshot() == before and profile_reset.pending() is None


def _kill_steps():
    return ["planned", "moved:0", "moved:5", "committed", "record", "cleared"]


@pytest.mark.parametrize("kill", _kill_steps())
def test_a_kill_at_any_step_leaves_the_old_profile_or_the_new_one_never_a_mix(kill):
    """P10: a journal still `moving` at the next start is rolled back (every tree exactly as before); one past its
    commit point (`done`) is finished forward. Either way the journal ends, and nothing is half."""
    places = _profile()
    before, moving = _snapshot(), _moving()

    def step(name):
        if name == kill:
            raise _Killed(name)
    profile_reset.request(profile_reset.START_OVER)
    with pytest.raises(_Killed):
        profile_reset.run(wait=0, _step=step)
    locks._registry.clear()                              # the OS lets a killed process's locks go
    answer = profile_reset.recover()
    assert profile_reset.pending() is None
    if kill in ("planned", "moved:0", "moved:5"):
        assert answer["status"] == "rolled-back"
        assert _snapshot() == before
    else:
        assert answer["status"] in ("done", "none")
        for place, rel in moving:
            assert not os.path.lexists(os.path.join(places[place], *rel.split("/")))
        assert profile_reset.backups()[0]["status"] == "done"


def test_a_real_process_killed_mid_move_is_rolled_back_at_the_next_start(tmp_path):
    """The same drill with a real child process ended by os._exit between two renames: its OS locks go with it, and
    the next start (this process) rolls the move back."""
    _profile()
    before = _snapshot()
    script = tmp_path / "kill.py"
    script.write_text(textwrap.dedent("""
        import os, sys
        sys.path.insert(0, sys.argv[1])
        from app import profile_reset
        profile_reset.request(profile_reset.START_OVER)
        profile_reset.run(wait=0, _step=lambda name: os._exit(9) if name == "moved:3" else None)
        os._exit(0)
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    code = subprocess.run([sys.executable, str(script), REPO], env=env, timeout=120).returncode
    assert code == 9
    assert profile_reset.pending()["status"] == profile_reset.MOVING
    assert first_run.state()["state"] == first_run.PROFILE_MOVE
    out = first_run.run(first_run.state())
    assert out["move"]["status"] == "rolled-back"
    assert _snapshot() == before


# --- holders: the running marks, the profile-move lock, another install ------------------------------------------- #

def _child(tmp_path, body, name):
    """A child Surasura program running `body` (after its imports), which prints "ready" then waits for stdin."""
    script = tmp_path / f"{name}.py"
    script.write_text(textwrap.dedent("""
        import sys
        sys.path.insert(0, sys.argv[1])
        from app import locks
    """) + textwrap.dedent(body) + "\nprint('ready', flush=True)\nsys.stdin.readline()\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    proc = subprocess.Popen([sys.executable, str(script), REPO], env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    return proc


def _end(proc):
    try:
        proc.stdin.write("\n")
        proc.stdin.flush()
    except OSError:
        pass
    proc.wait(timeout=60)


def test_another_surasura_program_alive_is_waited_for_then_refused_by_name_even_where_renames_never_refuse(tmp_path):
    """P5 / P13 / S17: Connect running (its mark held) → the gate waits (`on_wait` once), then refuses naming it;
    nothing renamed — with a rename that never refuses (Linux, macOS), the mark alone caught it. Once it ends, the
    same request runs."""
    _profile()
    before = _snapshot()
    proc = _child(tmp_path, 'locks.hold_running("connect")', "connect")
    try:
        renamed, told = [], []
        profile_reset.request(profile_reset.START_OVER)
        answer = profile_reset.run(wait=0.6, on_wait=told.append, _rename=lambda a, b: renamed.append(a))
        assert answer["status"] == "refused" and answer["reason"] == "running"
        assert "Connect" in answer["words"] and answer["holder"]["kind"] == "connect"
        assert len(told) == 1 and told[0][0]["pid"] == proc.pid
        assert renamed == [] and _snapshot() == before
        assert profile_reset.pending()["status"] == profile_reset.ASKED      # kept for *Try again*
    finally:
        _end(proc)
    assert profile_reset.run(wait=0)["status"] == "done"


def test_a_program_started_while_a_move_runs_waits_then_stops_and_leaves_no_mark(tmp_path):
    """No program can start in the middle of a move: the profile-move lock held → `hold_running` waits, then
    `MoveRunning`, its mark let go (so the mover never waits on it)."""
    proc = _child(tmp_path, 'held = locks.take(locks.PROFILE_MOVE, "Setting your old Surasura aside")', "mover")
    try:
        with pytest.raises(locks.MoveRunning):
            locks.hold_running("cli", wait=0.3)
        folder = os.path.join(path_utils.get_local_data_path(), "locks", locks.RUNNING_DIR)
        assert [n for n in os.listdir(folder) if n.startswith(f"{os.getpid()}-")] == []
        assert not locks._mark
    finally:
        _end(proc)
    assert locks.hold_running("cli", wait=0.3) is True
    locks.release_running()


def test_the_command_line_holds_a_mark_for_its_call_and_answers_busy_while_a_move_runs(tmp_path, monkeypatch):
    """surasura-cli (hato, Connect's runner, Piyo's server go through it): its mark held while a verb runs and let go
    after; a move running → `busy` (exit 3), the move's words, nothing read."""
    import io
    from app.cli import __main__ as cli
    seen = []
    real = locks.hold_running
    monkeypatch.setattr(locks, "hold_running", lambda kind, **kw: seen.append(kind) or real(kind, **kw))
    out = io.StringIO()
    cli.main(["status"], out=out)
    assert seen == ["cli"] and not locks._mark
    monkeypatch.setattr(locks, "MOVE_WAIT", 0.3)
    proc = _child(tmp_path, 'held = locks.take(locks.PROFILE_MOVE, "Setting your old Surasura aside")', "mover")
    try:
        out = io.StringIO()
        assert cli.main(["status"], out=out) == 3
        last = json.loads(out.getvalue().strip().splitlines()[-1])
        assert last["code"] == "busy" and last["message"] == locks.MOVE_RUNNING
    finally:
        _end(proc)
    assert not locks._mark


def test_a_program_that_marked_itself_first_is_seen_by_a_mover_that_starts_after(tmp_path):
    """The two orders: a mark taken before the mover's look is seen by it; the mover takes the profile-move lock
    before it looks, so a mark taken after sees the lock. Here: the mark first."""
    proc = _child(tmp_path, 'locks.hold_running("mcp")', "piyo")
    try:
        others = locks.running_others()
        assert [o["kind"] for o in others] == ["mcp"] and others[0]["pid"] == proc.pid
    finally:
        _end(proc)
    assert locks.running_others() == []                  # its mark went with it (and its file tidied)


def test_a_program_of_another_install_sharing_these_places_is_a_holder_too(tmp_path):
    """Another install's programs keep their marks in their own install folder in the local root: they share the
    roaming and local places, so they count."""
    folder = os.path.join(path_utils.local_data_root(), "cccccccccccccccc", "locks", locks.RUNNING_DIR)
    proc = _child(tmp_path, f"""
        import json, os
        from app import path_utils
        os.makedirs({folder!r}, exist_ok=True)
        held = path_utils.try_lock({os.path.join(folder, "4242-1-0.lock")!r})
        with open({os.path.join(folder, "4242-1-0.json")!r}, "w") as f:
            json.dump({{"pid": os.getpid(), "kind": "window"}}, f)
    """, "other")
    try:
        assert [o["kind"] for o in locks.running_others()] == ["window"]
    finally:
        _end(proc)
    assert locks.running_others() == []


def test_a_mark_a_dead_program_left_is_no_holder_and_is_tidied_away():
    folder = os.path.join(path_utils.get_local_data_path(), "locks", locks.RUNNING_DIR)
    _write(os.path.join(folder, "99999-1-0.lock"), "")
    _write(os.path.join(folder, "99999-1-0.json"), json.dumps({"pid": 99999, "kind": "window"}))
    assert locks.running_others() == []
    assert os.listdir(folder) == []


def test_this_programs_own_mark_is_never_its_own_holder_and_counts_in_process_holds():
    assert locks.hold_running("window") is True
    assert locks.hold_running("cli") is True                 # the command line called in-process: counted
    assert locks.running_others() == []
    locks.release_running()
    assert locks._mark
    locks.release_running()
    assert not locks._mark


def test_another_install_sharing_these_places_refuses_start_over(tmp_path):
    """P14: a source checkout beside an installed copy share the roaming and local places: refused while the note
    names another install whose library folder and program are still there; once its program is gone, it runs."""
    _profile()
    other = tmp_path / "other library"
    other.mkdir()
    exe = tmp_path / "Other" / "Surasura.exe"
    _write(str(exe), "")
    _write(os.path.join(path_utils.local_data_root(), path_utils.INSTALLS_NOTE),
           json.dumps([{"data_root": path_utils.get_user_data_path(), "exe": "x"},
                       {"data_root": str(other), "exe": str(exe)}]))
    before = _snapshot()
    answer = _start_over()
    assert answer["status"] == "refused" and answer["reason"] == "install" and str(other) in answer["words"]
    assert _snapshot() == before
    os.remove(exe)
    assert profile_reset.run(wait=0)["status"] == "done"


def test_an_update_staged_refuses_and_keeps_the_request():
    _profile()
    profile_reset.request(profile_reset.START_OVER)
    _write(ls.update_staged_path(), "{}")
    before = _snapshot()
    answer = profile_reset.run(wait=0)
    assert answer["status"] == "refused" and answer["reason"] == "update"
    assert _snapshot() == before and profile_reset.pending()["status"] == profile_reset.ASKED
    with pytest.raises(profile_reset.MoveRefused):
        profile_reset.request(profile_reset.START_OVER)


def test_the_helper_holding_a_store_refuses_and_nothing_moves():
    _profile()
    before = _snapshot()
    lock = ls.MaintenanceLock(ls.library_db_path("zh", path_utils.get_data_path("zh")))
    assert lock.try_acquire()
    try:
        answer = _start_over()
    finally:
        lock.close()
    assert answer["status"] == "refused" and answer["reason"] == "running" and _snapshot() == before


def test_connect_and_the_profile_move_lock_are_taken_for_the_whole_move():
    """Connect is taken, never only checked, and so is the profile-move lock: while the renames run, a Connect or any
    program starting can't take its lock (`hold_running` waits on it)."""
    _profile()
    seen = []
    _start_over(_step=lambda name: seen.append((locks.held_in_process("connect"),
                                                locks.held_in_process(locks.PROFILE_MOVE)))
                if name.startswith("moved") else None)
    assert seen and all(a and b for a, b in seen)
    assert not locks.held_in_process("connect") and not locks.held_in_process(locks.PROFILE_MOVE)


# --- put back's own refusals ------------------------------------------------------------------------------------- #

def _over_and_new():
    _profile()
    stamp = _stamp_of(_start_over())
    _write(path_utils.get_settings_path(), json.dumps({"target_language": "zh"}))
    return stamp


def test_a_backup_from_a_newer_surasura_is_refused_update_first():
    stamp = _over_and_new()
    before = _snapshot()
    where = profile_reset.record_path(stamp)
    record = json.load(open(where, encoding="utf-8"))
    record["app_version"] = "99.0.0"
    _write(where, json.dumps(record))
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    answer = profile_reset.run(wait=0)
    assert answer["status"] == "refused" and answer["reason"] == "newer" and "99.0.0" in answer["words"]
    assert _snapshot() == before


def test_a_backup_with_a_part_missing_is_refused_naming_it_and_nothing_moves():
    stamp = _over_and_new()
    places = path_utils.profile_places()
    before = _snapshot()
    import shutil
    shutil.rmtree(_in_backup(places, stamp, "library", "results"))
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    answer = profile_reset.run(wait=0)
    assert answer["status"] == "refused" and answer["reason"] == "missing"
    assert profile_reset.WHAT["results"] in answer["words"] and _snapshot() == before


def test_a_part_whose_place_is_taken_by_something_that_stays_is_refused():
    """A backup made when a part moved that now stays (another table): its place is occupied and never written over."""
    stamp = _over_and_new()
    places = path_utils.profile_places()
    where = profile_reset.record_path(stamp)
    record = json.load(open(where, encoding="utf-8"))
    _write(_in_backup(places, stamp, "roaming", "telemetry_id.json"), "{}")
    record["moves"].append({"place": "roaming", "role": "telemetry_id", "rel": "telemetry_id.json",
                            "dst": f"{path_utils.BACKUPS}/{profile_reset.PREFIX}{stamp}/telemetry_id.json"})
    _write(where, json.dumps(record))
    before = _snapshot()
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    answer = profile_reset.run(wait=0)
    assert answer["status"] == "refused" and answer["reason"] == "taken" and _snapshot() == before


def test_a_backup_that_never_finished_or_cant_be_read_is_refused():
    stamp = _over_and_new()
    where = profile_reset.record_path(stamp)
    record = json.load(open(where, encoding="utf-8"))
    _write(where, json.dumps(dict(record, status="started")))
    profile_reset.request(profile_reset.PUT_BACK, stamp)
    assert profile_reset.run(wait=0)["reason"] == "gone"
    _write(where, "{ not json")
    assert profile_reset.run(wait=0)["reason"] == "gone"


# --- the request and the start gate -------------------------------------------------------------------------------- #

def test_a_request_found_on_a_plain_start_is_asked_never_run_and_runs_only_with_a_yes():
    """P16: the gate runs it only on the restart's own start (or the learner's yes): `run` without `move` answers
    asked and moves nothing."""
    _profile()
    before = _snapshot()
    profile_reset.request(profile_reset.START_OVER)
    st = first_run.state()
    assert st["state"] == first_run.PROFILE_MOVE and st["journal"]["action"] == profile_reset.START_OVER
    assert first_run.needs_run(st)
    out = first_run.run(st)
    assert out["status"] == "asked" and _snapshot() == before
    out = first_run.run(st, move=True)
    assert out["status"] == "done" and out["move"]["status"] == "done"
    assert first_run.state()["state"] != first_run.PROFILE_MOVE


def test_an_asked_request_waits_behind_an_installed_library_folder_that_is_offline(monkeypatch, tmp_path):
    """The library on a NAS, offline at the start: library-missing comes first and the request waits."""
    profile_reset.request(profile_reset.START_OVER)
    gone = str(tmp_path / "offline library")
    monkeypatch.setattr(path_utils, "installed_library", lambda: gone)
    first_run.record(gone)
    assert first_run.state()["state"] == first_run.LIBRARY_MISSING


def test_a_request_is_taken_back_and_one_in_flight_never_is():
    profile_reset.request(profile_reset.START_OVER)
    assert profile_reset.cancel_request() is True and profile_reset.pending() is None
    assert profile_reset.cancel_request() is False
    _write(profile_reset.journal_path(), json.dumps({"action": "start-over", "status": "moving", "moves": []}))
    assert profile_reset.cancel_request() is False
    with pytest.raises(profile_reset.MoveRefused):
        profile_reset.request(profile_reset.START_OVER)


def test_a_journal_that_cant_be_written_refuses_the_request_and_writes_nothing(monkeypatch):
    def full(*_a, **_k):
        raise OSError(28, "No space left on device")
    with monkeypatch.context() as patched:
        patched.setattr(profile_reset.os, "replace", full)
        with pytest.raises(profile_reset.MoveRefused) as e:
            profile_reset.request(profile_reset.START_OVER)
    assert e.value.reason == "journal" and "No space" in e.value.words
    assert profile_reset.pending() is None


def test_a_journal_that_cant_be_read_is_never_guessed_at():
    _write(profile_reset.journal_path(), "{ half")
    assert profile_reset.pending()["status"] == "unreadable"
    answer = profile_reset.run(wait=0)
    assert answer["status"] == "refused" and answer["reason"] == "unreadable"
    assert first_run.state()["state"] == first_run.PROFILE_MOVE


def test_no_journal_runs_nothing():
    assert profile_reset.run()["status"] == "none" and profile_reset.recover()["status"] == "none"


# --- the network opt-outs (P7, F1) ---------------------------------------------------------------------------------- #

@pytest.mark.parametrize("settings, carried", [
    ({"telemetry_enabled": False, "update_check_enabled": False, "auto_update_enabled": True, "theme": "dark"},
     {"telemetry_enabled": False, "update_check_enabled": False}),
    ({"auto_update_enabled": False}, {"auto_update_enabled": False}),
    ({"telemetry_enabled": True, "onboarding_completed": True}, None),
])
def test_every_network_opt_out_carries_into_a_new_settings_file_and_nothing_else(settings, carried):
    """Start over never turns a network request back on: each opt-out of the moved settings is written into a new
    settings.json, those keys only (setup still runs: no `onboarding_completed`); none off → no settings.json."""
    _profile(settings=settings)
    stamp = _stamp_of(_start_over())
    if carried is None:
        assert not os.path.exists(path_utils.get_settings_path())
    else:
        with open(path_utils.get_settings_path(), encoding="utf-8") as f:
            assert json.load(f) == carried
    record = json.load(open(profile_reset.record_path(stamp), encoding="utf-8"))
    assert record["carried"] == (carried or {})


# --- the Backups list -------------------------------------------------------------------------------------------- #

def test_the_list_holds_every_kind_newest_first_a_stopped_one_first_and_sizes_add_up():
    """Started over, and each language's Sorted-again backups (3.0's records, no `kind`, are Sorted again; one a kill
    stopped after it moved something is *stopped part way*; one stopped before is not listed); sizes count every
    file in every place."""
    _profile()
    trash = os.path.join(path_utils.get_user_files_path("ja"), ".trash")
    old = _write(os.path.join(trash, ls.RESET_PREFIX + "20261030-101010", ls.RESET_RECORD),
                 json.dumps({"language": "ja", "status": "done", "started_at": "2026-10-30T10:10:10", "moves": []}))
    stopped_to = _write(os.path.join(trash, ls.RESET_PREFIX + "20261031-101010", "data", "Library", "a.srt"),
                        names("ja")[2])
    _write(os.path.join(trash, ls.RESET_PREFIX + "20261031-101010", ls.RESET_RECORD),
           json.dumps({"language": "ja", "status": "started", "started_at": "2026-10-31T10:10:10",
                       "moves": [{"step": "data", "from": "x", "to": os.path.dirname(os.path.dirname(stopped_to))}]}))
    _write(os.path.join(trash, ls.RESET_PREFIX + "20261031-111111", ls.RESET_RECORD),
           json.dumps({"language": "ja", "status": "started", "started_at": "2026-10-31T11:11:11",
                       "moves": [{"step": "data", "from": "x", "to": "nowhere"}]}))
    _write(os.path.join(trash, ls.RESET_PREFIX + "20261029-090909", ls.RESET_RECORD),
           json.dumps({"language": "ja", "status": "undone", "started_at": "2026-10-29T09:09:09", "moves": []}))
    assert [b["stamp"] for b in profile_reset.backups()] == [ls.RESET_PREFIX + "20261031-101010",
                                                             ls.RESET_PREFIX + "20261030-101010"]
    stamp = _stamp_of(_start_over())                     # the sorted-again ones go with User Files
    listed = profile_reset.backups()
    assert [(b["kind"], b["scope"], b["stopped"]) for b in listed] == [(profile_reset.STARTED_OVER, "profile", False)]
    places = path_utils.profile_places()
    total = sum(os.path.getsize(os.path.join(w, n)) for folder in places.values()
                for w, _d, files in os.walk(os.path.join(folder, path_utils.BACKUPS, profile_reset.PREFIX + stamp))
                for n in files)
    assert profile_reset.backup_size(listed[0]) == total > 0
    assert os.path.exists(old) is False


def test_both_languages_go_with_start_over():
    """Q4: the whole profile, Japanese and Chinese."""
    _profile()
    stamp = _stamp_of(_start_over())
    places = path_utils.profile_places()
    for lang in LANGUAGES:
        name = os.path.basename(ls.library_db_path(lang, path_utils.get_data_path(lang)))
        assert os.path.exists(_in_backup(places, stamp, "index", name))
        assert not os.path.exists(ls.library_db_path(lang, path_utils.get_data_path(lang)))


# --- the start order (R2) -------------------------------------------------------------------------------------------- #

def test_nothing_reads_or_writes_a_moving_place_before_the_windows_gate(monkeypatch):
    """R2: app_entry's start, up to the window's start gate, touches no place a Start over moves — telemetry (which
    reads settings.json) starts only after the gate (`after_gate`). Watched by every moving part's hash and time, and
    by telemetry's own start."""
    import app_entry
    from app import telemetry
    _profile()
    profile_reset.request(profile_reset.START_OVER)
    watched = {p["path"]: (_hash(p["path"]), os.stat(p["path"]).st_mtime_ns)
               for p in path_utils.profile_parts() if p["start_over"] == path_utils.MOVES}
    started = []
    monkeypatch.setattr(telemetry, "init", lambda: started.append("telemetry"))
    at_gate = {}

    class Window:
        @staticmethod
        def main(argv, after_gate=None):
            at_gate["marked"] = dict(locks._mark)
            at_gate["telemetry"] = list(started)
            at_gate["parts"] = {path: (_hash(path), os.stat(path).st_mtime_ns) for path in watched}
            after_gate()
            return 0
    monkeypatch.setattr(app_entry, "_qt_window", lambda: Window)
    monkeypatch.setattr(sys, "argv", ["app_entry.py"])
    import io                                            # (main wraps stdout's buffer: never pytest's own)
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO()))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO()))
    with pytest.raises(SystemExit) as e:
        app_entry.run()
    assert e.value.code == 0
    assert at_gate["telemetry"] == [] and started == ["telemetry"]
    assert at_gate["marked"].get("count") == 1                # the window held its running mark throughout
    assert at_gate["parts"] == watched
    assert not locks._mark                                   # the window's mark went with its run
