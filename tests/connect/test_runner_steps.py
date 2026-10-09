"""The loop's real steps (P2.4 rows 2.4.2, 2.4.4; P1.5 06-edges E8, E15; P1.3-AM37 #5): `runner.Steps` as the command
line's own verbs, in this process — what reaches `pick` (every word Connect ever made, G1.3-4), where the video comes
from (hato's pairing, else a video beside the subtitle; never a cloud placeholder, RD-S1), how Anki Miner's refusals
read (its window open → waiting; its profile changed → picked again; a crash → the batch in doubt), and the `connect`
verb's loop under its one lock.

What a wrong answer would cost: a word whose card you deleted made again behind your back; a cloud video downloaded by
opening it to cut one clip; Connect failing a job (or mining with another profile) because you had Anki Miner open;
two Connects at once mining one episode twice.

Real subtitles and words; synthetic titles and videos; Anki is never reached (the suites' `SURASURA_NO_ANKI_SYNC`).
"""
import os
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.connect import anki_miner, library, runner
from app.connect.ledger import Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


MAPPING = SimpleNamespace(word="Word")


def _steps():
    return runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})


def test_pick_is_handed_every_word_connect_ever_made_so_a_deleted_card_is_never_made_again(monkeypatch):
    c.library()
    with c.store() as s:
        first, second = s.ids("now")[:2]
        library.record_batch(s, first, {"上層部": [1001], "一生懸命": [1002]}, "2026-10-08T15:00:00Z", "7")
    seen = {}

    def pick(ns):
        seen.update(made=set(ns.made), job=ns.job, file=ns.file)
        return {"words": [], "subtitle": None}
    monkeypatch.setattr(verbs, "pick", pick)
    _steps().pick("ja", {"id": 8, "item_id": second}, "episode.mkv")
    assert seen["made"] == {"上層部", "一生懸命"}, "made words count as carded, whatever became of their cards"
    assert seen["job"] == "8" and os.path.isfile(seen["file"])


def test_a_video_comes_from_the_pairing_else_from_beside_the_subtitle(tmp_path):
    folder = tmp_path / "Example Show"
    folder.mkdir()
    subtitle = folder / "Example Show - 05.ja.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\n一生懸命\n", encoding="utf-8")
    assert runner.beside(str(subtitle)) is None
    video = folder / "Example Show - 05.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    assert runner.beside(str(subtitle)) == str(video), "the language tag (.ja) is no part of the video's name"
    other = folder / "Example Show - 06.mkv"
    other.write_bytes(b"\x1aE\xdf\xa3")
    assert runner.beside(str(subtitle)) == str(video), "never another episode's video"


def test_a_cloud_placeholder_counts_as_no_video_and_is_never_opened(tmp_path, monkeypatch):
    video = tmp_path / "Example Show - 05.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    real_stat = os.stat

    class Placeholder:
        def __init__(self, st):
            self.st = st
            self.st_file_attributes = 0x400000           # RECALL_ON_DATA_ACCESS: reading it would download it

        def __getattr__(self, name):
            return getattr(self.st, name)
    monkeypatch.setattr(runner.os, "stat", lambda p, *a, **k: Placeholder(real_stat(p, *a, **k)))
    assert runner._on_disk(str(video)) is False
    assert runner.beside(str(tmp_path / "Example Show - 05.ja.srt")) is None


def test_under_the_suites_anki_is_switched_off_and_the_job_waits_for_the_next_start():
    wait = _steps().blocked("ja")
    assert isinstance(wait, runner.Wait) and (wait.reason, wait.look) == (runner.ANKI_OFF, False)


@pytest.mark.parametrize("kind, expect", [
    ("busy", (runner.Wait, runner.ANKI_MINER_OPEN)),
    ("writer-busy", (runner.Wait, runner.WRITER_BUSY)),
    ("reviewing", (runner.Wait, runner.REVIEWING)),
    ("anki-closed", (runner.Wait, runner.ANKI_CLOSED)),
    ("profile-changed", (runner.Repick, None)),
    ("setup", (runner.Needs, None)),
])
def test_anki_miners_refusals_read_as_waits_a_re_pick_or_needs_you(monkeypatch, tmp_path, kind, expect):
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir: ({}, "p1", MAPPING))

    def refuse(*a, **k):
        raise anki_miner.AnkiMinerError(kind, "Anki Miner said no")
    monkeypatch.setattr(anki_miner, "mine_batch", refuse)
    picked = {"video": "v.mkv", "subtitle": "s.srt", "profile": "p1"}
    words = [{"word": "気配", "reading": "ケハイ", "line_start": 3.0}]
    with pytest.raises(expect[0]) as got:
        _steps().mine("ja", {"id": 3, "item_id": 1}, picked, words, 1)
    if expect[1] is not None:
        assert got.value.reason == expect[1] and got.value.resume == "mining"


