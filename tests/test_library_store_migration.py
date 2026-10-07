"""WP-L4 of the library store (Library_Store_Spec.md §10): migration, rebuild, re-import, Repair and JSON
mode — one builder for all of them.

Why these matter: 2.5's migration moves the user's library order once, so it must keep every row in its
PHASE's tier (on the laptop library 851 rows sit in another tier's folder), keep 267 dead rows restorable,
and prove before committing that Generate reads exactly what it read (I1). An older Surasura or a sync
tool may edit the copy afterwards: re-import applies small changes, asks first about big ones (Q4-8), never
trashes anything, and keeps graduated items graduated. Every test runs for Japanese and Chinese alike.
"""

import json
import os
import subprocess
import sys
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, entry, laptop_library, library, migrated, names,
                                              read_doc, roots, subprocess_env, touch, write_manifest, _episodes)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _build(language, doc):
    data_dir, user_files_dir = roots(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store(language, data_dir, user_files_dir)


def _report(language):
    return open(os.path.join(roots(language)[1], "library_migration_report.txt"), encoding="utf-8").read()


# --- 1. the real-shaped manifests ---------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_laptop_shaped_library_migrates(language):
    """2,034 rows, 267 dead, 851 in another tier's folder, 53 doubled titles, 1,818 with unknown entry keys:
    every row keeps its phase's tier, both proofs pass, the copy is the manifest plus one key."""
    from app import analyzer
    data_dir, user_files_dir, doc = laptop_library(language)
    write_manifest(user_files_dir, doc)
    assert 1_100_000 < os.path.getsize(ls.manifest_path(user_files_dir)) < 1_500_000   # the laptop's 1.28 MB
    before = analyzer.resolve_found_files(language, verbose=False)
    store = _build(language, doc)
    for phase in ls.PHASES:
        tier = ls.TIER_OF_PHASE[phase]
        assert [e["physical_path"] for _i, e, _a in store.ordered(tier)] == \
            [e["physical_path"] for e in doc["schedule"][phase]], phase
    assert store.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'missing'").fetchone()[0] == 267
    copy = read_doc(user_files_dir)
    copy.pop("surasura_library")
    assert copy == doc
    assert analyzer.resolve_found_files(language, verbose=False) == before, "Generate reads the same list (I1)"
    assert "Rows: NOW 143 · Soon 154 · 6+ Months 1737" in _report(language)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_dev_tree_shaped_library_migrates(language):
    data_dir, user_files_dir = roots(language)
    schedule = {}
    start = 0
    for phase, count in zip(ls.PHASES, (184, 884, 919)):
        folder = ls.TIERS[ls.TIER_OF_PHASE[phase]][1]
        rels = _episodes(language, folder, count, start=start)
        start += count
        for rel in rels:
            touch(data_dir, rel)
        schedule[phase] = [entry(rel) for rel in rels]
    doc = {"metadata": {"created": "2026-07-17"}, "schedule": schedule}
    store = _build(language, doc)
    assert [len(store.ids(t)) for t in ls.ANALYSED] == [184, 884, 919]
    assert store.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'missing'").fetchone()[0] == 0
    store.close()


# --- 2. the Graduated folder; 3. piece ids -------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_graduated_folder_comes_in_as_graduated(language):
    data_dir, user_files_dir, doc = library(language)
    w = names(language)
    grads = [f"Graduated/{w[5]}/{w[6]}_{n}.srt" for n in range(3)] + [f"Graduated/{w[7]}.txt"]
    for rel in grads:
        touch(data_dir, rel)
    touch(data_dir, "Graduated/cover.jpg")                     # not content
    write_manifest(user_files_dir, doc)
    store = _build(language, doc)
    got = [e["physical_path"] for _i, e, _a in store.ordered("graduated")]
    assert sorted(got) == sorted(grads)
    assert all(store.item(i)["graduated_at"] is None for i in store.ids("graduated"))     # dated "Earlier"
    sched = store.schedule()
    for phase in ls.PHASES:
        assert [e["physical_path"] for e in sched[phase]] == [e["physical_path"] for e in doc["schedule"][phase]]
    assert all(not r["physical_path"].startswith("Graduated/") for p in ls.PHASES for r in sched[p])
    assert store.sync_disk() is None, "disk sync never walks Graduated/"
    report = _report(language)
    assert "Graduated folder files imported: 4" in report and "Pieces made:" in report
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_piece_ids_are_runs_and_survive_a_rebuild(language):
    data_dir, user_files_dir, doc = library(language, shows=3, episodes=4)
    soon = doc["schedule"]["PHASE_2_SOON"]
    soon.insert(2, soon.pop(9))                                # one show split into two runs by another's episode
    write_manifest(user_files_dir, doc)
    store = _build(language, doc)
    pieces = [store.item(i)["piece_id"] for i in store.ids("soon")]
    folders = [store.item(i)["parent_folder"] for i in store.ids("soon")]
    runs = []
    for p, f in zip(pieces, folders):
        if f and (not runs or runs[-1] != (p, f)):
            runs.append((p, f))
    assert len({p for p, _f in runs}) == len(runs), "each run its own piece"
    assert len({f for _p, f in runs}) < len(runs), "a folder in two runs gets two pieces"
    by_id = {i: store.item(i)["piece_id"] for t in ls.ANALYSED for i in store.ids(t)}
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".old")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert {i: store.item(i)["piece_id"] for t in ls.ANALYSED for i in store.ids(t)} == by_id
    store.close()


