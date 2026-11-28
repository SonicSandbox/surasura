"""UPDATE-START (3.0.21): the first start after an update answers its numbers from the plan's first line.

Every update makes the last plan out of date: its header names the engine that wrote it (`analyzer.engine_id`: the
app's version, the token store's schema, `ENGINE_REVISION`), so the window's numbers can't follow it until the next
Generate — they keep the last figures, faded. That verdict is in the plan's first line, yet the numbers' first load read
the whole plan and worked out every input of the staleness check (`moves.plan_inputs`: every file of the library
stat'd, the run signature) before the check's first lines compared the engine. The window's first list waits for that
answer (OPEN-RACE), so a learner's first start after every update waited on it: at 20,000 files ~1.3 s of the start's
numbers on a desktop, many times that on a laptop on battery. Now a plan another engine or plan format wrote is answered
from its header and the counts table beside it (`plan_engine.read_counts`, the journey's): the same verdict, the same
faded figures (% known from the plan's counts, *N new* the last shown), without the rest.

On RP-2's libraries (tests/plan_file_cases.py: real Japanese and Chinese text across NOW, Soon and 6+ Months), one
real Generate as the window runs it; the update is the engine moved on in this process (`ENGINE_REVISION` + 1).
"""
import json
import os

import pytest

from app import analyzer, plan_engine, plan_rules
from app.services import moves as M
from tests import plan_file_cases as cases


@pytest.fixture(params=["ja", "zh"])
def generated(tmp_path, monkeypatch, request):
    """A generated library, this test's data root -> its language."""
    language = request.param
    root = str(tmp_path / "lib")
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    cases.build(root, f"rp2-{language}")
    settings = {"target_language": language, "anki_connect_url": "http://127.0.0.1:9"}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    from app import run_args
    from app.path_utils import ensure_data_setup
    ensure_data_setup(language)
    cases.generate(root, f"rp2-{language}", argv=run_args.analyzer_args(settings, language, headless=True)[1:])
    return language


def _numbers(language):
    """The window's numbers, as `open_library` makes them: the window's own staleness check."""
    from app import settings_manager
    numbers = M.Numbers(M.store_opener(language), language,
                        check=M.plan_check(language, settings_manager.load_settings()))
    return numbers


def _figures(table):
    return {item: (known, counted) for item, (known, counted, _n) in table.items()}


def _reads(monkeypatch):
    """Counts the whole plan's reads and the staleness check's inputs worked out."""
    seen = {"load": 0, "inputs": 0}
    real_load, real_inputs = plan_engine.load, M.plan_inputs

    def load(*a, **k):
        seen["load"] += 1
        return real_load(*a, **k)

    def inputs(*a, **k):
        seen["inputs"] += 1
        return real_inputs(*a, **k)
    monkeypatch.setattr(plan_engine, "load", load)
    monkeypatch.setattr(M, "plan_inputs", inputs)
    return seen


def test_an_ordinary_start_still_follows_the_order(generated, monkeypatch):
    # the plan this engine wrote: the whole read and the check, as before (nothing answered from the header)
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers._load()
    assert numbers.why() is None, numbers.why()
    assert seen == {"load": 1, "inputs": 1}


def test_an_ordinary_start_decompresses_the_plan_once(generated, monkeypatch):
    # the header asked first reads the first line alone: the whole plan is decompressed once, by the whole read
    # (read through for its CRC as well, the start's numbers paid the plan's decompression twice: ~40 ms at 20,000
    # files on a desktop, several times that on a laptop)
    asked = []
    real = plan_engine.read_header

    def header(path, formats=None, whole=True):
        asked.append(whole)
        return real(path, formats=formats, whole=whole)
    monkeypatch.setattr(plan_engine, "read_header", header)
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers._load()
    assert numbers.why() is None and seen["load"] == 1 and asked == [False]


