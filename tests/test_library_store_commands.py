"""WP-L2 of the library store (Library_Store_Spec.md §10): order keys, versions, the commands, the
placement log and undo.

Why these matter: the store must place and move items exactly as today's Content Manager does (a
property test against frozen copies of today's code, plus the placement rules Sonic answered: Q4-9, hato's
drops at the top of NOW, a batch Add keeping its order), and Undo must never erase later work — today's
whole-manifest snapshot undo erases every drag made after the change it undoes (RD-A6). Every test runs
for Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT.
"""

import json
import os
import random
import sqlite3
import statistics
import subprocess
import sys
import threading
import time

import pytest

from app import library_store as ls
from tests.test_library_store_support import (LANGUAGES, big_store, entry, library, migrated, names, paths, roots,
                                              subprocess_env, touch, write_manifest)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.environ.get("SURASURA_STORE_BENCH") == "1"


# ================================================================================================ #
# The reference model: frozen copies of today's Content Manager code (app/content_importer_gui.py at
# 2.4.0: place_new_entries ≈30, _entry_folder ≈63, move_manifest_items_relative ≈856,
# move_items_in_manifest ≈918), the method bodies as pure functions over one phase list.
# ================================================================================================ #

def ref_place_new_entries(existing, new_entries):
    last_of = {}
    for index, entry in enumerate(existing):
        folder = ref_entry_folder(entry)
        if folder:
            last_of[folder] = index
    placed, after = [], {}
    for entry in new_entries:
        folder = ref_entry_folder(entry)
        if folder in last_of:
            after.setdefault(last_of[folder], []).append(entry)
        else:
            placed.append(entry)
    for index, entry in enumerate(existing):
        placed.append(entry)
        placed.extend(after.get(index, ()))
    return placed


def ref_entry_folder(entry):
    if not isinstance(entry, dict):
        return ""
    folder = entry.get("parent_folder")
    if isinstance(folder, str):
        return folder
    parts = str(entry.get("physical_path") or "").split("/")
    return "/".join(parts[1:-1]) if len(parts) > 2 else ""


def ref_indices(lst, items):
    target_paths = set(items)
    return sorted(i for i, entry in enumerate(lst) if entry.get("physical_path") in target_paths)


def ref_move_relative(lst, items, target_path, position):
    indices_to_move = ref_indices(lst, items)
    if not indices_to_move:
        return
    target_indices = ref_indices(lst, [target_path])
    if not target_indices:
        return
    if position == "before":
        eff_target_idx = target_indices[0]
    else:
        eff_target_idx = target_indices[-1]
    moving_items = [lst[i] for i in indices_to_move]
    shift_adj = 0
    for i in reversed(indices_to_move):
        if i < eff_target_idx:
            shift_adj += 1
        del lst[i]
    eff_target_idx -= shift_adj
    if position == "before":
        insert_idx = eff_target_idx
    else:
        insert_idx = eff_target_idx + 1
    for item in reversed(moving_items):
        lst.insert(insert_idx, item)


def ref_nudge(lst, items, direction, current_bucket):
    indices_to_move = ref_indices(lst, items)
    if not indices_to_move:
        return
    visible_indices = []
    for i, entry in enumerate(lst):
        p = entry.get("physical_path", "")
        if p.startswith(current_bucket + "/"):
            visible_indices.append(i)
    visible_indices.sort()
    if direction == "up":
        first_moving = indices_to_move[0]
        target_idx = -1
        for idx in reversed(visible_indices):
            if idx < first_moving:
                target_idx = idx
                break
        if target_idx != -1:
            target_parent = lst[target_idx].get("parent_folder", "")
            moving_parent = lst[indices_to_move[0]].get("parent_folder", "")
            if target_parent and target_parent != moving_parent:
                while target_idx > 0 and lst[target_idx - 1].get("parent_folder") == target_parent:
                    if target_idx - 1 not in visible_indices:
                        break
                    target_idx -= 1
            moving_items = [lst[i] for i in indices_to_move]
            for i in reversed(indices_to_move):
                del lst[i]
            for item in reversed(moving_items):
                lst.insert(target_idx, item)
    elif direction == "down":
        last_moving = indices_to_move[-1]
        target_idx = -1
        for idx in visible_indices:
            if idx > last_moving:
                target_idx = idx
                break
        if target_idx != -1:
            target_parent = lst[target_idx].get("parent_folder", "")
            moving_parent = lst[indices_to_move[-1]].get("parent_folder", "")
            if target_parent and target_parent != moving_parent:
                while target_idx < len(lst) - 1 and lst[target_idx + 1].get("parent_folder") == target_parent:
                    if target_idx + 1 not in visible_indices:
                        break
                    target_idx += 1
            moving_items = [lst[i] for i in indices_to_move]
            for i in reversed(indices_to_move):
                del lst[i]
            insert_pos = target_idx - len(moving_items) + 1
            for item in reversed(moving_items):
                lst.insert(insert_pos, item)


class Model:
    """Today's library as lists, with Sonic's answered placement rules on top: a new episode joins its
    show (its real directory) after the show's last row in NOW or Soon, else lands at the top of NOW
    (Q4-9); hato's drops land at the top of NOW (Q4-11); a batch keeps its order (L-Q6). Tier changes
    re-place the rows as today's Demote / Promote / Graduate do (`place_new_entries` in the target tab);
    the file moves with them, as today (so each file's folder keeps matching its tier)."""

    NEXT_DOWN = {"now": "soon", "soon": "goal"}
    GRADUATE = {"now": None, "soon": "now", "goal": "soon"}

    def __init__(self, doc, store):
        self.lists = {}
        for tier in ls.ANALYSED:
            rows = [dict(e) for e in doc["schedule"][ls.TIERS[tier][0]]]
            for e in rows:
                e["_sid"] = store.item_id(e["physical_path"])
            self.lists[tier] = rows

    def ids(self, tier):
        return [e["_sid"] for e in self.lists[tier]]

    def insert(self, entries, tab):
        rel = entries[0]["physical_path"]
        d = rel.rsplit("/", 1)[0]
        if d == ls.HATO_FOLDER:
            self.lists["now"][0:0] = entries
            return
        if d in ls.TIER_OF_FOLDER:
            self.lists[tab] = ref_place_new_entries(self.lists[tab], entries)
            return
        rows = {t: [i for i, e in enumerate(self.lists[t]) if e["physical_path"].rsplit("/", 1)[0] == d]
                for t in ls.ANALYSED}
        for tier in ("soon", "now"):
            if rows[tier]:
                at = rows[tier][-1] + 1
                self.lists[tier][at:at] = entries
                return
        if rows["goal"]:
            self.lists["now"][0:0] = entries
            return
        self.lists[tab] = ref_place_new_entries(self.lists[tab], entries)

    def set_tier(self, tier, picked, target):
        lst = self.lists[tier]
        moving = [e for e in picked]
        self.lists[tier] = [e for e in lst if e not in moving]
        if target is None:
            return
        folder = ls.FOLDER_OF_TIER[target]
        for e in moving:
            e["physical_path"] = folder + "/" + e["physical_path"].split("/", 1)[1]
        self.lists[target] = ref_place_new_entries(self.lists[target], moving)