# --- 4. normalisation; 5. the schedule() proof -------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_normalisation_one_shape_at_a_time(language):
    data_dir, user_files_dir, doc = library(language)
    now = doc["schedule"]["PHASE_1_NOW"]
    first = now[0]["physical_path"]
    now += ["not an entry", {"type": "Folder", "physical_path": "HighPriority/x"}, {"title": "no path"},
            {"physical_path": ""}, dict(now[1], physical_path=first.replace("/", "\\")),
            dict(now[2], physical_path="HighPriority/" + names(language)[8] + "\udc81.srt")]
    if sys.platform == "win32":
        now.append(dict(now[3], physical_path=first.upper()))
    del doc["schedule"]["PHASE_2_SOON"]
    doc["schedule"]["PHASE_9_UNKNOWN"] = [{"kept": True}]
    norm = ls.normalise(doc)
    report = "\n".join(norm.report)
    for needle in ("not an object", "a Folder row", "no file path", "can't be encoded", "duplicates",
                   "PHASE_2_SOON: missing"):
        assert needle in report, needle
    write = ls.manifest_path(user_files_dir)
    os.makedirs(user_files_dir, exist_ok=True)
    with open(write, "w", encoding="utf-8", errors="surrogatepass") as f:
        json.dump(doc, f, indent=2, ensure_ascii=True)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    copy = read_doc(user_files_dir)
    assert copy["schedule"]["PHASE_9_UNKNOWN"] == [{"kept": True}]
    assert copy["schedule"]["PHASE_1_NOW"] == norm.tiers["now"]
    assert copy["schedule"]["PHASE_2_SOON"] == []
    assert "can't be encoded" in _report(language)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_previews_own_manifest_shape_migrates(language):
    data_dir, user_files_dir = roots(language)
    rel = "HighPriority/" + names(language)[9] + " [abcdefghijk].txt"
    touch(data_dir, rel)
    doc = {"schedule": {"PHASE_1_NOW": [{"title": rel.split("/")[1], "physical_path": rel, "parent_folder": "",
                                         "origin_source": "YouTube Preview", "type": "File", "status": "active"}]}}
    store = _build(language, doc)
    assert store.schedule()["PHASE_1_NOW"][0]["source_type"] is None
    copy = read_doc(user_files_dir)
    assert set(copy["schedule"]) == set(ls.PHASES)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_missing_and_a_null_source_type_read_alike(language):
    data_dir, user_files_dir, doc = library(language)
    now = doc["schedule"]["PHASE_1_NOW"]
    del now[0]["source_type"]
    now[1]["source_type"] = None
    store = _build(language, doc)
    sched = store.schedule()["PHASE_1_NOW"]
    assert sched[0]["source_type"] is None and sched[1]["source_type"] is None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_column_altered_on_purpose_fails_the_proof_and_rolls_back(language, monkeypatch):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    real = ls._columns
    monkeypatch.setattr(ls, "_columns", lambda e: real(e)[:2] + ("epub",))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert ls.check_mode(language, data_dir) == ("json", "migration failed")
    db = ls.library_db_path(language, data_dir)
    conn = ls._connect(db, "reader")
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0, "the rows rolled back"
    assert json.loads(conn.execute("SELECT value FROM meta WHERE key = 'migration_failed'").fetchone()[0])["error"]
    conn.close()


# --- 6. awkward files ---------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_bom_manifest_migrates(language):
    data_dir, user_files_dir, doc = library(language)
    os.makedirs(user_files_dir, exist_ok=True)
    with open(ls.manifest_path(user_files_dir), "w", encoding="utf-8-sig") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("shape", ["damaged", "empty", "missing"])
