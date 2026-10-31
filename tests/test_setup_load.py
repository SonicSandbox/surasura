"""Setup's load screen, its Qt-free half (Mado-O, Sonic 2026-10-30): the counts it shows come from the services that do
the work — the indexer prints `Indexer: n of m` as `Store.reconcile` tokenizes (a progress callback, no output
change), the load screen reads the newest such line back from the indexer's log (`setup_load.read_count`), and the
covers' disk scan counts its titles (`covers.scan(progress=)`). And `setup_wizard.sorted_offer`: D1's cards line
after the sort screen, only for what the sorting put in the mine line.

What a wrong answer would cost a learner:
  * a load screen stuck on "Reading the words…" with no count, or a count that jumps back (an old line read last);
  * an indexer that floods its log (a line per file over 20,000 files) or never says its last count;
  * a progress callback that changes what the store holds (a different list after setup);
  * a cards line offered for episodes he never sorted into Current.

Real Japanese / Chinese text, temp folders and temp stores only.
"""
import os

import pytest

from app import indexer
from app import token_index as ti
from app.services import covers as disk
from app.services import setup_load, setup_wizard
from tests.test_token_index import JA_ADVENTURE, JA_OTHER, ZH_ADVENTURE, _counting_tokenizer, _db, _write


# --- the count read back from the log ------------------------------------------------------------------------------ #
def _log(tmp_path, text, name="indexer-window.log"):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def test_the_count_is_the_newest_line_in_the_log(tmp_path):
    path = _log(tmp_path, "Indexer: starting (ja)\nIndexer: 3 of 40\n読み込み中…\nIndexer: 12 of 40\nIndexer: done\n")
    assert setup_load.read_count(path) == (12, 40)


@pytest.mark.parametrize("text", ["", "Indexer: starting (ja)\n", "Indexer: of 40\n", "Indexer: 3 of\n"],
                         ids=["empty", "no-count-yet", "no-done", "no-total"])
def test_no_count_yet_reads_as_none(tmp_path, text):
    assert setup_load.read_count(_log(tmp_path, text)) is None


def test_a_log_last_written_before_the_ask_is_an_earlier_runs(tmp_path):
    """`since`: the run asked for hasn't written its log yet — the earlier run's last count (often its whole total) is
    never shown as this one's."""
    path = _log(tmp_path, "Indexer: 5000 of 5000\n")
    written = os.path.getmtime(path)
    assert setup_load.read_count(path, since=written + 5) is None
    assert setup_load.read_count(path, since=written - 5) == (5000, 5000)


def test_no_log_reads_as_none(tmp_path):
    assert setup_load.read_count(None) is None and setup_load.read_count("") is None
    assert setup_load.read_count(str(tmp_path / "never-written.log")) is None


def test_a_long_log_is_read_from_its_end_only(tmp_path):
    """A log of a long run (20,000 files' lines before it): the newest count is in its last bytes, read alone — an old
    count further up is never what the screen shows."""
    head = "Indexer: 1 of 99999\n" + "東京の夜は長い。\n" * 3000
    path = _log(tmp_path, head + "Indexer: 15000 of 20000\n")
    assert os.path.getsize(path) > 10 * setup_load.TAIL
    assert setup_load.read_count(path) == (15000, 20000)


