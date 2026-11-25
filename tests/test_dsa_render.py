"""DSA-RENDER (3.0.19): the render's and the redraw's standard choices, each proved by a counter on real words.

- G4: the journey's English meanings are found through the table's key index — a page whose memo lacks a word
  decompresses only that word's block(s), never the whole 218,840-line table (`journey_render._gloss_lines`,
  scripts/build_gloss_data.py) — and the index finds exactly what a scan of every line finds, in the table's order.
- G3: a redraw's `Engine(plan).replan(order)` works the live numbers once (the plan's own order's are worked out only
  when asked first), and `plan_engine.check(..., chunked=False)` hashes with one C call — the same verdict.
- G11: the journey's chunk writes each word and each source row as JSON and UTF-8 once — the same bytes.
- G12: the score's row index is the table's, built once a table, not once a caller's memo (Connect's Swap: new each
  call).

What a wrong answer would cost a learner: a word shown with another word's meaning or none (a key the index misses,
the first entry of two out of order), a redraw that names the wrong first episode (the lazy numbers read before they
are worked out), a page that never opens (a chunk's JSON joined wrong)."""
import base64
import gzip
import hashlib
import importlib.util
import json
import lzma
import os
import zlib

import pytest

from app import journey_render as jr
from app import plan_engine, plan_rules, sentence_score
from app import gloss_ja_data, gloss_zh_data
from tests.test_journey_render_shape import WORDS, _NoPitch, _rows, _stats
from tests.test_plan_engine_property import synthetic_plan

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = {"ja": gloss_ja_data, "zh": gloss_zh_data}
# The tables' lines as the 2026-11-21 build wrote them (one lzma stream then): G4 changes how they are stored, never a
# line — so every meaning the page shows is the one it showed (count, sha256 of the lines joined with "\n").
LINES_OF_2026_11_21 = {"ja": (218_840, "190cca8b2ba0deabe80332a8bdaf217042cbab23ce83d7212bd942dd9244e22d"),
                       "zh": (125_101, "a25b985ba36333ca105f67243ed1a12863c99a541a5256a76aabcf75207cf3e2")}


