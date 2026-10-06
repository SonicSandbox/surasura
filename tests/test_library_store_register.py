"""P2.1's store points for `register` (agreed with the store's owner, Kura, 2026-10-06): what `register_headless`
answers, the pairing record compared by value, a path outside the library refused, and a back-fill registration that
logs no placement event.

Why these matter: hato records the answer (`file_id`, where it landed) beside its own ledger row and retries on its
next run, so the same record sent twice — or with its keys in another order — must write nothing and log nothing; a
path outside the library must never become a `../…` item; and the ~60 files already in hato's folder, paired by the
back-fill when Connect is first switched on, must never be mined because of it (✅ G1.1-2, the watermark). Every test
runs for Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT.
"""
import json
import os

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES, library, migrated, names, roots, touch, write_manifest


def _record(key, **more):
    """A pairing record shaped like hato's v1 (09-hato-layer §1), with synthetic paths."""
    record = {"schema": 1, "content_key": key, "producer": "hato", "producer_version": "1.0.10", "language": "ja",
              "video_path": "D:/Shows/Example/Example - 05.mkv", "video_size": 1473922811, "verdict": "timed",
              "show": {"title": "Example", "season": 1, "episode": 5, "movie": False}}
    record.update(more)
    return record


def _events(store):
    return [tuple(r) for r in store.conn.execute("SELECT item_id, kind, by, explicit FROM placement_log ORDER BY id")]


