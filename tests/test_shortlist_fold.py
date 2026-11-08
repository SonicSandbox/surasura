"""A Generate's example-sentence work, made cheaper without changing a byte (Haya-F7b, 2026-11-07; Sonic: "Is there a
way without tradeoff to get the speed back or even faster?").

What these prove, on real Japanese lines:
  - the shortlists taken in many offers at once (`plan_rules.offer_spread_later` / `fold_spread`: one sort where
    `keep_best` searched its pool for every candidate) are exactly the parts `offer_spread` keeps one offer at a time —
    the same candidates, in the same order, the first offered among equal ones — whatever the batch size, with lines
    said in many files, the same line twice in one file and full pools;
  - the per-file first sentences packed in bulk (`pack_firsts`) are the bytes the one-row-at-a-time packing wrote;
  - the plan compressed on a second thread is the bytes of one write a line, and a compressor that fails raises to the
    caller with the old plan left whole and no thread left behind.

What a wrong answer would cost a learner: a different sentence on a card than the last Generate showed (or than the
plan's re-pick shows after a drag), a plan the window can't read, or a Generate that hangs on a full disk.
The whole-run proof (every output byte for byte against the code before, a wide list included) is in the lane's
register; tests/plan_file_cases.py's hash list holds the outputs here.
"""
import gzip
import io
import json
import os
import random
import threading
from array import array
from unittest.mock import patch

import pytest

from app import analyzer, plan_rules

RESOURCES = os.path.join(os.path.dirname(__file__), "Test Resources", "ja")


