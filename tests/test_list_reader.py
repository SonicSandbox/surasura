"""a7: every reader of Generate's lists reads a list whose `Sources` passes Python's csv field limit.

An alpha's setup (2026-10-30): with few known words, as every new user starts, and a few thousand files, a common
word's `Sources` (every file it is in, `analyzer.group_sources`) passed 131,072 characters, and Python's csv refuses a
field over that: New arrivals' pick ranked by nothing, the shadow check failed and Connect's list couldn't be read. The
suite hid it — one test raised the limit for the whole process at import. Now one reader, `path_utils.list_reader`,
raises it for the process, and every list reader reads through it.

What a wrong answer would cost: a new user's arrivals ranked by no list, Connect's verbs refusing with "Surasura's list
can't be read", a Junban / Backfill run that matches no card — each only on a big library with few known words.
"""
import csv
import os
import re

import pandas as pd
import pytest

from app import analyzer, path_utils

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(ROOT, "tests", "Test Resources", "ja", "expected_output.csv")
PYTHON_DEFAULT = 131072


@pytest.fixture(autouse=True)
def default_field_limit():
    """Each case starts at Python's own limit, as a fresh process does: the reader under test must raise it itself."""
    before = csv.field_size_limit(PYTHON_DEFAULT)
    yield
    csv.field_size_limit(before)


def _write_big_list(folder):
    """The real list (Japanese rows, sentences with commas and quotes), its first word in 3,200 books' chapters."""
    with open(REAL, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    files = [f"[{n:04d}] 本好きの下剋上 ～司書になるためには手段を選んでいられません～ 第{n}章.txt" for n in range(3200)]
    rows[0]["Sources"] = analyzer.group_sources(files)
    assert len(rows[0]["Sources"]) > PYTHON_DEFAULT
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "priority_learning_list.csv")
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(os.path.join(folder, "progressive_learning_list.csv"), index=False, encoding="utf-8-sig")
    return path, rows


def test_python_still_refuses_the_field_unraised(tmp_path):
    # The witness: without the shared reader the list can't be read, so every case below proves its reader.
    path, _rows = _write_big_list(str(tmp_path))
    with open(path, encoding="utf-8-sig", newline="") as f, pytest.raises(csv.Error, match="field limit"):
        list(csv.DictReader(f))


def test_the_shared_reader_reads_the_whole_list_with_and_without_its_header(tmp_path):
    path, rows = _write_big_list(str(tmp_path))
    with open(path, encoding="utf-8-sig", newline="") as f:
        got = list(path_utils.list_reader(f))
    assert len(got) == len(rows) and got[0]["Word"] == "うう" and got[0]["Sources"] == rows[0]["Sources"]
    with open(path, encoding="utf-8-sig", newline="") as f:
        assert sum(1 for _ in path_utils.list_reader(f, header=False)) == len(rows) + 1


def test_new_arrivals_ranks_by_the_big_list(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import arrivals_worker
    _path, rows = _write_big_list(str(tmp_path))
    monkeypatch.setattr(analyzer, "RESULTS_DIR", str(tmp_path))
    got = arrivals_worker.Worker._listed(SimpleNamespace(), None)
    assert got[("うう", "ウウ")] == 0 and len(got) == len({(r["Word"], r["Reading"]) for r in rows})


@pytest.mark.parametrize("module", ["app.services.journey", "app.replan_preview"])
def test_the_shadow_check_reads_both_big_lists(monkeypatch, tmp_path, module):
    import importlib
    _write_big_list(str(tmp_path / "results"))
    monkeypatch.setattr(path_utils, "get_user_file", lambda rel: str(tmp_path / rel))
    lists = importlib.import_module(module)._lists()
    assert lists["priority"] and lists["progressive"] and lists["priority"][0]["Word"] == "うう"


def test_connects_verbs_read_and_count_the_big_list(tmp_path):
    from app.cli import verbs
    path, rows = _write_big_list(str(tmp_path))
    assert len(verbs._read_rows(path)) == len(rows)
    assert verbs._count_rows(path) == len(rows)


def test_junbans_index_and_the_exports_read_the_big_list(tmp_path):
    from app import anki_match, exports
    path, rows = _write_big_list(str(tmp_path))
    assert "うう" in anki_match.build_index(path, language="ja").rank_of
    assert exports.csv_has_data_rows(path) is True
    assert exports._count("csv", path) == len(rows)


def test_backfill_and_the_youtube_preview_read_the_big_list(monkeypatch, tmp_path):
    backfill = pytest.importorskip("modules.junban.backfill")
    preview = pytest.importorskip("modules.youtube_downloader.preview")
    path, _rows = _write_big_list(str(tmp_path))
    rank_of, words, _orths = backfill.list_index(path)
    assert rank_of and words[0] == ("うう", "ウウ")
    monkeypatch.setattr(preview, "library_contexts_path", lambda: path)
    by_lr, _by_lemma = preview.load_library_contexts()
    assert ("うう", "ウウ") in by_lr


def test_no_list_reader_goes_around_the_shared_one():
    """A new csv reader in the app or a shipped module would meet the limit again: the shared one is the only
    `csv.reader` / `csv.DictReader` (a list or a frequency list the user supplies, read the same way)."""
    found = []
    for top in ("app", os.path.join("modules", "junban"), os.path.join("modules", "youtube_downloader"),
                os.path.join("modules", "koe")):
        for folder, _dirs, names in os.walk(os.path.join(ROOT, top)):
            for name in names:
                if not name.endswith(".py") or "tests" in os.path.relpath(folder, ROOT).split(os.sep):
                    continue
                path = os.path.join(folder, name)
                if os.path.samefile(path, path_utils.__file__):
                    continue
                with open(path, encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if re.search(r"\bcsv\.(Dict)?[rR]eader\(", line):
                            found.append(f"{os.path.relpath(path, ROOT)}:{n}")
    assert found == []