def test_no_usable_manifest_waits_for_the_content_manager(language, shape):
    """The headless paths wait; the Content Manager's helper (`--from-folders`) sets a damaged file aside
    and builds from the folders, the same in ja and zh."""
    data_dir, user_files_dir, doc = library(language)
    os.makedirs(user_files_dir, exist_ok=True)
    target = ls.manifest_path(user_files_dir)
    if shape == "damaged":
        open(target, "w", encoding="utf-8").write('{"schedule": {"PHASE_1_NOW": [')
    elif shape == "empty":
        open(target, "w").close()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert ls.open_store(language, data_dir, user_files_dir) is None
    assert ls.maintain(language, data_dir, user_files_dir, from_folders=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    walked = {t: ls.walk_tree(os.path.join(data_dir, ls.FOLDER_OF_TIER[t]), ls.FOLDER_OF_TIER[t])[0]
              for t in ls.ANALYSED}
    for tier in ls.ANALYSED:
        assert sorted(e["physical_path"] for _i, e, _a in store.ordered(tier)) == sorted(r for r, _s, _m in walked[tier])
    if shape != "missing":
        trash = os.listdir(os.path.join(user_files_dir, ".trash"))
        assert any(f.startswith("master_manifest.") for f in trash), "set aside, never deleted"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_manifest_no_row_of_which_resolves_is_migrated_not_replaced(language):
    data_dir, user_files_dir, doc = library(language)
    dead = {"schedule": {"PHASE_1_NOW": [entry("HighPriority/" + names(language)[11] + "/gone.srt")]}}
    write_manifest(user_files_dir, dead)
    original = open(ls.manifest_path(user_files_dir), "rb").read()
    assert ls.maintain(language, data_dir, user_files_dir, export=False) == ls.EXIT_DONE
    assert open(ls.manifest_path(user_files_dir), "rb").read() == original, "never set aside"
    store = ls.open_store(language, data_dir, user_files_dir)
    summary = store.sync_disk()                                # then the folders' untracked files
    assert len(summary["added"]) == sum(len(doc["schedule"][p]) for p in ls.PHASES)
    gone = store.item_id(dead["schedule"]["PHASE_1_NOW"][0]["physical_path"])
    assert store.item(gone)["availability"] == "missing"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_read_error_is_retried_never_set_aside(language, monkeypatch):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    with monkeypatch.context() as m:
        m.setattr(ls, "read_manifest", lambda path: (_ for _ in ()).throw(ls.ManifestUnreadable("locked")))
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_FAILED
    assert os.path.exists(ls.manifest_path(user_files_dir))
    assert not os.path.exists(os.path.join(user_files_dir, ".trash"))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE


def test_a_half_written_file_is_read_again(tmp_path, monkeypatch):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"schedule": {}}), encoding="utf-8")
    real = os.fstat
    calls = []

    class Moved:
        def __init__(self, st):
            self.st_mtime_ns, self.st_size = st.st_mtime_ns + 1, st.st_size

    def fstat(fd):
        calls.append(fd)
        st = real(fd)
        return Moved(st) if len(calls) == 2 else st

    monkeypatch.setattr(os, "fstat", fstat)
    doc, _stat, problem = ls.read_manifest(str(path))
    assert doc == {"schedule": {}} and problem is None and len(calls) == 4


# --- 7. races, crashes, failure ----------------------------------------------------------------- #