def test_a_log_cut_mid_character_still_reads(tmp_path):
    """The tail can start inside a multi-byte character (Japanese lines before it): read, never an error."""
    path = tmp_path / "cut.log"
    body = ("あ" * (setup_load.TAIL // 3 + 1)).encode("utf-8")
    path.write_bytes(body[1:] + b"\nIndexer: 7 of 9\n")
    assert setup_load.read_count(str(path)) == (7, 9)


# --- the indexer's lines ------------------------------------------------------------------------------------------- #
def test_the_indexer_prints_a_count_at_most_twice_a_second_and_always_its_last(capsys):
    now = [100.0]
    told = indexer._progress_printer(clock=lambda: now[0])
    for done in range(1, 11):                       # ten files, ⅛ s apart: a line at the start, at ½ s, at 1 s …
        told(done, 10)
        now[0] += 0.125
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["Indexer: 1 of 10", "Indexer: 5 of 10", "Indexer: 9 of 10", "Indexer: 10 of 10"]
    assert all(setup_load._COUNT.fullmatch(line) for line in lines)      # each one the load screen reads


def test_the_last_count_is_printed_even_right_after_another(capsys):
    told = indexer._progress_printer(clock=lambda: 5.0)
    told(1, 2)
    told(2, 2)
    assert capsys.readouterr().out.splitlines() == ["Indexer: 1 of 2", "Indexer: 2 of 2"]


@pytest.mark.parametrize("language, texts", [("ja", (JA_ADVENTURE, JA_OTHER)), ("zh", (ZH_ADVENTURE,))])
def test_reconcile_counts_each_file_it_tokenizes_and_holds_the_same_as_without(tmp_path, language, texts):
    """`reconcile(progress=)`: (done, total) after each file tokenized, of those that needed it — and the store holds
    exactly what a run without it holds. A second run with nothing changed tokenizes nothing and counts nothing."""
    files = []
    for k, text in enumerate(texts):
        f = tmp_path / f"{language}-{k}.txt"
        _write(f, text)
        files.append(str(f))
    heard = []
    with_ = ti.open_store(language, path=_db(tmp_path, "with.db"))
    with_.reconcile(files, _counting_tokenizer(language), progress=lambda d, t: heard.append((d, t)))
    without = ti.open_store(language, path=_db(tmp_path, "without.db"))
    without.reconcile(files, _counting_tokenizer(language))
    try:
        n = len(files)
        assert heard == [(k, n) for k in range(1, n + 1)]
        assert with_.total_tokens() == without.total_tokens() > 0
        agg = "SELECT lemma, count FROM aggregate ORDER BY lemma"
        assert with_.conn.execute(agg).fetchall() == without.conn.execute(agg).fetchall()
        heard.clear()
        with_.reconcile(files, _counting_tokenizer(language), progress=lambda d, t: heard.append((d, t)))
        assert heard == []
    finally:
        with_.close()
        without.close()


# --- the covers' count --------------------------------------------------------------------------------------------- #
class _Writer:
    def can_write(self):
        return True


def test_the_covers_scan_counts_each_title_and_ends_on_the_whole(monkeypatch, tmp_path):
    looked = []
    monkeypatch.setattr(disk, "_my_turn", lambda _writer, _cancel: True)
    monkeypatch.setattr(disk, "_scan_one", lambda _lang, _data, work, _writer: looked.append(work) or work == "b")
    heard = []
    found = disk.scan("ja", iter(["a", "b", "c"]), _Writer(), data_dir=str(tmp_path),
                      progress=lambda d, t: heard.append((d, t)))
    assert found == 1 and looked == ["a", "b", "c"]
    assert heard == [(1, 3), (2, 3), (3, 3)]


def test_the_covers_scan_with_no_titles_counts_nothing(tmp_path):
    heard = []
    assert disk.scan("ja", [], _Writer(), data_dir=str(tmp_path), progress=lambda d, t: heard.append((d, t))) == 0
    assert heard == []


def test_a_cancelled_covers_scan_still_ends_its_count(monkeypatch, tmp_path):
    """Setup's *Stop*, or another library opening: the scan stops between titles — its count still ends, so the load
    screen goes on."""
    monkeypatch.setattr(disk, "_my_turn", lambda _writer, _cancel: True)
    monkeypatch.setattr(disk, "_scan_one", lambda *_a: False)
    stop = iter([False, True])
    heard = []
    disk.scan("ja", ["a", "b", "c"], _Writer(), cancel=lambda: next(stop, True), data_dir=str(tmp_path),
              progress=lambda d, t: heard.append((d, t)))
    assert heard[-1] == (3, 3)


# --- D1 after sorting ---------------------------------------------------------------------------------------------- #
def test_nothing_sorted_offers_no_line(monkeypatch):
    """No ids (Stop before anything came in) or no library: no line, nothing opened."""
    opened = []
    monkeypatch.setattr(setup_wizard, "_window_store", lambda *a, **kw: opened.append(a))
    assert setup_wizard.sorted_offer("ja", []) is False
    monkeypatch.setattr(setup_wizard, "_window_store", lambda *a, **kw: None)
    assert setup_wizard.sorted_offer("ja", [1, 2]) is False