def _state_version(store):
    return store.meta()["state_version"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_register_headless_answers_where_the_item_landed_and_what_became_of_the_pairing(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    w = names(language)
    drop = touch(data_dir, f"{ls.HATO_FOLDER}/{w[80]}.srt")
    first = ls.register_headless(language, drop, _record("v1-aa"), data_dir, user_files_dir)
    assert (first.code, first.landed, first.tier, first.position, first.pairing) == (ls.EXIT_DONE, "now-top", "now", 1,
                                                                                    "new")
    again = ls.register_headless(language, drop, _record("v1-aa"), data_dir, user_files_dir)
    assert again == ls.Registered(ls.EXIT_DONE, first.file_id, "already", "now", 1, "same")
    changed = ls.register_headless(language, drop, _record("v1-aa", verdict="untimed"), data_dir, user_files_dir)
    assert (changed.file_id, changed.landed, changed.pairing) == (first.file_id, "already", "replaced")

    # A file outside hato's folder follows §6.10 rule 3: after its show's last row
    show = os.path.dirname(doc["schedule"]["PHASE_1_NOW"][0]["physical_path"])
    beside = touch(data_dir, f"{show}/{w[81]}.srt")
    placed = ls.register_headless(language, beside, _record("v1-bb"), data_dir, user_files_dir)
    assert (placed.landed, placed.tier, placed.pairing) == ("show", "now", "new") and placed.position > 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_register_lands_in_new_arrivals_with_the_switch_on(language):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.bookkeeping({"arrivals_on": 1}, copy_carries=True)
    store.close()
    drop = touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[82]}.srt")
    answer = ls.register_headless(language, drop, _record("v1-cc"), data_dir, user_files_dir)
    assert (answer.landed, answer.tier, answer.position, answer.pairing) == ("arrivals", "arrivals", 1, "new")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_record_with_its_keys_reordered_writes_nothing(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    drop = touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[83]}.srt")
    record = _record("v1-dd")
    store.register(drop, record)
    version, events = _state_version(store), _events(store)
    twin = dict(reversed(list(record.items())))
    assert json.dumps(twin) != json.dumps(record) and twin == record
    assert store.register(drop, twin) is None, "nothing to undo"
    assert (_state_version(store), _events(store)) == (version, events), "no write, no event"
    stored = store.conn.execute("SELECT pairing FROM pairings WHERE content_key = 'v1-dd'").fetchone()[0]
    assert stored == json.dumps(record, sort_keys=True, ensure_ascii=False), "written canonically"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_row_written_before_keys_were_sorted_equals_its_record(language):
    """A 2.5 store holds rows in hato's own key order; the same record again is still `same`."""
    store = migrated(language)
    data_dir, _u = roots(language)
    drop = touch(data_dir, f"{ls.HATO_FOLDER}/{names(language)[84]}.srt")
    record = _record("v1-ee")
    store.register(drop, record)
    with store._writing():
        store.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = 'v1-ee'",
                           (json.dumps(dict(reversed(list(record.items()))), ensure_ascii=False),))
    version = _state_version(store)
    assert store.register(drop, record) is None and _state_version(store) == version
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_path_outside_the_library_is_refused_before_anything_is_written(language, tmp_path):
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    version, count = _state_version(store), store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    outside = tmp_path / "elsewhere" / f"{names(language)[85]}.srt"
    outside.parent.mkdir()
    outside.write_text("1\n00:00:01,000 --> 00:00:02,000\n" + names(language)[85] + "\n", encoding="utf-8")
    for path in (str(outside), os.path.join(data_dir, "..", "stray.srt"), "../stray.srt", data_dir):
        with pytest.raises(ls.NotInLibrary):
            store.register(path, _record("v1-out"))
    assert (_state_version(store), store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]) == (version, count)
    assert store.conn.execute("SELECT COUNT(*) FROM pairings").fetchone()[0] == 0
    store.close()
    answer = ls.register_headless(language, str(outside), _record("v1-out"), data_dir, user_files_dir)
    assert answer == ls.Registered(ls.EXIT_BAD_DATA, None, None, None, None, None)


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows'")
def test_a_path_on_another_drive_is_refused_not_a_crash():
    store = migrated("ja")
    other = "Z:\\Shows\\x.srt" if not os.environ["SURASURA_TEST_ROOT"].upper().startswith("Z") else "Y:\\x.srt"
    with pytest.raises(ls.NotInLibrary):
        store.register(other, _record("v1-drive"))
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_backfill_registration_logs_no_event_so_connect_sees_nothing(language):
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    w = names(language)
    quiet = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[86]}.srt"), _record("v1-ff"), backfill=True)
    new = quiet.added[0]
    assert store.ids("now")[0] == new, "placed as any hato drop"
    rows, gap = store.read_events("connect")
    assert not gap and [r for r in rows if r[1] == new] == [], "neither placed nor entered_mine_line"
    assert store.conn.execute("SELECT item_id FROM pairings WHERE content_key = 'v1-ff'").fetchone()[0] == new
    # an item already in the library, paired by the back-fill: nothing logged either
    existing = store.ids("soon")[0]
    store.register(os.path.join(data_dir, store.item(existing)["rel_path"]), _record("v1-gg"), backfill=True)
    assert [r for r in store.read_events("connect")[0] if r[1] == existing] == []
    # the same drop without the flag is logged as hato's, never explicit
    loud = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[87]}.srt"), _record("v1-hh")).added[0]
    assert [(r[2], r[3], r[4]) for r in store.read_events("connect")[0] if r[1] == loud] == [
        ("placed", "hato", 0), ("entered_mine_line", "hato", 0)]
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_events_say_who_made_them_and_only_a_person_is_explicit(language):
    """✅ G1.3-5: another program's placement counts like yours, its name recorded. A register is logged as its
    record's producer (a short name, else "hato"); `move` / `set_tier` as their `by`, explicit only for "user"."""
    store = migrated(language)
    data_dir, _u = roots(language)
    store.register_reader("connect")
    w = names(language)
    tool = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[88]}.srt"), _record("v1-ii", producer="tool_2")).added[0]
    odd = store.register(touch(data_dir, f"{ls.HATO_FOLDER}/{w[89]}.srt"),
                         _record("v1-jj", producer="Not A Name!")).added[0]
    item = store.ids("soon")[0]
    store.move([item], "now", by="my-script")
    store.set_tier([item], "graduated", by="my-script")
    other = store.ids("soon")[0]
    store.move([other], "now")
    log = [(r[1], r[2], r[3], r[4]) for r in store.read_events("connect")[0]]
    assert (tool, "placed", "tool_2", 0) in log and (odd, "placed", "hato", 0) in log
    assert (item, "placed", "my-script", 0) in log and (item, "finished", "my-script", 0) in log
    assert (other, "placed", "user", 1) in log
    store.close()