def _run_property(language, steps, seed):
    store = migrated(language, shows=4, episodes=5, loose=2)
    data_dir, user_files_dir = roots(language)
    from tests.test_library_store_support import read_doc
    doc = read_doc(user_files_dir)
    model = Model(doc, store)
    rng = random.Random(seed)
    words = names(language)
    tainted = set()
    counter = [0]

    def fresh(word_dir, ext=".srt"):
        counter[0] += 1
        return f"{word_dir}/{words[(counter[0] * 7) % len(words)]}_{counter[0]:04d}{ext}"

    for step in range(steps):
        op = rng.choices(["drag", "nudge", "insert", "remove", "tier"], [40, 20, 15, 10, 15])[0]
        tier = rng.choice([t for t in ls.ANALYSED if model.lists[t]] or ["now"])
        lst = model.lists[tier]
        if op == "drag" and len(lst) >= 2:
            k = rng.randint(1, min(3, len(lst) - 1))
            picked = rng.sample(lst, k)
            target = rng.choice([e for e in lst if e not in picked])
            pos = rng.choice(["before", "after"])
            ref_move_relative(lst, [e["physical_path"] for e in picked], target["physical_path"], pos)
            kw = {"before_id": target["_sid"]} if pos == "before" else {"after_id": target["_sid"]}
            store.move([e["_sid"] for e in picked], tier, **kw)
        elif op == "nudge" and lst:
            k = rng.randint(1, min(2, len(lst)))
            picked = rng.sample(lst, k)
            direction = rng.choice(["up", "down"])
            ref_nudge(lst, [e["physical_path"] for e in picked], direction, ls.FOLDER_OF_TIER[tier])
            store.nudge([e["_sid"] for e in picked], direction)
        elif op == "insert":
            kind = rng.choice(["show", "newshow", "loose", "hato"])
            tab = rng.choice(list(ls.ANALYSED))
            folder = ls.FOLDER_OF_TIER[tab]
            if kind == "show":
                dirs = sorted({e["physical_path"].rsplit("/", 1)[0] for t in ls.ANALYSED for e in model.lists[t]
                               if e["physical_path"].count("/") == 2} - tainted)
                if not dirs:
                    continue
                d = rng.choice(dirs)
                tab = ls.TIER_OF_FOLDER[d.split("/", 1)[0]]
            elif kind == "newshow":
                counter[0] += 1
                d = f"{folder}/{words[counter[0] % len(words)]}{counter[0]}"
            elif kind == "loose":
                d = folder
            else:
                d, tab = ls.HATO_FOLDER, "now"
            rels = [fresh(d, ".txt" if kind == "loose" else ".srt") for _ in range(rng.randint(1, 3))]
            files = [touch(data_dir, r, f"{r}\n") for r in rels]
            entries = [ls.make_entry(r, "Manual Import", ls._detect_source_type(f)) for r, f in zip(rels, files)]
            change = store.insert(files, tab)
            for e, sid in zip(entries, change.added):
                e["_sid"] = sid
            model.insert(entries, tab)
        elif op == "remove" and lst:
            picked = rng.sample(lst, rng.randint(1, min(2, len(lst))))
            model.lists[tier] = [e for e in lst if e not in picked]
            store.remove([e["_sid"] for e in picked])
        elif op == "tier" and lst:
            picked = rng.sample(lst, rng.randint(1, min(2, len(lst))))
            if rng.random() < 0.5 and tier in Model.NEXT_DOWN:
                target = Model.NEXT_DOWN[tier]
            else:
                target = Model.GRADUATE[tier]
            for e in picked:
                tainted.add(e["physical_path"].rsplit("/", 1)[0])
                if target:
                    tainted.add(ls.FOLDER_OF_TIER[target] + "/" + e["physical_path"].split("/", 1)[1].rsplit("/", 1)[0])
            sids = [e["_sid"] for e in picked]
            model.set_tier(tier, picked, target)
            store.set_tier(sids, target or "graduated")
        else:
            continue
        for t in ls.ANALYSED:
            assert store.ids(t) == model.ids(t), f"step {step}: {op} diverged in {t}"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_property_1000_random_steps_match_todays_code(language):
    """WP-L2 #1: a fixed seed, 1,000 random moves, nudges, inserts, removes and tier changes on a library
    whose folders match their tiers, no undo → the same order as today's code after every step."""
    _run_property(language, 1000, seed=20261004)


