"""`surasura-cli register` (P2.1 row 2.1.1; P1.5 09-hato-layer §2): hato's pairing record into the library store.

What a wrong answer would cost:
  * the preview off must be 2.5 byte for byte — a register that wrote anything would change a library hato's users
    never asked Connect into, and add an Add to the window's undo stack;
  * hato retries on its next run and records `file_id` beside its ledger row: the same record twice (or with its keys
    reordered) must write nothing, and a busy store must say `busy`, never `failed`;
  * a record on the command line would land in the log: it travels on stdin;
  * a path outside the library must never become an item, and a copy that isn't the file hato paired must never be
    mined — both `bad-data`, nothing written.

Real Japanese and Chinese subtitles from tests/Test Resources, synthetic titles, the test's own root.
"""
import json
import os

import pytest

from app import library_store
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _register(rec, *args):
    return h.call("register", "--pairing", c.write_record(rec), *args)


def _pairings(lang="ja"):
    with c.store(lang) as s:
        return s.conn.execute("SELECT COUNT(*) FROM pairings").fetchone()[0]


def test_with_the_preview_off_register_answers_skipped_and_writes_nothing():
    c.library(connect=False)
    path = c.drop("Example Show - 05.ja.srt")
    before, stored = c.snapshot(), c.store_state()
    code, line = _register(c.record(path, "video-05"))
    assert code == 0 and line["skipped"] == "connect preview off" and line["landed"] == "skipped"
    assert line["file_id"] is None and line["content_key"].startswith("v1-")
    before.pop("record.json", None)
    after = c.snapshot()
    after.pop("record.json", None)
    assert after == before, "master_manifest.json, the store and every other file byte-identical"
    assert c.store_state() == stored, "nothing written to the store (its WAL included)"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_hato_drop_lands_at_the_top_of_now_with_its_pairing(lang):
    c.library(lang)
    path = c.drop(f"Example Show - 05.{lang}.srt", lang)
    code, line = _register(c.record(path, "video-05", lang))
    assert code == 0, line
    assert (line["landed"], line["tier"], line["position"], line["pairing"]) == ("now-top", "now", 1, "new")
    with c.store(lang) as s:
        assert s.ids("now")[0] == line["file_id"]
        assert json.loads(s.conn.execute("SELECT pairing FROM pairings").fetchone()[0])["library_path"] == path
        assert (line["file_id"], "entered_mine_line", "hato") in c.events(s), "logged for Connect, as hato's"


def test_the_same_record_twice_or_reordered_writes_nothing_and_a_changed_one_replaces():
    c.library()
    path = c.drop("Example Show - 05.ja.srt")
    rec = c.record(path, "video-05")
    code, first = _register(rec)
    assert code == 0
    with c.store() as s:
        version, log = s.meta()["state_version"], c.events(s)
    code, again = _register(rec)
    assert code == 0 and (again["landed"], again["pairing"], again["file_id"]) == ("already", "same", first["file_id"])
    twin = dict(reversed(list(rec.items())))
    code, lines = c.register_stdin(json.dumps(twin, ensure_ascii=False).encode("utf-8"))
    assert code == 0 and h.answer(lines)["pairing"] == "same", lines
    with c.store() as s:
        assert (s.meta()["state_version"], c.events(s)) == (version, log), "no write, no event, no undo entry"
    code, changed = _register(dict(rec, verdict="untimed", untimed_tier="same"))
    assert code == 0 and (changed["landed"], changed["pairing"]) == ("already", "replaced")
    assert _pairings() == 1, "one pairing per video"