def test_a_crash_leaves_the_batch_in_doubt_never_failed(monkeypatch):
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir: ({}, "p1", MAPPING))

    def crash(*a, **k):
        raise anki_miner.AnkiMinerError("crashed", "Anki Miner stopped")
    monkeypatch.setattr(anki_miner, "mine_batch", crash)
    got = _steps().mine("ja", {"id": 3, "item_id": 1}, {"video": "v", "subtitle": "s", "profile": "p1"},
                        [{"word": "気配", "reading": "ケハイ", "line_start": 3.0}], 1)
    assert got["doubt"] is True and [o["outcome"] for o in got["outcomes"]] == ["uncertain"]


def test_no_anki_miner_skips_the_mine_step(monkeypatch):
    monkeypatch.setattr(anki_miner, "find", lambda loaded: None)
    with pytest.raises(runner.Skip):
        _steps().mine("ja", {"id": 3, "item_id": 1}, {}, [], 1)


@pytest.mark.parametrize("answer, reason", [
    ({"skipped": "the list is out of date: Generate first"}, "the list is out of date: Generate first"),
    ({"skipped": "an update is waiting: restart first"}, "an update is waiting: restart first"),
])
def test_a_junban_skipped_answer_is_named_as_a_skip_and_is_never_a_reorder(monkeypatch, answer, reason):
    # a skipped answer means the re-sort is owed: the job must stop, naming why, not look as if it reordered
    monkeypatch.setattr(verbs, "junban", lambda ns: dict(answer))
    with pytest.raises(runner.Skip) as got:
        _steps().order("ja", {"id": 8, "item_id": 1})
    assert str(got.value) == reason
    monkeypatch.setattr(verbs, "junban", lambda ns: {})
    assert _steps().order("ja", {"id": 8, "item_id": 1}) is None, "a clean answer raises nothing"


def test_the_connect_verb_runs_the_loop_and_a_second_one_steps_aside():
    import threading
    from app import locks
    from app.connect import kick
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
        library.ensure_reader(s)
        item = s.ids("now")[-1]
        library.place(s, item, "now", source="user")
    code, line = h.call("connect")
    assert code == 0 and line["languages"]["ja"]["waiting"] == {str(item): runner.ANKI_OFF}
    with Ledger() as ledger, c.store() as s:
        (job,) = ledger.jobs("ja")
        assert (job["state"], job["store_id"]) == ("waiting", library.store_id(s)), "kept with the store it came from"
    taken, done = threading.Event(), threading.Event()

    def other():
        with locks.take(kick.LOCK, "Connect (this test)"):
            taken.set()
            done.wait(60)
    holder = threading.Thread(target=other)
    holder.start()
    try:
        assert taken.wait(10)
        code, line = h.call("connect")
        assert code == 0 and line["skipped"] == "already running"
    finally:
        done.set()
        holder.join()


def test_a_newer_ledger_is_needs_you_through_the_verb():
    import sqlite3
    from app.connect import ledger as book
    c.library()
    os.makedirs(book.folder(), exist_ok=True)
    old = sqlite3.connect(book.path())
    old.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    old.execute("INSERT INTO meta VALUES ('schema', '99')")
    old.commit()
    old.close()
    code, line = h.call("connect")
    assert (code, line["code"]) == (4, "needs-you") and "newer" in line["message"]


def test_a_newer_ledger_is_needs_you_through_consume_only_too():
    # the consume-only path reads the ledger before its own loop, so a newer one must be refused there as well
    import sqlite3
    from app.connect import ledger as book
    c.library()
    os.makedirs(book.folder(), exist_ok=True)
    old = sqlite3.connect(book.path())
    old.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    old.execute("INSERT INTO meta VALUES ('schema', '99')")
    old.commit()
    old.close()
    code, line = h.call("connect", "--consume-only")
    assert (code, line["code"]) == (4, "needs-you") and "newer" in line["message"]


def test_a_store_that_cant_be_written_is_needs_you_and_the_job_never_goes_on_unrecorded(monkeypatch):
    # The mining's receipt and made words are the record G1.3-4 reads: when the store refuses the write the job must
    # stop as Needs you, never return as if its cards were recorded.
    from app import library_store
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]

    tried = []

    def read_only(*a, **k):
        tried.append(True)
        raise library_store.StoreReadOnly("the library store is damaged and needs Repair")
    monkeypatch.setattr(library, "record_batch", read_only)
    with pytest.raises(runner.Needs) as caught:
        _steps().record("ja", {"item_id": item}, {"上層部": [1001]}, "2026-10-08T15:00:00Z", "7")
    # the store opened and the write was attempted: the Needs is the refused write's, not a store that never opened
    assert tried == [True]
    assert caught.value.kind == "no-store" and "can't be written" in caught.value.say
