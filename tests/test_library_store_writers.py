"""The Content Manager in store mode (Library_Store_Spec §7 Phase 2, §10 WP-L7; L2.1 row 2.1.2).

Every order and tier action is one store command (check → file work → commit), the tree is read from the store,
the disk walk and the 500 ms poll run on a worker — never on the window's thread — and Undo reverses each change
alone. JSON mode (no store yet) is 2.4's code with Undo off and the copy lock around its save; read-only mode shows
the library and refuses every change. The store never moves a file (I3).

A real Tk window on the test's SURASURA_TEST_ROOT (data/<lang>, User Files/<lang>), synthetic libraries named with
real Japanese and Chinese words from tests/Test Resources/; every proof runs for both languages. Timed figures are
asserted tightly only in the timed run (`SURASURA_STORE_BENCH=1`, under the test lock), loosely otherwise.
"""

import json
import os
import subprocess
import sys
import threading
import types
import time
from unittest.mock import patch

import pytest
import tkinter as tk

from app import library_store as ls
from app import content_importer_gui as cig
from app.content_importer_gui import ContentImporterApp
from tests.test_library_store_support import (LANGUAGES, library, names, no_line, read_doc, roots, subprocess_env,
                                              touch, write_manifest)

BENCH = bool(os.environ.get("SURASURA_STORE_BENCH"))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def window():
    made = []

    def make(language):
        cig._DIALOGS[0] = 0                              # a dialog hold left by an earlier test's root never releases
        root = tk.Tk()
        app = ContentImporterApp(root, language)
        made.append(root)
        return app
    yield make
    for root in made:
        try:
            root.destroy()
        except Exception:
            pass


def _store_library(language, **kw):
    data_dir, user_files_dir, doc = library(language, **kw)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return data_dir, user_files_dir, doc


def _tree_paths(app):
    """Every file row the tree shows, in order (relative to data/<lang>)."""
    out = []

    def walk(parent):
        for child in app.tree.get_children(parent):
            vals = app.tree.item(child, "values")
            if vals and not str(vals[0]).startswith("GROUP:"):
                out.append(os.path.relpath(vals[0], app.data_root).replace("\\", "/"))
            walk(child)
    walk("")
    return out


def _order(app, tier):
    return [e["physical_path"] for _i, e, _a in app._store().ordered(tier)]


def _snapshot(root):
    snap = {}
    for r, _dirs, files in os.walk(root):
        for name in files:
            with open(os.path.join(r, name), "rb") as f:
                snap[os.path.relpath(os.path.join(r, name), root)] = f.read()
    return snap