_MIGRATE = """
import sys
from app import library_store as ls
lang, data, uf, slow = sys.argv[1:5]
if slow == "slow":
    real = ls._prove
    def prove(store, norm):
        real(store, norm)
        print("inside", flush=True)
        import time; time.sleep(60)
    ls._prove = prove
sys.exit(ls.maintain(lang, data, uf))
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_helpers_migrating_at_once(language):
    data_dir, user_files_dir, doc = laptop_library(language)
    write_manifest(user_files_dir, doc)
    procs = [subprocess.Popen([sys.executable, "-c", _MIGRATE, language, data_dir, user_files_dir, "-"],
                              cwd=REPO, env=subprocess_env()) for _ in range(2)]
    codes = sorted(p.wait(120) for p in procs)
    assert codes[0] == ls.EXIT_DONE and codes[1] in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    store = ls.open_store(language, data_dir, user_files_dir)
    assert sum(len(store.ids(t)) for t in ls.ANALYSED) == 2034
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_write_during_the_build_is_re_imported(language, monkeypatch):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    real = ls._prove

    def prove_then_save(store, norm):
        real(store, norm)
        edited = json.loads(json.dumps(doc))
        edited["schedule"]["PHASE_1_NOW"].insert(0, edited["schedule"]["PHASE_3_LATER"].pop(2))
        write_manifest(user_files_dir, edited)                # a JSON-mode window saves meanwhile

    monkeypatch.setattr(ls, "_prove", prove_then_save)
    assert ls.maintain(language, data_dir, user_files_dir, export=False) == ls.EXIT_DONE
    monkeypatch.setattr(ls, "_prove", real)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.ids("now")[0] == store.item_id(doc["schedule"]["PHASE_3_LATER"][2]["physical_path"])
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_crash_mid_migration(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    original = open(ls.manifest_path(user_files_dir), "rb").read()
    proc = subprocess.Popen([sys.executable, "-c", _MIGRATE, language, data_dir, user_files_dir, "slow"], cwd=REPO,
                            env=subprocess_env(), stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "inside"
    proc.kill()
    proc.wait(10)
    assert open(ls.manifest_path(user_files_dir), "rb").read() == original, "the JSON untouched"
    assert ls.open_store(language, data_dir, user_files_dir) is None
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert len(store.ids("now")) == len(doc["schedule"]["PHASE_1_NOW"])
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failed_migration_is_json_mode_and_retries_only_when_asked(language, monkeypatch):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)

    def boom(store, norm):
        raise RuntimeError("an unexpected manifest")

    monkeypatch.setattr(ls, "_prove", boom)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert ls.open_store(language, data_dir, user_files_dir) is None
    for _ in range(10):                                        # ten JSON-mode saves, each a trigger
        write_manifest(user_files_dir, doc)
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    backups = [f for f in os.listdir(os.path.join(user_files_dir, ".trash")) if f.startswith("master_manifest.")]
    assert len(backups) == 1, backups
    monkeypatch.setattr(ls, "_prove", lambda store, norm: None)
    assert ls.maintain(language, data_dir, user_files_dir, retry=True) == ls.EXIT_DONE   # Try again
    assert ls.open_store(language, data_dir, user_files_dir) is not None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_app_version_retries_a_failed_migration(language, monkeypatch):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    monkeypatch.setattr(ls, "_prove", lambda s, n: (_ for _ in ()).throw(RuntimeError("x")))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    monkeypatch.setattr(ls, "_prove", lambda s, n: None)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    monkeypatch.setattr(ls, "_app_version", lambda: "9.9.9")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE


# --- 8. versions at migration; 9. JSON mode ------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("csv_newer", [False, True])
def test_versions_at_migration(language, csv_newer):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    csv = os.path.join(os.environ["SURASURA_TEST_ROOT"], "results", "priority_learning_list.csv")
    os.makedirs(os.path.dirname(csv), exist_ok=True)
    open(csv, "w").close()
    shift = 60 if csv_newer else -60
    st = os.stat(ls.manifest_path(user_files_dir))
    os.utime(csv, (st.st_mtime + shift, st.st_mtime + shift))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    v, meta = store.versions(), store.meta()
    assert v["epoch"] == 1 and meta["log_seq"] == 0
    assert v["analysed_order_version"] == (v["order_version"] if csv_newer else 0)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_window_switches_once_the_store_is_ready(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    opener = ls.StoreOpener(language, data_dir, user_files_dir)
    assert opener.check() == "json" and opener.handle() is None
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert opener.check() == "store" and opener.handle() is not None
    opener.handle().close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_json_mode_save_with_no_store_at_this_key_is_re_imported(language, tmp_path):
    """A copied Surasura folder (a new key, no database): its JSON-mode save is kept, then re-imported
    when its store is built from the copy."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    store.close()
    moved = str(tmp_path / "moved" / "data" / language)
    import shutil
    shutil.copytree(data_dir, moved)
    assert ls.open_store(language, moved, user_files_dir) is None
    doc = read_doc(user_files_dir)
    doc["schedule"]["PHASE_1_NOW"].insert(0, doc["schedule"]["PHASE_2_SOON"].pop(3))
    ls.json_mode_save(language, moved, user_files_dir, doc)
    assert ls.maintain(language, moved, user_files_dir) == ls.EXIT_DONE
    other = ls.open_store(language, moved, user_files_dir)
    assert other.ids("now")[0] == other.item_id(doc["schedule"]["PHASE_1_NOW"][0]["physical_path"])
    other.close()


# --- 10. re-import ------------------------------------------------------------------------------- #

def _edit(language, fn):
    _d, user_files_dir = roots(language)
    doc = read_doc(user_files_dir)
    fn(doc)
    write_manifest(user_files_dir, doc)
    return doc


