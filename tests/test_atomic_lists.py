"""a7: a list is written whole or not at all, and its readers read only a finished run's list.

Alpha 6's logs: New arrivals' worker and the journey's shadow compare each read `priority_learning_list.csv` while a
Generate was writing it ("field larger than field limit": an unclosed quote at the cut end made one giant field). Now
the analyzer writes each list to a temp beside it and replaces it (`analyzer.write_list`), so a reader sees the last
list or the new one, never half; New arrivals' worker leaves the list unread while a Generate is writing one (no stamp
for its plan's run, `results` held) and asks again later; the shadow compare reads the lists only while `results/`'s
run stamp names the run that landed (a Generate drops its stamp before it writes anything), checked before and after.

What a wrong answer would cost: an arrival's pick ranking its words by no list at all (the log line Sonic's zip held),
a shadow compare that logs a false difference, or — with the replace refused because a reader holds the old list open —
a Generate that fails at its very end.
"""
import csv
import io
import os
import threading
import time

import pandas as pd

from app import analyzer, plan_engine
from app.services import journey as J

REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja", "expected_output.csv")


def _rows():
    with open(REAL, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_a_list_read_while_it_is_being_written_is_the_last_one_whole(tmp_path):
    """Read in the middle of the write (half the new list on disk): the reader gets the old list, every row; after
    it, the new list, every row — real Japanese rows, example sentences with commas and quotes."""
    rows = _rows()
    path = str(tmp_path / "priority_learning_list.csv")
    old = pd.DataFrame(rows[:120])
    old.to_csv(path, index=False, encoding="utf-8-sig")
    new = pd.DataFrame(rows)
    seen = {}

    def write(tmp):
        text = new.to_csv(index=False)
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text[:len(text) // 2])
            f.flush()
            seen["mid"] = _read(path)           # a reader, mid-way
            f.write(text[len(text) // 2:])
    analyzer.write_list(write, path)
    assert len(seen["mid"]) == 120 and seen["mid"][0]["Word"] == rows[0]["Word"]
    assert _read(path) == _read_frame(new)
    assert os.listdir(tmp_path) == ["priority_learning_list.csv"], "no temp left beside it"


def _read_frame(df):
    return list(csv.DictReader(io.StringIO(df.to_csv(index=False))))


def test_a_reader_reading_over_and_over_never_sees_half_a_list(tmp_path):
    """A reader thread reading over and over (a short pause between reads, as real readers come and go) while the list
    is written forty times, long and short in turn: every read parses at the default field limit and holds exactly
    one of the two lists."""
    rows = _rows()
    path = str(tmp_path / "progressive_learning_list.csv")
    short, full = pd.DataFrame(rows[:40]), pd.DataFrame(rows)
    short.to_csv(path, index=False, encoding="utf-8-sig")
    sizes, errors, stop = set(), [], threading.Event()

    def reader():
        while not stop.is_set():
            try:
                sizes.add(len(_read(path)))
            except PermissionError:
                pass                            # Windows: the replace's own instant; a reader tries again
            except Exception as e:              # a half list: csv.Error (field limit), a cut character, no rows
                errors.append(repr(e))
            time.sleep(0.01)
    t = threading.Thread(target=reader)
    t.start()
    try:
        for n in range(40):
            df = full if n % 2 == 0 else short
            analyzer.write_list(lambda tmp, df=df: df.to_csv(tmp, index=False, encoding="utf-8-sig"), path)
    finally:
        stop.set()
        t.join(10)
    assert errors == [] and sizes <= {40, len(rows)} and sizes, (errors[:3], sizes)


def test_a_reader_holding_the_old_list_open_is_waited_for(tmp_path):
    """Windows refuses to replace a file another handle holds open: the write waits for the reader, then replaces."""
    rows = _rows()
    path = str(tmp_path / "priority_learning_list.csv")
    pd.DataFrame(rows[:10]).to_csv(path, index=False, encoding="utf-8-sig")
    held = open(path, encoding="utf-8-sig")
    threading.Timer(0.5, held.close).start()
    started = time.monotonic()
    analyzer.write_list(lambda tmp: pd.DataFrame(rows).to_csv(tmp, index=False, encoding="utf-8-sig"), path)
    assert len(_read(path)) == len(rows) and time.monotonic() - started < 5, "replaced once the reader let go"
    assert os.listdir(tmp_path) == ["priority_learning_list.csv"]


def test_a_write_that_fails_leaves_the_last_list_and_no_temp(tmp_path):
    rows = _rows()
    path = str(tmp_path / "priority_learning_list.csv")
    pd.DataFrame(rows[:10]).to_csv(path, index=False, encoding="utf-8-sig")

    def broken(tmp):
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("Word,Reading\n冒険,")
        raise OSError("the disk is full")
    try:
        analyzer.write_list(broken, path)
    except OSError:
        pass
    assert len(_read(path)) == 10 and os.listdir(tmp_path) == ["priority_learning_list.csv"]


def test_a_temp_a_killed_run_left_goes_at_the_next_write_and_a_fresh_one_stays(tmp_path):
    """A Generate killed mid-write leaves `<list>.<pid>.tmp` behind: the next write removes it once it is a minute old;
    one written this minute (another process writing now) is left alone."""
    rows = _rows()
    path = str(tmp_path / "priority_learning_list.csv")
    stale, fresh = tmp_path / "priority_learning_list.csv.111.tmp", tmp_path / "priority_learning_list.csv.222.tmp"
    stale.write_text("Word,Reading\n冒険,", encoding="utf-8")
    fresh.write_text("Word,Reading\n冒険,", encoding="utf-8")
    old = time.time() - 120
    os.utime(stale, (old, old))
    analyzer.write_list(lambda tmp: pd.DataFrame(rows).to_csv(tmp, index=False, encoding="utf-8-sig"), path)
    assert sorted(os.listdir(tmp_path)) == ["priority_learning_list.csv", "priority_learning_list.csv.222.tmp"]


# --- the readers -------------------------------------------------------------------------------------------------- #
def test_new_arrivals_reads_the_last_whole_list_unless_a_generate_is_writing_one(monkeypatch, tmp_path):
    """The worker's list: its plan's run's (the stamp names it) — read; no stamp but nothing writing (a run was stopped
    or failed: the last good list is whole) — read; no stamp and a Generate holding `results` — not now (None), and
    the pick asks again later rather than keep an empty list."""
    from types import SimpleNamespace
    from app import arrivals_worker, locks
    monkeypatch.setattr(analyzer, "RESULTS_DIR", str(tmp_path))
    pd.DataFrame(_rows()).to_csv(tmp_path / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    whole = len({(r["Word"], r["Reading"]) for r in _rows()})
    worker = SimpleNamespace(_listed=lambda signature: arrivals_worker.Worker._listed(worker, signature))
    listed = arrivals_worker.Worker._listed
    analyzer._set_run_stamp(str(tmp_path), "run-7")
    got = listed(worker, "run-7")
    assert len(got) == whole and got[("うう", "ウウ")] == 0
    analyzer._set_run_stamp(str(tmp_path), None)
    assert len(listed(worker, "run-7")) == whole, "a stopped run left the last good list: read"
    warm = {"listed": None, "signature": "run-7"}
    with locks.take("results", "Generate"):
        assert listed(worker, "run-7") is None, "a Generate is writing: not now"
        assert arrivals_worker.Worker._list_of(worker, warm) == {} and warm["listed"] is None, "never kept"
    assert len(arrivals_worker.Worker._list_of(worker, warm)) == whole and len(warm["listed"]) == whole


class _Plan:
    def __init__(self, signature):
        self.header = {"run_signature": signature, "language": "ja", "order_free_signature": "f"}


def _engine(monkeypatch):
    """The re-plan's engine as a stand-in: the claim is about when the lists are read, not what they hold."""
    monkeypatch.setattr(plan_engine, "stands_aside", lambda plan: False)
    monkeypatch.setattr(plan_engine, "Engine", type("E", (), {"__init__": lambda self, *a, **k: None,
                                                              "replan": lambda self, files: "result"}))


def test_the_shadow_compare_reads_no_list_while_a_generate_writes_them(monkeypatch):
    """The stamp is gone (a Generate started after the one that landed): the lists are never read — no comparison, no
    log line — where alpha 6 read them first and logged "the comparison failed"."""
    reads = []
    monkeypatch.setattr(J, "_stamped", lambda signature: False)
    _engine(monkeypatch)
    previous, plan = _Plan("run-1"), _Plan("run-2")
    previous.files = plan.files = []
    assert J.shadow(previous, plan, lambda: reads.append(1) or {}, stamp=True) == ""
    assert reads == []


def test_the_shadow_compare_drops_lists_a_generate_began_replacing_as_they_were_read(monkeypatch):
    stamps = iter([True, False])
    monkeypatch.setattr(J, "_stamped", lambda signature: next(stamps))
    _engine(monkeypatch)
    previous, plan = _Plan("run-1"), _Plan("run-2")
    previous.files = plan.files = []

    def damaged():
        raise csv.Error("field larger than field limit (131072)")
    assert J.shadow(previous, plan, damaged, stamp=True) == "", "the stamp went: nothing said"