def _other_process(language, code):
    """Run `code` in another process against the same store (`store` is open there)."""
    data_dir, user_files_dir = roots(language)
    script = ("import sys; sys.path.insert(0, %r)\n"
              "from app import library_store as ls\n"
              "store = ls.open_store(%r, %r, %r)\n" % (REPO, language, data_dir, user_files_dir)) + code
    out = subprocess.run([sys.executable, "-c", script], env=subprocess_env(), capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr


def _pump(app, until, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if until():
            return True
        time.sleep(0.01)
    return False


# --- #2 The four flows that add files without an Add ------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_four_flows_show_their_files_with_no_focus_change(window, language, tmp_path):
    """Test with samples, pasted text, a YouTube download and the splicer each drop files into a tier folder; in
    store mode each shows them at once — the sync follows the flow (A1's amendment), placed by §6.10 rule 3.
    (Samples copy only into empty tiers: the library starts in 6+ Months.)"""
    _store_library(language, tiers=("goal",))
    app = window(language)
    assert app._store_mode() == "store"
    app.target_folder_var.set("HighPriority")

    from app.path_utils import seed_samples
    with patch("app.path_utils.seed_samples", wraps=seed_samples):
        app._seed_samples_clicked()
    samples = [r for r in _order(app, "now") + _order(app, "soon") if "sample" in r.lower()]
    assert samples, "the samples joined the library"

    app._save_pasted_text(names(language)[20], "\n".join(names(language)[:5]), "HighPriority")
    pasted = f"HighPriority/{names(language)[20]}.txt"
    assert pasted in _tree_paths(app)

    video = tmp_path / "Processed" / f"{names(language)[21]} [k3GuCkTa3V4].txt"
    video.parent.mkdir(parents=True)
    video.write_text("\n".join(names(language)[5:9]), encoding="utf-8")
    app._on_youtube_downloaded([str(video)])
    assert f"HighPriority/{video.name}" in _tree_paths(app)

    spliced = touch(app.data_root, f"HighPriority/{names(language)[22]}/ch01.txt", names(language)[23])
    app._refresh_on_focus = True                         # the splicer was launched; its window closes
    app._on_focus_in(None)
    assert _pump(app, lambda: "HighPriority/" + os.path.relpath(spliced, os.path.join(app.data_root, "HighPriority"))
                 .replace("\\", "/") in _tree_paths(app))


# --- #3 The store never moves a file ------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_no_order_or_tier_action_moves_a_file(window, language):
    """Drag, ▲▼, Demote, Graduate (Soon → NOW and NOW → Graduated) and Reset change the order and the tiers and
    leave every file where it is, with the same bytes (I3, L5: Sonic, "The store should never move any of the
    files")."""
    data_dir, _uf, _doc = _store_library(language)
    no_line(ls.open_store(language, data_dir, _uf)).close()   # 2.x's tier actions, as 2.4 drew them (no Soon line)
    app = window(language)
    before = _snapshot(data_dir)
    now = [os.path.join(data_dir, *p.split("/")) for p in _order(app, "now")]
    soon = [os.path.join(data_dir, *p.split("/")) for p in _order(app, "soon")]
    order0 = {t: _order(app, t) for t in ls.ANALYSED}

    app.target_folder_var.set("HighPriority")
    app.move_manifest_items_relative([now[0]], now[-1], "after")
    app.move_items_in_manifest([now[-1]], "up")
    with patch.object(app, "_resolve_items_to_paths", return_value=now[:2]), \
         patch.object(app.tree, "selection", return_value=("row",)):
        app.demote_content()
        app.graduate_content()                           # NOW -> Graduated, the same two (from Soon now)
    app.target_folder_var.set("LowPriority")
    with patch.object(app, "_resolve_items_to_paths", return_value=soon[:3]), \
         patch.object(app.tree, "selection", return_value=("row",)):
        app.graduate_content()
    graduated = [os.path.relpath(p, data_dir).replace("\\", "/") for p in soon[:3]]
    assert all(g in _order(app, "now") for g in graduated), "Graduate from Soon took the three to NOW"
    app.reset_to_folder_structure()

    assert {t: _order(app, t) for t in ls.ANALYSED} != order0
    assert _snapshot(data_dir) == before, "a store action moved, renamed or changed a file"


# --- the placement rules through the window (RD-L-Q6, Q4-9) --------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_add_files_lands_in_the_order_chosen_and_a_new_episode_joins_its_show(window, language, tmp_path):
    """L-Q6: Add Files of a, b, c lands a, b, c (2.4: c, b, a). Q4-9, an Add on any tab (G1.1-14): an episode
    of a show with no row in NOW or Soon goes to the top of NOW; one whose show has a row in Soon joins it there."""
    data_dir, _uf, doc = _store_library(language)
    app = window(language)
    words = names(language)
    picks = []
    for w in words[30:33]:
        f = tmp_path / "downloads" / f"{w}.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(w, encoding="utf-8")
        picks.append(str(f))
    app.target_folder_var.set("LowPriority")
    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=picks):
        app.add_files()
    soon = _order(app, "soon")
    assert soon[:3] == [f"LowPriority/{w}.txt" for w in words[30:33]], "a, b, c — in the order chosen"

    goal_show = doc["schedule"]["PHASE_3_LATER"][0]["parent_folder"]
    episode = tmp_path / "ep" / f"{goal_show}_第99話.srt"
    episode.parent.mkdir(parents=True)
    episode.write_text(words[34], encoding="utf-8")
    app.target_folder_var.set("GoalContent")
    with patch.object(app, "get_current_dir", return_value=os.path.join(data_dir, "GoalContent", goal_show)), \
         patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(episode)]):
        app.add_files()
    assert _order(app, "now")[0] == f"GoalContent/{goal_show}/{episode.name}", "Q4-9: the top of NOW"

    soon_show = doc["schedule"]["PHASE_2_SOON"][0]["parent_folder"]
    episode2 = tmp_path / "ep" / f"{soon_show}_第99話.srt"
    episode2.write_text(words[35], encoding="utf-8")
    app.target_folder_var.set("HighPriority")
    with patch.object(app, "get_current_dir", return_value=os.path.join(data_dir, "LowPriority", soon_show)), \
         patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(episode2)]):
        app.add_files()
    soon = _order(app, "soon")
    rows = [r for r in soon if f"/{soon_show}/" in r]
    assert rows[-1].endswith(episode2.name), "after the show's last row in Soon, whichever tab it was added on"