# ================================================================================================ #
# 2. undo
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_proof_add_then_a_drag_then_undo_the_add(language):
    """ORDER L1.2's proof: Add; a drag of another item; undo(the Add) → the Add undone, the drag kept.
    Today's whole-manifest snapshot would erase the drag (RD-A6)."""
    store = migrated(language)
    data_dir, _u = roots(language)
    rel = "HighPriority/" + names(language)[40] + "/" + names(language)[41] + ".srt"
    add = store.insert([touch(data_dir, rel)], "now")
    new_id = add.added[0]
    now = store.ids("now")
    drag = store.move([now[-1]], "now", before_id=now[1])
    dragged = store.ids("now")
    undone = store.undo(add)
    assert undone.notes == []
    assert new_id not in store.ids("now")
    assert store.ids("now") == [i for i in dragged if i != new_id], "the drag must survive the Add's undo"
    assert drag is not None
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_an_older_change_while_a_newer_one_stands(language):
    store = migrated(language)
    ids = store.ids("soon")
    first = store.move([ids[0]], "soon", after_id=ids[5])
    second = store.move([ids[8]], "soon", before_id=ids[2])
    after_second = store.ids("soon")
    store.undo(first)
    expected = list(after_second)
    expected.remove(ids[0])
    expected.insert(0, ids[0])
    assert store.ids("soon") == expected
    assert store.item(ids[8])["changed_in"] == second.version
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_undos_in_a_row_on_the_same_item(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    ids = store.ids("now")
    original = list(ids)
    a = store.move([ids[0]], "now", after_id=ids[4])
    b = store.move([ids[0]], "now", after_id=ids[8])
    assert store.undo(b).notes == [] and store.undo(a).notes == []
    assert store.ids("now") == original
    rel = "HighPriority/" + names(language)[50] + "/" + names(language)[51] + ".srt"
    add = store.insert([touch(data_dir, rel)], "now")
    new_id = add.added[0]
    drag = store.move([new_id], "now", after_id=original[6])
    assert store.undo(drag).notes == [] and store.undo(add).notes == []
    assert store.ids("now") == original
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_drag_remove_undo_undo_restores_the_order(language):
    """Review R3: Undo-Remove put the row back with a NEW `changed_in`, so undoing the drag before it was
    refused ("1 item changed since"). Each undo restores the `changed_in` it replaced (§6.11)."""
    store = migrated(language)
    ids = store.ids("soon")
    original = list(ids)
    drag = store.move([ids[1]], "soon", after_id=ids[5])
    rem = store.remove([ids[1]])
    assert store.undo(rem).notes == []
    assert store.undo(drag).notes == []
    assert store.ids("soon") == original
    store.close()


_FOREIGN_MOVE = """
import sys
from app import library_store as ls
lang, data, uf, item, anchor = sys.argv[1:6]
s = ls.open_store(lang, data, uf)
s.move([int(item)], "now", after_id=int(anchor))
s.close()
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_item_another_process_changed_is_skipped_with_the_note(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    mine = store.move([ids[0], ids[1]], "now", after_id=ids[6])
    subprocess.run([sys.executable, "-c", _FOREIGN_MOVE, language, data_dir, user_files_dir, str(ids[1]),
                    str(ids[9])], cwd=REPO, env=subprocess_env(), check=True, timeout=60)
    out = store.undo(mine)
    assert out.notes == ["1 item changed since and was left as it is"]
    assert store.ids("now")[0] == ids[0]
    assert store.ids("now").index(ids[1]) == store.ids("now").index(ids[9]) + 1
    # a foreign change between two of mine is still caught
    ids = store.ids("now")
    c1 = store.move([ids[3]], "now", after_id=ids[7])
    subprocess.run([sys.executable, "-c", _FOREIGN_MOVE, language, data_dir, user_files_dir, str(ids[3]),
                    str(ids[10])], cwd=REPO, env=subprocess_env(), check=True, timeout=60)
    cur = store.ids("now")
    c2 = store.move([ids[3]], "now", before_id=cur[0])
    assert store.undo(c2).notes == []
    assert store.ids("now") == cur, "undoing my later change restores the foreign version"
    assert store.undo(c1).notes == ["1 item changed since and was left as it is"]
    assert store.ids("now") == cur
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_respace_between_a_change_and_its_undo(language):
    """Re-spacing never touches changed_in, so it can't cause a false conflict (G4)."""
    store = migrated(language, shows=6, episodes=6)
    ids = store.ids("goal")
    original = list(ids)
    change = store.move([ids[2]], "goal", after_id=ids[20])
    a, b = store.ids("goal")[10], store.ids("goal")[11]
    for n in range(60):                                       # halve the gap after `a` until it re-spaces
        others = [i for i in store.ids("goal") if i not in (a, ids[2])]
        store.move([others[-1 - (n % 5)]], "goal", after_id=a)
    seq_before_undo = store.ids("goal")
    assert store.undo(change).notes == []
    expected = [i for i in seq_before_undo if i != ids[2]]
    expected.insert(expected.index(original[1]) + 1, ids[2])
    assert store.ids("goal") == expected
    assert b
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_of_a_move_of_three_separate_runs(language):
    store = migrated(language, shows=4, episodes=5)
    ids = store.ids("soon")
    before = list(ids)
    picked = [ids[1], ids[2], ids[7], ids[12], ids[13], ids[14]]
    change = store.move(picked, "soon", after_id=ids[20])
    assert store.ids("soon") != before
    assert store.undo(change).notes == []
    assert store.ids("soon") == before, "id for id"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("command", ["set_watched", "pin"])
def test_status_write_undo_uses_the_value_check(language, command):
    """This window's set_watched (or pin), then a second writer standing in for Connect sets the same item
    again: this window's undo leaves that item, with the note, and reverts the untouched ones."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")[:3]
    change = getattr(store, command)(ids)
    other = ls.open_store(language, data_dir, user_files_dir, role="connect")
    if command == "set_watched":
        other.set_watched([ids[1]], False)
    else:
        other.unpin([ids[1]])
        other.pin([ids[1]])
    other.close()
    out = store.undo(change)
    assert out.notes == ["1 item changed since and was left as it is"]
    column = "watched" if command == "set_watched" else "pinned"
    assert sorted(i for i, _c, _n, _o in out.status) == sorted([ids[0], ids[2]])
    assert store.item(ids[0])[column] in (0, None)
    assert store.item(ids[2])[column] in (0, None)
    if command == "pin":
        assert store.item(ids[1])[column] is not None, "the second writer's pin is left as it is"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_add_trashes_rows_and_files_and_put_back_restores_both(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    rel = "LowPriority/" + names(language)[60] + "/" + names(language)[61] + ".srt"
    full = touch(data_dir, rel, "冒険\n")
    add = store.insert([full], "soon")
    with store._writing():
        store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES ('k', ?, '{}', 'x')",
                           (add.added[0],))
    ok, skipped = store.undo_check(add)                       # checked before any file is touched
    assert ok == add.added and skipped == []
    trashed = {i: ls.trash_file(data_dir, rel) for i in ok}
    assert not os.path.exists(full) and os.path.exists(os.path.join(data_dir, trashed[ok[0]]))
    undo = store.undo(add, trashed_paths=trashed)
    assert ok[0] not in store.ids("soon")
    row = store.trash_rows()[-1]
    assert row["item_id"] == ok[0] and row["trashed_path"] == trashed[ok[0]]
    back, note = ls.put_back(data_dir, row["trashed_path"], row["rel_path"])
    assert back == rel and note is None
    store.undo(undo)                                          # Undo the Undo-Add = Put back
    assert ok[0] in store.ids("soon") and os.path.exists(full)
    assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = 'k'").fetchone()[0] == ok[0]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_add_checks_before_touching_files(language):
    """An item changed since the Add: undo_check names it before any file work, and an undo that would
    have trashed its file refuses whole."""
    store = migrated(language)
    data_dir, _u = roots(language)
    rel = "GoalContent/" + names(language)[62] + ".txt"
    add = store.insert([touch(data_dir, rel)], "goal")
    store.move(add.added, "goal", after_id=store.ids("goal")[3])
    ok, skipped = store.undo_check(add)
    assert ok == [] and skipped == add.added
    with pytest.raises(ls.StoreConflict):
        store.undo(add, trashed_paths={add.added[0]: ".trash/x"})
    assert add.added[0] in store.ids("goal")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_graduate_strips_its_block_with_a_backup(language):
    store = migrated(language)
    _d, user_files_dir = roots(language)
    ids = store.ids("now")[:2]
    rels = [store.item(i)["rel_path"] for i in ids]
    grad = os.path.join(user_files_dir, "GraduatedList.txt")
    words = names(language)
    with open(grad, "w", encoding="utf-8") as f:
        f.write(f"# my list\n{words[0]}\n")
    original = open(grad, encoding="utf-8").read()
    change = store.set_tier(ids, "graduated")
    for rel in rels:                                          # today's Graduate appends one block per file
        with open(grad, "a", encoding="utf-8") as f:
            f.write(f"\n# Source: {rel} (2 words graduated)\n{words[1]}\n{words[2]}\n")
    store.undo(change)
    assert ls.strip_graduated_block(user_files_dir, language, rels) == 2
    assert open(grad, encoding="utf-8").read() == original
    assert [f for f in os.listdir(os.path.join(user_files_dir, ".trash")) if f.startswith("GraduatedList.")]
    assert store.ids("now")[:2] == ids
    store.close()


# ================================================================================================ #
# 3. re-spacing
# ================================================================================================ #

def _item_rows_changed(store, fn):
    before = store.conn.total_changes
    logs = store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0]
    fn()
    logs = store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0] - logs
    return store.conn.total_changes - before - logs


@pytest.mark.parametrize("language", LANGUAGES)
def test_sixty_moves_into_one_gap_respace_locally(language):
    store = migrated(language, shows=10, episodes=10)
    ids = store.ids("soon")
    anchor = ids[50]
    worst = 0
    respaced = False
    for n in range(60):
        cur = store.ids("soon")
        mover = cur[-1]
        changed = _item_rows_changed(store, lambda: store.move([mover], "soon", after_id=anchor))
        worst = max(worst, changed)
        respaced = respaced or changed > 3
        cur.remove(mover)
        cur.insert(cur.index(anchor) + 1, mover)
        assert store.ids("soon") == cur
    assert respaced, "60 halvings of one gap must re-space"
    assert worst <= 65, worst
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_long_run_of_moves_after_one_anchor_keeps_the_order(language):
    store = migrated(language, shows=8, episodes=8)
    ids = store.ids("goal")
    anchor = ids[3]
    expected = list(ids)
    for n in range(400):
        mover = expected[-1 - (n % 20)] if expected[-1 - (n % 20)] != anchor else expected[-21]
        store.move([mover], "goal", after_id=anchor)
        expected.remove(mover)
        expected.insert(expected.index(anchor) + 1, mover)
    assert store.ids("goal") == expected
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_whole_tier_renumber_path(language):
    """A tier too small for any window to stop short of both ends: the whole tier renumbered 1024, 2048, …"""
    store = migrated(language, shows=1, episodes=4, loose=0)
    ids = store.ids("now")
    canonical = [1024.0 * (i + 1) for i in range(len(ids))]
    renumbered = None
    for n in range(200):
        store.move([ids[3] if n % 2 == 0 else ids[2]], "now", after_id=ids[0])
        ords = [r[0] for r in store.conn.execute("SELECT ord FROM items WHERE tier = 'now' ORDER BY ord, id")]
        if n and ords == canonical:
            renumbered = n
            break
    assert renumbered is not None, "the gap ran out without the whole tier renumbered"
    assert store.ids("now")[:2] == [ids[0], ids[3] if renumbered % 2 == 0 else ids[2]]
    store.close()


def test_plan_ords_respaces_locally_and_whole():
    seq = list(range(1, 101))
    ords = {i: float(i) for i in seq}
    ords[51] = 50.0 + 1e-13
    plan = ls._plan_ords(seq, ords, {51})
    assert len(plan) <= 33 and all(plan[a] < plan[b] for a, b in zip(sorted(plan), sorted(plan)[1:]))
    import math
    tiny, key = {}, 1.0
    for i in seq:                       # every fixed key one ulp from the next: no room anywhere
        if i != 50:
            tiny[i] = key
            key = math.nextafter(key, 2.0)
    plan = ls._plan_ords(seq, tiny, {50})
    assert sorted(plan.values()) == [1024.0 * (i + 1) for i in range(100)]


# ================================================================================================ #
# 4. no-ops; 5. changed_since
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_noops_commit_nothing(language):
    store = migrated(language)
    store.register_reader("connect")
    ids = store.ids("now")
    v = store.versions()
    logs = store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0]
    mtime = os.stat(store.db_path + "-wal").st_mtime_ns if os.path.exists(store.db_path + "-wal") else None
    assert store.move([ids[2], ids[3]], "now", after_id=ids[3]) is None             # anchor inside ids
    assert store.move([ids[2], ids[3]], "now", after_id=ids[1]) is None             # already there
    assert store.move([ids[2], ids[3]], "now", before_id=ids[4]) is None
    assert store.move([ids[0]], "now") is None                                     # already at the top
    assert store.set_tier([ids[0]], "now") is None
    assert store.nudge([ids[0]], "up") is None
    assert store.set_watched([ids[0]], False) is None
    assert store.unpin([ids[0]]) is None
    assert store.versions() == v
    assert store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0] == logs
    if mtime is not None:
        assert os.stat(store.db_path + "-wal").st_mtime_ns == mtime
    store.close()


_OTHER = """
import sys
from app import library_store as ls
lang, data, uf, what, item = sys.argv[1:6]
s = ls.open_store(lang, data, uf, role="connect")
item = int(item)
if what == "move":
    ids = s.ids("now"); s.move([item], "now", after_id=ids[-1])
elif what == "receipt":
    s.receipt(item, "2026-10-04T20:00:00Z")
elif what == "pin":
    s.pin([item])
elif what == "watched":
    s.set_watched([item])
elif what == "sync":
    s.sync_disk()
s.close()
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_changed_since_counts_other_writers_only(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)

    def other(what, item):
        subprocess.run([sys.executable, "-c", _OTHER, language, data_dir, user_files_dir, what, str(item)],
                       cwd=REPO, env=subprocess_env(), check=True, timeout=60)

    ids = store.ids("now")
    token = store.token()
    store.move([ids[0]], "now", after_id=ids[4])
    assert not store.changed_since(token), "your own bumps don't count"
    for what in ("receipt", "pin", "watched"):
        other(what, ids[2])
        assert not store.changed_since(token), f"a {what} never reloads a view"
    other("move", ids[1])
    assert store.changed_since(token)
    token = store.token()
    os.remove(os.path.join(data_dir, store.item(ids[5])["rel_path"]))
    assert store.sync_disk() is not None
    assert not store.changed_since(token)                     # this process's own sync
    os.remove(os.path.join(data_dir, store.item(ids[6])["rel_path"]))
    other("sync", 0)
    assert store.changed_since(token), "another writer's availability change reloads"
    token = store.token()
    with store._writing():
        store._set_meta({"epoch": store._meta()["epoch"] + 1})
    assert store.changed_since(token), "a new epoch always reloads"
    store.close()


# ================================================================================================ #
# 6. the placement log
# ================================================================================================ #

def _events(store, after=0):
    return [tuple(r) for r in store.conn.execute(
        "SELECT item_id, kind, by, explicit FROM placement_log WHERE id > ? ORDER BY id", (after,))]


def _last_log(store):
    return store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM placement_log").fetchone()[0]


def _current(store):
    return store.ids("now") + store.ids("soon")


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_reader_no_log_rows(language):
    """2.5's case: nothing registered a reader, so no command writes the log."""
    store = migrated(language)
    data_dir, _u = roots(language)
    ids = store.ids("now")
    store.move([ids[0]], "now", after_id=ids[3])
    store.insert([touch(data_dir, "HighPriority/" + names(language)[70] + ".txt")], "now")
    store.set_tier([ids[1]], "graduated")
    store.remove([ids[2]])
    assert store.conn.execute("SELECT COUNT(*) FROM placement_log").fetchone()[0] == 0
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_move_and_its_knock_on(language):
    store = migrated(language)
    store.register_reader("connect")
    cur = _current(store)
    outside = cur[25]
    pushed = cur[19]
    mark = _last_log(store)
    store.move([outside], "now", before_id=cur[0])
    assert _events(store, mark) == [(outside, "placed", "user", 1), (outside, "entered_mine_line", "user", 1),
                                    (pushed, "left_mine_line", "user", 0)]
    mark = _last_log(store)
    store.nudge([store.ids("now")[5]], "down")
    assert [e[1:] for e in _events(store, mark)] == [("placed", "user", 1)]
    mark = _last_log(store)
    assert store.move([store.ids("now")[1]], "now", after_id=store.ids("now")[0]) is None
    assert _events(store, mark) == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_insert_and_the_previews_commit(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    pushed = _current(store)[19]
    mark = _last_log(store)
    change = store.insert([touch(data_dir, ls.HATO_FOLDER + "/" + names(language)[71] + ".srt")], "now")
    new = change.added[0]
    assert _events(store, mark) == [(new, "placed", "user", 1), (new, "entered_mine_line", "user", 1),
                                    (pushed, "left_mine_line", "user", 0)]
    mark = _last_log(store)
    rel = "HighPriority/" + names(language)[72] + " [abcdefghijk].txt"
    preview = {"title": rel.rsplit("/", 1)[1], "physical_path": rel, "parent_folder": "",
               "origin_source": "YouTube Preview", "type": "File", "status": "active"}
    change = store.insert([touch(data_dir, rel)], "now", placement="top", entries=[preview])
    assert store.ids("now")[0] == change.added[0]
    assert _events(store, mark)[0] == (change.added[0], "placed", "user", 1)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_set_tier_remove_restore(language):
    store = migrated(language)
    store.register_reader("connect")
    cur = _current(store)
    mark = _last_log(store)
    store.set_tier([cur[0]], "graduated")
    assert _events(store, mark) == [(cur[0], "finished", "user", 1), (cur[20], "entered_mine_line", "user", 0),
                                    (cur[0], "left_mine_line", "user", 1)]
    mark = _last_log(store)
    demoted = store.ids("goal")[0]
    store.set_tier([demoted], "soon")                         # lands at the top of Soon: inside the line
    assert _events(store, mark)[:2] == [(demoted, "placed", "user", 1), (demoted, "entered_mine_line", "user", 1)]
    assert [e[1:] for e in _events(store, mark)[2:]] == [("left_mine_line", "user", 0)]
    mark = _last_log(store)
    victim = _current(store)[3]
    entering = _current(store)[20]
    removed = store.remove([victim])
    assert _events(store, mark) == [(victim, "removed", "user", 1), (entering, "entered_mine_line", "user", 0),
                                    (victim, "left_mine_line", "user", 1)]
    mark = _last_log(store)
    store.restore(removed.trash_ids)
    assert _events(store, mark) == [(victim, "restored", "user", 1), (victim, "entered_mine_line", "user", 1),
                                    (entering, "left_mine_line", "user", 0)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_register_is_hatos_and_never_explicit(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    mark = _last_log(store)
    rel = ls.HATO_FOLDER + "/" + names(language)[73] + ".srt"
    change = store.register(touch(data_dir, rel), {"content_key": "c1"})
    new = change.added[0]
    assert [e for e in _events(store, mark) if e[0] == new] == [(new, "placed", "hato", 0),
                                                                (new, "entered_mine_line", "hato", 0)]
    assert all(e[2] == "hato" and e[3] == 0 for e in _events(store, mark))
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_sync_reset_and_reimport_write_crossings_only(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.register_reader("connect")
    mark = _last_log(store)
    rel = ls.HATO_FOLDER + "/" + names(language)[74] + ".srt"
    touch(data_dir, rel)
    summary = store.sync_disk()
    new = summary["added"][0]
    kinds = _events(store, mark)
    assert (new, "entered_mine_line", "sync", 0) in kinds and all(e[1] != "placed" for e in kinds)
    assert all(e[2:] == ("sync", 0) for e in kinds)
    mark = _last_log(store)
    store.move([store.ids("now")[0]], "now", after_id=store.ids("now")[-1])
    mark = _last_log(store)
    store.reset_order()
    assert all(e[1] in ("entered_mine_line", "left_mine_line") and e[2:] == ("sync", 0) for e in _events(store, mark))
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    from tests.test_library_store_support import read_doc
    doc = read_doc(user_files_dir)
    soon = doc["schedule"]["PHASE_2_SOON"]
    doc["schedule"]["PHASE_1_NOW"].insert(0, soon.pop(10))   # an older version's move into the top of NOW
    write_manifest(user_files_dir, doc)
    mark = _last_log(store)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    got = _events(store, mark)
    assert got and all(e[1] in ("entered_mine_line", "left_mine_line") and e[2:] == ("sync", 0) for e in got)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_undo_carries_the_undone_changes_values(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    ids = store.ids("goal")
    move = store.move([ids[0]], "goal", after_id=ids[4])
    mark = _last_log(store)
    store.undo(move)
    assert _events(store, mark) == [(ids[0], "placed", "undo", 1)]
    reg = store.register(touch(data_dir, "GoalContent/" + names(language)[75] + ".srt"), {"content_key": "c2"})
    mark = _last_log(store)
    store.undo(reg)
    assert _events(store, mark) == [(reg.added[0], "removed", "undo", 0)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_log_status_writes_pieces_and_rollbacks_write_nothing(language):
    store = migrated(language)
    store.register_reader("connect")
    ids = store.ids("now")
    mark = _last_log(store)
    store.set_watched(ids[:2])
    store.pin(ids[:2])
    store.unpin(ids[:1])
    store.receipt(ids[3], "2026-10-04T20:00:00Z")
    piece = store.item(ids[0])["piece_id"]
    members = [i for i in ids if store.item(i)["piece_id"] == piece]
    store.split(piece, members[2])
    with pytest.raises(sqlite3.IntegrityError):
        with store._command("move") as cmd:                   # a command that fails midway
            store._put("now", [ids[5]], ("top",), cmd.version)
            cmd.event(ids[5], "placed", 1)
            cmd.touch(["now"])
            store.conn.execute("UPDATE items SET tier = 'finished' WHERE id = ?", (ids[6],))
    assert _events(store, mark) == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_mine_line_counts_available_items_only(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    cur = _current(store)
    mark = _last_log(store)
    os.remove(os.path.join(data_dir, store.item(cur[4])["rel_path"]))
    store.sync_disk()
    assert (cur[20], "entered_mine_line", "sync", 0) in _events(store, mark)
    assert (cur[4], "left_mine_line", "sync", 0) in _events(store, mark)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_pruning_and_gap_detection(language):
    store = migrated(language)
    store.register_reader("connect")
    store.register_reader("other")
    ids = store.ids("now")
    for i in range(6):
        store.move([ids[i]], "now", after_id=ids[10])
    events, gap = store.read_events("connect")
    assert len(events) >= 6 and not gap
    store.advance_reader("connect", events[3][0])
    assert store.prune_log() == 0, "'other' hasn't read any"
    store.advance_reader("other", events[2][0])
    assert store.prune_log() == events[2][0]                  # past every reader's watermark
    assert store.read_events("connect")[1] is False
    assert store.prune_log(now=time.time() + 31 * 86400) > 0  # after 30 days, read or not
    events, gap = store.read_events("other")
    assert events == [] and gap, "the log is empty while log_seq is above the watermark"
    store.move([ids[0]], "now", after_id=ids[11])
    store.move([ids[1]], "now", after_id=ids[11])
    with store._writing():
        store.conn.execute("DELETE FROM placement_log WHERE id = (SELECT MIN(id) FROM placement_log)")
    events, gap = store.read_events("other")
    assert events and gap, "the oldest id left is above the watermark + 1"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_connects_watermark_starts_at_log_seq(language):
    """✅ G1.1-2: older events are never mined — the watermark is set when Connect is first switched on."""
    store = migrated(language)
    store.register_reader("window")
    ids = store.ids("now")
    store.move([ids[0]], "now", after_id=ids[3])
    store.register_reader("connect")
    assert store.meta()["reader:connect"] == _last_log(store) > 0
    assert store.read_events("connect") == ([], False)
    store.register_reader("connect")                         # set once
    store.move([ids[1]], "now", after_id=ids[3])
    assert len(store.read_events("connect")[0]) >= 1
    store.close()


# ================================================================================================ #
# 7. versions
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_versions_plan_current_and_journey_pending(language):
    store = migrated(language)
    ids = store.ids("now")
    v = store.versions()
    assert store.journey_pending()                           # a migration starts pending (no order CSV)
    store.record_analysed(v["order_version"])
    store.record_planned(v["order_version"], v["pins_version"])
    assert store.versions()["state_version"] == v["state_version"], "bookkeeping bumps nothing"
    assert not store.journey_pending() and store.plan_current()
    store.move([ids[0]], "now", after_id=ids[2])
    assert store.journey_pending() and not store.plan_current()
    v = store.versions()
    store.record_planned(v["order_version"], v["pins_version"])
    assert store.plan_current() and store.journey_pending()
    store.record_analysed(v["order_version"])
    assert not store.journey_pending()
    store.pin([ids[1]])
    assert not store.plan_current(), "a pin makes the plan not current"
    store.record_analysed(5 + v["order_version"])
    store.record_analysed(3)
    assert store.versions()["analysed_order_version"] == 5 + v["order_version"]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_which_version_moves_on_what(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("now")
    v0 = store.versions()
    store.receipt(ids[0], "2026-10-04T21:00:00Z")
    v1 = store.versions()
    assert (v1["order_version"], v1["availability_version"]) == (v0["order_version"], v0["availability_version"])
    assert v1["state_version"] == v0["state_version"] + 1
    rel = store.item(ids[1])["rel_path"]
    full = os.path.join(data_dir, rel)
    os.rename(full, full.replace(".srt", "_v2.srt"))
    store.sync_disk()                                         # a rename
    v2 = store.versions()
    assert v2["order_version"] > v1["order_version"]
    os.remove(os.path.join(data_dir, store.item(ids[2])["rel_path"]))
    store.sync_disk()                                         # an analysed item going missing
    v3 = store.versions()
    assert v3["order_version"] > v2["order_version"] and v3["availability_version"] > v2["availability_version"]
    gid = store.set_tier([ids[3]], "graduated").items[0]["id"]
    v4 = store.versions()
    os.remove(os.path.join(data_dir, store.item(gid)["rel_path"]))
    store.sync_disk()                                         # any availability change, any tier
    v5 = store.versions()
    assert v5["availability_version"] > v4["availability_version"] and v5["order_version"] == v4["order_version"]
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    from tests.test_library_store_support import read_doc
    doc = read_doc(user_files_dir)
    doc["schedule"]["PHASE_1_NOW"][0]["status"] = "watched"   # an entry edit by an older version
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    assert store.versions()["order_version"] > v5["order_version"]
    store.close()


# ================================================================================================ #
# 8. the new commands
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_insert_at_before_and_after_an_anchor(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    ids = store.ids("soon")
    files = [touch(data_dir, f"LowPriority/{w[80]}/{w[81]}_{n}.srt") for n in range(3)]
    change = store.insert_at(files, ids[4], before=True)
    got = store.ids("soon")
    assert got[got.index(ids[4]) - 3:got.index(ids[4])] == change.added
    assert all(store.item(i)["changed_in"] == change.version for i in change.added)
    files2 = [touch(data_dir, f"GoalContent/{w[82]}_{n}.txt") for n in range(2)]
    after = store.insert_at(files2, ids[4], before=False)
    got = store.ids("soon")
    assert got[got.index(ids[4]) + 1:got.index(ids[4]) + 3] == after.added, "the anchor's tier, not the folder's"
    store.undo(after)
    store.undo(change)
    assert store.ids("soon") == ids
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_register_finds_a_synced_row_or_adds_one(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    rel = f"HighPriority/{w[1]}/{w[90]}.srt"
    touch(data_dir, rel)
    synced = store.sync_disk()["added"][0]
    before = store.item(synced)["changed_in"]
    change = store.register(os.path.join(data_dir, rel), {"content_key": "k-synced"})
    assert change.added == [] and store.item(synced)["changed_in"] == before, "a pairing alone leaves changed_in"
    assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = 'k-synced'").fetchone()[0] == synced
    first = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[91]}.srt"), {"content_key": "h1"})
    assert store.ids("now")[0] == first.added[0], "a hato drop at the top of NOW, no Hato rows yet"
    second = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[92]}.srt"), {"content_key": "h2"})
    assert store.ids("now")[0] == second.added[0], "and with Hato rows present (today: after them)"
    with store._writing():
        store._set_meta({"arrivals_on": 1})
    third = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[93]}.srt"), {"content_key": "h3"})
    assert store.ids("arrivals") == third.added
    assert all(e["physical_path"] != f"{ls.HATO_FOLDER}/{w[93]}.srt" for e in store.schedule()["PHASE_1_NOW"])
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_register_restores_the_keys_previous_pairing(language):
    """Review R6: hato re-registering a content key against a new file, then Undo: the new item went (as an
    Add) and its pairing with it, but the key's earlier pairing was never put back, so the key mapped to
    nothing."""
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    paired = store.ids("soon")[2]
    store.register(os.path.join(data_dir, store.item(paired)["rel_path"]), {"content_key": "k-moved"})
    change = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[94]}.srt"), {"content_key": "k-moved"})
    assert change.added
    key = "SELECT item_id FROM pairings WHERE content_key = 'k-moved'"
    assert store.conn.execute(key).fetchone()[0] == change.added[0]
    store.undo(change)
    assert change.added[0] not in store.ids("now")
    assert store.conn.execute(key).fetchone()[0] == paired
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_register_with_no_store(language):
    data_dir, user_files_dir, doc = library(language)
    w = names(language)
    path = touch(data_dir, f"{ls.HATO_FOLDER}/{w[94]}.srt")
    assert ls.register_headless(language, path, {"content_key": "none"}, data_dir, user_files_dir) == ls.EXIT_NEEDS_YOU
    assert not os.path.exists(ls.library_db_path(language, data_dir)), "nothing written"
    write_manifest(user_files_dir, doc)
    assert ls.register_headless(language, path, {"content_key": "built"}, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.conn.execute("SELECT COUNT(*) FROM pairings").fetchone()[0] == 1
    assert store.ids("now")[0] == store.item_id(f"{ls.HATO_FOLDER}/{w[94]}.srt")
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_split_and_join_move_nothing(language):
    store = migrated(language)
    ids = store.ids("now")
    piece = store.item(ids[0])["piece_id"]
    members = [i for i in ids if store.item(i)["piece_id"] == piece]
    v = store.versions()
    split = store.split(piece, members[2])
    assert store.ids("now") == ids and store.versions()["order_version"] == v["order_version"]
    new_piece = store.item(members[2])["piece_id"]
    assert new_piece != piece and store.item(members[1])["piece_id"] == piece
    assert store.item(members[2])["changed_in"] == split.version
    join = store.join([piece, new_piece])
    assert {store.item(i)["piece_id"] for i in members} == {piece}
    store.undo(join)
    assert store.item(members[3])["piece_id"] == new_piece
    store.undo(split)
    assert {store.item(i)["piece_id"] for i in members} == {piece}
    assert store.ids("now") == ids
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_status_writes_never_touch_changed_in_or_order(language):
    store = migrated(language)
    ids = store.ids("soon")[:3]
    before = [store.item(i)["changed_in"] for i in ids]
    v = store.versions()
    store.set_watched(ids)
    store.pin(ids)
    store.unpin(ids[:1])
    assert [store.item(i)["changed_in"] for i in ids] == before
    after = store.versions()
    assert after["order_version"] == v["order_version"] and after["pins_version"] == v["pins_version"] + 2
    store.close()


# ================================================================================================ #
# 9. insert
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_add_folder_leaves_graduated_and_demoted_episodes_where_they_are(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    show = [i for i in store.ids("now") if store.item(i)["parent_folder"]][:4]
    rels = [store.item(i)["rel_path"] for i in show]
    store.set_tier([show[0]], "graduated")
    store.set_tier([show[1]], "soon")
    folder = rels[0].rsplit("/", 1)[0]
    new = touch(data_dir, f"{folder}/{names(language)[95]}_第05話.srt")
    change = store.insert([os.path.join(data_dir, r) for r in rels] + [new], "now")
    assert [e[1] for e in change.existing] == show
    assert store.item(show[0])["tier"] == "graduated" and store.item(show[1])["tier"] == "soon"
    soon = store.ids("soon")
    assert soon[soon.index(show[1]) + 1] == change.added[0], "joins its show after its last row (in Soon)"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_row_a_sync_added_mid_copy_is_taken_over(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    started = ls._now()
    rel = f"GoalContent/{names(language)[96]}.txt"
    full = touch(data_dir, rel)
    synced = store.sync_disk()["added"][0]
    change = store.insert([full], "goal", started_at=started)
    assert change.added == [synced]
    assert store.item(synced)["entry"]["origin_source"] == "Manual Import"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_commits_recheck(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    w = names(language)
    rel = f"HighPriority/{w[97]}.txt"
    check = store.check(paths=[rel])
    full = touch(data_dir, rel)                                # the file work
    other = ls.open_store(language, data_dir, user_files_dir)
    other.receipt(other.ids("soon")[0], "2026-10-04T22:00:00Z")
    other.move([other.ids("goal")[0]], "goal", after_id=other.ids("goal")[3])
    change = store.insert([full], "now", check=check)
    assert change.added, "a change elsewhere never throws an Add away"
    rel2 = f"HighPriority/{w[98]}.txt"
    check = store.check(paths=[rel2])
    full2 = touch(data_dir, rel2)
    other.insert([full2], "now")                              # another window added the same file
    other.close()
    v = store.versions()
    with pytest.raises(ls.StoreConflict):
        store.insert([full2], "now", check=check)
    assert store.versions() == v
    store.close()


# ================================================================================================ #
# 10. remove and Put back
# ================================================================================================ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_remove_with_sixty_pairings_and_three_links(language):
    store = migrated(language)
    victim = store.ids("now")[2]
    with store._writing():
        store.conn.executemany("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES (?, ?, ?, ?)",
                               [(f"key{n}", victim, json.dumps({"n": n}), "t") for n in range(60)])
        store.conn.executemany("INSERT INTO anki_links (item_id, note_id, source, linked_at) VALUES (?, ?, ?, ?)",
                               [(victim, 1000 + n, "anki_miner", "t") for n in range(3)])
    removed = store.remove([victim])
    assert store.conn.execute("SELECT COUNT(*) FROM pairings WHERE item_id = ?", (victim,)).fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM anki_links WHERE item_id = ?", (victim,)).fetchone()[0] == 0
    state = json.loads(store.trash_rows()[-1]["item_state"])
    assert len(state["pairings"]) == 60 and len(state["anki_links"]) == 3
    other = store.ids("now")[0]
    with store._writing():
        store.conn.execute("INSERT INTO pairings (content_key, item_id, pairing, paired_at) VALUES ('key7', ?, 'newer', 'u')",
                           (other,))
    store.restore(removed.trash_ids)
    assert store.conn.execute("SELECT COUNT(*) FROM pairings WHERE item_id = ?", (victim,)).fetchone()[0] == 59
    assert store.conn.execute("SELECT pairing FROM pairings WHERE content_key = 'key7'").fetchone()[0] == "newer"
    assert store.conn.execute("SELECT COUNT(*) FROM anki_links WHERE item_id = ?", (victim,)).fetchone()[0] == 3
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_twelve_runs_put_back_one_at_a_time_in_any_order(language):
    store = migrated(language, shows=10, episodes=6)
    ids = store.ids("goal")
    before = list(ids)
    runs = [ids[i:i + 2] for i in range(1, 60, 5)][:12]
    removed = store.remove([i for run in runs for i in run])
    order = list(removed.trash_ids)
    random.Random(7).shuffle(order)
    for trash_id in order:
        store.restore([trash_id])
    assert store.ids("goal") == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_back_never_overwrites_and_recreates_folders(language):
    data_dir, _u = roots(language)
    w = names(language)
    rel = f"LowPriority/{w[100]}/{w[101]}.srt"
    touch(data_dir, rel, "old\n")
    trashed = ls.trash_file(data_dir, rel)
    newer = touch(data_dir, rel, "newer\n")
    back, note = ls.put_back(data_dir, trashed, rel)
    assert back == rel.replace(".srt", "_1.srt") and note
    assert open(newer, encoding="utf-8").read() == "newer\n"
    rel2 = f"LowPriority/{w[102]}/{w[103]}.srt"
    touch(data_dir, rel2)
    trashed2 = ls.trash_file(data_dir, rel2)
    os.rmdir(os.path.join(data_dir, "LowPriority", w[102]))
    assert ls.put_back(data_dir, trashed2, rel2) == (rel2, None)
    os.remove(os.path.join(data_dir, rel2))
    assert ls.put_back(data_dir, trashed2, rel2) == (None, "purged")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_trash_row_already_restored_is_refused(language):
    store = migrated(language)
    removed = store.remove([store.ids("now")[0]])
    store.restore(removed.trash_ids)
    v = store.versions()
    with pytest.raises(ls.StoreConflict, match="already"):
        store.restore(removed.trash_ids)
    assert store.versions() == v
    store.close()


# ================================================================================================ #
# 11. crashes
# ================================================================================================ #

class _Faulty:
    """A connection that raises at the Nth statement inside a transaction (COMMIT included)."""

    def __init__(self, conn, fail_at):
        self._conn, self.fail_at, self.n = conn, fail_at, 0

    def _tick(self, sql):
        if self._conn.in_transaction and not sql.startswith(("ROLLBACK", "PRAGMA query_only")):
            self.n += 1
            if self.n == self.fail_at:
                raise sqlite3.OperationalError(f"injected at statement {self.n}")

    def execute(self, sql, *args):
        self._tick(sql)
        return self._conn.execute(sql, *args)

    def executemany(self, sql, *args):
        self._tick(sql)
        return self._conn.executemany(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _dump(store):
    conn = store.conn
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        out[name] = sorted(map(repr, conn.execute(f"SELECT * FROM {name}").fetchall()))
    return out


def _inject(store, command):
    """Raise at each statement of `command` in turn: nothing changes, until it runs clean."""
    real = store.conn
    for fail_at in range(1, 200):
        before = _dump(store)
        store.conn = _Faulty(real, fail_at)
        try:
            result = command()
        except sqlite3.OperationalError as exc:
            assert "injected" in str(exc)
            store.conn = real
            assert not real.in_transaction
            assert _dump(store) == before, f"statement {fail_at} left a change behind"
            continue
        finally:
            store.conn = real
        assert _dump(store) != before
        return result, fail_at
    raise AssertionError("never completed")


@pytest.mark.parametrize("language", LANGUAGES)
def test_fault_injection_at_every_statement_of_every_command(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    w = names(language)
    store.register_reader("connect")
    ids = store.ids("now")
    counts = {}
    move, counts["move"] = _inject(store, lambda: store.move([ids[0], ids[5]], "now", after_id=ids[9]))
    _r, counts["undo"] = _inject(store, lambda: store.undo(move))
    _r, counts["nudge"] = _inject(store, lambda: store.nudge([ids[3]], "down"))
    _r, counts["set_tier"] = _inject(store, lambda: store.set_tier([ids[1]], "goal"))
    f = touch(data_dir, f"HighPriority/{w[110]}/{w[111]}.srt")
    _r, counts["insert"] = _inject(store, lambda: store.insert([f], "now"))
    removed, counts["remove"] = _inject(store, lambda: store.remove([ids[2]]))
    _r, counts["restore"] = _inject(store, lambda: store.restore(removed.trash_ids))
    g = touch(data_dir, f"{ls.HATO_FOLDER}/{w[112]}.srt")
    _r, counts["register"] = _inject(store, lambda: store.register(g, {"content_key": "inj"}))
    _r, counts["set_watched"] = _inject(store, lambda: store.set_watched([ids[4]]))
    _r, counts["pin"] = _inject(store, lambda: store.pin([ids[4]]))
    piece = store.item(ids[6])["piece_id"]
    members = [i for i in store.ids("now") if store.item(i)["piece_id"] == piece]
    _r, counts["split"] = _inject(store, lambda: store.split(piece, members[1]))
    touch(data_dir, f"LowPriority/{w[113]}.txt")
    _r, counts["sync_disk"] = _inject(store, lambda: store.sync_disk())
    store.move([store.ids("goal")[0]], "goal", after_id=store.ids("goal")[-1])
    _r, counts["reset_order"] = _inject(store, lambda: store.reset_order())
    assert all(n > 2 for n in counts.values()), counts
    assert store.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    store.close()


_KILLED = """
import sys, time
from app import library_store as ls
lang, data, uf = sys.argv[1:4]
s = ls.open_store(lang, data, uf)
with s._writing():
    s.conn.execute("UPDATE items SET ord = -ord")
    print("in", flush=True)
    time.sleep(60)
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_process_killed_mid_transaction_leaves_the_old_order(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    before = {t: store.ids(t) for t in ls.ANALYSED}
    store.close()
    proc = subprocess.Popen([sys.executable, "-c", _KILLED, language, data_dir, user_files_dir], cwd=REPO,
                            env=subprocess_env(), stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "in"
    proc.kill()
    proc.wait(10)
    store = ls.open_store(language, data_dir, user_files_dir)
    assert store.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert {t: store.ids(t) for t in ls.ANALYSED} == before
    ids = store.ids("now")
    assert store.move([ids[0]], "now", after_id=ids[1]) is not None, "the write lock came back"
    store.close()


# ================================================================================================ #
# 12. two writers
# ================================================================================================ #

_WRITER_MOVES = """
import sys
from app import library_store as ls
lang, data, uf, item, anchor, n = sys.argv[1:7]
s = ls.open_store(lang, data, uf)
for i in range(int(n)):
    s.move([int(item)], "soon", after_id=int(anchor)) if i % 2 == 0 else s.move([int(item)], "soon")
s.move([int(item)], "soon", after_id=int(anchor))
s.close()
"""


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_writers_both_land(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    ids = store.ids("soon")
    count = len(ids)

    def spawn(item, anchor):
        return subprocess.Popen([sys.executable, "-c", _WRITER_MOVES, language, data_dir, user_files_dir,
                                 str(item), str(anchor), "40"], cwd=REPO, env=subprocess_env())

    a, b = spawn(ids[0], ids[5]), spawn(ids[1], ids[9])
    assert a.wait(120) == 0 and b.wait(120) == 0
    got = store.ids("soon")
    assert len(got) == count and sorted(got) == sorted(ids)
    assert got[got.index(ids[5]) + 1] == ids[0] and got[got.index(ids[9]) + 1] == ids[1]
    a, b = spawn(ids[2], ids[5]), spawn(ids[2], ids[9])        # the same item
    assert a.wait(120) == 0 and b.wait(120) == 0
    got = store.ids("soon")
    assert sorted(got) == sorted(ids)
    assert got[got.index(ids[2]) - 1] in (ids[5], ids[9], ids[0])
    errors = []

    def thread(item, anchor):
        try:
            s = ls.open_store(language, data_dir, user_files_dir)
            for i in range(30):
                s.move([item], "soon", after_id=anchor) if i % 2 == 0 else s.move([item], "soon")
            s.move([item], "soon", after_id=anchor)
            s.close()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=thread, args=(ids[3], ids[7])),
               threading.Thread(target=thread, args=(ids[4], ids[11]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    got = store.ids("soon")
    assert got[got.index(ids[7]) + 1] == ids[3] and got[got.index(ids[11]) + 1] == ids[4]
    store.close()


# ================================================================================================ #
# 13. 100k; 14. the full command, timed (the done condition)
# ================================================================================================ #

def _flush_alone(folder):
    """The flush measured alone on the same disk: a one-row commit, synchronous=FULL, WAL."""
    db = os.path.join(folder, "flush_probe.db")
    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
    times = []
    for i in range(40):
        t0 = time.perf_counter()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO t VALUES (?)", (i,))
        conn.execute("COMMIT")
        times.append(time.perf_counter() - t0)
    conn.close()
    return statistics.median(times)


def _record(line):
    out = os.environ.get("SURASURA_STORE_BENCH_OUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(line + "\n")


@pytest.mark.parametrize("language", LANGUAGES)
def test_100k_moves_touch_only_the_moved_rows(language):
    """B2: a 100k library built in one transaction; 20 moves; each commits only the moved row, its log
    rows (a reader registered) and the two version rows — never a whole tier. The median against the
    flush alone + 1 ms is asserted in the timed run (SURASURA_STORE_BENCH=1)."""
    store = big_store(language, 100_000 if BENCH else 20_000)
    store.register_reader("connect")
    ids = store.ids("soon")
    rng = random.Random(3)
    times = []
    for _ in range(20):
        item, anchor = rng.sample(ids, 2)
        before = store.conn.total_changes
        logs = _last_log(store)
        t0 = time.perf_counter()
        store.move([item], "soon", after_id=anchor)
        times.append(time.perf_counter() - t0)
        log_rows = _last_log(store) - logs
        assert store.conn.total_changes - before == 1 + log_rows + 2      # the item, its log rows, 2 versions
    if BENCH:
        flush = _flush_alone(os.path.dirname(store.db_path))
        median = statistics.median(times)
        _record(f"13 {language} 100k: move median {median * 1000:.2f} ms, flush alone {flush * 1000:.2f} ms")
        assert median <= flush + 0.001, (median, flush)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("size", [2_000, 100_000])
def test_the_full_move_command_timed(language, size):
    """The done condition (WP-L2 #14): `move` as built — its reads, item rows and log rows, the commit,
    under the write lock — over 1,000 moves of 1 item and of 12, on the real schema, a reader registered:
    p50 ≤ 2 ms and p95 ≤ 5 ms on this desktop. The budgets are asserted only in the timed run
    (SURASURA_STORE_BENCH=1, under the test lock); otherwise a short functional pass at 2k."""
    if size > 2_000 and not BENCH:
        pytest.skip("the 100k timing runs in the timed proof only")
    store = big_store(language, size)
    store.register_reader("connect")
    ids = store.ids("soon")
    rng = random.Random(size)
    runs = 1000 if BENCH else 50
    seq = list(ids)
    for block in (1, 12):
        times = []
        for _ in range(runs):
            start = rng.randrange(0, len(seq) - block - 1)
            moving = seq[start:start + block]
            anchor = rng.choice([i for i in rng.sample(seq, 3) if i not in moving] or [seq[-1]])
            t0 = time.perf_counter()
            store.move(moving, "soon", after_id=anchor)
            times.append(time.perf_counter() - t0)
            if size <= 2_000:
                del seq[start:start + block]
                at = seq.index(anchor) + 1
                seq[at:at] = moving
        times.sort()
        p50, p95 = times[len(times) // 2], times[int(len(times) * 0.95)]
        if BENCH:
            _record(f"14 {language} {size}: {block}-item move p50 {p50 * 1000:.2f} ms p95 {p95 * 1000:.2f} ms")
            assert p50 <= 0.002 and p95 <= 0.005, (block, p50, p95)
        if size <= 2_000:
            assert store.ids("soon") == seq
    assert sorted(store.ids("soon")) == sorted(ids)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_set_tier_and_a_small_insert_timed_at_100k(language):
    """§6.12: a set_tier or a small insert costs what a move does. Timed in the bench run only."""
    if not BENCH:
        pytest.skip("timed in the bench run only")
    store = big_store(language, 100_000)
    store.register_reader("connect")
    data_dir, _u = roots(language)
    rng = random.Random(9)
    ids = store.ids("goal")
    tiers, inserts = [], []
    for n in range(200):
        item = rng.choice(ids)
        t0 = time.perf_counter()
        store.set_tier([item], "soon" if n % 2 == 0 else "goal")
        tiers.append(time.perf_counter() - t0)
    for n in range(100):
        rel = f"LowPriority/{names(language)[n % 20]}{n}/{n:03d}.srt"
        full = touch(data_dir, rel)
        t0 = time.perf_counter()
        store.insert([full], "soon")
        inserts.append(time.perf_counter() - t0)
    for name, times in (("set_tier", tiers), ("insert", inserts)):
        times.sort()
        p50, p95 = times[len(times) // 2], times[int(len(times) * 0.95)]
        _record(f"14 {language} 100k: {name} p50 {p50 * 1000:.2f} ms p95 {p95 * 1000:.2f} ms")
        assert p50 <= 0.002 and p95 <= 0.005, (name, p50, p95)
    store.close()