def test_the_record_travels_on_stdin_never_in_the_log():
    c.library()
    path = c.drop("Example Show - 06.ja.srt")
    rec = c.record(path, "video-06")
    code, lines = c.register_stdin(b"\xef\xbb\xbf" + json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    assert code == 0 and h.answer(lines)["pairing"] == "new", lines
    with open(os.path.join(h.root(), "local", "logs", "cli.log"), encoding="utf-8") as f:
        log = f.read()
    assert "register" in log and rec["video_path"] not in log and rec["content_key"] not in log


def test_a_file_already_synced_by_the_window_is_already_and_only_paired():
    c.library()
    with c.store() as s:
        item = s.ids("now")[1]
        path = os.path.join(c.dirs()[0], s.item(item)["rel_path"])
    code, line = _register(c.record(path, "video-07"))
    assert code == 0 and (line["file_id"], line["landed"], line["pairing"], line["position"]) == (item, "already",
                                                                                                    "new", 2)


def test_with_new_arrivals_on_a_drop_waits_there():
    """The 3.0 copy (the store's `arrivals_on`): a hato drop lands at the end of New arrivals, outside Current."""
    c.library(arrivals=True)
    first = _register(c.record(c.drop("Example Show - 05.ja.srt"), "video-05"))[1]
    second = _register(c.record(c.drop("Example Show - 06.ja.srt"), "video-06"))[1]
    assert (first["landed"], first["tier"], first["position"]) == ("arrivals", "arrivals", 1)
    assert (second["landed"], second["position"]) == ("arrivals", 2) and "rule" not in second
    with c.store() as s:
        assert first["file_id"] not in s.ids("now") + s.ids("soon")


def test_a_backfill_registration_pairs_but_logs_no_event():
    c.library()
    path = c.drop("Example Show - 04.ja.srt")
    with c.store() as s:
        s.register_reader("connect")
    code, line = _register(c.record(path, "video-04"), "--backfill")
    assert code == 0 and line["pairing"] == "new"
    with c.store() as s:
        rows, gap = s.read_events("connect")
        assert not gap and [r for r in rows if r[1] == line["file_id"]] == []


@pytest.mark.parametrize("bad, code, error", [
    ("outside", 1, "bad-data"), ("missing", 1, "bad-data"), ("changed", 1, "bad-data"), ("no-field", 1, "bad-data"),
    ("key", 1, "bad-data"), ("schema-2", 2, "version-skew"), ("lang", 2, "usage"), ("not-json", 1, "bad-data"),
    ("too-big", 1, "bad-data"), ("null-path", 1, "bad-data"),
])
def test_a_record_it_cant_take_writes_nothing(bad, code, error, tmp_path):
    c.library()
    path = c.drop("Example Show - 05.ja.srt")
    rec = c.record(path, "video-05")
    args = []
    if bad == "outside":
        outside = tmp_path / "Example Show - 05.ja.srt"
        outside.write_bytes(open(path, "rb").read())
        rec = c.record(str(outside), "video-05")
    elif bad == "missing":
        rec["library_path"] = path + ".gone"
    elif bad == "changed":
        with open(path, "ab") as f:
            f.write("\n終わり\n".encode("utf-8"))          # the copy isn't the file hato paired
    elif bad == "no-field":
        del rec["verdict"]
    elif bad == "key":
        rec["content_key"] = "v1-ABC"
    elif bad == "schema-2":
        rec["schema"] = 2
    elif bad == "lang":
        args = ["--lang", "zh"]
    elif bad == "null-path":
        rec["library_path"] = None
    before, stored = c.snapshot(), c.store_state()
    if bad == "not-json":
        got, lines = c.register_stdin("{not json".encode("utf-8"))
        line = h.answer(lines)
    elif bad == "too-big":
        got, lines = c.register_stdin(json.dumps(dict(rec, padding="x" * 70000)).encode("utf-8"))
        line = h.answer(lines)
    else:
        got, line = _register(rec, *args)
    assert (got, line["code"]) == (code, error), line
    after = c.snapshot()
    after.pop("record.json", None), before.pop("record.json", None)
    assert after == before and c.store_state() == stored


def test_an_update_staged_answers_update_staged():
    c.library()
    path = c.drop("Example Show - 05.ja.srt")
    marker = library_store.update_staged_path()
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as f:
        f.write("{}")
    code, line = _register(c.record(path, "video-05"))
    assert (code, line["code"]) == (3, "update-staged")
    os.remove(marker)
    assert _pairings() == 0


def test_no_store_and_no_manifest_needs_you():
    h.seed_library("ja", templates=False)
    h.write_settings(connect_enabled=True)
    path = c.drop("Example Show - 05.ja.srt")
    code, line = _register(c.record(path, "video-05"))
    assert (code, line["code"], line["ask"]) == (4, "needs-you", "Open Surasura once")


def test_a_held_store_answers_busy_after_wait(monkeypatch):
    """The store's write lock held past --wait: `busy` (exit 3) and nothing written — hato retries next run."""
    c.library()
    path = c.drop("Example Show - 05.ja.srt")

    def held(*_a, **_k):
        raise library_store.StoreBusy("held")
    monkeypatch.setattr(library_store, "register_headless", held)
    code, line = _register(c.record(path, "video-05"), "--wait", "0.3")
    assert (code, line["code"], line["lock"]) == (3, "busy", "library")


def test_nan_or_infinity_in_a_record_is_bad_data():
    c.library()
    rec = c.record(c.drop("Example Show - 05.ja.srt"), "video-05")
    text = json.dumps(dict(rec, timing={"outcome": "CONFIDENT", "match_rate": float("nan")}))
    code, lines = c.register_stdin(text.encode("utf-8"))
    assert (code, h.answer(lines)["code"]) == (1, "bad-data")


def test_a_register_that_builds_the_store_still_queues_the_drop():
    """Review P2.1 #2: no store yet, a usable manifest: register builds the store and sets Connect's watermark before
    registering (`register_headless(reader=…)`), so the drop is logged — and nothing that was already there."""
    from app import library_store as ls
    from app.connect.ledger import Ledger
    h.seed_library("ja", templates=False)
    h.write_settings(connect_enabled=True)
    data_dir, user_files = c.dirs()
    assert ls.maintain("ja", data_dir, user_files, from_folders=True) == ls.EXIT_DONE
    os.remove(ls.library_db_path("ja", data_dir))            # the manifest stays: the store is rebuilt from it
    for side in ("-wal", "-shm"):
        if os.path.exists(ls.library_db_path("ja", data_dir) + side):
            os.remove(ls.library_db_path("ja", data_dir) + side)
    code, line = _register(c.record(c.drop("Example Show - 05.ja.srt"), "video-05"))
    assert code == 0 and line["landed"] == "now-top", line
    from app.connect import inbox
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [line["file_id"]], "logged after Connect's watermark"
        assert [(j["item_id"], j["source"]) for j in ledger.jobs("ja")] == [(line["file_id"], "hato")]


@pytest.mark.parametrize("producer", ["AnkiMiner", "my tool", "", "x" * 33])
def test_a_producer_that_isnt_a_short_program_name_is_bad_data(producer):
    """Intent review #4: the placement log records the producer as who registered: never rewritten to "hato"."""
    c.library()
    code, line = _register(c.record(c.drop("Example Show - 05.ja.srt"), "video-05", producer=producer))
    assert (code, line["code"]) == (1, "bad-data") and "producer" in line["fields"]