# --- #4 Read-only mode ------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_read_only_mode_shows_the_library_and_refuses_every_change(window, language, tmp_path):
    data_dir, user_files_dir, _doc = _store_library(language)
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test")
    app = window(language)
    assert app._store_mode() == "read-only"
    app.refresh_file_list(force=True)
    shown = _tree_paths(app)
    assert shown, "the library is still shown (from its copy)"
    copy = read_doc(user_files_dir)
    before = _snapshot(data_dir)
    first = os.path.join(data_dir, *shown[0].split("/"))
    last = os.path.join(data_dir, *shown[-1].split("/"))
    app.move_manifest_items_relative([first], last, "after")
    pick = tmp_path / f"{names(language)[40]}.txt"
    pick.write_text("x", encoding="utf-8")
    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[str(pick)]) as dialog:
        app.add_files()
        dialog.assert_not_called()
    with patch.object(app, "_resolve_items_to_paths", return_value=[first]), \
         patch.object(app.tree, "selection", return_value=("row",)):
        app.remove_files()
        app.demote_content()
    app._sync_disk_to_manifest()
    assert read_doc(user_files_dir) == copy and _snapshot(data_dir) == before
    assert "repaired" in app.status_var.get()
    assert app.store_banner.winfo_manager() == "pack" and "Repair" in app.store_banner_var.get()


# --- #5 The size guard -------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_size_guard_asks_and_keep_mine_keeps_the_order_off_the_windows_thread(window, language):
    """An outside edit of the copy moving over 5 % of the library waits for the user (Q4-8): the window shows the
    question with both answers; "Keep mine" runs off the window's thread (it waits for the maintenance lock) and
    the store's order stays."""
    data_dir, user_files_dir, _doc = _store_library(language)
    copy = read_doc(user_files_dir)
    copy["schedule"]["PHASE_1_NOW"].reverse()
    copy["schedule"]["PHASE_2_SOON"].reverse()
    write_manifest(user_files_dir, copy)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    app = window(language)
    order = _order(app, "now")
    app._update_store_banner()
    assert app.store_banner.winfo_manager() == "pack"
    assert app.store_banner_buttons.winfo_manager() == "pack"
    assert "changed outside Surasura" in app.store_banner_var.get()

    caller = []
    real = ls.resolve_reimport
    with patch.object(ls, "resolve_reimport", side_effect=lambda *a: caller.append(threading.current_thread())
                      or real(*a)):
        app._answer_size_guard(False)
        assert _pump(app, lambda: caller and not app._store().meta().get("reimport_pending"))
    assert caller[0] is not threading.main_thread()
    assert _order(app, "now") == order
    app._update_store_banner()
    assert app.store_banner.winfo_manager() == ""


# --- #6 JSON mode -------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_json_mode_switches_to_the_store_when_one_appears(window, language):
    """A window opened before the store existed checks the mode before every save: once the helper has built the
    store, the next drag is a store command — the copy is the helper's to write, not the window's."""
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    app = window(language)
    assert app._store_mode() == "json"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    copy_before = read_doc(user_files_dir)
    now = [os.path.join(data_dir, *e["physical_path"].split("/")) for e in doc["schedule"]["PHASE_1_NOW"]]
    app.target_folder_var.set("HighPriority")
    app.move_manifest_items_relative([now[0]], now[-1], "after")
    assert _order(app, "now")[-1] == doc["schedule"]["PHASE_1_NOW"][0]["physical_path"]
    assert read_doc(user_files_dir) == copy_before


