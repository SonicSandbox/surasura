"""WP-L5 of the library store (Library_Store_Spec.md §10): disk sync, renames, missing files, Reset and the
poll.

Why these matter: files reach the library without an Add (hato's drops, YouTube downloads, pasted text,
a file copied in by hand), so the disk sync decides where they land; it must place them exactly as today's
sync does except where Sonic answered otherwise (Q4-9: a show with no row in NOW or Soon sends a new
episode to the top of NOW; hato's drops at the top of NOW; a new episode follows its show into another
tier), keep a renamed file's place, and never remove anything. Reset (R-1) re-sorts within each item's
tier and never moves a file. Every test runs for Japanese and Chinese alike.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unicodedata

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, big_store, entry, laptop_library, library, migrated,
                                              names, read_doc, roots, subprocess_env, touch, write_manifest)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"


def _record(line):
    out = os.environ.get("SURASURA_STORE_BENCH_OUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _todays_sync(language, doc):
    """Today's `_sync_disk_to_manifest` (the 2.4.0 Content Manager's), run on a copy of `doc` in a folder of
    its own: returns its schedule."""
    from app.content_importer_gui import ContentImporterApp
    data_dir, _u = roots(language)
    own = os.path.join(os.environ["SURASURA_TEST_ROOT"], "todays_sync", language)
    write_manifest(own, doc)
    cm = ContentImporterApp.__new__(ContentImporterApp)
    cm.data_root = data_dir
    cm.user_files_root = own
    cm.language = language
    cm._warn_manifest_once = lambda *a, **k: None
    cm._store_mode, cm._store = (lambda: "json"), (lambda: None)   # 2.4.0's code: 2.5's JSON mode
    cm._sync_disk_to_manifest()
    return read_doc(own)["schedule"]


def _rule3(store_before, rel, data_dir):
    """Where §6.10 rule 3 sends a new file, from the library as it stood before the sync: (tier, anchor id or
    None for the top)."""
    folder = rel.rsplit("/", 1)[0]
    if folder == ls.HATO_FOLDER:
        return "now", None
    if folder in ls.TIER_OF_FOLDER:
        return ls.TIER_OF_FOLDER[folder], None
    rows = [(t, i) for t, ids in store_before.items() for i, r in ids if r.rsplit("/", 1)[0] == folder]
    for tier in ("soon", "now"):
        here = [i for t, i in rows if t == tier]
        if here:
            return tier, here[-1]
    if rows:
        return "now", None
    return None                                                 # a new show: today's rule


def _snapshot(store):
    return {t: [(i, store.item(i)["rel_path"]) for i in store.ids(t)] for t in ls.TIERS}


def _add_files(language, data_dir, specs):
    out = []
    for n, rel in enumerate(specs):
        touch(data_dir, rel, f"{rel} {n}\n")
        out.append(rel)
    return out


# --- 1. parity ----------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_parity_on_today_shaped_folders(language):
    """Each folder in its tier: the same rows and placement as today's sync, except exactly the cases rule 3
    lists (a show with no row in NOW or Soon → the top of NOW; hato's drops at the top of NOW)."""
    store = migrated(language, shows=3, episodes=4)
    data_dir, user_files_dir = roots(language)
    doc = read_doc(user_files_dir)
    w = names(language)
    shows = {t: sorted({e["physical_path"].rsplit("/", 1)[0] for e in doc["schedule"][ls.TIERS[t][0]]
                        if e["physical_path"].count("/") == 2}) for t in ls.ANALYSED}
    plain = [f"{shows['now'][0]}/{w[40]}_new.srt", f"{shows['soon'][1]}/{w[41]}_new.srt",
             f"LowPriority/{w[42]}/{w[43]}.srt", f"GoalContent/{w[44]}.txt", f"HighPriority/{w[45]}.txt"]
    special = [f"{shows['goal'][0]}/{w[46]}_new.srt", f"{ls.HATO_FOLDER}/{w[47]}.srt"]
    before = _snapshot(store)
    _add_files(language, data_dir, plain + special)
    today = _todays_sync(language, doc)
    summary = store.sync_disk()
    assert len(summary["added"]) == len(plain) + len(special)
    for tier in ls.ANALYSED:
        mine = [e["physical_path"] for _i, e, _a in store.ordered(tier)]
        theirs = [e["physical_path"] for e in today[ls.TIERS[tier][0]]]
        assert [p for p in mine if p not in special] == [p for p in theirs if p not in special], tier
    tops = special + [r for r in plain if r.count("/") == 1 and r.startswith("HighPriority/")]
    assert set(store.ids("now")[:len(tops)]) == {store.item_id(r) for r in tops}, "the top of NOW"
    for rel in special:
        assert _rule3(before, rel, data_dir) == ("now", None)
    rows = {e["physical_path"]: e for _i, e, _a in store.ordered("now") + store.ordered("soon") + store.ordered("goal")}
    for rel in plain:
        assert rows[rel]["origin_source"] == "Disk Sync"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_parity_on_the_laptop_shaped_library(language):
    """851 rows in another tier's folder, 267 dead: every placement follows the store's tiers, and every
    difference from today's sync is a case rule 3 lists."""
    data_dir, user_files_dir, doc = laptop_library(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    w = names(language)
    later = doc["schedule"]["PHASE_3_LATER"]
    soon = doc["schedule"]["PHASE_2_SOON"]
    low_in_later = next(e["physical_path"] for e in later if e["physical_path"].startswith("LowPriority/"))
    high_in_soon = soon[0]["physical_path"]
    goal_show = next(e["physical_path"] for e in later if e["physical_path"].startswith("GoalContent/"))
    new = _add_files(language, data_dir, [
        low_in_later.rsplit("/", 1)[0] + f"/{w[50]}_new.srt",      # its show only in 6+ Months → top of NOW
        high_in_soon.rsplit("/", 1)[0] + f"/{w[51]}_new.srt",      # its show in Soon → after its last Soon row
        goal_show.rsplit("/", 1)[0] + f"/{w[52]}_new.srt",
        f"LowPriority/{w[53]}/{w[54]}.srt",                          # a new show: today's rule
        f"{ls.HATO_FOLDER}/{w[55]}.srt"])
    before = _snapshot(store)
    today = _todays_sync(language, read_doc(user_files_dir))
    store.sync_disk()
    for rel in new:
        expected = _rule3(before, rel, data_dir)
        item = store.item(store.item_id(rel))
        seq = store.ids(item["tier"])
        at = seq.index(item["id"])
        if expected is None:                                      # rule 3's "no item yet": today's placement
            phase = next(p for p in ls.PHASES if any(e["physical_path"] == rel for e in today[p]))
            assert item["tier"] == ls.TIER_OF_PHASE[phase]
            theirs = [e["physical_path"] for e in today[phase]]
            prev = theirs[theirs.index(rel) - 1] if theirs.index(rel) else None
            assert (store.item(seq[at - 1])["rel_path"] if at else None) == prev
        else:
            tier, anchor = expected
            assert item["tier"] == tier, rel
            assert (seq[at - 1] if at else None) == anchor or (anchor is None and at < 5), rel
    store.close()


# --- 2. graduated; 3. hato's drops --------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_graduated_files_are_never_re_added(language):
    store = migrated(language)
    ids = store.ids("now")[:3]
    store.set_tier(ids, "graduated")                           # the files stay in HighPriority (L5)
    assert store.sync_disk() is None
    assert sorted(store.ids("graduated")) == sorted(ids)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_hatos_drops_land_at_the_top_of_now(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[60]}.srt")
    first = store.sync_disk()["added"][0]
    assert store.ids("now")[0] == first
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[61]}.srt")
    second = store.sync_disk()["added"][0]
    assert store.ids("now")[:2] == [second, first], "also when the Hato group already has rows"
    store.set_tier([first], "soon")                            # one demoted video
    touch(data_dir, f"{ls.HATO_FOLDER}/{w[62]}.srt")
    third = store.sync_disk()["added"][0]
    assert store.ids("now")[0] == third, "a demoted drop pulls later drops nowhere"
    assert store.ids("arrivals") == []
    store.close()


# --- 4. new episodes, by sync, register and an Add alike ------------------------------------------ #

def _three_ways(store, data_dir, rel_for, tab):
    """The same placement question asked of sync_disk, register and insert (an Add on `tab`)."""
    out = {}
    touch(data_dir, rel_for("sync"))
    out["sync"] = store.sync_disk()["added"][0]
    rel = rel_for("register")
    out["register"] = store.register(touch(data_dir, rel), {"content_key": rel}).added[0]
    rel = rel_for("add")
    out["add"] = store.insert([touch(data_dir, rel)], tab).added[0]
    return out


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_with_rows_in_soon_and_6_months(language):
    store = migrated(language, shows=2, episodes=4)
    data_dir, _u = roots(language)
    goal_show = [i for i in store.ids("goal") if store.item(i)["parent_folder"]][:4]
    store.set_tier(goal_show[:2], "soon")                       # the show now sits in Soon and 6+ Months
    folder = store.item(goal_show[0])["rel_path"].rsplit("/", 1)[0]
    got = _three_ways(store, data_dir, lambda how: f"{folder}/{names(store.language)[63]}_{how}.srt", "goal")
    soon = store.ids("soon")
    last = soon.index(goal_show[1])
    assert soon[last + 1:last + 4] == [got["sync"], got["register"], got["add"]], \
        "each right after the show's last Soon row — an Add on the 6+ Months tab too"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_episode_follows_its_demoted_show(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    show = [i for i in store.ids("now") if store.item(i)["parent_folder"]][:4]
    store.set_tier(show, "soon")
    folder = store.item(show[0])["rel_path"].rsplit("/", 1)[0]
    touch(data_dir, f"{folder}/{names(language)[64]}_new.srt")
    new = store.sync_disk()["added"][0]
    soon = store.ids("soon")
    assert store.item(new)["tier"] == "soon" and soon[soon.index(show[-1]) + 1] == new
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("where", ["goal", "graduated"])
def test_q4_9_a_show_with_no_row_in_now_or_soon(language, where):
    """✅ G1.1-14, Q4-9 always: the top of NOW, for a sync, register and an Add on any tab."""
    store = migrated(language, shows=6, episodes=2)
    data_dir, _u = roots(language)
    goal = [i for i in store.ids("goal") if store.item(i)["parent_folder"]]
    shows = [goal[n:n + 2] for n in range(0, 12, 2)]          # a fresh show for each way and tab
    if where == "graduated":
        store.set_tier(goal, "graduated")
    w = names(language)
    for n, (tab, how) in enumerate([(t, h) for t in ("goal", "soon") for h in ("sync", "register", "add")]):
        folder = store.item(shows[n][0])["rel_path"].rsplit("/", 1)[0]
        rel = f"{folder}/{w[65]}_{how}_{tab}.srt"
        full = touch(data_dir, rel)
        if how == "sync":
            new = store.sync_disk()["added"][0]
        elif how == "register":
            new = store.register(full, {"content_key": rel}).added[0]
        else:
            new = store.insert([full], tab).added[0]
        assert store.ids("now")[0] == new, (how, tab)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_directory_with_no_item_yet_is_todays_rule(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    touch(data_dir, f"LowPriority/{w[66]}/{w[67]}.srt")
    synced = store.sync_disk()["added"][0]
    assert store.ids("soon")[0] == synced, "a sync: its folder's tier, at the top"
    add = store.insert([touch(data_dir, f"GoalContent/{w[68]}/{w[69]}.srt")], "goal").added[0]
    assert store.ids("goal")[0] == add, "an Add: the tab chosen"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_same_named_shows_in_two_tier_folders_stay_apart(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    show = w[70]
    touch(data_dir, f"HighPriority/{show}/{show}_01.srt")
    touch(data_dir, f"GoalContent/{show}/{show}_01.srt")
    store.sync_disk()
    high, goal = store.item_id(f"HighPriority/{show}/{show}_01.srt"), store.item_id(f"GoalContent/{show}/{show}_01.srt")
    assert store.item(high)["tier"] == "now" and store.item(goal)["tier"] == "goal"
    touch(data_dir, f"GoalContent/{show}/{show}_02.srt")
    new = store.sync_disk()["added"][0]
    assert store.item(new)["tier"] == "now" and store.ids("now")[0] == new, \
        "its own show (all in 6+ Months) decides: Q4-9, not the same-named show in NOW"
    store.close()


# --- 5. renames; 6. missing; 7. no delta; 8. a stale walk --------------------------------------- #

def _rename(data_dir, old, new):
    os.makedirs(os.path.dirname(os.path.join(data_dir, new)), exist_ok=True)
    os.rename(os.path.join(data_dir, old), os.path.join(data_dir, new))


@pytest.mark.parametrize("language", LANGUAGES)
def test_renames(language):
    store = migrated(language, shows=3, episodes=4)
    data_dir, _u = roots(language)
    ids = store.ids("soon")
    rel = store.item(ids[2])["rel_path"]
    _rename(data_dir, rel, rel.replace(".srt", "_renamed.srt"))
    summary = store.sync_disk()
    assert summary["renamed"] == [ids[2]] and store.ids("soon") == ids, "one candidate: place kept"
    # two candidates: the same size and time — no guess
    a, b = store.item(ids[5])["rel_path"], store.item(ids[6])["rel_path"]
    for p in (a, b):
        with open(os.path.join(data_dir, p), "w", encoding="utf-8") as f:
            f.write("同じ\n")
        os.utime(os.path.join(data_dir, p), ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    store.sync_disk()
    _rename(data_dir, a, a.replace(".srt", "_x.srt"))
    os.remove(os.path.join(data_dir, b))
    summary = store.sync_disk()
    assert len(summary["added"]) == 1 and sorted(summary["missing"]) == sorted([ids[5], ids[6]])
    # the same size with a different modified time: new
    c = store.item(ids[7])["rel_path"]
    full = os.path.join(data_dir, c)
    st = os.stat(full)
    _rename(data_dir, c, c.replace(".srt", "_y.srt"))
    os.utime(os.path.join(data_dir, c.replace(".srt", "_y.srt")), ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    summary = store.sync_disk()
    assert len(summary["added"]) == 1 and summary["missing"] == [ids[7]]
    # edited, synced, then renamed: the refreshed fingerprint keeps its place
    d = store.item(ids[8])["rel_path"]
    with open(os.path.join(data_dir, d), "a", encoding="utf-8") as f:
        f.write("追記\n")
    store.sync_disk()
    _rename(data_dir, d, d.replace(".srt", "_z.srt"))
    assert store.sync_disk()["renamed"] == [ids[8]]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_case_only_rename_is_re_pointed_not_duplicated(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    item = store.ids("now")[-1]                                 # a loose file: its name is ASCII-cased
    rel = store.item(item)["rel_path"]
    new = rel.rsplit("/", 1)[0] + "/" + rel.rsplit("/", 1)[1].upper().replace(".TXT", ".Txt")
    if new == rel:
        new = rel[:-4] + ".TXT"
    _rename(data_dir, rel, new)
    store.sync_disk()
    count = len(store.ids("now"))
    assert store.item(item)["rel_path"] == new and store.sync_disk() is None
    assert len(store.ids("now")) == count
    store.close()


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS keeps NFC and NFD names apart")
@pytest.mark.parametrize("language", LANGUAGES)
def test_nfc_to_nfd_on_windows_is_a_rename(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    nfc = f"HighPriority/{w[71]}ガ.txt"
    touch(data_dir, nfc)
    item = store.sync_disk()["added"][0]
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    _rename(data_dir, nfc, nfd)
    assert store.sync_disk()["renamed"] == [item] and store.item(item)["rel_path"] == nfd
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_missing_and_back(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    item = store.ids("goal")[2]
    full = os.path.join(data_dir, store.item(item)["rel_path"])
    keep = full + ".aside"
    os.rename(full, keep)
    assert store.sync_disk()["missing"] == [item]
    assert store.item(item)["availability"] == "missing" and item in store.ids("goal"), "never removed"
    os.rename(keep, full)
    assert store.sync_disk()["back"] == [item] and store.item(item)["availability"] == "available"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_fingerprint_refresh_is_carried_by_the_next_export(language):
    """Review R4: a sync that only refreshed a file's size and time never marked the copy behind, so after
    a rebuild (a new PC) the record's stale fingerprint broke the rename rules for an edited, then renamed
    subtitle. The refresh is bookkeeping the copy carries (§6.6)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    item = store.ids("soon")[3]
    rel = store.item(item)["rel_path"]
    with open(os.path.join(data_dir, rel), "a", encoding="utf-8") as f:
        f.write(names(language)[30] * 40 + "\n")             # an edited subtitle: same name, new size
    size = os.path.getsize(os.path.join(data_dir, rel))
    assert store.sync_disk() is None
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    rec = ls._records(read_doc(user_files_dir)["surasura_library"])[ls.path_key(rel)]
    assert rec["size"] == size
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_delta_writes_nothing(language):
    store = migrated(language)
    v = store.versions()
    changes = store.conn.total_changes
    assert store.sync_disk() is None
    assert store.versions() == v and store.conn.total_changes == changes
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_stale_walk(language):
    """A stale walk neither re-adds a path renamed away since, nor marks missing a file just put back."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    new_rel = f"HighPriority/{w[72]}.txt"
    touch(data_dir, new_rel)
    gone = store.ids("soon")[1]
    gone_rel = store.item(gone)["rel_path"]
    os.rename(os.path.join(data_dir, gone_rel), os.path.join(data_dir, gone_rel) + ".x")
    stale = ls.walk_library(data_dir)                           # sees new_rel, misses gone_rel
    os.rename(os.path.join(data_dir, new_rel), os.path.join(data_dir, new_rel) + ".moved")
    os.rename(os.path.join(data_dir, gone_rel) + ".x", os.path.join(data_dir, gone_rel))
    assert store.sync_disk(stale) is None
    assert store.item_id(new_rel) is None and store.item(gone)["availability"] == "available"
    store.close()


_SYNC = """
import sys
from app import library_store as ls
lang, data, uf = sys.argv[1:4]
s = ls.open_store(lang, data, uf)
s.sync_disk()
s.close()
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_processes_syncing_never_duplicate(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    w = names(language)
    added = _add_files(language, data_dir, [f"LowPriority/{w[73]}/{w[74]}_{n}.srt" for n in range(20)])
    procs = [subprocess.Popen([sys.executable, "-c", _SYNC, language, data_dir, user_files_dir], cwd=REPO,
                              env=subprocess_env()) for _ in range(2)]
    assert all(p.wait(60) == 0 for p in procs)
    keys = [r[0] for r in store.conn.execute("SELECT rel_key FROM items")]
    assert len(keys) == len(set(keys))
    assert all(store.item_id(rel) is not None for rel in added)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_name_that_cant_be_encoded_is_skipped_and_listed(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    bad = os.path.join(data_dir, "HighPriority", f"{w[75]}\udc81.txt")
    try:
        with open(bad, "w", encoding="utf-8") as f:
            f.write("x\n")
    except (OSError, UnicodeEncodeError):
        pytest.skip("this file system refuses the name")
    touch(data_dir, f"HighPriority/{w[76]}.txt")
    summary = store.sync_disk()
    assert len(summary["added"]) == 1 and len(summary["bad"]) == 1
    store.close()


# --- 11. changed_in and the log; 12. Reset ------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_reset_moved_skips_an_older_undo(language):
    store = migrated(language)
    ids = store.ids("now")
    mine = store.move([ids[0]], "now", after_id=ids[5])
    store.reset_order()
    assert store.undo(mine).notes == ["1 item changed since and was left as it is"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_synced_new_item_crossing_the_line_logs_that_and_nothing_else(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    pushed = (store.ids("now") + store.ids("soon"))[19]
    mark = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM placement_log").fetchone()[0]
    touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[77]}.srt")
    new = store.sync_disk()["added"][0]
    events = [tuple(r) for r in store.conn.execute(
        "SELECT item_id, kind, by, explicit FROM placement_log WHERE id > ? ORDER BY id", (mark,))]
    assert events == [(new, "entered_mine_line", "sync", 0), (pushed, "left_mine_line", "sync", 0)]
    store.close()


def _copy_bytes(user_files_dir):
    """What an older reader reads, byte for byte (the copy minus `surasura_library`), and the item records."""
    doc = read_doc(user_files_dir)
    lib = doc.pop("surasura_library")
    return json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8"), lib["items"], lib["graduated"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_reset_per_r1_and_undo_byte_equal(language):
    data_dir, user_files_dir, doc = library(language, shows=3, episodes=4)
    doc["schedule"]["PHASE_2_SOON"].reverse()
    doc["schedule"]["PHASE_1_NOW"].insert(0, doc["schedule"]["PHASE_3_LATER"].pop(3))   # a 6+ Months file in NOW
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    grad = store.ids("goal")[0]
    store.set_tier([grad], "graduated")
    gone = store.ids("now")[2]
    os.remove(os.path.join(data_dir, store.item(gone)["rel_path"]))
    store.sync_disk()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    before = _copy_bytes(user_files_dir)
    tiers_before = {i: store.item(i)["tier"] for t in ls.TIERS for i in store.ids(t)}
    disk_before = sorted(os.path.relpath(os.path.join(r, f), data_dir) for r, _d, fs in os.walk(data_dir) for f in fs)
    change = store.reset_order()
    order = ls.reset_walk(data_dir)
    pos = {ls.path_key(r): n for n, r in enumerate(order)}
    for tier in ls.ANALYSED:
        rels = [store.item(i)["rel_path"] for i in store.ids(tier)]
        present = [r for r in rels if ls.path_key(r) in pos]
        assert present == sorted(present, key=lambda r: pos[ls.path_key(r)]), tier
        assert rels[len(present):] == [r for r in rels if ls.path_key(r) not in pos], "missing items at the end"
    assert store.ids("now")[-1] == gone and store.item(gone)["availability"] == "missing"
    assert {i: store.item(i)["tier"] for t in ls.TIERS for i in store.ids(t)} == tiers_before, "tiers and ids kept"
    assert store.ids("graduated") == [grad]
    assert sorted(os.path.relpath(os.path.join(r, f), data_dir) for r, _d, fs in os.walk(data_dir) for f in fs) == \
        disk_before, "no file moved (I3)"
    store.undo(change)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert _copy_bytes(user_files_dir) == before, "Reset → Undo: the copy byte-equal"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_reset_adds_untracked_files_as_reset_entries(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    rel = f"LowPriority/{w[78]}/{w[79]}.srt"
    touch(data_dir, rel)
    change = store.reset_order()
    item = store.item(store.item_id(rel))
    assert item["tier"] == "soon" and item["entry"]["origin_source"] == "Reset" and "source_type" not in item["entry"]
    store.undo(change)
    assert store.item_id(rel) is None
    store.close()


# --- 13. the poll; 14. the window's stall --------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_poll_sees_drops_into_show_folders(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    poll = ls.DiskPoll(store)
    assert poll.check() is False                                # the baseline
    assert poll.check() is False
    show = store.item(store.ids("soon")[0])["rel_path"].rsplit("/", 1)[0]
    time.sleep(0.02)
    touch(data_dir, f"{show}/{w[80]}_drop.srt")
    assert poll.check() is True
    assert len(store.sync_disk()["added"]) == 1
    assert poll.check() is False
    time.sleep(0.02)
    touch(data_dir, f"{show}/S2/{w[81]}.srt")                   # a new sub-folder changes its parent's time
    assert poll.check() is True and len(store.sync_disk()["added"]) == 1
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("folders", [70, 700])
def test_the_polls_cost(language, folders):
    data_dir, user_files_dir = roots(language)
    w = names(language)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    for n in range(folders):
        rel = f"LowPriority/{w[n % len(w)]}{n:04d}/{n}.srt"
        touch(data_dir, rel)
        doc["schedule"]["PHASE_2_SOON"].append(entry(rel))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    poll = ls.DiskPoll(store)
    poll.check()
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        poll.check()
        times.append(time.perf_counter() - t0)
    median = sorted(times)[10]
    _record(f"13 {language} poll at {len(poll.folders)} folders: median {median * 1000:.2f} ms")
    if BENCH and folders == 70:
        assert median <= 0.005, median
    store.close()


_STALL = """
import sys, threading, time, json, os
sys.setswitchinterval(float(sys.argv[5]))
import tkinter as tk
from app import library_store as ls
lang, data, uf = sys.argv[1:4]
mode = sys.argv[4]
root = tk.Tk(); root.withdraw()
gaps, last = [], [time.perf_counter()]
def probe():
    now = time.perf_counter(); gaps.append(now - last[0]); last[0] = now
    root.after(1, probe)
done = threading.Event()
result = {}
def worker():
    s = ls.open_store(lang, data, uf)
    t0 = time.perf_counter(); r = s.sync_disk(); result["sync"] = time.perf_counter() - t0
    result["added"] = len(r["added"]) if r else 0
    s.close(); done.set()
root.after(200, lambda: threading.Thread(target=worker, daemon=True).start())
root.after(1, probe)
def finish():
    if done.is_set():
        root.quit()
    else:
        root.after(20, finish)
root.after(250, finish)
root.mainloop()
result["stall"] = max(gaps[5:])
print(json.dumps(result))
"""


@pytest.mark.skipif(not BENCH, reason="the 100k stall is measured in the timed proof only (100k files on disk)")
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_windows_stall_during_a_100k_sync(language):
    """WP-L5 #14: the Content Manager's worker running `sync_disk` at 100k, a Tk `after(1)` probe on the
    window's thread: the longest stall is recorded (and the fix is chosen on that number, at L2.1)."""
    store = big_store(language, 100_000)
    data_dir, user_files_dir = roots(language)
    for t in ls.ANALYSED:
        for _i, e, _a in store.ordered(t):
            touch(data_dir, e["physical_path"], "x\n")
    store.sync_disk()                                            # fingerprints settle
    w = names(language)
    for n in range(50):
        touch(data_dir, f"LowPriority/{w[n % len(w)]}9{n}/{n}.srt")
    store.close()
    for mode, interval in (("delta", 0.005), ("none", 0.005), ("none", 0.0005)):
        out = subprocess.run([sys.executable, "-c", _STALL, language, data_dir, user_files_dir, mode, str(interval)],
                             cwd=REPO, env=subprocess_env(), capture_output=True, text=True, timeout=600)
        assert out.returncode == 0, out.stderr[-1500:]
        r = json.loads(out.stdout.strip().splitlines()[-1])
        _record(f"14 {language} 100k sync ({'50 new files' if r['added'] else 'no change'}, switch interval "
                f"{interval * 1000:.1f} ms): sync {r['sync'] * 1000:.0f} ms, longest window stall {r['stall'] * 1000:.1f} ms")
