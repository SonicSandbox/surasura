"""DSA-SMALL (3.0.19): the analyzer's small standard choices, each proven against the code before it.

- **E-WRITE — one writer of the two lists, without pandas.** The Generate and the redraw after a move imported pandas
  (~0.35 s a process) only to write `priority_learning_list.csv` and `progressive_learning_list.csv`. Now both call one
  function, `analyzer.write_rows` (the standard library's csv). Its bytes are pandas' `to_csv` bytes for the same rows:
  checked here against pandas itself on real Japanese and Chinese rows — commas, quotes, line breaks inside a
  sentence, mixed scripts, empty cells — and on the number columns pandas turns into floats (a gap, a float among
  whole numbers). The coverage cut keeps the column kinds of the whole list, as the frame it cut did. A real Generate
  and its redraw, ja + zh at level 2, load no pandas at all.

What a wrong answer would cost: a list whose bytes differ (every reader parses it, but the plan file's hash list and
the journey's text are pinned to them), or a "Score" written 170 where the old list wrote 170.0 — a reader comparing
the two lists would see every word move.
"""
import csv
import io
import json
import math
import os
import random
import subprocess
import sys

import pytest

from app import analyzer
from tests import plan_file_cases as cases

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
WHOLE = ("Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)")


def _ja_rows():
    """The real Japanese list (tests/Test Resources/ja/expected_output.csv) as the analyzer hands its rows over: its
    counts whole numbers, its text as written."""
    with open(os.path.join(RES, "ja", "expected_output.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for column in WHOLE:
            row[column] = int(row[column])
    return rows


def _zh_rows():
    """Chinese rows from the night-market subtitles (simplified and traditional lines, a line break inside a cue,
    full-width commas and an ASCII comma, quotes): each cue's first two characters a word, the cue its sentence."""
    with open(os.path.join(RES, "zh", "night_market.srt"), encoding="utf-8-sig", newline="") as f:
        cues = [block.split("\n", 2)[2] for block in f.read().replace("\r\n", "\n").split("\n\n") if block.count("\n") >= 2]
    rows = []
    for i, cue in enumerate(cues):
        text = cue.strip().replace("\n", "\r\n") if i % 3 == 0 else cue.strip()        # (CRLF inside a field too)
        rows.append({"Word": text[:2], "Orth": text[:2], "Forms": "", "Reading": "", "Kana": "", "Tier": "Outside",
                     "Score": 40 - i, "Occurrences": 9 + i, "Count (High)": i, "Count (Low)": 0, "Count (Goal)": 1,
                     "Modality": "", "Sources": 'night_market, "夜市"' if i % 2 else "night_market",
                     "Context 1": text, "Src 1": "HighPriority/night_market.srt"})
    return rows


def _pandas(rows, columns=None):
    """What the code before wrote: `pd.DataFrame(rows[, columns=]).to_csv(index=False, encoding='utf-8-sig')`."""
    pd = pytest.importorskip("pandas")
    buf = io.BytesIO()
    (pd.DataFrame(rows) if columns is None else pd.DataFrame(rows, columns=columns)).to_csv(
        buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def _pandas_cut(rows, upto):
    """The Generate's coverage cut before E-WRITE: the frame made, `_MinSeq` dropped, its first rows taken by
    `iterrows()` into a new frame (`upto` 0: `df.iloc[0:0]`)."""
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame(rows)
    if upto == 0:
        df = df.iloc[0:0]
    else:
        needed = []
        for _i, row in df.iterrows():
            needed.append(row)
            if len(needed) == upto:
                break
        df = pd.DataFrame(needed)
    buf = io.BytesIO()
    df.drop(columns=["_MinSeq"], errors="ignore").to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def _ours(tmp_path, rows, columns=None, upto=None):
    path = os.path.join(tmp_path, "list.csv")
    analyzer.write_rows(path, rows, columns, upto)
    with open(path, "rb") as f:
        return f.read()


def _with_gaps(rows):
    """The progressive list's shape: a word with no stats has no Context columns and no Score (pandas: a gap)."""
    out = []
    for i, row in enumerate(rows):
        row = dict(row)
        if i % 4 == 1:
            row = {k: v for k, v in row.items() if not k.startswith(("Context", "Src")) and k != "Score"}
        out.append(row)
    return out


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_one_writer_writes_the_bytes_pandas_wrote_for_real_rows(tmp_path, language):
    """The list as the analyzer hands it over (whole-number counts, real sentences): byte for byte pandas'."""
    rows = _ja_rows() if language == "ja" else _zh_rows()
    if language == "ja":                    # (a sentence quoting an English title, as subtitles do)
        rows[0]["Context 1"] = rows[0]["Context 1"] + ' "Spider, Thread"'
    got = _ours(tmp_path, rows)
    assert got == _pandas(rows)
    assert b'""' in got                     # (a quote inside a field, written doubled)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_gap_or_a_float_makes_a_number_column_pandas_float_column(tmp_path, language):
    """A gap (a key a row lacks, or None) or one float among whole numbers: pandas writes that column's whole numbers
    as 170.0 and the gap empty; a whole-number column with neither stays 170. Text columns with a gap stay text."""
    rows = _ja_rows() if language == "ja" else _zh_rows()
    gaps = _with_gaps(rows)
    assert _ours(tmp_path, gaps) == _pandas(gaps)
    floats = [dict(r, Score=r["Score"] + 0.5) if i == 3 else r for i, r in enumerate(rows)]
    got = _ours(tmp_path, floats)
    assert got == _pandas(floats)
    assert f',{rows[0]["Score"]}.0,'.encode() in got                # (the column read as pandas read it)
    nones = [dict(r, **{"Count (Low)": None, "Modality": None}) if i % 5 == 2 else r for i, r in enumerate(rows)]
    assert _ours(tmp_path, nones) == _pandas(nones)
    nans = [dict(r, Modality=float("nan"), Tier=float("nan")) if i == 1 else r for i, r in enumerate(rows)]
    assert _ours(tmp_path, nans) == _pandas(nans)


def test_bools_and_floats_of_every_size_are_written_as_pandas_wrote_them(tmp_path):
    """Floats pandas formats itself (its float column) against Python's: shortest digits, exponents both ways, NaN,
    infinities, -0.0; a bool column; bools among whole numbers (text to pandas)."""
    rng = random.Random(7)
    values = [0.1, 1e16, 1e15, 1.5e15, 1e-5, 1e-4, 123456789.123456789, -0.0, math.inf, -math.inf, float("nan"),
              5e-324, 1.7976931348623157e308, 2 / 3, 100.0]
    values += [rng.uniform(-1e6, 1e6) for _ in range(300)] + [math.ldexp(rng.random(), rng.randint(-60, 60))
                                                              for _ in range(300)]
    rows = [{"Word": f"語{i}", "Baseline %": v, "Current %": i, "Known": i % 2 == 0, "Mixed": True if i % 7 else i}
            for i, v in enumerate(values)]
    assert _ours(tmp_path, rows) == _pandas(rows)


def test_the_column_order_is_each_key_where_it_is_first_met(tmp_path):
    """The progressive list's rows carry their Context columns in each word's own order, some none: the header is
    every key in the order first met, as pandas' frame made it."""
    rows = _with_gaps(_ja_rows())
    rows[0] = {k: rows[0][k] for k in reversed(list(rows[0]))}
    rows[2]["Extra"] = "ー"
    assert _ours(tmp_path, rows) == _pandas(rows)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_redraws_header_keeps_the_generates_columns(tmp_path, language):
    """The redraw writes the Generate's header (`columns`): a row's other keys left out, a column it lacks empty —
    `pd.DataFrame(rows, columns=columns)`'s bytes."""
    rows = _with_gaps(_ja_rows() if language == "ja" else _zh_rows())
    columns = [c for c in rows[0] if c != "Sources"] + ["Context 9"]
    assert _ours(tmp_path, rows, columns) == _pandas(rows, columns)


@pytest.mark.parametrize("upto", [0, 1, 7, None])
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_coverage_cut_keeps_the_whole_lists_column_kinds(tmp_path, language, upto):
    """The cut list (the coverage target) is the first rows; each column's kind is read over the whole list, as the
    frame was made before it was cut: a Score column with a gap in a row the cut drops is still written 170.0. 0: the
    header alone (the target already met)."""
    rows = [dict(r, _MinSeq=i) for i, r in enumerate(_ja_rows() if language == "ja" else _zh_rows())]
    rows[-1].pop("Score")                              # (a gap only past the cut)
    n = len(rows) if upto is None else upto
    columns = [c for c in dict.fromkeys(k for r in rows for k in r) if c != "_MinSeq"]
    assert _ours(tmp_path, rows, columns, n) == _pandas_cut(rows, n)


def _kept_and_read(tmp_path, rows, keep, columns=None, upto=None):
    """`write_rows`' rows handed to the page (`keep`), and the same list as the page's reader reads it from the file."""
    from app import journey_render
    path = os.path.join(tmp_path, "list.csv")
    kept = analyzer.write_rows(path, rows, columns, upto, keep)
    return kept, journey_render._records(path, *keep)


@pytest.mark.parametrize("which", ["priority", "progressive"])
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_rows_handed_to_the_journey_are_the_list_as_it_reads_it(tmp_path, language, which):
    """Left 2: the page drawn by the run that wrote the two lists took them back from the file (`journey_render.
    _records`, 0.04 s at 2k). `write_rows`' `keep` hands back the same rows: each kept column's text as csv wrote it —
    a count as its digits, a gap / None / NaN empty, a float column's 170.0, a sentence with a CRLF, quotes and commas
    as is — the same columns (the Context / Src ones only for the progressive list), the coverage cut the same."""
    from app import journey_render
    keep = (journey_render.PRIORITY_COLUMNS, False) if which == "priority" else (journey_render.ROW_COLUMNS, True)
    rows = _with_gaps(_ja_rows() if language == "ja" else _zh_rows())
    rows[0]["Context 1"] = (rows[0].get("Context 1") or "") + ' "Spider, Thread"\r\n二行目'
    rows[1]["Occurrences (Global)"] = 12.5
    rows[2]["Modality"] = float("nan")
    rows[3]["Kana"] = None
    rows[4]["Word"] = "NA"                              # (a word spelled like pandas' missing value stays the word)
    rows[5]["Forms"] = True
    rows[6]["Kana"] = 0.1 + 0.2                         # (a float among a text column's cells: csv writes its repr)
    kept, read = _kept_and_read(tmp_path, rows, keep)
    assert kept == read and len(kept) == len(rows)
    assert all(isinstance(v, str) for row in kept for v in row.values())
    assert any(k.startswith("Context ") for k in kept[0]) == (which == "progressive")
    cut, read_cut = _kept_and_read(tmp_path, rows, keep, upto=7)
    assert cut == read_cut and len(cut) == 7
    header = [c for c in rows[0] if c != "Sources"] + ["Context 9"]     # (the redraw's header: the Generate's)
    assert _kept_and_read(tmp_path, rows, keep, header)[0] == _kept_and_read(tmp_path, rows, keep, header)[1]
    assert analyzer.write_rows(os.path.join(tmp_path, "list.csv"), rows) is None, "no keep: nothing held"


def test_the_rows_handed_to_the_journey_on_empty_and_one_column_lists(tmp_path):
    """The empty edges: a list of no rows (the header alone) is [] both ways; a one-column row of an empty cell is a
    row both ways (csv writes it \"\")."""
    from app import journey_render
    keep = (journey_render.PRIORITY_COLUMNS, False)
    assert _kept_and_read(tmp_path, [], keep, ["Word", "Reading"]) == ([], [])
    assert _kept_and_read(tmp_path, [{}, {}], keep) == ([], []), "rows of no columns: empty lines, no rows"
    kept, read = _kept_and_read(tmp_path, [{"Word": ""}, {"Word": None}, {"Word": "猫"}], keep)
    assert kept == read == [{"Word": ""}, {"Word": ""}, {"Word": "猫"}]


def test_the_rows_are_kept_for_the_journey_only_when_a_page_is_drawn():
    """`_page_keep`: without `--static` no page is drawn, so the writer holds no rows; with it, the journey's own
    columns — the priority list's words, the progressive list's columns with its sentences."""
    from argparse import Namespace
    from app import journey_render
    assert analyzer._page_keep(Namespace(static=False), True) is None
    assert analyzer._page_keep(Namespace(), False) is None
    assert analyzer._page_keep(Namespace(static=True), True) == (journey_render.PRIORITY_COLUMNS, False)
    assert analyzer._page_keep(Namespace(static=True), False) == (journey_render.ROW_COLUMNS, True)


def test_the_journey_drawn_with_the_rows_never_reads_the_lists(tmp_path, monkeypatch):
    """`generate_static_html(rows=, priority=)` hands the lists to `journey_render.render` as they are; with neither
    (the reuse path, a re-render) the page reads them from results, as before."""
    from app import journey_render, static_html_generator as gen
    seen = []
    monkeypatch.setattr(gen, "PRIORITY_CSV", str(tmp_path / "p.csv"))         # (never the real results' lists)
    monkeypatch.setattr(gen, "PROGRESSIVE_CSV", str(tmp_path / "q.csv"))
    monkeypatch.setattr(journey_render, "store_facts", lambda language: type("Facts", (), {"marks": None})())
    monkeypatch.setattr(journey_render, "render", lambda language, rows=None, priority=None, **kw: seen.append(
        (rows, priority)) or (_ for _ in ()).throw(RuntimeError("drawn")))
    rows, priority = [{"Word": "夜市", "Context 1": "夜市に行った。"}], [{"Word": "夜市"}]
    with pytest.raises(RuntimeError):
        gen.generate_static_html(open_browser=False, language="ja", rows=rows, priority=priority)
    with pytest.raises(RuntimeError):
        gen.generate_static_html(open_browser=False, language="ja")
    assert seen == [(rows, priority), (None, None)]


def test_an_empty_text_cell_and_a_one_column_row(tmp_path):
    """Edge cases of the csv module itself, which both writers share: a row of one empty cell is written "" (else it
    would read as no row), an empty string and None both empty."""
    rows = [{"Word": ""}, {"Word": None}, {"Word": "猫"}]
    assert _ours(tmp_path, rows) == _pandas(rows)


_NO_PANDAS = """
import runpy, sys
from app import journey_render
reads, records = [], journey_render._records
def counted(path, *a, **k):
    reads.append(path)
    return records(path, *a, **k)
journey_render._records = counted
sys.argv = [sys.argv[1]] + sys.argv[2:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    sys.stderr.write("\\nPANDAS-LOADED %s\\nLIST-READS %d\\n" % ("pandas" in sys.modules, len(reads)))
"""


def _analyzer(root, language, *args):
    """The analyzer as the window runs it (a child), at level 2 -> (exit code, output, whether pandas was loaded); the
    journey's reads of a list from results (`journey_render._records`) counted in `_analyzer.reads`."""
    env = cases.child_env(root)
    env["SURASURA_SENTENCE_TABLE"] = "2"
    p = subprocess.run([sys.executable, "-c", _NO_PANDAS, os.path.join(cases.REPO, "app", "analyzer.py"),
                        f"--language={language}", "--static", "--no-open", *args],
                       cwd=cases.REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    loaded = [line for line in p.stderr.splitlines() if line.startswith("PANDAS-LOADED ")]
    assert loaded, p.stderr[-2000:]
    _analyzer.reads = int([line for line in p.stderr.splitlines() if line.startswith("LIST-READS ")][-1].split()[1])
    return p.returncode, p.stdout + p.stderr, loaded[-1] == "PANDAS-LOADED True"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_neither_the_generate_nor_the_redraw_loads_pandas_or_reads_back_its_lists(tmp_path, language):
    """A full Generate of RP-2's real library, then the journey redrawn from its plan (`--from-plan`, the keeper's
    redraw after a move): both write the two lists, neither loads pandas, and neither's journey reads back the lists
    it has just written (Left 2: `write_rows` hands them over)."""
    root = str(tmp_path)
    case = f"rp2-{language}"
    cases.build(root, case)
    code, out, loaded = _analyzer(root, language, *cases.ALL_CASES[case][3])
    assert code == 0, out[-3000:]
    assert os.path.exists(os.path.join(root, "results", "priority_learning_list.csv"))
    assert not loaded, "the Generate loads no pandas"
    assert _analyzer.reads == 0, "the Generate's journey takes the lists it wrote, never reads them back"
    words, files = _compact_json(root)
    from tests.test_e_redraw import _move
    _move(root, language, "top")                        # (a show to the top: the keeper's redraw is owed)
    code, out, loaded = _analyzer(root, language, "--from-plan")
    assert code == 0 and "Redrew the journey" in out, out[-3000:]
    assert not loaded, "the redraw loads no pandas"
    assert _analyzer.reads == 0, "the redraw's journey takes the lists it wrote"
    words_after, files_after = _compact_json(root)
    assert words_after.keys() == words.keys()
    assert files_after != files and sorted(files_after, key=json.dumps) == sorted(files, key=json.dumps), (
        "the redraw's file statistics: the Generate's entries, in the new order")


def _compact_json(root):
    """G11: word_stats.json and file_statistics.json written with no indent (one line: the C encoder), parsed."""
    out = []
    for name in ("word_stats.json", "file_statistics.json"):
        with open(os.path.join(root, "results", name), encoding="utf-8") as f:
            text = f.read()
        assert "\n" not in text and text, name
        out.append(json.loads(text))
    assert out[0] and out[1]
    return out


def _verses():
    """The scripture-style lines led by their verse numbers (tests/Test Resources/ja/verses_sample.srt)."""
    with open(os.path.join(RES, "ja", "verses_sample.srt"), encoding="utf-8-sig") as f:
        blocks = f.read().replace("\r\n", "\n").split("\n\n")
    return [b.split("\n", 2)[2].strip() for b in blocks if b.count("\n") >= 2]


def test_only_i_plus_ones_rounds_share_one_tagger(tmp_path, monkeypatch):
    """G12: the list's chooser shows a line led by digits as `strip_verse_number` makes it, with a fugashi tagger
    made the first time one is needed. *Only i+1* asks the chooser once a round; each round made a tagger of its own
    (~0.1 s) for lines not yet kept. Now one a chooser: two rounds, both with new verse lines, make one."""
    from collections import namedtuple
    from app import sentence_score
    from app.connect import sentences as connect_sentences
    made = []
    real = analyzer.JapaneseTokenizer

    def _counted():
        made.append(1)
        return real()
    monkeypatch.setattr(analyzer, "JapaneseTokenizer", _counted)
    monkeypatch.setattr(connect_sentences, "files_seen", lambda language, ai: {})
    Line = namedtuple("Line", "file number text heard")
    root = analyzer.get_data_path("ja")
    verses = _verses()
    rounds = iter([verses[:2], verses[2:4]])

    def _choose(language, keys, **kw):
        lines = next(rounds)
        return {key: [Line(os.path.join(root, "HighPriority", "verses.srt"), i, text, None)]
                for i, (key, text) in enumerate(zip(keys, lines))}
    monkeypatch.setattr(sentence_score, "choose", _choose)
    table = type("Table", (), {"head": {"run_signature": "run-1"}})()
    chooser = analyzer.ListSentences("ja", 3, clean_only=True, results_dir=str(tmp_path), table=table, young={})
    first = chooser([("そこ", "ソコ"), ("荒れ野", "アレノ")])
    second = chooser([("見る", "ミル"), ("わたし", "ワタシ")])
    assert first[("そこ", "ソコ")][0] == "そこでモーサヤは、主に命じられたとおりにした。"      # (the verse number cut)
    assert second[("見る", "ミル")][0].startswith("見よ")
    assert len(made) == 1, "one tagger for both rounds"
    made.clear()
    rounds = iter([verses[:2]])
    run_tagger = real().tagger                          # (the Generate's own tokenizer's)
    (tmp_path / "b").mkdir()
    given = analyzer.ListSentences("ja", 3, clean_only=True, results_dir=str(tmp_path / "b"), table=table, young={},
                                   tagger=run_tagger)
    assert given([("そこ", "ソコ"), ("荒れ野", "アレノ")])[("そこ", "ソコ")][0] == first[("そこ", "ソコ")][0]
    assert made == [] and given.tagger is run_tagger, "the run's tagger given: none made"
    assert analyzer.ListSentences("zh", 3, tagger=run_tagger).tagger is None
    with open(analyzer.__file__, encoding="utf-8") as f:                    # (the Generate hands its own over)
        source = f.read()
    call = source[source.index("_chooser = ListSentences("):]
    assert 'tagger=tokenizer.tagger if language == "ja" else None,' in call[:call.index("\n    ") + 200]


def _relpath_series(file_path, data_dir):
    """`_series_name` as it was (every file through `os.path.relpath`), the reference."""
    try:
        rel = os.path.relpath(file_path, data_dir).replace("\\", "/")
    except ValueError:
        return os.path.basename(file_path)
    parts = [p for p in rel.split("/") if p]
    if len(parts) < 2:
        return rel
    if len(parts) == 2:
        return parts[1]
    return analyzer._VOLUME_SUFFIX_RE.sub("", parts[1]) or parts[1]


def test_a_files_work_is_cut_from_its_folder_once_never_relpath_a_file(tmp_path, monkeypatch):
    """G9: a run names each spoken file's work (the songs' step, the walk's dispersion) — `os.path.relpath` for every
    file made both paths absolute and compared them part by part (0.45 s of the songs' step at 20,000 files). Now the
    data folder's prefix is made once and cut off; the same answer for every shape a path takes: a show's folder, a
    volume suffix, a loose file, mixed case, `..`, a doubled separator, another folder, another drive."""
    data_dir = str(tmp_path / "data" / "ja")
    high = os.path.join(data_dir, "HighPriority")
    paths = [os.path.join(high, "Hoshi Matsuri", "Hoshi Matsuri - 01.ja.srt"),
             os.path.join(high, "蜘蛛の糸 Vol. 2", "第1章.txt"), os.path.join(high, "蜘蛛の糸（芥川龍之介）.txt"),
             os.path.join(high, "夜市", "季1", "night_market.srt"), os.path.join(data_dir.upper(), "HighPriority", "x", "y.srt"),
             os.path.join(high, "..", "LowPriority", "夜市", "a.srt"), high + os.sep + os.sep + "夜市" + os.sep + "b.srt",
             os.path.join(str(tmp_path), "elsewhere", "c.srt"), data_dir + "2" + os.sep + "Soon" + os.sep + "d.srt"]
    if os.name == "nt":
        paths.append("Q:" + os.sep + os.path.join("Q", "show", "e.srt"))
    want = [_relpath_series(p, data_dir) for p in paths]
    calls = []
    real = os.path.relpath
    monkeypatch.setattr(os.path, "relpath", lambda *a: calls.append(a) or real(*a))
    assert [analyzer._series_name(p, data_dir) for p in paths] == want
    assert len(calls) == len(paths) - 4, "only the odd shapes ask relpath (the first four are plain)"
    calls.clear()
    plain = [os.path.join(high, f"作品{i}・外伝", f"{i:02}.srt") for i in range(200)]
    assert [analyzer._series_name(p, data_dir) for p in plain] == [f"作品{i}・外伝" for i in range(200)]
    assert calls == [], "a file under the data folder as written: no relpath"


def test_a_work_is_cut_without_relpath_however_the_run_spells_its_root(tmp_path, monkeypatch):
    """G9 (session 2's re-measure): a run joins each file onto the data folder as it spells it — `resolve_found_files`'
    `os.path.join(data_dir, physical_path)`, under a root given as `H:/…` (a bench, a test root) or `H:\\…` (an
    install). A prefix made with `abspath` turned `H:/…` into `H:\\…` and matched no file of such a run: every one
    took `relpath` again (0.31 s at 20,000 files). The prefix as the run spells it matches every file, both ways."""
    roots = [str(tmp_path).replace("\\", "/"), str(tmp_path)]
    for root in roots:
        data_dir = os.path.join(root, "data", "ja")
        paths = [os.path.join(data_dir, rel) for rel in
                 ("HighPriority/ぼっち・ざ・ろっく！/ep01.ja.srt", "LowPriority/薬屋のひとりごと 2/第3話.srt",
                  "GoalContent/夜市.txt", "HighPriority/Show 0001/Show 0001 - 01.srt")]
        want = [_relpath_series(p, data_dir) for p in paths]
        calls = []
        real = os.path.relpath
        monkeypatch.setattr(os.path, "relpath", lambda *a: calls.append(a) or real(*a))
        assert [analyzer._series_name(p, data_dir) for p in paths] == want == \
            ["ぼっち・ざ・ろっく！", "薬屋のひとりごと", "夜市.txt", "Show"]
        assert calls == [], f"the run's own spelling ({root[:3]}…): no relpath"
        monkeypatch.setattr(os.path, "relpath", real)


def test_a_kept_works_song_numbers_reach_the_walk_without_a_set_a_file(tmp_path):
    """G9: a work's kept answer is handed over as kept (each file's sorted numbers), the one read now the same shape
    — so a Generate after nothing changed makes no set per file — and the walk's reader blanks those lines by number
    (`_sentences_of`): a song line keeps its place with no words, every other line as read."""
    from tests import test_song_lines as songs
    from app import token_index as ti
    found, data_dir, db = songs._indexed_show(tmp_path)
    store = ti.open_store("ja", db)
    try:
        first = analyzer.song_sentences(found, data_dir, store, None, "ja")
        again = analyzer.song_sentences(found, data_dir, store, None, "ja", stats := {})
        assert stats == {"read": 0, "kept": 1}
        assert again == first and all(isinstance(v, list) and v == sorted(v) and v for v in again.values())
        path = found[0][0]
        lines = store.file_tokens(path)
    finally:
        store.close()
    numbers = set(again[path])
    blanked = [(s[0], []) if no in numbers else s for no, s in enumerate(lines)]     # (the rule before, by a set)
    out = analyzer.blank_songs(lines, again[path])                      # (the walk's `_sentences_of` calls it)
    assert out == blanked and any(not s[1] for s in out) and any(s[1] for s in out)
    past = again[path] + [len(lines), len(lines) + 40]                 # (a kept answer for a longer reading)
    assert analyzer.blank_songs(lines, past) == blanked, "a number past the file's end is no line"
    assert analyzer.blank_songs(lines, []) is lines and analyzer.blank_songs(lines, None) is lines
