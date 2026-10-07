"""The change feed (L3.1 row 3.1.2; the L2.2 pack 04 §4.1, 06 §6.3): what lets 3.0's window repaint a change hato,
Connect or another window made in a fraction of a second, without a full re-read and without a disk sync.

Why these matter: every command, sync, import and undo that changes anything a view draws must stamp the rows it
changed with its version (`feed_in`) — a writer that forgets leaves a stale row on screen until the next full re-read.
Unlike `changed_in` (K25), an undo takes a new version, so a window that saw the change also sees it undone. Rows that
leave leave a tombstone for a day; a window asleep longer re-reads in full. A reader switched off (Connect's preview)
returns the library to logging nothing. Every test runs for Japanese and Chinese, under the per-test
SURASURA_TEST_ROOT, with real words from tests/Test Resources/; the cross-process timing holds its budget in the timed
run (SURASURA_STORE_BENCH=1).
"""

import json
import os
import statistics
import subprocess
import sys
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, arrivals_off, big_store, migrated, names, pieces_ok,
                                              read_doc, roots, subprocess_env, touch, write_manifest)

BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _feeds(store):
    return dict(store.conn.execute("SELECT id, feed_in FROM items"))


def _stamped(store, before):
    """{id: feed_in} of the rows whose feed version moved since `before`, and the store's version now."""
    now = _feeds(store)
    return {i: f for i, f in now.items() if before.get(i) != f}, store.meta()["state_version"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_writer_advances_feed_in(language):
    """04 §4.1 rule 1: each command, status write, sync, undo and import stamps exactly the rows it changed with its
    version — and the rows it didn't touch keep theirs."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    w = names(language)
    now, soon, goal = store.ids("now"), store.ids("soon"), store.ids("goal")

    def check(label, action, expect):
        before = _feeds(store)
        out = action()
        stamped, version = _stamped(store, before)
        assert stamped and set(stamped.values()) == {version}, label
        assert set(expect(out)) <= set(stamped), (label, sorted(set(expect(out)) - set(stamped)))
        return out

    check("move", lambda: store.move([goal[0]], "goal", after_id=goal[2]), lambda c: [goal[0]])
    check("set_tier", lambda: store.set_tier([goal[1]], "graduated"), lambda c: [goal[1]])
    check("insert", lambda: store.insert([touch(data_dir, f"GoalContent/{w[40]}.srt")], "goal"), lambda c: c.added)
    check("insert_at", lambda: store.insert_at([touch(data_dir, f"GoalContent/{w[41]}.srt")], goal[3]),
          lambda c: c.added)
    check("register", lambda: store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[42]}.srt"), {"content_key": "k1"}),
          lambda c: c.added)
    check("set_watched", lambda: store.set_watched([soon[0]]), lambda c: [soon[0]])
    check("pin", lambda: store.pin([soon[1]]), lambda c: [soon[1]])
    check("unpin", lambda: store.unpin([soon[1]]), lambda c: [soon[1]])
    check("receipt", lambda: store.receipt(soon[2], "2026-10-06T10:00:00Z"), lambda c: [soon[2]])
    piece = store.item(goal[4])["piece_id"]
    members = [r[0] for r in store.conn.execute("SELECT id FROM items WHERE piece_id = ? ORDER BY ord", (piece,))]
    if len(members) > 1:
        split = check("split", lambda: store.split(piece, members[1]), lambda c: members[1:])
        check("join", lambda: store.join([piece, split.pieces["created"][0]]), lambda c: members[1:])
    check("set_soon_line", lambda: store.set_soon_line(len(now) - 1), lambda c: [now[-1]])
    moved = check("move into NOW", lambda: store.move([soon[3]], "now"), lambda c: [soon[3]])
    check("undo", lambda: store.undo(moved), lambda c: [soon[3]])
    os.remove(os.path.join(data_dir, store.item(now[0])["rel_path"]))
    touch(data_dir, f"LowPriority/{w[43]}/{w[44]}.srt")
    check("sync", lambda: store.sync_disk(), lambda s: s["missing"] + s["added"])
    check("reset", lambda: store.reset_order(), lambda c: [it["id"] for it in c.items] or [])
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    doc = read_doc(user_files_dir)                              # an older Surasura moves a row within 6+ Months
    later = doc["schedule"]["PHASE_3_LATER"]
    later.insert(0, later.pop())
    write_manifest(user_files_dir, doc)
    before = _feeds(store)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    stamped, version = _stamped(store, before)
    assert stamped and set(stamped.values()) == {version}, "a re-import"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_window_reading_the_feed_keeps_the_true_order_through_a_re_space(language):
    """04 §4.1 as built (L3.1's adversarial review): the feed carries each row's key, so the keys a re-space gives a drag's
    neighbours are sent with that drag — a window that applies only what the feed sends keeps the store's order, drag
    after drag, through every re-space (the same gap halved until the keys run out), in every tier."""
    store = migrated(language, shows=3, episodes=6)
    first = store.read_feed()
    model = {r["id"]: (r["tier"], r["ord"]) for r in first["items"]}
    seen, epoch = first["version"], first["epoch"]
    ids = store.ids("goal")
    respaced = 0
    for n in range(200):
        ords = dict(store.conn.execute("SELECT id, ord FROM items WHERE tier = 'goal'"))
        item = ids[-1 - n % 2]
        store.move([item], "goal", after_id=ids[0])
        now = dict(store.conn.execute("SELECT id, ord FROM items WHERE tier = 'goal'"))
        respaced += sum(1 for i in now if i != item and now[i] != ords[i])
        feed = store.read_feed(seen, epoch)
        assert not feed["full"]
        for r in feed["items"]:
            model[r["id"]] = (r["tier"], r["ord"])
        seen = feed["version"]
        for tier in ls.ANALYSED:
            drawn = sorted((v[1], i) for i, v in model.items() if v[0] == tier)
            assert [i for _o, i in drawn] == store.ids(tier), (n, tier)
    assert respaced, "no re-space in 200 halvings"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_advances_feed_in_not_back(language):
    """K25's difference: undo puts `changed_in` back (its own conflict rule needs it) but takes a NEW feed version, so a
    window that read the move also reads it undone."""
    store = migrated(language)
    goal = store.ids("goal")
    old_changed = store.item(goal[0])["changed_in"]
    change = store.move([goal[0]], "goal", after_id=goal[-1])
    moved = store.item(goal[0])["feed_in"]
    store.undo(change)
    item = store.item(goal[0])
    assert item["changed_in"] == old_changed, "undo restores changed_in"
    assert item["feed_in"] > moved and item["feed_in"] == store.meta()["state_version"], "and advances feed_in"
    assert store.ids("goal") == goal
    loose = next(i for i in goal if not store.item(i)["parent_folder"])     # a piece of its own: no piece changes
    change = store.move([loose], "goal")
    moved = store.item(loose)["feed_in"]
    store.undo(change)
    assert store.item(loose)["feed_in"] > moved, "the undo's own placement stamps the row"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_removed_rows_leave_a_tombstone_and_put_back_clears_it(language):
    """04 §4.1 rule 2: a row that leaves `items` writes `gone(kind, id, feed_in, at)`; Put back deletes it and gives
    the row a new version; an Undo-Add tombstones the rows it took out."""
    store = migrated(language)
    data_dir, _u = roots(language)
    victim = store.ids("soon")[1]
    seen = store.meta()["state_version"]
    epoch = store.meta()["epoch"]
    removed = store.remove([victim])
    feed = store.read_feed(seen, epoch)
    assert not feed["full"] and feed["gone"] == [("item", victim)]
    assert victim not in {r["id"] for r in feed["items"]}
    store.restore(removed.trash_ids)
    assert store.conn.execute("SELECT COUNT(*) FROM gone").fetchone()[0] == 0
    assert store.item(victim)["feed_in"] == store.meta()["state_version"]
    add = store.insert([touch(data_dir, f"GoalContent/{names(language)[45]}.srt")], "goal")
    store.undo(add)
    assert store.conn.execute("SELECT kind, id FROM gone").fetchall() == [("item", add.added[0])]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_gone_rows_pruned_after_24_hours_by_their_time(language):
    """04 §4.1 rule 3: the helper prunes tombstones older than a day — by their time, not their count — and raises
    `feed_floor` to the newest version they held."""
    store = migrated(language)
    victim = store.ids("soon")[0]
    store.remove([victim])
    held = store.conn.execute("SELECT feed_in FROM gone").fetchone()[0]
    assert store.prune_gone(now=time.time() + 3600) == 0, "an hour old: kept"
    assert store.prune_gone(now=time.time() + 25 * 3600) == 1
    assert store.conn.execute("SELECT COUNT(*) FROM gone").fetchone()[0] == 0
    assert store.meta()["feed_floor"] == held
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_window_behind_feed_floor_re_reads(language):
    """06 §6.3: a window asleep past the tombstones' day (a laptop lid) could have missed a removal: `seen` below
    `feed_floor` reads everything again, as at open; a window that read after the floor reads only what changed."""
    store = migrated(language)
    first = store.read_feed()
    assert first["full"] and len(first["items"]) == sum(len(store.ids(t)) for t in ls.TIERS)
    asleep = first["version"]
    store.remove([store.ids("soon")[0]])
    awake = store.read_feed(asleep, first["epoch"])["version"]
    store.prune_gone(now=time.time() + 25 * 3600)
    assert store.read_feed(asleep, first["epoch"])["full"], "behind the floor: a full re-read"
    later = store.read_feed(awake, first["epoch"])
    assert not later["full"] and later["items"] == [] and later["gone"] == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_feed_read_holds_only_what_changed_and_a_new_epoch_reads_all(language):
    """04 §4.1 #4: after the first full read, a read gives only the rows stamped since — a drag, its pieces — and the
    options a view draws (the line); a rebuild (a new epoch) makes every window read in full."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    first = store.read_feed()
    goal = store.ids("goal")
    store.move([goal[-1]], "goal")
    feed = store.read_feed(first["version"], first["epoch"])
    assert not feed["full"] and goal[-1] in {r["id"] for r in feed["items"]}
    assert len(feed["items"]) < len(goal) and all(r["feed_in"] > first["version"] for r in feed["items"])
    assert feed["options"]["soon_line"] == store.meta()["soon_line"] and feed["options"]["arrivals_on"] == 1
    assert store.read_feed(feed["version"], feed["epoch"])["items"] == [], "nothing since: nothing read"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):                        # a new PC: rebuilt from the copy
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.read_feed(feed["version"], feed["epoch"])["full"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_unregister_reader_returns_the_library_to_logging_nothing(language):
    """Michi's P2.1 review #19 (P3.1's switch), ✅ L3.1 call c: a reader switched off is gone, so no command logs
    again; the log's rows stay (who placed what is kept), the copy carries them, and the helper's run ages them out
    after 30 days with no reader left; switched on again its watermark starts past every id ever logged (✅ G1.1-2)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    count = lambda: store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0]
    store.register_reader("connect")
    store.move([store.ids("soon")[0]], "now")
    kept = count()
    assert kept > 0
    last = store.conn.execute("SELECT MAX(id) FROM placement_log").fetchone()[0]
    assert store.unregister_reader("connect") is True and store.unregister_reader("connect") is False
    store.move([store.ids("soon")[0]], "now")
    assert count() == kept, "nothing logged, and the rows already there stay"
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert count() == kept, "younger than 30 days: the helper keeps them"
    lib = read_doc(user_files_dir)["surasura_library"]
    assert len(lib["tables"]["placement_log"]["rows"]) == kept and not any(k.startswith("reader") for k in lib["meta"])
    with store._writing():                                       # 31 days on: the helper ages them out
        store.conn.execute("UPDATE placement_log SET at = ?", (time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 31 * 86400)),))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert count() == 0
    store.register_reader("connect")
    assert store.meta()["reader:connect"] >= last, "never reads an event from before"
    store.move([store.ids("soon")[0]], "now")
    rows, gap = store.read_events("connect")
    assert rows and not gap and min(r[0] for r in rows) > last
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reader_switched_off_leaves_the_others_rows_to_the_prune(language):
    """✅ L3.1 call c: switching one reader off deletes no row, even those every reader left has read; the prune
    then deletes what the readers left have passed, as before."""
    store = migrated(language)
    count = lambda: store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0]
    store.register_reader("connect")
    store.register_reader("other")
    store.move([store.ids("soon")[0]], "now")
    events, _gap = store.read_events("other")
    store.advance_reader("other", events[-1][0])
    kept = count()
    assert store.unregister_reader("connect") is True and count() == kept, "nothing deleted by the switch"
    assert store.prune_log() == kept and count() == 0, "'other' has read them all: the prune takes them"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_merged_away_works_tombstone_and_the_helpers_tidy(language):
    """06 §6.5: a work with no item and no trash row of one goes in the helper's run, leaving a tombstone the window
    reads; one whose items wait in the trash stays (Put back finds it)."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    loose = [i for i in store.ids("goal") if store.item(i)["parent_folder"] == ""]
    show = [i for i in store.ids("soon") if store.item(i)["parent_folder"]]
    work_loose, work_show = store.item(loose[0])["work_id"], store.item(show[0])["work_id"]
    members = [i for i in show if store.item(i)["work_id"] == work_show]
    store.remove(members)                                       # in the trash: its work stays
    with store._writing():                                      # a work left empty by hand (as a merge leaves one)
        store.conn.execute("UPDATE items SET work_id = ? WHERE id = ?", (work_show, loose[0]))
    seen, epoch = store.meta()["state_version"], store.meta()["epoch"]
    assert store.tidy_works() == [work_loose]
    feed = store.read_feed(seen, epoch)
    assert ("work", work_loose) in feed["gone"]
    assert store.conn.execute("SELECT 1 FROM works WHERE id = ?", (work_show,)).fetchone()
    store.close()


_WRITER = r"""
import json, os, sys, time
sys.path.insert(0, {repo!r})
from app import library_store as ls
data_dir, user_files_dir, count, gap = {data_dir!r}, {user_files_dir!r}, {count}, {gap}
print("ready", flush=True)
sys.stdin.readline()
for n in range(count):
    rel = f"{{ls.HATO_FOLDER}}/feed_{{n:03d}}.srt"
    path = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{{n}}\n")
    answer = ls.register_headless({language!r}, path, {{"content_key": f"feed-{{n}}"}}, data_dir, user_files_dir)
    print(json.dumps([answer.file_id, time.time()]), flush=True)
    time.sleep(gap)
"""


def _poll_latencies(language, n_items, count, gap):
    store = big_store(language, n_items)
    data_dir, user_files_dir = roots(language)
    script = _WRITER.format(repo=REPO, data_dir=data_dir, user_files_dir=user_files_dir, count=count, gap=gap,
                            language=language)
    proc = subprocess.Popen([sys.executable, "-c", script], env=subprocess_env(), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, encoding="utf-8")
    assert proc.stdout.readline().strip() == "ready"
    feed = store.read_feed()
    seen, epoch, version = feed["version"], feed["epoch"], store.data_version()
    seen_at = {}
    proc.stdin.write("go\n")
    proc.stdin.flush()
    deadline = time.time() + count * gap + 30
    import threading
    commits = {}

    def collect():
        for line in proc.stdout:
            item, at = json.loads(line)
            commits[item] = at
    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    while time.time() < deadline and (len(seen_at) < count or len(commits) < count):
        time.sleep(ls.FEED_POLL)
        now_version = store.data_version()
        if now_version == version:
            continue
        version = now_version
        feed = store.read_feed(seen, epoch)
        t = time.time()
        for row in feed["items"]:
            seen_at.setdefault(row["id"], t)
        seen = feed["version"]
    proc.wait(timeout=30)
    reader.join(timeout=5)
    store.close()
    return [seen_at[i] - commits[i] for i in commits if i in seen_at], commits


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_processes_register_reaches_a_polling_reader(language):
    """04 §4.1's measurement as a proof: hato's register in another process every 0.3 s, a window polling
    `data_version` every 100 ms — every drop is read, p95 ≤ 150 ms after its commit at 2k, 20k and 200k (the timed run;
    otherwise 2k, five drops, unbudgeted)."""
    sizes = (2_000, 20_000, 200_000) if BENCH else (2_000,)
    for n in sizes:
        latencies, commits = _poll_latencies(language, n, 30 if BENCH else 5, 0.3 if BENCH else 0.05)
        assert len(latencies) == len(commits), "every drop reaches the window"
        if BENCH:
            p95 = statistics.quantiles(latencies, n=20)[-1]
            print(f"\nfeed {language} {n}: p50 {statistics.median(latencies) * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms")
            assert p95 <= 0.150, (n, p95)
        root = os.environ["SURASURA_TEST_ROOT"]                 # the next size: a store of its own
        db = ls.library_db_path(language, roots(language)[0])
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db + suffix):
                os.remove(db + suffix)
        assert root