def _lines():
    """Real Japanese lines: a subtitle file's dialogue and a short text's sentences."""
    out = []
    with open(os.path.join(RESOURCES, "phrases_sample.srt"), encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.isdigit() and "-->" not in line:
                out.append(line)
    with open(os.path.join(RESOURCES, "context_test.txt"), encoding="utf-8-sig") as f:
        out += [line.strip() for line in f if line.strip()]
    return out


LINES = _lines()


def _offers(rng, n, files, texts):
    """`n` candidates as the walk makes them: (short, long, cost, its unknowns, the text, its file, its set phrases,
    the order-free key, its sentence number, the audio key) — a few files and lines, so lines repeat across files and
    the very same line comes twice in one file (same key, another sentence number)."""
    paths = [f"Show {i:02d} - 0{i % 9 + 1}.srt" for i in range(files)]
    pool = rng.sample(LINES, min(texts, len(LINES)))
    out = []
    for s_no in range(n):
        text = rng.choice(pool)
        src = rng.randrange(files)
        short, long = int(len(text) < 10), int(len(text) > 50)
        cost, unknowns = rng.randrange(3), rng.randrange(4)
        key = plan_rules.order_free_key(short, long, cost, unknowns, text, paths[src])
        out.append((short, long, cost, frozenset(), text, src, None, key, s_no, None))
    return out


@pytest.mark.parametrize("fold", [1, 2, 5, 64])
def test_shortlists_taken_in_at_once_are_the_ones_kept_offer_by_offer(fold):
    """Every batch size gives `offer_spread`'s two parts, element for element (the same tuples: the first offered
    among equal keys), from small pools that never fill to full ones that turn most offers away."""
    rng = random.Random(fold)
    with patch.object(plan_rules, "FOLD", fold):
        for trial in range(300):
            size = rng.choice((3, 5, 60))
            offers = _offers(rng, rng.randrange(0, 400), files=rng.randrange(1, 12), texts=rng.randrange(1, 40))
            spread, best = [], []
            for ctx in offers:
                plan_rules.offer_spread(spread, best, ctx, size, 7, 5, 4)
            spread2, best2, waiting = [], [], []
            for ctx in offers:
                plan_rules.offer_spread_later(spread2, best2, waiting, ctx, size, 7, 5, 4)
            plan_rules.fold_spread(spread2, best2, waiting, size, 7, 5, 4)
            assert not waiting
            assert [id(c) for c in spread2] == [id(c) for c in spread], trial
            assert [id(c) for c in best2] == [id(c) for c in best], trial


def test_a_line_said_twice_in_one_file_keeps_its_first_sentence_and_one_in_another_file_is_its_own():
    """The same line again in the same file (one key) is kept once — its first sentence number, as `keep_best` kept
    it, even when the second comes in the same batch — and the line in another file is another candidate."""
    text = LINES[0]
    key0 = plan_rules.order_free_key(0, 0, 0, 0, text, "Show 01 - 01.srt")
    key1 = plan_rules.order_free_key(0, 0, 0, 0, text, "Show 02 - 01.srt")
    a, again = ((0, 0, 0, frozenset(), text, 0, None, key0, s_no, None) for s_no in (3, 9))
    other = (0, 0, 0, frozenset(), text, 1, None, key1, 3, None)
    spread, best = [], []
    for ctx in (a, other, again):
        plan_rules.offer_spread(spread, best, ctx, 60, 7, 5, 4)
    spread2, best2 = [], []
    plan_rules.fold_spread(spread2, best2, [a, other, again], 60, 7, 5, 4)
    assert spread2 == spread == [a, other] and best2 == best == [a]
    assert spread2[0][8] == 3


def test_an_empty_fold_changes_nothing():
    spread, best = [LINES[0]], [LINES[1]]
    plan_rules.fold_spread(spread, best, [], 60, 7, 5, 4)
    assert spread == [LINES[0]] and best == [LINES[1]]


def _pack_firsts_one_by_one(rows):
    """The packing before (F7, 2026-11-07): one row at a time."""
    cols = {name: array("i") for name in plan_rules._FIRSTS_INTS}
    flags, hashes = array("b"), array("I")
    cols["cow_at"].append(0)
    cols["crowd_at"].append(0)
    for src, number, short, long, cowords, crowd, text_hash, chars in rows:
        cols["src"].append(src)
        cols["number"].append(number)
        cols["chars"].append(chars)
        flags.append(short | (long << 1))
        hashes.append(text_hash)
        cols["cow"].extend(cowords)
        cols["cow_at"].append(len(cols["cow"]))
        cols["crowd"].extend(crowd)
        cols["crowd_at"].append(len(cols["crowd"]))
    out = {"n": len(rows), "order": plan_rules.sys.byteorder}
    import base64
    for name, arr in list(cols.items()) + [("flags", flags), ("hash", hashes)]:
        out[name] = base64.b64encode(arr.tobytes()).decode("ascii")
    return out


def test_first_sentences_packed_in_bulk_are_the_bytes_packed_one_by_one():
    """Real lines' lengths and hashes, rows with and without co-words and set phrases, and no rows at all: the same
    JSON, and `Firsts` reads every row back."""
    rng = random.Random(7)
    rows = []
    for number, text in enumerate(LINES):
        cowords = tuple(sorted(rng.sample(range(500), rng.randrange(0, 5))))
        crowd = tuple(sorted(rng.sample(range(40), rng.randrange(0, 2))))
        rows.append((rng.randrange(30), number, int(len(text) < 10), int(len(text) > 50), cowords, crowd,
                     plan_rules.text_hash_of(text), len(text)))
    for case in (rows, rows[:1], []):
        packed = plan_rules.pack_firsts(case)
        assert json.dumps(packed) == json.dumps(_pack_firsts_one_by_one(case))
        firsts = plan_rules.Firsts(packed)
        assert [firsts[j][2:] for j in range(len(firsts))] == [
            (short, long, src, cowords, crowd, number, text_hash, chars)
            for src, number, short, long, cowords, crowd, text_hash, chars in case]


def _plan_lines():
    yield json.dumps({"format": 3, "language": "ja"})
    for start in range(0, len(LINES), 3):
        yield json.dumps({"sentences": [[t, None, 0, 0, 1, [2, 5], [], i, plan_rules.text_hash_of(t), len(t)]
                                        for i, t in enumerate(LINES[start:start + 3], start)]}, ensure_ascii=False)


def test_the_plan_compressed_on_a_thread_is_the_bytes_of_one_write_a_line(tmp_path):
    """Lines handed over a few bytes at a time (many chunks, a line cut across none) give the one-write-a-line file."""
    reference = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=reference, compresslevel=3, mtime=0) as gz:
        for line in _plan_lines():
            gz.write(line.encode("utf-8"))
            gz.write(b"\n")
    for chunk in (7, 200, 1 << 20):             # every line on its own · lines joined and on their own · one chunk
        results = str(tmp_path / f"results-{chunk}")
        os.makedirs(results)
        with patch.object(analyzer, "_PLAN_WRITE_CHUNK", chunk):
            analyzer.write_plan_file(results, _plan_lines())
        with open(os.path.join(results, analyzer.PLAN_FILE), "rb") as f:
            assert f.read() == reference.getvalue()


def test_a_compressor_that_fails_raises_and_leaves_the_old_plan_whole(tmp_path):
    """The disk fills while the thread writes: the error reaches the caller, the old plan's bytes stay, no temp file,
    and the thread has stopped (the lines after the error were drained, never waited on forever)."""
    results = str(tmp_path / "results")
    os.makedirs(results)
    analyzer.write_plan_file(results, iter([json.dumps({"format": 3, "language": "ja"})]))
    with open(os.path.join(results, analyzer.PLAN_FILE), "rb") as f:
        old = f.read()
    real = gzip.GzipFile.write
    calls = []

    def full_disk(self, data):
        calls.append(len(data))
        if len(calls) >= 2:
            raise OSError(28, "No space left on device")
        return real(self, data)

    with patch.object(analyzer, "_PLAN_WRITE_CHUNK", 7), patch.object(gzip.GzipFile, "write", full_disk):
        with pytest.raises(OSError):
            analyzer.write_plan_file(results, _plan_lines())
    with open(os.path.join(results, analyzer.PLAN_FILE), "rb") as f:
        assert f.read() == old
    assert sorted(os.listdir(results)) == [analyzer.PLAN_FILE]
    assert not [t for t in threading.enumerate() if t.name == "plan-gzip"]