@pytest.mark.parametrize("language", LANGUAGES)
def test_reimport_rules_one_to_five(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    grad = store.ids("soon")[0]
    store.set_tier([grad], "graduated")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    grad_path = store.item(grad)["rel_path"]
    unlisted = store.ids("goal")[4]
    unlisted_prev = store.ids("goal")[3]
    old_rel = store.item(ids[5])["rel_path"]
    new_rel = old_rel.replace(".srt", "_1.srt")                 # an older version's in-place rename
    os.rename(os.path.join(data_dir, old_rel), os.path.join(data_dir, new_rel))
    added_rel = "LowPriority/" + names(language)[12] + "/new.srt"
    touch(data_dir, added_rel)

    def change(doc):
        s = doc["schedule"]
        s["PHASE_1_NOW"].insert(0, s["PHASE_1_NOW"].pop(3))                       # rule 1: order
        s["PHASE_2_SOON"].insert(0, s["PHASE_3_LATER"].pop(0))                     # rule 1: tier
        s["PHASE_1_NOW"].append(entry(grad_path))                                   # rule 2
        for e in s["PHASE_1_NOW"]:
            if e["physical_path"] == old_rel:
                e["physical_path"], e["title"] = new_rel, new_rel.rsplit("/", 1)[1]  # rule 3
        s["PHASE_3_LATER"] = [e for e in s["PHASE_3_LATER"] if store.item_id(e["physical_path"]) != unlisted]
        s["PHASE_2_SOON"].append(entry(added_rel))                                  # rule 5

    doc = _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.ids("now")[0] == ids[3]
    assert store.item(store.item_id(doc["schedule"]["PHASE_2_SOON"][0]["physical_path"]))["tier"] == "soon"
    assert store.item(grad)["tier"] == "graduated", "graduated items stay graduated"
    assert store.item(ids[5])["rel_path"] == new_rel, "renamed: same id, same state"
    goal = store.ids("goal")
    assert unlisted in goal and goal[goal.index(unlisted) - 1] == unlisted_prev, "unlisted: kept in place"
    assert store.ids("soon")[-1] == store.item_id(added_rel)
    assert store.item(store.item_id(added_rel))["entry"] == entry(added_rel)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_reimport_of_2_4_0s_demote_and_graduate(language):
    """2.4.0 still moves files: its Demote (HighPriority → LowPriority) and its Graduate (into Graduated/,
    the row dropped) keep their ids, pairings and Anki links."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    demoted, graduated = ids[1], ids[2]
    with store._writing():
        store.conn.execute("INSERT INTO pairings VALUES ('p1', ?, '{}', 't')", (demoted,))
        store.conn.execute("INSERT INTO anki_links VALUES (?, 77, 'x', 't')", (graduated,))
    d_old = store.item(demoted)["rel_path"]
    g_old = store.item(graduated)["rel_path"]
    d_new = "LowPriority/" + d_old.split("/", 1)[1]
    g_new = "Graduated/" + g_old.split("/", 1)[1]
    for old, new in ((d_old, d_new), (g_old, g_new)):
        os.makedirs(os.path.dirname(os.path.join(data_dir, new)), exist_ok=True)
        os.rename(os.path.join(data_dir, old), os.path.join(data_dir, new))

    def change(doc):
        s = doc["schedule"]
        row = next(e for e in s["PHASE_1_NOW"] if e["physical_path"] == d_old)
        s["PHASE_1_NOW"] = [e for e in s["PHASE_1_NOW"] if e["physical_path"] not in (d_old, g_old)]
        s["PHASE_2_SOON"].insert(0, dict(row, physical_path=d_new, origin_source="Manual Import"))

    _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.item(demoted)["tier"] == "soon" and store.item(demoted)["rel_path"] == d_new
    assert store.item(graduated)["tier"] == "graduated" and store.item(graduated)["rel_path"] == g_new
    assert store.conn.execute("SELECT item_id FROM pairings").fetchone()[0] == demoted
    assert store.conn.execute("SELECT item_id FROM anki_links").fetchone()[0] == graduated
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_a_reimport_moved_skips_an_older_undo(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    mine = store.move([ids[0]], "now", after_id=ids[4])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    first = store.item(ids[0])["rel_path"]

    def change(doc):
        now = doc["schedule"]["PHASE_1_NOW"]
        row = next(e for e in now if e["physical_path"] == first)
        now.remove(row)
        now.insert(8, row)

    _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.undo(mine).notes == ["1 item changed since and was left as it is"]
    store.close()


def _big(language):
    return migrated(language, shows=10, episodes=10)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("kind", ["tiers", "order"])
def test_the_size_guard_asks_before_a_big_change(language, kind):
    store = _big(language)
    data_dir, user_files_dir = roots(language)
    total = sum(len(store.ids(t)) for t in ls.ANALYSED)
    big = int(total * 0.06) + 1

    def change(doc):
        s = doc["schedule"]
        if kind == "tiers":
            for _ in range(big):
                s["PHASE_2_SOON"].append(s["PHASE_3_LATER"].pop(0))
        else:
            later = s["PHASE_3_LATER"]
            later[:big + 1] = later[:big + 1][::-1]

    before = {t: store.ids(t) for t in ls.ANALYSED}
    _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert {t: store.ids(t) for t in ls.ANALYSED} == before, "nothing applied yet"
    assert store.meta().get("reimport_pending")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=False)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert {t: store.ids(t) for t in ls.ANALYSED} == before, "Keep mine"
    assert read_doc(user_files_dir)["schedule"]["PHASE_3_LATER"][0]["physical_path"] == \
        store.ordered("goal")[0][1]["physical_path"], "and the copy is ours again"
    _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=True)
    assert {t: store.ids(t) for t in ls.ANALYSED} != before, "Use that order"
    assert not store.meta().get("reimport_pending")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_return_from_2_4_0s_content_manager(language):
    """2.4.0's Content Manager rewrote the copy (it round-trips `surasura_library`) with a big change:
    the size guard asks first."""
    from app.content_importer_gui import ContentImporterApp
    store = _big(language)
    data_dir, user_files_dir = roots(language)
    cm = ContentImporterApp.__new__(ContentImporterApp)
    cm.get_manifest_path = lambda: ls.manifest_path(user_files_dir)
    cm._warn_manifest_once = lambda *a, **k: None
    cm._manifest_unreadable = False
    cm.language, cm.data_root, cm.user_files_root = language, data_dir, user_files_dir
    cm._store_mode, cm._store = (lambda: "json"), (lambda: None)   # 2.4.0's code: 2.5's JSON mode
    manifest = cm.load_manifest()
    manifest["schedule"]["PHASE_3_LATER"].reverse()
    time.sleep(0.02)        # a tick after the export (GitHub's clock: 15.6 ms): same size + one mtime would read as ours
    cm.save_manifest(manifest)
    assert "surasura_library" in read_doc(user_files_dir)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_written_by_another_store(language):
    """A `User Files` folder from another install: re-imported by rules 1–5 through the size guard — 6 %
    of the items moved asks, 4 % applies — never a rebuild; this store keeps its ids and extra state."""
    store = _big(language)
    data_dir, user_files_dir = roots(language)
    total = sum(len(store.ids(t)) for t in ls.ANALYSED)
    meta = store.meta()

    def foreign(count):
        def change(doc):
            doc["surasura_library"]["store_id"] = "another-install"
            for _ in range(count):
                doc["schedule"]["PHASE_2_SOON"].append(doc["schedule"]["PHASE_3_LATER"].pop(0))
            doc["surasura_library"]["content_sha"] = ls.content_sha(doc)
        return change

    _edit(language, foreign(int(total * 0.06) + 1))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=False)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    soon_before = len(store.ids("soon"))
    _edit(language, foreign(int(total * 0.04)))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert len(store.ids("soon")) == soon_before + int(total * 0.04)
    after = store.meta()
    assert after["store_id"] == meta["store_id"] and after["epoch"] == meta["epoch"], "never a rebuild"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unusable_copy_is_set_aside(language, monkeypatch):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    open(ls.manifest_path(user_files_dir), "w", encoding="utf-8").write("{ not json")
    real = ls._check_copy
    monkeypatch.setattr(ls, "_check_copy", lambda s, retry_wait=1.0: real(s, retry_wait=0.01))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    trash = os.listdir(os.path.join(user_files_dir, ".trash"))
    assert any(open(os.path.join(user_files_dir, ".trash", f), encoding="utf-8").read() == "{ not json"
               for f in trash if f.startswith("master_manifest."))
    assert "surasura_library" in read_doc(user_files_dir), "the store exported its own version"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_backup_failure_applies_nothing(language, monkeypatch):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    before = {t: store.ids(t) for t in ls.ANALYSED}
    _edit(language, lambda d: d["schedule"]["PHASE_1_NOW"].reverse())
    monkeypatch.setattr(ls, "backup_to_trash", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_FAILED
    assert {t: store.ids(t) for t in ls.ANALYSED} == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_our_own_copy_newer_than_the_store_rebuilds(language):
    """A restored .bak or a lost -wal: the copy (ours, matching) is newer than the database."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    epoch = store.meta()["epoch"]
    store.close()
    db = ls.library_db_path(language, data_dir)
    import shutil
    shutil.copyfile(db, db + ".older")
    store = ls.open_store(language, data_dir, user_files_dir)
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[4])
    order = store.ids("now")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store.close()
    for suffix in ("-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    os.replace(db + ".older", db)                              # the database lost the move
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.ids("now") == order and store.meta()["epoch"] == epoch + 1
    store.close()


# --- 11. rebuild --------------------------------------------------------------------------------- #

def _new_pc(store):
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + f".{time.time_ns()}")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_rebuild_keeps_ids_and_its_first_export_replaces_the_copy(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    victim = store.ids("soon")[2]
    with store._writing():
        store.conn.execute("INSERT INTO anki_links VALUES (?, 5, 'x', 't')", (store.ids("now")[1],))
    removed = store.remove([victim])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    linked = store.ids("now")[1]
    _new_pc(store)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.trash_rows()[0]["item_id"] == victim
    assert store.conn.execute("SELECT item_id FROM anki_links").fetchone()[0] == linked
    assert read_doc(user_files_dir)["surasura_library"]["store_id"] == store.meta()["store_id"]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NOTHING, "no re-import loop"
    store.restore(removed.trash_ids)
    assert victim in store.ids("soon")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_with_two_paths_sharing_a_key_is_deduplicated(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    _new_pc(store)
    doc = read_doc(user_files_dir)
    twin = dict(doc["schedule"]["PHASE_1_NOW"][0])
    twin["physical_path"] = twin["physical_path"].replace("/", "\\")
    doc["schedule"]["PHASE_2_SOON"].append(twin)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert len(store.ids("soon")) == len(doc["schedule"]["PHASE_2_SOON"]) - 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_rebuilding_from_an_edited_copy_applies_the_rules(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    gone_from_list = store.ids("goal")[3]
    rel = store.item(gone_from_list)["rel_path"]
    _new_pc(store)

    def change(doc):
        s = doc["schedule"]
        s["PHASE_1_NOW"].insert(0, s["PHASE_1_NOW"].pop(4))  # a small edit: applied (a big one asks first)
        s["PHASE_3_LATER"] = [e for e in s["PHASE_3_LATER"] if e["physical_path"] != rel]

    doc = _edit(language, change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert [e["physical_path"] for _i, e, _a in store.ordered("now")] == \
        [e["physical_path"] for e in doc["schedule"]["PHASE_1_NOW"]]
    assert gone_from_list in store.ids("goal"), "an unlisted item is kept (rule 4)"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_use_that_order_applies_only_the_file_it_asked_about(language, monkeypatch):
    """Review R7: "Use that order" re-read the file as it was NOW and applied it with the guard off, outside
    the maintenance lock: a file saved again after the question went in unseen and unguarded. Now it runs
    under the lock, and a file saved since drops the question; the next run asks again."""
    store = _big(language)
    data_dir, user_files_dir = roots(language)
    big = int(sum(len(store.ids(t)) for t in ls.ANALYSED) * 0.06) + 1
    before = {t: store.ids(t) for t in ls.ANALYSED}
    _edit(language, lambda d: d["schedule"]["PHASE_3_LATER"].__setitem__(
        slice(0, big + 1), d["schedule"]["PHASE_3_LATER"][:big + 1][::-1]))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    with monkeypatch.context() as m:                           # another helper holds the maintenance lock
        m.setattr(ls, "MAINT_WAIT", 0.2)
        held = ls.MaintenanceLock(store.db_path)
        assert held.try_acquire()
        try:
            assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=True) is False
        finally:
            held.close()
    assert store.meta().get("reimport_pending"), "still asked"
    time.sleep(0.01)
    _edit(language, lambda d: d["schedule"]["PHASE_2_SOON"].reverse())    # saved again after the question
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=True) is False
    assert {t: store.ids(t) for t in ls.ANALYSED} == before, "nothing applied unseen"
    assert not store.meta().get("reimport_pending")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU, "the next run asks again"
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=True)
    assert {t: store.ids(t) for t in ls.ANALYSED} != before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_keep_mine_never_takes_a_file_saved_after_the_question(language):
    """Review N1: "Keep mine" recorded the file as it was NOW as the store's own, so a file another program
    saved after the question was overwritten by the next export, unseen and without a backup. Now a file
    saved since drops the question; the next run checks it again (with its backups) and asks."""
    store = _big(language)
    data_dir, user_files_dir = roots(language)
    big = int(sum(len(store.ids(t)) for t in ls.ANALYSED) * 0.06) + 1
    _edit(language, lambda d: d["schedule"]["PHASE_3_LATER"].__setitem__(
        slice(0, big + 1), d["schedule"]["PHASE_3_LATER"][:big + 1][::-1]))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    time.sleep(0.01)
    newer = _edit(language, lambda d: d["schedule"]["PHASE_2_SOON"].reverse())
    saved = open(ls.manifest_path(user_files_dir), "rb").read()
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=False) is False
    assert not store.meta().get("reimport_pending")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU, "asked again about the newer file"
    assert open(ls.manifest_path(user_files_dir), "rb").read() == saved, "never exported over it"
    assert read_doc(user_files_dir)["schedule"]["PHASE_2_SOON"] == newer["schedule"]["PHASE_2_SOON"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_rebuild_interrupted_before_its_re_import_keeps_the_edit(language, monkeypatch):
    """Review R2: a rebuild committed the records' order and the edited file's stat, then re-imported the
    edit in a second transaction. A failure between the two left a ready store that took the edited file
    as its own: the next export overwrote the edit, and no copy of it was kept. Now the edited file is
    kept in the trash first and the re-import runs in the rebuild's own transaction."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    _new_pc(store)
    doc = _edit(language, lambda d: d["schedule"]["PHASE_1_NOW"].insert(0, d["schedule"]["PHASE_1_NOW"].pop(4)))
    edited = open(ls.manifest_path(user_files_dir), "rb").read()

    def fails(*a, **k):
        raise OSError("the helper was stopped")
    with monkeypatch.context() as m:
        m.setattr(ls.Store, "reimport", fails)
        assert ls.maintain(language, data_dir, user_files_dir) != ls.EXIT_DONE
    trash = os.path.join(user_files_dir, ".trash")
    assert any(open(os.path.join(trash, f), "rb").read() == edited for f in os.listdir(trash)),         "the edited copy is kept in the trash before the rebuild applies it"
    assert open(ls.manifest_path(user_files_dir), "rb").read() == edited, "nothing exported over the edit"
    assert ls.maintain(language, data_dir, user_files_dir, retry=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert [e["physical_path"] for _i, e, _a in store.ordered("now")] ==         [e["physical_path"] for e in doc["schedule"]["PHASE_1_NOW"]], "the edit is applied on the next run"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ["rebuild", "repair"])
def test_ids_and_log_ids_are_never_reused(language, how):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    w = names(language)
    newest = store.insert([touch(data_dir, f"HighPriority/{w[20]}.txt")], "now").added[0]
    store.register_reader("connect")
    store.register(os.path.join(data_dir, store.item(store.ids("goal")[0])["rel_path"]), {"content_key": "k"})
    store.remove([newest])
    store.advance_reader("connect", 812)
    with store._writing():
        store.conn.execute("DELETE FROM placement_log")       # pruned empty, the watermark at 812
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    epoch = store.meta()["epoch"]
    undo_me = store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[2])
    token = store.token()
    if how == "rebuild":
        _new_pc(store)
        assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    else:
        db = store.db_path
        store.close()
        ls.mark_damaged(db, "a test")
        assert ls.maintain(language, data_dir, user_files_dir, repair=True) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    used = {r[0] for q in ("SELECT item_id FROM trash", "SELECT item_id FROM placement_log",
                           "SELECT item_id FROM pairings", "SELECT item_id FROM anki_links") for r in store.conn.execute(q)}
    added = store.insert([touch(data_dir, f"HighPriority/{w[21]}.txt")], "now").added[0]
    assert added not in used and added > newest
    event = store.conn.execute("SELECT MAX(id) FROM placement_log").fetchone()[0]
    assert event > 812
    assert store.meta()["epoch"] == epoch + 1
    with pytest.raises(ls.UndoRefused):
        store.undo(undo_me)
    assert store.changed_since(token)
    v = store.versions()
    assert v["analysed_order_version"] == 0 and v["planned_order_version"] == 0 and v["planned_pins_version"] == 0
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_soon_line_is_re_derived_from_the_tiers(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    now = len(store.ids("now"))
    with store._writing():
        store._set_meta({"soon_line": now + 7})               # disagrees with the tiers
    store.close()
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.meta()["soon_line"] == now, "at open"
    with store._writing():
        store._set_meta({"soon_line": 2})
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    doc = read_doc(user_files_dir)
    doc["surasura_library"]["meta"]["soon_line"] = 3
    write_manifest(user_files_dir, doc)
    _new_pc(store)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.meta()["soon_line"] == now, "and after the rebuild"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_big_edit_found_by_a_rebuild_asks_first(language):
    """A copy an older version edited heavily, met by a rebuild (a new PC): the records' order is built,
    and the edit waits for the user (Q4-8) like any other big outside change."""
    store = migrated(language, shows=10, episodes=10)
    data_dir, user_files_dir = roots(language)
    order = {t: store.ids(t) for t in ls.ANALYSED}
    _new_pc(store)
    _edit(language, lambda d: d["schedule"]["PHASE_3_LATER"].reverse())
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    store = ls.open_store(language, data_dir, user_files_dir)
    assert {t: store.ids(t) for t in ls.ANALYSED} == order and store.meta().get("reimport_pending")
    assert ls.resolve_reimport(language, data_dir, user_files_dir, use_theirs=True)
    assert store.ids("goal") == order["goal"][::-1]
    store.close()