HOLD = ("import time, sys\n"
        "lock = ls._copy_lock(ls.library_db_path(%r, %r))\n"
        "assert lock.acquire(5, 0.001)\n"
        "open(%r, 'w').close()\n"
        "time.sleep(%r)\n"
        "lock.release(); lock.close()\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_save_waits_for_the_copy_lock_another_process_holds(window, language, tmp_path):
    """§6.7: every 2.5 JSON-mode save of the manifest takes the copy lock around its replace, so it never lands
    between the helper's look and its own replace."""
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    app = window(language)
    assert app._store_mode() == "json"
    flag = str(tmp_path / "held")
    data_dir_, uf = roots(language)
    script = ("import sys; sys.path.insert(0, %r)\nfrom app import library_store as ls\n" % REPO
              + HOLD % (language, data_dir_, flag, 0.8))
    holder = subprocess.Popen([sys.executable, "-c", script], env=subprocess_env())
    try:
        deadline = time.monotonic() + 30
        while not os.path.exists(flag) and time.monotonic() < deadline:
            time.sleep(0.01)
        t0 = time.monotonic()
        doc["schedule"]["PHASE_1_NOW"].reverse()
        app.save_manifest(doc)
        waited = time.monotonic() - t0
    finally:
        holder.wait(30)
    assert waited > 0.3, f"saved after {waited:.3f} s while another process held the copy lock"
    assert read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"] == doc["schedule"]["PHASE_1_NOW"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_save_without_a_lock_file_saves_and_says_so(window, language, capsys):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    app = window(language)
    doc["schedule"]["PHASE_1_NOW"].reverse()
    with patch.object(ls, "library_db_path", side_effect=ls.StoreRefused("no local folder")):
        app.save_manifest(doc)
    assert read_doc(user_files_dir)["schedule"]["PHASE_1_NOW"] == doc["schedule"]["PHASE_1_NOW"]
    assert "without the copy lock" in capsys.readouterr().out


# --- #7 The tree's fast path ---------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_tree_ignores_receipts_and_pins_but_follows_another_windows_move(window, language, monkeypatch):
    """The tree's key is (epoch, order_version, availability_version): a receipt or a pin written by another
    process never rebuilds it; another window's move, or a file deleted on disk, does, within one poll of the
    worker."""
    _store_library(language)
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    app = window(language)
    assert _pump(app, lambda: bool(_tree_paths(app)))
    app._refresh_from_focus = lambda: None               # only the worker's poll may redraw here
    calls = []
    real = ls.Store.ordered
    monkeypatch.setattr(ls.Store, "ordered", lambda self, tier: calls.append(tier) or real(self, tier))
    first = app._store().ids("now")[0]
    _other_process(language, f"store.pin([{first}])\nstore.receipt({first}, '2026-10-05T00:00:00Z')\n")
    app.refresh_file_list()
    _pump(app, lambda: False, timeout=0.8)               # the worker's first results drained, its polls seen
    assert calls == [], "a pin or a receipt rebuilt the tree"

    shown = _tree_paths(app)
    _other_process(language, f"ids = store.ids('now')\nstore.move([ids[0]], 'now', after_id=ids[-1])\n")
    t0 = time.monotonic()
    assert _pump(app, lambda: _tree_paths(app) != shown, timeout=3.0), "another window's move never showed"
    took = time.monotonic() - t0
    assert _tree_paths(app) == [p for p in _order(app, "now")]
    assert took < (1.2 if BENCH else 3.0), took

    # An availability change (a file deleted outside the app): the worker's poll sees its folder change, the sync
    # marks it missing, and the tree drops the row within one poll.
    gone = _tree_paths(app)[0]
    os.remove(os.path.join(app.data_root, *gone.split("/")))
    t0 = time.monotonic()
    assert _pump(app, lambda: gone not in _tree_paths(app), timeout=3.0), "a deleted file stayed in the tree"
    assert time.monotonic() - t0 < (1.2 if BENCH else 3.0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_move_between_the_first_draw_and_the_workers_start_still_shows(window, language, monkeypatch):
    """The tree is drawn at open, the worker starts after it: another window's move in between is checked against
    the versions the tree was drawn at (the worker's first poll), never taken as the worker's starting point."""
    _store_library(language)
    app = window(language)                               # SURASURA_NO_UI_TIMERS: no worker yet
    assert _pump(app, lambda: bool(_tree_paths(app)))
    app._refresh_from_focus = lambda: None
    shown = _tree_paths(app)
    _other_process(language, "ids = store.ids('now')\nstore.move([ids[0]], 'now', after_id=ids[-1])\n")
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    app._start_store_worker()
    assert _pump(app, lambda: _tree_paths(app) != shown, timeout=3.0), "a move made before the worker started never showed"
    assert _tree_paths(app) == _order(app, "now")


# --- S1.1's smoothness rows 1, 2, 4: the worker, at 2k and 20k ------------------------------------------- #

def _big_library(language, n):
    """`n` files on disk in show folders (a 6+ Months heavy shape: NOW 1 %, Soon ~45 %, the rest 6+ Months),
    migrated into a store."""
    data_dir, user_files_dir = roots(language)
    words = names(language)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    shares = (("now", max(1, n // 100)), ("soon", n * 45 // 100))
    counts = dict(shares)
    counts["goal"] = n - counts["now"] - counts["soon"]
    k = 0
    for tier in ls.ANALYSED:
        folder = ls.FOLDER_OF_TIER[tier]
        for i in range(counts[tier]):
            show = words[(k // 25) % len(words)] + str(k // 25)
            rel = f"{folder}/{show}/{i:05d}.srt"
            path = os.path.join(data_dir, folder, show, f"{i:05d}.srt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(show)
            doc["schedule"][ls.TIERS[tier][0]].append(ls.make_entry(rel, "Disk Sync", "subtitle"))
            k += 1
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return data_dir


@pytest.mark.parametrize("size", [2000, 20000])
def test_open_and_focus_walk_on_the_worker_never_the_windows_thread(window, size, monkeypatch):
    """Store mode: opening walks the disk once, on the worker; a focus return asks the worker for a sync and
    redraws only if the store's versions moved — the window's thread never walks (2.4's JSON path: ≈100 ms at 2k,
    ≈0.9 s at 20k on it, per focus). The figures are printed for the as-built notes."""
    language = "ja"
    _big_library(language, size)
    # One sync is one walk: in this process under SYNC_IN_PROCESS_AT items, in a process of its own above it
    # (20k), where an in-process count of walk_library would see none. Both are counted, with the thread asking.
    walks, in_process = [], []
    real_sync, real_walk = ls.sync_for_window, ls.walk_library

    def counted(store, *args, **kwargs):
        # Counted when it ends: a focus return asked while a sync still runs (20k: its own process, slower on a busy
        # machine) shares one follow-up by design, so the next focus return waits for this one to finish.
        try:
            return real_sync(store, *args, **kwargs)
        finally:
            walks.append(threading.current_thread())
    monkeypatch.setattr(ls, "sync_for_window", counted)
    monkeypatch.setattr(ls, "walk_library", lambda d: in_process.append(threading.current_thread()) or real_walk(d))
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    t0 = time.perf_counter()
    app = window(language)
    assert _pump(app, lambda: len(walks) >= 1 and bool(_tree_paths(app)), timeout=60)
    opened = time.perf_counter() - t0
    _pump(app, lambda: False, timeout=0.6)
    assert len(walks) == 1, f"open walked {len(walks)} times"

    focus = []
    for _ in range(5):
        t1 = time.perf_counter()
        app._refresh_from_focus()
        focus.append(time.perf_counter() - t1)
        _pump(app, lambda: len(walks) >= 2 + _, timeout=30)
    assert all(t is not threading.main_thread() for t in walks + in_process), "a walk ran on the window's thread"
    assert len(walks) == 6, f"{len(walks)} syncs for an open and five focus returns"
    focus.sort()
    print(f"\n[store mode] {size} files: open {opened * 1000:.0f} ms (tree shown), "
          f"focus on the window's thread p50 {focus[2] * 1000:.1f} ms, max {focus[-1] * 1000:.1f} ms")
    assert focus[2] < (0.02 if BENCH else 0.25), focus


@pytest.mark.parametrize("size", [2000, 20000])
def test_a_drag_in_store_mode_is_one_store_command_and_one_redraw(window, size, monkeypatch):
    """S1.1's row 2: the 20k drag saved 226 ms and parsed the manifest twice. In store mode a drag is one `move`
    (~1 ms) and one redraw of the visible tier; timed in NOW and in the largest tier (6+ Months)."""
    language = "ja"
    data_dir = _big_library(language, size)
    app = window(language)
    timings = {}
    for folder, tier in (("HighPriority", "now"), ("GoalContent", "goal")):
        app.target_folder_var.set(folder)
        app.tree = app.tier_trees[folder]
        app.refresh_file_list(force=True)
        rows = [os.path.join(data_dir, *p.split("/")) for p in _order(app, tier)]
        took = []
        for i in range(5):
            t0 = time.perf_counter()
            app.move_manifest_items_relative([rows[i]], rows[-1], "after")
            took.append(time.perf_counter() - t0)
        took.sort()
        timings[tier] = (len(rows), took[2])
        moved = [os.path.relpath(r, data_dir).replace("\\", "/") for r in reversed(rows[:5])]
        assert _order(app, tier)[-5:] == moved, "each drag lands right after the same anchor"
    print(f"\n[store mode] drag at {size}: " + ", ".join(f"{t} ({n} rows) p50 {s * 1000:.0f} ms"
                                                      for t, (n, s) in timings.items()))
    assert timings["now"][1] < (0.1 if BENCH else 1.0)


# --- L2.1 review (reviews/L2.1-adversary.md): Undo against the worker, failures, the banner, the first check --- #

def _graduated_window(window, language, monkeypatch, timers=False):
    data_dir, user_files_dir, _doc = _store_library(language)
    if timers:
        monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    app = window(language)
    assert _pump(app, lambda: bool(_tree_paths(app)))
    return data_dir, user_files_dir, app


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_remove_holds_the_workers_poll_off_its_put_back(window, language, monkeypatch):
    """Adversary #1: Undo-Remove puts a file back into a folder the worker polls every 0.5 s; a sync in between
    would list the returned file as a new row and make the restore conflict (every later Undo stuck). The file
    work and the commit hold the worker off: the item comes back in its place, once."""
    data_dir, _uf, app = _graduated_window(window, language, monkeypatch, timers=True)
    app.target_folder_var.set("HighPriority")
    before = _order(app, "now")
    victim = os.path.join(data_dir, *before[1].split("/"))
    with patch.object(app, "_resolve_items_to_paths", return_value=[victim]), \
         patch.object(app.tree, "selection", return_value=("row",)):
        app.remove_files()
    assert not os.path.exists(victim)
    real = ls.put_back

    def slow_put_back(*a, **k):
        out = real(*a, **k)
        time.sleep(1.2)                                  # two of the worker's polls pass mid-command
        return out
    monkeypatch.setattr(ls, "put_back", slow_put_back)
    app.undo_last_action()
    assert "Undid" in app.status_var.get(), app.status_var.get()
    assert os.path.exists(victim)
    assert _order(app, "now") == before, "the item is back in its place, listed once"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failed_undo_puts_its_files_back_and_can_be_tried_again(window, language, monkeypatch):
    """Adversary #1: Undo-Remove's commit fails (busy) → the put-back files return to `.trash`, the record stays,
    and the next Undo works; Undo-Add's file work failing partway → the files already trashed come back."""
    data_dir, _uf, app = _graduated_window(window, language, monkeypatch)
    app.target_folder_var.set("HighPriority")
    before = _order(app, "now")
    victims = [os.path.join(data_dir, *p.split("/")) for p in before[:2]]
    with patch.object(app, "_resolve_items_to_paths", return_value=victims), \
         patch.object(app.tree, "selection", return_value=("row",)):
        app.remove_files()
    with patch.object(ls.Store, "undo", side_effect=ls.StoreBusy("held")):
        app.undo_last_action()
    assert not any(os.path.exists(v) for v in victims), "the put-back files went back to the trash"
    app.undo_last_action()
    assert all(os.path.exists(v) for v in victims) and _order(app, "now") == before

    pick = [touch(os.path.join(os.environ["SURASURA_TEST_ROOT"], "incoming"), f"{names(language)[i]}.txt")
            for i in (44, 45)]
    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=pick):
        app.add_files()
    added = [os.path.join(data_dir, "HighPriority", os.path.basename(p)) for p in pick]
    assert all(os.path.exists(a) for a in added)
    calls = []
    real = ls.trash_file

    def fail_second(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("held open by a reader")
        return real(*a, **k)
    monkeypatch.setattr(ls, "trash_file", fail_second)
    app.undo_last_action()
    assert all(os.path.exists(a) for a in added), "the file already trashed came back"
    monkeypatch.setattr(ls, "trash_file", real)
    app.undo_last_action()
    assert not any(os.path.exists(a) for a in added)


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_graduate_strips_only_the_blocks_of_what_it_put_back(window, language, monkeypatch, tmp_path):
    """Adversary #2: graduate A and B from NOW; B is moved by another window; Undo puts A back and strips A's
    GraduatedList block only — B stays graduated with its words listed."""
    data_dir, user_files_dir, app = _graduated_window(window, language, monkeypatch)
    app.target_folder_var.set("HighPriority")
    now = _order(app, "now")
    a, b = (os.path.join(data_dir, *p.split("/")) for p in now[:2])
    grad = os.path.join(user_files_dir, "GraduatedList.txt")
    with open(grad, "w", encoding="utf-8") as f:
        f.write("# Graduated Words\n")
    index = {os.path.basename(a): [names(language)[46]], os.path.basename(b): [names(language)[47]]}
    with patch.object(app, "_resolve_items_to_paths", return_value=[a, b]), \
         patch.object(app.tree, "selection", return_value=("row",)), \
         patch.object(app, "_load_graduate_index", return_value=index):
        app.graduate_content()
    store = app._store()
    b_id = store.item_id(now[1])
    _other_process(language, f"store.set_tier([{b_id}], 'goal')\nstore.set_tier([{b_id}], 'graduated')\n")
    app.undo_last_action()
    text = open(grad, encoding="utf-8").read()
    assert now[0] not in text and now[1] in text, text


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failed_add_says_so_and_never_reports_success(window, language, monkeypatch):
    """Adversary #3: the store's insert fails (busy): the copies go to the trash and the window says nothing was
    added — never "Successfully added"."""
    data_dir, _uf, app = _graduated_window(window, language, monkeypatch)
    app.target_folder_var.set("HighPriority")
    pick = touch(os.path.join(os.environ["SURASURA_TEST_ROOT"], "incoming"), f"{names(language)[48]}.txt")
    shown = []
    with patch("app.content_importer_gui.filedialog.askopenfilenames", return_value=[pick]), \
         patch.object(ls.Store, "insert", side_effect=ls.StoreBusy("held")), \
         patch("app.content_importer_gui.messagebox.showinfo", side_effect=lambda *a, **k: shown.append(a)):
        app.add_files()
    assert shown == [], shown
    assert "nothing was changed" in app.status_var.get()
    assert not os.path.exists(os.path.join(data_dir, "HighPriority", os.path.basename(pick)))


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_idle_window_never_opens_the_database_on_its_thread(window, language, monkeypatch):
    """Adversary #4: the banner's state comes from the worker; an idle window's drain (every 100 ms) probes
    nothing on the window's thread."""
    _data, _uf, app = _graduated_window(window, language, monkeypatch, timers=True)
    _pump(app, lambda: False, timeout=1.0)                       # open settles
    probes = []
    real = ls._probe
    monkeypatch.setattr(ls, "_probe", lambda *a, **k: (probes.append(threading.current_thread()), real(*a, **k))[1])
    _pump(app, lambda: False, timeout=1.5)
    assert [t for t in probes if t is threading.main_thread()] == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failed_sync_is_asked_again_at_the_next_poll(window, language, monkeypatch):
    """Adversary #8: a sync that fails (a timeout at 20k+) is retried by the next poll, not left for a focus."""
    calls = []

    def flaky(store):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("sync timed out")
        return None
    _data, _uf, app = _graduated_window(window, language, monkeypatch, timers=True)
    _pump(app, lambda: False, timeout=0.6)
    monkeypatch.setattr(ls, "sync_for_window", flaky)
    app._request_sync()                                          # fails…
    assert _pump(app, lambda: len(calls) >= 2, timeout=3.0), calls   # …and the next poll walks again


def test_a_block_over_a_thousand_items_moves_behind_a_progress_mark(window, monkeypatch):
    """Adversary #9 / intent #4 (§6.12): a move of over 1,000 items shows the busy cursor before the command."""
    _big_library("ja", 3000)
    app = window("ja")
    app.target_folder_var.set("GoalContent")
    app.tree = app.tier_trees["GoalContent"]
    app.refresh_file_list(force=True)
    data_dir = app.data_root
    rows = [os.path.join(data_dir, *p.split("/")) for p in _order(app, "goal")]
    cursors = []
    real = ls.Store.move
    monkeypatch.setattr(ls.Store, "move", lambda self, *a, **k: (cursors.append(str(app.root.cget("cursor"))),
                                                                real(self, *a, **k))[1])
    app.move_manifest_items_relative(rows[:1200], rows[-1], "after")
    app.move_manifest_items_relative(rows[1200:1201], rows[-1], "after")
    assert cursors == ["watch", ""], cursors


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_busy_first_check_never_runs_the_json_code_on_a_store(window, language, monkeypatch, store_helper_spawns):
    """Adversary #10: the database is busy at the window's first look; until the check settles the window
    neither writes the copy (2.4's open sync), nor starts a build, nor takes a change (2.4's Graduate would move
    files) — then it settles into store mode."""
    data_dir, user_files_dir, _doc = _store_library(language)
    copy = read_doc(user_files_dir)
    before = _snapshot(data_dir)
    real = ls.check_mode

    def busy_first(language_, data_dir_, busy_wait=ls.BUSY_AT_OPEN):
        if busy_wait == 0.0 and not getattr(busy_first, "settled", False):
            return "read-only", "busy"
        if busy_wait != 0.0:
            time.sleep(0.8)
            busy_first.settled = True
        return real(language_, data_dir_, busy_wait=busy_wait)
    monkeypatch.setattr(ls, "check_mode", busy_first)
    app = window(language)
    app.root.update()
    assert app._store_unsettled()
    first = os.path.join(data_dir, *_tree_paths(app)[0].split("/")) if _tree_paths(app) else None
    app.target_folder_var.set("HighPriority")
    with patch.object(app, "_resolve_items_to_paths", return_value=[first]), \
         patch.object(app.tree, "selection", return_value=("row",)):
        app.graduate_content()
    app._sync_disk_to_manifest()
    assert "busy" in app.status_var.get()
    assert read_doc(user_files_dir) == copy and _snapshot(data_dir) == before
    assert store_helper_spawns == []
    assert _pump(app, lambda: app._store_mode() == "store", timeout=5.0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_windows_first_focus_during_the_opens_walk_adds_no_second_walk(window, language, monkeypatch):
    """Smoothness #5 (S1.1 row 4): on a shown window the first FocusIn comes after the worker started; while the
    open's walk runs it asks for none of its own."""
    _store_library(language)
    walks = []
    real = ls.sync_for_window
    monkeypatch.setattr(ls, "sync_for_window", lambda s: walks.append(1) or time.sleep(0.5) or real(s))
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    app = window(language)
    assert _pump(app, lambda: bool(walks))                      # the open's walk is running
    app._refresh_from_focus()                                    # the window's own first focus
    _pump(app, lambda: False, timeout=1.5)
    assert len(walks) == 1, walks
    app._refresh_from_focus()                                    # a real return later: a walk of its own
    assert _pump(app, lambda: len(walks) == 2, timeout=3.0)


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_windows_change_waits_for_a_drag_to_end(window, language, monkeypatch):
    """Smoothness #6: a redraw drops the tree's selection; one arriving mid-drag (a hato drop, another window's
    move) waits for the button's release, then shows."""
    _store_library(language)
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    app = window(language)
    assert _pump(app, lambda: bool(_tree_paths(app)))
    _pump(app, lambda: False, timeout=0.8)
    app._refresh_from_focus = lambda: None
    shown = _tree_paths(app)
    app._drag_item = app.tree.get_children("")[0]                # the button is down on a row
    _other_process(language, "ids = store.ids('now')\nstore.move([ids[0]], 'now', after_id=ids[-1])\n")
    _pump(app, lambda: False, timeout=1.5)
    assert _tree_paths(app) == shown, "redrawn mid-drag"
    app.on_drag_stop(types.SimpleNamespace(y=-1))                # released over nothing
    assert _pump(app, lambda: _tree_paths(app) != shown, timeout=2.0)


# --- L3.2 The library watched, not checked ---------------------------------------------------------------- #

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows' change reports")


def _settled_window(window, language, monkeypatch):
    """A store-mode window whose open has walked and whose watch is up (its worker idle from here)."""
    _store_library(language)
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    app = window(language)
    assert _pump(app, lambda: bool(_tree_paths(app)) and app.__dict__.get("_lookout") is not None
                 and app._open_walked, timeout=10)
    _pump(app, lambda: False, timeout=0.5)                       # the open's own commit's ring, drained
    return app


@windows_only
@pytest.mark.parametrize("language", LANGUAGES)
def test_an_idle_watched_window_never_wakes_its_worker(window, language, monkeypatch):
    """The old poll woke the worker twice a second, all day; watched, an idle window's worker sleeps until the
    hourly round (the Tk drain's 100 ms timer is the window's own, counted apart)."""
    app = _settled_window(window, language, monkeypatch)
    lookout = app._lookout
    assert lookout.tree.alive and not lookout.slow
    assert lookout.timeout() > 3000                              # the next thing due: the round, an hour away
    before = lookout.wakes
    _pump(app, lambda: False, timeout=1.5)
    assert lookout.wakes == before, f"{lookout.wakes - before} wake-ups idle"


@windows_only
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_dropped_into_a_folder_without_items_shows_through_the_watch(window, language, monkeypatch):
    """The old poll only stat'ed folders that hold items: a drop into a new show folder waited for a focus. The
    watch reports it; its folder alone is synced (a scoped sync), and the tree shows it."""
    app = _settled_window(window, language, monkeypatch)
    app._refresh_from_focus = lambda: None                       # only the watch may bring it in here
    scoped = []
    real = ls.sync_for_window
    monkeypatch.setattr(ls, "sync_for_window", lambda s, folders=None: scoped.append(folders) or real(s, folders))
    word = names(language)[30]
    rel = f"HighPriority/{word}/{word}_第01話.srt"           # NOW: the tab the tree shows
    t0 = time.monotonic()
    touch(app.data_root, rel, f"{word}\n")
    assert _pump(app, lambda: rel in _tree_paths(app), timeout=5.0), "a drop into a new folder never showed"
    took = time.monotonic() - t0
    assert [f"HighPriority/{word}"] in scoped, scoped              # its folder, never the whole library
    assert took < (1.0 if BENCH else 5.0), took


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_watch_the_slow_look_runs_in_front_only(window, language, monkeypatch):
    """No watch (macOS / Linux, a drive that can't report): the folders are looked at every SLOW_S while the
    window is in front, never behind or minimized; a drop is still found while in front."""
    from app import library_watch as lw
    monkeypatch.setattr(lw, "watchable", lambda: False)
    monkeypatch.setattr(lw, "SLOW_S", 0.1)
    app = _settled_window(window, language, monkeypatch)
    lookout = app._lookout
    assert lookout.slow and lookout.tree.state == "fallback"
    app._set_front(True)                                         # in front (the test's window may never get focus)
    _pump(app, lambda: lookout.slow_looks >= 3, timeout=3.0)
    assert lookout.slow_looks >= 3
    app._set_front(False)                                        # behind, or minimized (<Unmap>)
    _pump(app, lambda: False, timeout=0.3)
    behind = lookout.slow_looks
    _pump(app, lambda: False, timeout=1.0)
    assert lookout.slow_looks == behind, "looked while behind"
    app._set_front(True)
    rel = _tree_paths(app)[0]
    os.remove(os.path.join(app.data_root, *rel.split("/")))
    assert _pump(app, lambda: rel not in _tree_paths(app), timeout=3.0), "the slow look never found the change"