def test_the_first_line_alone_answers_a_plan_whose_end_is_cut_off(generated, tmp_path):
    # what the numbers ask (`whole=False`) reads no further than the first line; the analyzer's whole read still
    # refuses the damaged file
    path = _numbers(generated)._plan_path()
    data = open(path, "rb").read()
    cut = str(tmp_path / "cut.json.gz")
    open(cut, "wb").write(data[:len(data) // 2])
    whole = plan_engine.read_header(path)
    assert plan_engine.read_header(cut, whole=False) == whole and whole["language"] == generated
    assert plan_engine.read_header(cut) is None


def test_after_an_update_the_numbers_answer_from_the_plans_first_line(generated, monkeypatch):
    before = _numbers(generated)
    before._load()
    assert before.why() is None
    shown = dict(before._table)                            # the last figures the window showed (its cache's)
    monkeypatch.setattr(analyzer, "ENGINE_REVISION", analyzer.ENGINE_REVISION + 1)   # the update
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers.seed(shown)                                    # the start's cached figures (`LibraryReader._seed_figures`)
    numbers._load()
    assert numbers.why() == "stale: engine", "the same verdict (the window's log line, the rows' fade)"
    assert seen == {"load": 0, "inputs": 0}, "never the whole plan read nor every file stat'd for the header's verdict"
    table = numbers._table
    assert isinstance(table, M.Kept), "kept, faded: never shown as current"
    assert _figures(table) == _figures(shown), "% known from the plan's own counts, every row's"
    assert {i: n for i, (_k, _c, n) in table.items()} == {i: n for i, (_k, _c, n) in shown.items()}, \
        "each row's *N new* the last shown"
    assert numbers.wait_first(0) is True, "the first answer is in: the first list is built"


def test_after_an_update_with_no_start_figures_the_rows_keep_their_percent_known(generated, monkeypatch):
    # no first screen's cache (its first start in a new place, a cache another library wrote): % known still from the
    # plan's counts, *N new* none — as the whole read gave them
    before = _numbers(generated)
    before._load()
    shown = dict(before._table)
    monkeypatch.setattr(analyzer, "ENGINE_REVISION", analyzer.ENGINE_REVISION + 1)
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers._load()
    assert numbers.why() == "stale: engine" and seen["load"] == 0
    assert _figures(numbers._table) == _figures(shown)
    assert all(n is None for _k, _c, n in numbers._table.values())


def test_a_plan_with_no_counts_table_beside_it_is_read_whole_as_before(generated, monkeypatch):
    # a plan from before the counts table (ENGINE 48), or one whose table is another run's: the whole read, the same
    # verdict and figures — never an answer without the files' counts
    before = _numbers(generated)
    before._load()
    shown = dict(before._table)
    os.remove(os.path.join(os.path.dirname(before._plan_path()), plan_engine.COUNTS_FILE))
    monkeypatch.setattr(analyzer, "ENGINE_REVISION", analyzer.ENGINE_REVISION + 1)
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers._load()
    assert numbers.why() == "stale: engine" and seen["load"] == 1
    assert _figures(numbers._table) == _figures(shown)


@pytest.mark.skipif(plan_rules.SENTENCE_TABLE < 2, reason="the plan format's own verdict is release 2's")
def test_after_an_update_of_the_plans_format_the_same(generated, monkeypatch):
    # 11-26's update (*stale: format*): the plan's format moved on, the engine's id not compared yet
    before = _numbers(generated)
    before._load()
    shown = dict(before._table)
    monkeypatch.setattr(plan_engine, "FORMAT", plan_engine.FORMAT + 1)
    monkeypatch.setattr(plan_engine, "FORMATS", plan_engine.FORMATS + (plan_engine.FORMAT,))
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers._load()
    assert numbers.why() == "stale: format" and seen == {"load": 0, "inputs": 0}
    assert _figures(numbers._table) == _figures(shown)


def test_files_that_came_in_since_still_say_so_after_an_update(generated, monkeypatch):
    # `_stale`'s own reasons before the check keep their order: a library that gained an item since the plan says so
    # (the Generate the window asks for is the same), from the header path too
    before = _numbers(generated)
    before._load()
    item = next(iter(before._table))
    monkeypatch.setattr(analyzer, "ENGINE_REVISION", analyzer.ENGINE_REVISION + 1)
    real_order = M.Numbers._order
    monkeypatch.setattr(M.Numbers, "_order", lambda self, store: real_order(self, store) + [(10 ** 9, "now")])
    seen = _reads(monkeypatch)
    numbers = _numbers(generated)
    numbers._load()
    assert numbers.why() == "stale: files came in since the last Generate" and seen["load"] == 0
    assert item in numbers._table