def _builder():
    spec = importlib.util.spec_from_file_location("build_gloss_data", os.path.join(REPO, "scripts",
                                                                                   "build_gloss_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_lines(module):
    """Every line of a meanings module (bytes), its blocks decompressed one after another — the test's own reader."""
    data = base64.b64decode(module.DATA)
    filters = [{"id": lzma.FILTER_LZMA2, "dict_size": module.BLOCK_DICT}]
    out = []
    for start, end in zip(module.BLOCKS, module.BLOCKS[1:]):
        out += lzma.decompress(data[start:end], format=lzma.FORMAT_RAW, filters=filters).split(b"\n")
    return out


def _scanned(lines, wanted):
    """What `Meanings._load` found before the index: every line scanned, its keys matched (the 3.0.18 rule)."""
    wanted = {k.encode("utf-8") for k in wanted}
    index = {}
    for line in lines:
        first = line.find(b"\t")
        second = line.find(b"\t", first + 1)
        if second < 0:
            continue
        keys = line[:second].replace(b"\t", b",").split(b",")
        if wanted.isdisjoint(keys):
            continue
        entry = line.decode("utf-8").split("\t")
        for key in dict.fromkeys(keys):
            if key in wanted:
                index.setdefault(key.decode("utf-8"), []).append(entry)
    return index


class _Counted:
    """lzma's decompressors, counting the table's bytes they hand out: a block (raw LZMA2) or the one stream of the
    format before (`LZMADecompressor`) — the index's own read (zlib's, once a process) apart."""

    def __init__(self, monkeypatch):
        self.out = self.index = 0
        real_decompress, real_class = lzma.decompress, lzma.LZMADecompressor
        counter = self
        inside = []                                      # (`lzma.decompress` itself makes an LZMADecompressor)

        def decompress(data, *a, **k):
            inside.append(1)
            try:
                found = real_decompress(data, *a, **k)
            finally:
                inside.pop()
            counter.out += len(found)
            return found

        class Decompressor:
            def __init__(self, *a, **k):
                self._real = real_class(*a, **k)

            def decompress(self, data, *a, **k):
                found = self._real.decompress(data, *a, **k)
                if not inside:
                    counter.out += len(found)
                return found

            def __getattr__(self, name):
                return getattr(self._real, name)

        real_zlib = zlib.decompress

        def index_read(data, *a, **k):
            found = real_zlib(data, *a, **k)
            counter.index += len(found)
            return found

        monkeypatch.setattr(lzma, "decompress", decompress)
        monkeypatch.setattr(lzma, "LZMADecompressor", Decompressor)
        monkeypatch.setattr(zlib, "decompress", index_read)


# --------------------------------------------------------------------------------------------------------------- #
# G4: the meanings' index
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_word_the_memo_lacks_decompresses_its_own_block_not_the_whole_meanings_table(language, monkeypatch):
    # why: one new word on a page (a Generate that brought one file) cost the whole table — 17 MB of JA lines
    # decompressed and 218,840 lines walked in Python (0.46 s) — for a few hundred bytes of meaning.
    getattr(jr, "_GLOSS_INDEX", {}).clear()
    word, reading = WORDS[language][0]
    counted = _Counted(monkeypatch)
    meanings = jr.Meanings(language)
    meanings.prepare([(word, reading, word)])
    assert meanings.of(word, reading, word)              # a real word: a real meaning
    block = 1_000_000                                    # a few blocks of 2,048 lines (the whole table before: 17 MB)
    assert 0 < counted.out < block, counted.out
    read = counted.index
    counted.out = counted.index = 0
    meanings.prepare([(word, reading, word)])
    assert 0 < counted.out < block and counted.index == 0 < read     # the index is read once a process


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_index_finds_every_entry_a_whole_scan_finds_in_the_tables_order(language):
    # why: a key the index misses is a word shown without its meaning; two entries out of order, the wrong one first
    # (`_pick` takes the first whose reading matches). A sample across the whole table — every 211th line's keys, the
    # samples' real words, a word in no dictionary, mixed scripts — against the 3.0.18 scan of every line.
    module = MODULES[language]
    lines = _all_lines(module)
    wanted = {w for w, _r in WORDS[language]} | {"ナイ語彙ゼロ", "zz"}
    for line in lines[::211]:
        wanted.update(k.decode("utf-8") for k in jr._line_keys(line))
    found = jr.Meanings(language)._load(wanted)
    assert found == _scanned(lines, wanted)
    assert len(found) > 900                              # (the sample is real: most of its keys have entries)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_tables_lines_are_the_2026_11_21_builds_line_for_line(language):
    # why: the new storage must not move one meaning — the same lines, in the same order, under the same Revision
    # (the journey's memo and render signature key on it: no learner re-reads every meaning after this update).
    module = MODULES[language]
    lines = _all_lines(module)
    n, digest = LINES_OF_2026_11_21[language]
    assert len(lines) == n and module.REVISION == "2026-11-21"
    assert hashlib.sha256(b"\n".join(lines)).hexdigest() == digest
    assert module.FORMAT == 2 and module.BLOCKS[0] == 0 and len(module.BLOCKS) == -(-n // module.BLOCK_LINES) + 1


def _built(tmp_path, lines, monkeypatch, block_lines=3):
    """`_pack_blocks`' module for these lines (str), in small blocks, through the build's own template."""
    build = _builder()
    monkeypatch.setattr(build, "BLOCK_LINES", block_lines)
    data, blocks, index = build._pack_blocks(lines)
    text = build.TEMPLATE.format(revision="2026-11-25", source="test", n=len(lines), what="lines",
                                 data=build._wrap(data), format=build.FORMAT, block_lines=block_lines,
                                 block_dict=build.BLOCK_DICT, buckets=build.BUCKETS,
                                 blocks=build._wrap_numbers(blocks), index=build._wrap(index))
    path = tmp_path / "gloss_test_data.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"gloss_test_data_{tmp_path.name}", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return build, module


@pytest.mark.parametrize("count", [0, 1, 3, 7])
def test_the_build_round_trips_any_number_of_lines_and_blocks(tmp_path, monkeypatch, count):
    # why: the last block short, exactly full, one line, none — each is a line a page could ask for. Real JMdict lines
    # (two entries share 冒険's reading; a kana-only entry has no kanji field).
    adventure = "冒険".encode("utf-8")
    real = [line.decode("utf-8") for line in _all_lines(gloss_ja_data)
            if adventure in line.split(b"\t")[0].split(b",") or line.startswith(b"\t")][:count]
    assert len(real) == count
    build, module = _built(tmp_path, real, monkeypatch)
    assert build.module_lines(module) == real
    wanted = {k for line in real for k in jr._line_keys(line.encode("utf-8"))} | {"あ".encode("utf-8")}
    assert list(jr._gloss_lines(module, wanted)) == [line.encode("utf-8") for line in real]
    assert set(jr._gloss_lines(module, {b"never-a-key"})) <= set(line.encode("utf-8") for line in real)
    assert list(jr._gloss_lines(module, set())) == []


def test_a_rebuild_of_the_same_lines_keeps_the_revision_and_writes_nothing(tmp_path, monkeypatch):
    # why: the Revision is the meanings' (memo key, render signature): a rebuild that moves no line moves nothing.
    lines = [line.decode("utf-8") for line in _all_lines(gloss_zh_data)[1000:1010]]
    build = _builder()
    out = tmp_path / "gloss_zh_data.py"
    monkeypatch.setattr(build, "cedict_lines", lambda entries: lines)
    monkeypatch.setattr(build, "load_cedict", lambda gold: ({}, "2026-09-23"))
    monkeypatch.setattr(build, "jmdict_lines", lambda path: (lines, "2026-09-28"))
    outputs = {"ja": str(tmp_path / "gloss_ja_data.py"), "zh": str(out)}
    build.main(outputs=outputs)
    first = out.read_text(encoding="utf-8")
    old = build._read_module(str(out))
    assert build.module_lines(old) == lines
    monkeypatch.setattr(build, "date", _Day)
    build.main(outputs=outputs)
    assert out.read_text(encoding="utf-8") == first      # same lines: the old Revision, nothing written


class _Day:
    """`date` on a day the first build never saw."""

    @staticmethod
    def today():
        return _Day

    @staticmethod
    def isoformat():
        return "2099-01-01"


def test_an_old_one_stream_module_reads_back_for_the_rebuilds_comparison():
    # why: the first rebuild compares against a format-1 table (one stream) — its lines must read back exactly.
    build = _builder()
    lines = ["冒険\tぼうけん\tn;vs|adventure", "\tあっ\tint|ah!"]
    old = type("Old", (), {"DATA": build._pack(lines), "REVISION": "2026-11-21"})
    assert build.module_lines(old) == lines


# --------------------------------------------------------------------------------------------------------------- #
# G3: the redraw's numbers once, its digest in one call
# --------------------------------------------------------------------------------------------------------------- #

def _plan_order(plan):
    return [(entry[0], entry[1]) for entry in plan.files]


def _counting_numbers(monkeypatch):
    calls = []
    real = plan_engine.Engine._numbers

    def counted(self, *a, **k):
        calls.append(1)
        return real(self, *a, **k)
    monkeypatch.setattr(plan_engine.Engine, "_numbers", counted)
    return calls


def test_a_redraws_replan_works_the_live_numbers_once(monkeypatch):
    # why: `Engine(plan)` worked the plan's own order's numbers and the redraw's `replan` then worked its order's —
    # two passes over every (file, word) use, 0.149 s each at 20k; the first was never read.
    plan = synthetic_plan(3)
    order = _plan_order(plan)
    order = [x for x in order if x[1] == "now"][::-1] + [x for x in order if x[1] != "now"]
    calls = _counting_numbers(monkeypatch)
    eng = plan_engine.Engine(plan)
    assert calls == []
    eng.replan(order)
    assert len(calls) == 1


def test_the_plans_own_numbers_are_worked_out_at_the_first_ask_and_are_the_eager_ones(monkeypatch):
    # why: a caller that moves or reads before any replan (the window's moves, *N new*) must find the plan's own
    # numbers, as eagerly worked ones were.
    plan = synthetic_plan(4)
    referee = plan_engine.Engine(plan)
    referee.replan(_plan_order(plan))                    # the plan's own order, worked out on purpose
    calls = _counting_numbers(monkeypatch)
    lazy = plan_engine.Engine(plan)
    first_item = plan.files[0][0]
    lazy.move(first_item, "goal")
    referee.move(first_item, "goal")
    assert len(calls) == 1
    for name in sorted(plan_engine._LIVE - {"_order_v"}):
        assert getattr(lazy, name) == getattr(referee, name), name
    assert lazy.result().priority == referee.result().priority
    assert getattr(plan_engine.Engine(plan), "_spelled", None) is None    # (other names stay missing)


def test_a_bad_order_is_refused_at_once_and_a_failed_replan_keeps_the_plans_numbers():
    # why: the plan's order is still checked when the engine is made (a PlanError there, as before), and a replan
    # refused for its order leaves the engine its plan's numbers, never half of the refused order's.
    plan = synthetic_plan(5)
    with pytest.raises(plan_engine.PlanError):
        plan_engine.Engine(plan, ids=[plan.files[0][0]] * len(plan.files))     # one item twice in the order
    eng = plan_engine.Engine(plan)
    with pytest.raises(plan_engine.PlanError):
        eng.replan([("not/in/the/plan.srt", "now")])
    referee = plan_engine.Engine(plan)
    referee.replan(_plan_order(plan))
    assert eng._ranked == referee._ranked and eng._first == referee._first


def test_the_redraws_check_hashes_in_one_call_with_the_same_verdict(monkeypatch):
    # why: the redraw's own process has no thread to wait beside it: the chunked digest (meant for a worker beside
    # the window) took 0.449 s at 20k against 0.034 s for the C encoder — the same text, the same digest.
    files = [[f"now/{w}.srt", f"sig-{w}", "NOW", 1.0, "text"] for w, _r in WORDS["ja"]]
    parts = {"files": files, "known": "冒険|ぼうけん", "settings": {"zh_script": "asis"}}
    header = {"language": "ja", "engine": "e", "run_signature": "r", "format": plan_engine.FORMAT,
              "weights": {"now": 10, "soon": 5, "goal": 2},
              "order_free_signature": plan_rules.signature_digest(parts, order_free=True, chunked=False)}
    plan = plan_engine.Plan(header, [], [], [], [], None)
    pieces = []
    real = plan_rules.SIGNATURE_ENCODER.iterencode
    monkeypatch.setattr(plan_rules.SIGNATURE_ENCODER, "iterencode",
                        lambda o, _one_shot=False: pieces.append(_one_shot) or real(o, _one_shot))
    assert plan_engine.check(plan, "ja", "e", "r", parts, chunked=False) is None
    assert pieces == [True]                              # `encode`'s one C call (its `_one_shot`), never piecewise
    pieces.clear()
    assert plan_engine.check(plan, "ja", "e", "r", parts) is None          # the window's workers: chunked, as ever
    assert pieces == [False]


# --------------------------------------------------------------------------------------------------------------- #
# G11: each word and source row encoded once
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", ["ja", "zh"])
def test_each_source_row_is_written_as_json_once_and_the_chunk_is_its_json(language, monkeypatch):
    # why: `sized` wrote each new source row's JSON to count its bytes, then the chunk wrote the whole table again.
    # The chunk's bytes must stay the page's JSON exactly: the joined pieces are `_json` of the chunk itself.
    rows_made = []
    real_row = jr.Sources.row

    def row(self, rel):
        found = real_row(self, rel)
        rows_made.append(found)
        return found
    monkeypatch.setattr(jr.Sources, "row", row)
    encoded = []
    real_encode = jr._ENCODE

    def encode(obj):
        encoded.append(obj)
        return real_encode(obj)
    monkeypatch.setattr(jr, "_ENCODE", encode)
    out = jr.build(language, _rows(language, 6), _stats(6), pitch=_NoPitch())
    made = {id(r) for r in rows_made}
    assert made
    times = {}
    for obj in encoded:
        for item in ([obj] + (list(obj) if isinstance(obj, list) else [])):
            if id(item) in made:
                times[id(item)] = times.get(id(item), 0) + 1
    assert set(times.values()) == {1}, times
    for chunk in out.chunks:
        text = gzip.decompress(chunk)
        assert text == real_encode(json.loads(text)).replace("</", "<\\/").encode("utf-8")


# --------------------------------------------------------------------------------------------------------------- #
# G12: the score's row index, once a table
# --------------------------------------------------------------------------------------------------------------- #

class _Table:
    """A sentence table's head as `_choose` reads it first: its list rows' keys and the rows that hold lines."""

    def __init__(self, language):
        self.head = {"keys": [[w, r] for w, r in WORDS[language]], "rows": [0, 2, 4]}

    def rows(self):
        keys = self.head["keys"]
        return {(keys[k][0], keys[k][1]): k for k in self.head["rows"]}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_scores_row_index_is_built_once_a_table_not_once_a_callers_memo(language, monkeypatch):
    # why: Connect's Swap hands no memo (or a new one) at each call: the rows' index and `set(rows)` were built again
    # every call, though they are the table's alone.
    built = []
    real = sentence_score._key_rows
    monkeypatch.setattr(sentence_score, "_key_rows", lambda keys: built.append(1) or real(keys))
    getattr(sentence_score, "_INDEX", []).clear()
    tab = _Table(language)
    moment = type("M", (), {"root": REPO, "known": (), "young": {}})()
    for memo in (None, {}, None):
        assert sentence_score._choose(tab, language, [("ナイ語彙", "")], 2, moment, (), (), None, None, False, False,
                                      (), False, memo) == {}
    assert len(built) == 1
    other = _Table(language)                             # another table (a new Generate): its own index
    sentence_score._choose(other, language, [("ナイ語彙", "")], 2, moment, (), (), None, None, False, False, (), False)
    assert len(built) == 2
    exact, by_lemma = sentence_score._table_rows(other)[0]
    assert exact[(WORDS[language][2][0], WORDS[language][2][1])] == 2
    assert sentence_score._table_rows(other)[1] == {0, 2, 4}
